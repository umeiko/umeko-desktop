// Shared by the native and Python editions. Runs only against portable bundles.
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import https from 'node:https';
import {createHash, randomUUID} from 'node:crypto';
import {createGunzip, createInflateRaw, crc32} from 'node:zlib';
import {Readable, Transform} from 'node:stream';
import {pipeline} from 'node:stream/promises';
import {fileURLToPath} from 'node:url';

const MAX_ARCHIVE = 2 * 1024 ** 3, MAX_EXPANDED = 8 * 1024 ** 3;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
let logFile;
const emit = value => {
  const line = JSON.stringify(value) + '\n';
  if (logFile) {try {fs.appendFileSync(logFile,line,{mode:0o600});} catch {}}
  process.stdout.write(line);
};
let lastState = '', lastStatus = 0;
const status = (state, message, progress = -1, extra = {}) => {
  if (state === 'extracting' && lastState === state && Date.now() - lastStatus < 100) return;
  lastState = state; lastStatus = Date.now(); emit({state, message, progress, ...extra});
};
const exists = file => fsp.lstat(file).then(() => true, () => false);
const readJSON = async file => JSON.parse(await fsp.readFile(file, 'utf8'));
const writeJSON = (file, data) => fsp.writeFile(file, JSON.stringify(data), {mode: 0o600});
export const platformKey = () => `${{win32:'windows',darwin:'macos',linux:'linux'}[process.platform]}-${process.arch === 'arm64' ? 'arm64' : 'x64'}`;

function releaseURL(url, repo, tag) {
  const prefix = `https://github.com/umeiko/${repo}/releases/download/${encodeURIComponent(tag)}/`;
  if (typeof url !== 'string' || !url.startsWith(prefix) || new URL(url).hash) throw Error('更新包地址无效');
  return url;
}
export function selectAsset(assets, repo, tag, platform = platformKey()) {
  if (!Array.isArray(assets)) throw Error('发布资源列表无效');
  const prefix = repo.endsWith('-cpp') ? `UmekoCpp-${tag}-` : `Umeko-${tag.replace(/^v/, '')}-`;
  const suffix = platform.startsWith('linux-') ? '.tar.gz' : '.zip';
  const found = assets.filter(a => typeof a.name === 'string' && a.name.startsWith(prefix) &&
    (repo.endsWith('-cpp') ? a.name === prefix + platform + suffix :
      (a.name.startsWith(prefix + platform + '-') && a.name.endsWith(suffix) && /^[a-f0-9]{7,40}$/.test(a.name.slice((prefix + platform + '-').length, -suffix.length)))));
  if (found.length !== 1) throw Error('未找到唯一匹配当前系统与架构的更新包，请查看发布页');
  const asset = found[0];
  if (!Number.isSafeInteger(asset.size) || asset.size <= 0 || asset.size > MAX_ARCHIVE) throw Error('更新包大小无效');
  releaseURL(asset.browser_download_url, repo, tag);
  const checksum = assets.find(a => a.name === asset.name + '.sha256');
  if (checksum) releaseURL(checksum.browser_download_url, repo, tag);
  if (!/^sha256:[a-f0-9]{64}$/i.test(asset.digest || '') && !checksum) throw Error('发布包缺少 SHA-256 校验信息');
  return {name:asset.name, url:asset.browser_download_url, bytes:asset.size,
    sha256:/^sha256:[a-f0-9]{64}$/i.test(asset.digest || '') ? asset.digest.slice(7).toLowerCase() : '', checksumUrl:checksum?.browser_download_url || ''};
}

function request(url, redirects = 0) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:' || parsed.username || parsed.password || redirects > 6) return reject(Error('下载重定向无效'));
    const req = https.get(parsed, {headers:{'User-Agent':'Umeko-Updater','Accept-Encoding':'identity'}}, res => {
      if ([301,302,303,307,308].includes(res.statusCode)) {
        res.resume();
        try {request(new URL(res.headers.location, url).href, redirects + 1).then(resolve, reject);}
        catch {reject(Error('下载重定向地址无效'));}
      } else if (res.statusCode === 200) resolve(res);
      else {res.resume(); reject(Error(`下载失败，HTTP ${res.statusCode}`));}
    });
    req.setTimeout(30000, () => req.destroy(Error('下载超时，请重试')));
    req.on('error', reject);
  });
}
async function digest(file) {
  const hash = createHash('sha256');
  for await (const chunk of fs.createReadStream(file)) hash.update(chunk);
  return hash.digest('hex');
}
export async function download(job, fetch = request) {
  const a = job.asset || selectAsset(job.assets || [], job.repo, job.version);
  if (!a || path.basename(a.name) !== a.name || !Number.isSafeInteger(a.bytes) || a.bytes <= 0 || a.bytes > MAX_ARCHIVE) throw Error('更新包信息无效');
  releaseURL(a.url, job.repo, job.version);
  let sha = a.sha256;
  if (!/^[a-f0-9]{64}$/.test(sha || '')) {
    releaseURL(a.checksumUrl, job.repo, job.version);
    const res = await fetch(a.checksumUrl); let raw = '';
    for await (const chunk of res) {raw += chunk; if (raw.length > 4096) throw Error('校验文件过大');}
    const match = /^([a-f0-9]{64})\s+\*?(.+?)\s*$/i.exec(raw);
    if (!match || match[2] !== a.name) throw Error('SHA-256 文件内容无效');
    sha = match[1].toLowerCase();
  }
  await fsp.mkdir(job.cache, {recursive:true, mode:0o700});
  const archive = path.join(job.cache, a.name), partial = archive + '.part';
  status('downloading', '正在下载新版本…', 0);
  let received = 0, last = 0;
  try {
    const response = await fetch(a.url);
    await pipeline(response, new Transform({transform(chunk, _, cb) {
      received += chunk.length;
      if (received > a.bytes) return cb(Error('更新包超过预期大小'));
      if (Date.now() - last > 150) {last = Date.now(); status('downloading', `正在下载… ${Math.round(received / a.bytes * 100)}%`, received / a.bytes);}
      cb(null, chunk);
    }}), fs.createWriteStream(partial, {mode:0o600}));
    status('verifying', '正在校验 SHA-256…');
    if (received !== a.bytes || await digest(partial) !== sha) throw Error('SHA-256 或文件大小校验失败，请重新下载');
    await fsp.rename(partial, archive);
    status('ready', 'SHA-256 校验通过，可以安装新版本。', 1, {archive, sha256:sha});
  } finally {await fsp.rm(partial, {force:true});}
}

// Never extract through an archive-created symlink, including directory links.
export function safeName(name) {
  name = name.replaceAll('\\', '/').replace(/\/$/, '');
  if (!name || name.startsWith('/') || name.includes(':') || /[\x00-\x1f]/.test(name) || name.split('/').some(p => !p || p === '..' || p === '.' || /[. ]$/.test(p) || /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)/i.test(p))) throw Error('更新包包含不安全路径：' + name);
  return name;
}
async function parentDirs(root, name) {
  let current = root;
  for (const part of name.split('/').slice(0, -1)) {
    current = path.join(current, part);
    if (await exists(current)) {if (!(await fsp.lstat(current)).isDirectory()) throw Error('更新包路径穿过链接或文件');}
    else await fsp.mkdir(current);
  }
}
function linkTarget(name, target) {
  if (target.includes('\\') || target.includes(':') || path.posix.isAbsolute(target)) throw Error('更新包包含不安全链接');
  const normalized = path.posix.normalize(path.posix.join(path.posix.dirname(name), target));
  if (normalized === '..' || normalized.startsWith('../')) throw Error('更新包链接越界');
}
async function readAt(file, position, size) {
  const buffer = Buffer.alloc(size);
  const {bytesRead} = await file.read(buffer, 0, size, position);
  if (bytesRead !== size) throw Error('更新包被截断');
  return buffer;
}
async function saveEntry(root, entry, stream, expanded) {
  const name = safeName(entry.name);
  if (name.startsWith('__MACOSX/')) {for await (const _ of stream) {} return;}
  await parentDirs(root, name);
  const dest = path.join(root, name);
  if (entry.type === 'directory') {
    if (entry.size !== 0) throw Error('更新包目录条目无效');
    for await (const _ of stream) {}
    if (await exists(dest)) {if (!(await fsp.lstat(dest)).isDirectory()) throw Error('更新包目录冲突');}
    else await fsp.mkdir(dest);
    return;
  }
  if (await exists(dest)) throw Error('更新包包含重复路径');
  let bytes = 0, crc = 0;
  const measure = new Transform({transform(chunk, _, cb) {
    bytes += chunk.length; expanded.value += chunk.length; crc = crc32(chunk, crc);
    if (bytes > entry.size || expanded.value > MAX_EXPANDED) return cb(Error('更新包解压大小超过限制'));
    cb(null, chunk);
  }});
  if (entry.type === 'symlink') {
    let target = entry.target;
    if (target === undefined) {
      let raw = '';
      for await (const chunk of stream) {
        bytes += chunk.length; expanded.value += chunk.length; crc = crc32(chunk,crc); raw += chunk;
        if (bytes > entry.size || bytes > 4096 || expanded.value > MAX_EXPANDED) throw Error('更新包链接过长');
      }
      target = raw;
    } else if (entry.size !== 0) throw Error('更新包链接条目无效');
    linkTarget(name, target); await fsp.symlink(target, dest);
  } else {
    await pipeline(stream, measure, fs.createWriteStream(dest, {flags:'wx',mode:(entry.mode & 0o777) || 0o644}));
  }
  if (entry.type !== 'symlink' || entry.target === undefined) {
    if (bytes !== entry.size || (entry.crc !== undefined && crc !== entry.crc)) throw Error('更新包文件校验失败');
  }
}

async function extractZip(archive, root) {
  const file = await fsp.open(archive); const expanded = {value:0};
  try {
    const size = (await file.stat()).size, tail = await readAt(file, Math.max(0,size-65557), Math.min(size,65557));
    let end = -1;
    for (let p = tail.length - 22; p >= 0; p--) if (tail.readUInt32LE(p) === 0x06054b50 && p + 22 + tail.readUInt16LE(p+20) === tail.length) {end = p; break;}
    if (end < 0 || tail.readUInt16LE(end+4) || tail.readUInt16LE(end+6)) throw Error('ZIP 格式无效');
    const count = tail.readUInt16LE(end+10); let offset = tail.readUInt32LE(end+16);
    if (count === 65535 || offset === 0xffffffff) throw Error('不支持 ZIP64 更新包');
    for (let i = 0; i < count; i++) {
      const h = await readAt(file,offset,46);
      if (h.readUInt32LE(0) !== 0x02014b50 || h.readUInt16LE(8) & 1) throw Error('ZIP 目录无效或已加密');
      const length = h.readUInt16LE(28), name = (await readAt(file,offset+46,length)).toString('utf8');
      const mode = h.readUInt32LE(38) >>> 16, method = h.readUInt16LE(10), packed = h.readUInt32LE(20), unpacked = h.readUInt32LE(24);
      const local = h.readUInt32LE(42), header = await readAt(file,local,30);
      if (header.readUInt32LE(0) !== 0x04034b50 || ![0,8].includes(method) || unpacked === 0xffffffff) throw Error('ZIP 文件格式不支持');
      const start = local + 30 + header.readUInt16LE(26) + header.readUInt16LE(28);
      if (start + packed > size) throw Error('ZIP 文件越界');
      const source = packed ? fs.createReadStream(archive,{start,end:start+packed-1}) : Readable.from([]);
      const stream = method === 8 ? source.pipe(createInflateRaw()) : source;
      source.on('error', error => stream.destroy(error));
      await saveEntry(root,{name,size:unpacked,mode,crc:h.readUInt32LE(16),type:name.endsWith('/')?'directory':(mode & 0o170000) === 0o120000?'symlink':'file'},stream,expanded);
      status('extracting', '正在展开新版本…', 0.15 + 0.65 * (i+1)/count);
      offset += 46 + length + h.readUInt16LE(30) + h.readUInt16LE(32);
    }
  } finally {await file.close();}
}

function tarText(buffer) {return buffer.toString('utf8').split('\0')[0];}
function tarNumber(buffer) {const n = parseInt(tarText(buffer).trim() || '0',8); if (!Number.isSafeInteger(n) || n < 0) throw Error('TAR 数值无效'); return n;}
async function extractTar(archive, root) {
  const tar = path.join(root, '.archive.tar'); let inflated = 0;
  await pipeline(fs.createReadStream(archive), createGunzip(), new Transform({transform(c,_,cb) {inflated += c.length; cb(inflated > MAX_EXPANDED ? Error('更新包过大') : null,c);}}),fs.createWriteStream(tar,{flags:'wx',mode:0o600}));
  const file = await fsp.open(tar); let offset = 0, pax = {}, global = {}, longName, longLink; const expanded = {value:0};
  try {
    while (offset + 512 <= inflated) {
      const h = await readAt(file,offset,512); if (h.every(b => b === 0)) break;
      const sum = h.reduce((a,b,i) => a + (i >= 148 && i < 156 ? 32 : b),0);
      if (sum !== tarNumber(h.subarray(148,156))) throw Error('TAR 头校验失败');
      const size = tarNumber(h.subarray(124,136)), type = String.fromCharCode(h[156]), start = offset + 512;
      if (start + size > inflated) throw Error('TAR 文件被截断');
      let name = tarText(h.subarray(0,100)), prefix = tarText(h.subarray(345,500)); if (prefix) name = prefix + '/' + name;
      if (['x','g','L','K'].includes(type)) {
        if (size > 1024*1024) throw Error('TAR 扩展信息过大');
        const raw = await readAt(file,start,size);
        if (type === 'L') longName = tarText(raw).replace(/\n$/,'');
        else if (type === 'K') longLink = tarText(raw).replace(/\n$/,'');
        else {
          const values = {}; let p = 0;
          while (p < raw.length) {const space = raw.indexOf(32,p), n = Number(raw.subarray(p,space).toString()); if (space < p || !Number.isSafeInteger(n) || n <= 0 || p+n > raw.length) throw Error('PAX 格式无效'); const line = raw.subarray(space+1,p+n-1).toString(), eq = line.indexOf('='); values[line.slice(0,eq)] = line.slice(eq+1); p += n;}
          if (type === 'g') global = {...global,...values}; else pax = values;
        }
      } else {
        const attrs = {...global,...pax}; name = attrs.path || longName || name;
        const target = attrs.linkpath || longLink || tarText(h.subarray(157,257));
        if (!['0','\0','5','2'].includes(type)) throw Error('更新包含不支持的 TAR 条目');
        const stream = size ? fs.createReadStream(tar,{start,end:start+size-1}) : Readable.from([]);
        await saveEntry(root,{name,size,mode:tarNumber(h.subarray(100,108)),type:type==='5'?'directory':type==='2'?'symlink':'file',target},stream,expanded);
        pax = {}; longName = longLink = undefined;
        status('extracting', '正在展开新版本…', 0.15 + 0.65 * start/inflated);
      }
      offset = start + Math.ceil(size/512)*512;
    }
  } finally {await file.close(); await fsp.rm(tar,{force:true});}
}

function insideDirectory(root, file) {
  const relative = path.relative(root, file);
  return relative !== '' && !path.isAbsolute(relative) && relative !== '..' && !relative.startsWith('..' + path.sep);
}
export async function prepare(job, jobFile) {
  const install = await fsp.realpath(job.installDir), executable = await fsp.realpath(job.executable);
  if (!insideDirectory(install,executable) || !await exists(path.join(install,job.resourceRelative,'build-info.json'))) throw Error('仅打包版支持安装更新；源码版本请使用 Git 更新');
  if (path.dirname(install) === install || !/^[a-f0-9]{64}$/.test(job.sha256 || '')) throw Error('安装任务无效');
  // Copy the running app and libraries out of the destination before Windows locks them.
  const helper = path.join(await fsp.realpath(path.dirname(jobFile)),'installer-runtime' + (process.platform === 'darwin' ? '.app' : ''));
  if (insideDirectory(install,helper)) throw Error('更新缓存目录不能位于安装目录内');
  if (await exists(helper)) throw Error('安装任务已存在，请重新下载');
  status('preparing','正在准备独立安装器…');
  await fsp.access(path.dirname(install),fs.constants.W_OK);
  await fsp.cp(install,helper,{recursive:true,dereference:false,verbatimSymlinks:true,preserveTimestamps:true});
  const helperExe = path.join(helper,path.relative(install,executable));
  await writeJSON(jobFile,{...job,installDir:install,executable,helperExe});
  status('prepared','独立安装器已准备就绪',1,{jobFile,helperExe});
}

async function renameRetry(source, target) {
  for (let attempt = 0; ; attempt++) {
    try {await fsp.rename(source,target); return;}
    catch (error) {if (attempt >= 30 || !['EPERM','EACCES','EBUSY'].includes(error.code)) throw error; await sleep(200);}
  }
}
export async function install(job, jobFile) {
  // The UI creates this marker only after it has loaded successfully. The parent
  // quits only after seeing it, so a failed helper launch never closes the app.
  status('waiting','正在等待主程序与所有 agent 退出…');
  const until = Date.now() + 120000;
  while (true) {
    if (await exists(jobFile+'.cancel')) throw Error('安装已取消，未修改现有版本。');
    try {process.kill(job.parentPid,0);} catch (error) {if (error.code === 'ESRCH') break; throw error;}
    if (Date.now() > until) throw Error('主程序尚未退出，未修改安装文件。请关闭其他窗口后重试。');
    await sleep(200);
  }
  if (!await exists(jobFile+'.commit')) throw Error('主程序未确认安装交接，未修改现有版本。');
  const installDir = await fsp.realpath(job.installDir);
  const lock = path.join(path.dirname(installDir),'.'+path.basename(installDir)+'.update-lock');
  await fsp.mkdir(lock); // one installer per destination
  let stage, backup, outcome, moved = false, activated = false;
  try {
    stage = await fsp.mkdtemp(path.join(path.dirname(installDir),'.umeko-stage-'));
    status('verifying','安装前再次校验 SHA-256…',0.05);
    if (await digest(job.archive) !== job.sha256) throw Error('安装包已改变，SHA-256 校验失败');
    const archiveName = job.archiveName || path.basename(job.archive);
    if (archiveName.endsWith('.zip')) await extractZip(job.archive,stage);
    else if (archiveName.endsWith('.tar.gz')) await extractTar(job.archive,stage);
    else throw Error('不支持的更新包格式');
    const payload = path.join(stage,job.payloadRelative), resource = path.join(payload,job.resourceRelative);
    const info = await readJSON(path.join(resource,'build-info.json'));
    if (String(info.version).replace(/^v/,'') !== job.version.replace(/^v/,'').replace(/-minimal$/,'')) throw Error('安装包版本与发布版本不一致');
    if (job.edition && info.edition !== job.edition) throw Error('安装包版本类型不匹配');
    const arch = {AMD64:'x64',x86_64:'x64',aarch64:'arm64',arm64:'arm64',x64:'x64'}[info.architecture];
    if (arch !== process.arch || info.system !== {win32:'Windows',darwin:'Darwin',linux:'Linux'}[process.platform]) throw Error('安装包系统或架构不匹配');
    const relativeExe = path.relative(installDir,await fsp.realpath(job.executable));
    const realPayload = await fsp.realpath(payload);
    for (const required of [relativeExe, path.join(job.resourceRelative,'runtime/update-engine.mjs'),path.join(job.resourceRelative,'runtime/node',process.platform==='win32'?'node.exe':'bin/node')]) {
      const file = path.join(payload,required);
      if (!insideDirectory(payload,file) || !(await fsp.stat(file)).isFile() || !insideDirectory(realPayload,await fsp.realpath(file))) throw Error('更新包缺少必要运行文件');
    }
    backup = installDir + '.previous-' + randomUUID();
    status('installing','正在安装新版本…',0.9);
    await renameRetry(installDir,backup); moved = true;
    try {await renameRetry(payload,installDir); activated = true;}
    catch (error) {await renameRetry(backup,installDir); moved = false; throw error;}
    await writeJSON(jobFile + '.result',{backup,installDir,version:job.version});
    outcome = {backup};
  } catch (error) {
    if (moved && !activated && !await exists(installDir)) {
      try {await renameRetry(backup,installDir);} catch (restore) {throw Error(`${error.message}；自动恢复失败，旧版本保存在 ${backup}：${restore.message}`);}
    }
    throw error;
  } finally {if (stage) await fsp.rm(stage,{recursive:true,force:true}).catch(()=>{}); await fsp.rmdir(lock).catch(()=>{});}
  status('complete','安装完成，点击确定启动新版本。',1,outcome);
}

async function cleanup(job, jobFile) {
  const ready = await readJSON(jobFile + '.ready'), until = Date.now() + 120000;
  while (true) {
    try {process.kill(ready.pid,0);} catch (error) {if (error.code === 'ESRCH') break; throw error;}
    if (Date.now() > until) return;
    await sleep(250);
  }
  const cache = path.dirname(jobFile);
  if (path.resolve(job.cache) !== cache || !await exists(jobFile+'.result') ||
    path.resolve(job.installDir).startsWith(cache + path.sep)) return;
  await fsp.rm(cache,{recursive:true,force:true,maxRetries:10,retryDelay:300});
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const [mode, jobFile] = process.argv.slice(2), job = await readJSON(jobFile);
    if (mode !== 'cleanup') logFile = jobFile + '.log';
    if (mode === 'download') await download(job);
    else if (mode === 'prepare') await prepare(job,jobFile);
    else if (mode === 'install') await install(job,jobFile);
    else if (mode === 'cleanup') await cleanup(job,jobFile);
    else throw Error('未知更新操作');
  } catch (error) {status('error',error.message); process.exitCode = 1;}
}
