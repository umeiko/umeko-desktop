// Shared Pi installer: all paths use the embedded CLI; no shell evaluation.
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import tls from 'node:tls';
import {spawn} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import {createInterface} from 'node:readline';
import {pipeline} from 'node:stream/promises';
import {Transform} from 'node:stream';
import {setTimeout as delay} from 'node:timers/promises';
import {updateRequest, updateCertificates, extractPackageArchive} from './update-engine.mjs';

const PACKAGE='@earendil-works/pi-coding-agent';
const MAX_ARCHIVE=256*1024**2;
export const safeMessage = value => String(value || '').replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'').replace(/(https?:\/\/)[^\s/@]+@/g,'$1***@').replace(/\bBearer\s+[^\s,;]+/gi,'Bearer ***').replace(/((?:_authToken|authorization|password|token)\s*[:=]\s*)[^\s,;]+/gi,'$1***').slice(-1800);
const abortError=()=>Object.assign(Error('安装已取消'),{code:'ABORT_ERR'});
function check(signal) { if(signal?.aborted)throw abortError(); }
export function retryable(error) {
  if(error?.code==='ABORT_ERR')return false;
  const text=String(error?.message || error);
  if(/\b(E404|ETARGET|E401|E403|EBADENGINE|ERESOLVE)\b|path does not exist|not found.*version|repository not found|not a pi|invalid (?:package|source)|归档|ZIP |不支持|没有 Pi|不是 Pi/i.test(text))return false;
  return /\b(EAI_AGAIN|ENOTFOUND|ECONN\w*|ETIMEDOUT|EHOSTUNREACH|ENETUNREACH|EINTEGRITY|ERR_TLS\w*|CERT_\w*|UNABLE_TO_\w*|SELF_SIGNED\w*|DEPTH_ZERO_SELF_SIGNED_CERT)\b|network|fetch failed|socket|timed? ?out|TLS|certificate|SSL|unexpected end|HTTP (408|429|5\d\d)|connection|网络|超时/i.test(text);
}
export function networkProfiles(proxy, caFile) {
  const routes=proxy ? [proxy.replace(/^socks5:/,'socks5h:'),''] : [''];
  const trusts=caFile ? [caFile,''] : [''];
  return routes.flatMap(route=>trusts.map(ca=>({proxy:route,caFile:ca,label:(route?'系统代理':'直连')+' · '+(ca?'自定义 CA':'系统证书')})));
}
export function profileEnvironment(base, profile) {
  const env={...base};
  for(const key of Object.keys(env))if(/^(https?_proxy|all_proxy|no_proxy|npm_config_(https?_proxy|proxy|cafile|ca|strict_ssl|offline|fetch_retries|fetch_timeout)|node_extra_ca_certs|node_tls_reject_unauthorized|git_ssl_no_verify|git_ssl_cainfo)$/i.test(key))delete env[key];
  env.npm_config_proxy=profile.proxy;env.npm_config_https_proxy=profile.proxy;
  env.npm_config_cafile=profile.caFile;env.npm_config_ca='';
  env.npm_config_strict_ssl='true';env.npm_config_fetch_retries='0';env.npm_config_fetch_timeout='20000';
  delete env.GIT_SSL_NO_VERIFY;env.NODE_USE_SYSTEM_CA='1';
  // Command-scope Git overrides leave the user's Git configuration untouched.
  let count=Number(env.GIT_CONFIG_COUNT || 0);if(!Number.isInteger(count)||count<0||count>64)count=0;
  for(const [key,value] of [['http.proxy',profile.proxy],['http.sslVerify','true'],...((profile.gitCaFile||profile.caFile) ? [['http.sslCAInfo',profile.gitCaFile||profile.caFile]] : []),...(profile.gitURL?.startsWith('https://') ? [['http.'+profile.gitURL+'.sslVerify','true'],['http.'+profile.gitURL+'.proxy',profile.proxy]] : []),['http.lowSpeedLimit','1'],['http.lowSpeedTime','20']]) {
    env['GIT_CONFIG_KEY_'+count]=key;env['GIT_CONFIG_VALUE_'+count]=value;count++;
  }
  env.GIT_CONFIG_COUNT=String(count);
  if(profile.proxy) {env.HTTPS_PROXY=profile.proxy;env.HTTP_PROXY=profile.proxy;env.ALL_PROXY=profile.proxy;}
  else env.NO_PROXY='*';
  if(profile.caFile)env.NODE_EXTRA_CA_CERTS=profile.caFile;
  if(profile.gitCaFile||profile.caFile)env.GIT_SSL_CAINFO=profile.gitCaFile||profile.caFile;
  return env;
}
export async function runProcess(program,args,{cwd,env,signal,timeout=45000}={}) {
  check(signal);
  return new Promise((resolve,reject)=>{
    const child=spawn(program,args,{cwd,env,windowsHide:true,detached:process.platform!=='win32',stdio:['ignore','pipe','pipe']});
    let output='',stopped=false,expired=false;
    const collect=data=>{output=(output+data.toString()).slice(-24000);};
    child.stdout.on('data',collect);child.stderr.on('data',collect);
    const stop=()=>{
      if(stopped || !child.pid)return;stopped=true;
      if(process.platform==='win32') {
        const killer=spawn('taskkill',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});killer.on('error',()=>child.kill());
      } else {try{process.kill(-child.pid,'SIGTERM');}catch{};const forced=setTimeout(()=>{try{process.kill(-child.pid,'SIGKILL');}catch{}},500);forced.unref();}
    };
    const cancel=()=>stop();signal?.addEventListener('abort',cancel,{once:true});
    const timer=setTimeout(()=>{expired=true;stop();},timeout);
    const finish=(error)=>{clearTimeout(timer);signal?.removeEventListener('abort',cancel);if(error)reject(error);else resolve(output);};
    child.on('error',error=>finish(error));
    child.on('close',code=>finish(signal?.aborted ? abortError() : expired ? Object.assign(Error('网络尝试超时 ETIMEDOUT'),{code:'ETIMEDOUT'}) : code ? Error(safeMessage(output)||'安装进程退出：'+code) : null));
  });
}
function npmCLI() {
  const nodeDir=path.dirname(process.execPath);
  const candidates=[path.join(nodeDir,'node_modules/npm/bin/npm-cli.js'),path.join(nodeDir,'../lib/node_modules/npm/bin/npm-cli.js')];
  for(const entry of (process.env.PATH||'').split(path.delimiter)) {
    try{const file=fs.realpathSync(path.join(entry,process.platform==='win32'?'npm.cmd':'npm'));if(file.endsWith('.js'))candidates.push(file);}catch{}
    candidates.push(path.join(entry,'node_modules/npm/bin/npm-cli.js'));
  }
  candidates.push('/usr/share/nodejs/npm/bin/npm-cli.js','/usr/local/lib/node_modules/npm/bin/npm-cli.js');
  const file=candidates.find(file=>fs.existsSync(file));if(!file)throw Error('内置 npm 缺失，请重新解压完整应用');return file;
}
async function commandValue(program,args,run,env,cwd,signal) {
  try{return (await run(program,args,{cwd,env,signal,timeout:2500})).trim();}catch(error){check(signal);return '';}
}
// UI hosts pass their existing Qt/PAC resolver's result. Agent commands can also
// discover manual desktop settings asynchronously when they have no host proxy.
export async function systemProxy(url,run=runProcess,env=process.env,signal) {
  const host=new URL(url).hostname;
  if(String(env.no_proxy||env.NO_PROXY||'').split(',').some(item=>{const rule=item.trim().replace(/^\./,'').replace(/:\d+$/,'');return rule==='*'||rule && (host===rule||host.endsWith('.'+rule));}))return '';
  for(const key of ['https_proxy','HTTPS_PROXY','all_proxy','ALL_PROXY','http_proxy','HTTP_PROXY'])if(env[key])return env[key].includes('://')?env[key]:'http://'+env[key];
  if(process.platform==='linux') {
    const get=async(schema,key)=>(await commandValue('gsettings',['get','org.gnome.system.proxy'+schema,key],run,env,undefined,signal)).replace(/^'|'$/g,'');
    if(await get('','mode')==='manual')for(const schema of ['.https','.http','.socks']) {
      const [address,port]=await Promise.all([get(schema,'host'),get(schema,'port')]);
      if(address && /^\d+$/.test(port) && Number(port)>0 && Number(port)<=65535)return (schema==='.socks'?'socks5://':'http://')+address+':'+port;
    }
  } else if(process.platform==='darwin') {
    const data=await commandValue('/usr/sbin/scutil',['--proxy'],run,env,undefined,signal);
    const value=key=>data.match(new RegExp('\\b'+key+'\\s*:\\s*(\\S+)'))?.[1];
    for(const kind of ['HTTPS','HTTP','SOCKS'])if(value(kind+'Enable')==='1' && value(kind+'Proxy'))return (kind==='SOCKS'?'socks5://':'http://')+value(kind+'Proxy')+':'+value(kind+'Port');
  } else if(process.platform==='win32') {
    const script="$p=Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings';if($p.ProxyEnable){$p.ProxyServer}";
    const data=await commandValue('powershell.exe',['-NoProfile','-NonInteractive','-Command',script],run,env,undefined,signal);
    const proxy=data.match(/(?:^|;)https=([^;]+)/)?.[1] || data.match(/(?:^|;)http=([^;]+)/)?.[1] || (!data.includes('=')?data:'');
    if(proxy)return proxy.includes('://')?proxy:'http://'+proxy;
  }
  return '';
}
export async function downloadArchive(url,file,profile,{signal,request=updateRequest,integrity}={}) {
  const ca=[...new Set([...updateCertificates(kind=>kind==='default'?tls.rootCertificates:(tls.getCACertificates?.('system') || [])),...(profile.caFile?[await fsp.readFile(profile.caFile,'utf8')]:[])])];
  const response=await request(url,{proxy:profile.proxy,ca,signal,connectTimeout:20000});
  if(response.statusCode!==200){response.resume();throw Error('HTTP '+response.statusCode);}
  if(Number(response.headers['content-length'])>MAX_ARCHIVE){response.destroy();throw Error('插件归档过大');}
  let bytes=0;const meter=new Transform({transform(chunk,_,done){bytes+=chunk.length;done(bytes>MAX_ARCHIVE?Error('插件归档过大'):null,chunk);}});
  await pipeline(response,meter,fs.createWriteStream(file,{flags:'wx',mode:0o600}),{signal});
  if(integrity) {
    const value=integrity.split(/\s+/).find(value=>/^sha512-[A-Za-z0-9+/=]+$/.test(value)) || integrity.split(/\s+/).find(value=>/^sha1-[A-Za-z0-9+/=]+$/.test(value));
    if(!value)throw Error('EINTEGRITY 软件源没有提供受支持的完整性校验');
    const [algorithm,digest]=value.split('-'),hash=createHash(algorithm);
    for await(const chunk of fs.createReadStream(file)){check(signal);hash.update(chunk);}
    if(hash.digest('base64')!==digest)throw Error('EINTEGRITY 离线包完整性校验失败');
  }
}
async function packageRoot(folder) {
  const ready=async dir=>{
    try {
      const manifest=JSON.parse(await fsp.readFile(path.join(dir,'manifest.json'),'utf8'));
      if(manifest.kind?.startsWith('umeko-'))throw Error('这不是 Pi 扩展包，请在对应的 Widget 或供应商页面导入');
    }catch(error){if(error.code!=='ENOENT' && !(error instanceof SyntaxError))throw error;}
    if(fs.existsSync(path.join(dir,'package.json')))return true;
    return ['extensions','skills','prompts','themes'].some(name=>fs.existsSync(path.join(dir,name)));
  };
  if(await ready(folder))return folder;
  const children=await fsp.readdir(folder,{withFileTypes:true});
  const directories=children.filter(item=>item.isDirectory());
  if(directories.length===1 && await ready(path.join(folder,directories[0].name)))return path.join(folder,directories[0].name);
  throw Error('离线包没有 Pi 插件入口或 package.json');
}
export async function installPackage(input,options={}) {
  const {signal,onProgress=()=>{},run=runProcess,download=downloadArchive,extract=extractPackageArchive,sleep=(ms)=>delay(ms,undefined,{signal})}=options;
  const source=String(input.source||'').trim();
  if(!source || source.startsWith('-') || source.length>4096 || /[\r\n\0]/.test(source))throw Error('Invalid source');
  const cwd=path.resolve(input.cwd),agentDir=path.resolve(input.agentDir),release=path.resolve(input.release);
  const base={...process.env,...input.environment,PI_CODING_AGENT_DIR:agentDir,PI_SKIP_VERSION_CHECK:'1',NO_COLOR:'1',NODE_USE_SYSTEM_CA:'1'};
  delete base.NODE_OPTIONS;delete base.NODE_PATH;delete base.PI_OFFLINE;delete base.NODE_TLS_REJECT_UNAUTHORIZED;
  const state=path.join(agentDir,'umeko-install-cache');await fsp.mkdir(state,{recursive:true});base.npm_config_cache=path.join(state,'npm');
  const cli=path.join(release,'node_modules',PACKAGE,'dist/cli.js');
  const native=(value,env)=>run(process.execPath,[cli,'install',value,input.local?'--approve':'--no-approve',...(input.local?['--local']:[])],{cwd,env,signal,timeout:input.attemptTimeout||180000});
  const archive=/\.(zip|tgz|tar\.gz)(?:[?#].*)?$/i.test(source);
  const remote=source.startsWith('npm:') || /^(git:|https?:\/\/|ssh:|git@)/i.test(source);
  if(!remote && !archive)return native(source,base);
  if(/^http:\/\//i.test(source))throw Error('离线包和 Git 下载地址须使用 HTTPS');
  const npm=source.startsWith('npm:');
  let git;
  if(remote && !npm && !archive) {
    const {parseGitUrl}=await import(pathToFileURL(path.join(release,'node_modules',PACKAGE,'dist/utils/git.js')));
    git=parseGitUrl(source);
  }
  const target=npm ? base.npm_config_registry || 'https://registry.npmjs.org' : remote ? git?.repo?.replace(/^git:/,'https:') || source : 'https://registry.npmjs.org';
  const proxy=input.proxy===undefined?await systemProxy(/^https?:/.test(target)?target:'https://github.com',run,base,signal):input.proxy;
  let caFile=input.caFile || base.npm_config_cafile || base.NODE_EXTRA_CA_CERTS || '';
  let npmFile;
  const getNpm=()=>npmFile ||= npmCLI();
  if(!caFile)try{const raw=await commandValue(process.execPath,[getNpm(),'config','get','cafile','--json'],run,base,cwd,signal);const value=JSON.parse(raw);if(typeof value==='string')caFile=value;}catch{}
  const profiles=networkProfiles(proxy,caFile);
  const environmentFor=async profile=>{
    const roots=updateCertificates(kind=>kind==='default'?tls.rootCertificates:(tls.getCACertificates?.('system') || []));
    const pem=roots.join('\n')+(profile.caFile?'\n'+await fsp.readFile(profile.caFile,'utf8'):'');
    const gitCaFile=path.join(state,'ca-'+createHash('sha256').update(pem).digest('hex').slice(0,16)+'.pem');
    if(!fs.existsSync(gitCaFile))await fsp.writeFile(gitCaFile,pem,{mode:0o600});
    return profileEnvironment(base,{...profile,gitCaFile,gitURL:git?.repo});
  };
  const localArchive=archive && !remote;
  let round=0;
  while(true) {
    check(signal);round++;
    const failures=[],definitive=[];
    const recordFailure=(error,profile)=>{
      failures.push(error);
      // A reachable direct registry can establish a missing version or invalid
      // credentials even when another proxy route only reports a network error.
      if(npm && !profile.proxy && /\b(E404|ETARGET|E401|EBADENGINE|ERESOLVE)\b/.test(String(error.message)))definitive.push(error);
    };
    if(!archive)for(let index=0;index<profiles.length;index++) {
      const profile=profiles[index];
      onProgress({message:`正在安装 · ${profile.label}（${index+1}/${profiles.length}，第 ${round} 轮）`,stage:'native',round});
      try{return await native(source,await environmentFor(profile));}catch(error){check(signal);recordFailure(error,profile);}
    }
    // Download first, then install from a prepared local package / offline npm
    // cache. Work directories are private and never registered before success.
    const archiveURL=archive && remote ? source : git?.host==='github.com' ? `https://api.github.com/repos/${git.path}/zipball/${encodeURIComponent(git.ref || 'HEAD')}` : '';
    if(npm || archive || archiveURL)for(let index=0;index<profiles.length;index++) {
      const profile=profiles[index];
      const temporary=await fsp.mkdtemp(path.join(state,'preparing-'));let keep='';
      try {
        const env=await environmentFor(profile);
        onProgress({message:`正在下载离线包 · ${profile.label}（${index+1}/${profiles.length}）`,stage:'download',round});
        if(npm) {
          let tarball;
          try {
            // Metadata is small; stream the package itself with the updater's
            // idle timeout, so a large but progressing download is not cut off.
            const raw=await run(process.execPath,[getNpm(),'view',source.slice(4),'name','version','dist','--json'],{cwd,env,signal,timeout:30000});
            let metadata=JSON.parse(raw);if(Array.isArray(metadata))metadata=metadata.at(-1);
            const dist=metadata.dist;
            if(!dist?.tarball?.startsWith('https://') || !dist.integrity)throw Error('软件源需要通过 npm 下载');
            tarball=path.join(temporary,'download.tgz');
            await download(dist.tarball,tarball,profile,{signal,integrity:dist.integrity});
          } catch(error) {
            check(signal);
            // npm retains scoped authentication for private registries; never
            // copy a registry token into our generic HTTP/redirect transport.
            const raw=await run(process.execPath,[getNpm(),'pack',source.slice(4),'--json','--ignore-scripts','--pack-destination',temporary],{cwd,env,signal,timeout:180000});
            const metadata=JSON.parse(raw.slice(raw.indexOf('[')));const name=metadata[0]?.filename;
            if(!name || path.basename(name)!==name)throw Error('npm 离线包文件名无效');
            tarball=path.join(temporary,name);
          }
          if((await fsp.stat(tarball)).size>MAX_ARCHIVE)throw Error('插件归档过大');
          await run(process.execPath,[getNpm(),'install','--prefix',path.join(temporary,'deps'),tarball,'--ignore-scripts','--no-audit','--no-fund','--legacy-peer-deps'],{cwd,env,signal,timeout:90000});
          onProgress({message:'离线包已就绪，正在通过内嵌 Pi 安装…',stage:'offline',round});
          return await native(source,{...env,npm_config_offline:'true'});
        }
        const suffix=localArchive ? (source.toLowerCase().endsWith('.zip')?'.zip':'.tgz') : archiveURL && /\.(tgz|tar\.gz)(?:[?#].*)?$/i.test(archiveURL)?'.tgz':'.zip';
        const file=path.join(temporary,'package'+suffix);
        if(localArchive)await fsp.copyFile(path.resolve(cwd,source),file);else await download(archiveURL,file,profile,{signal});
        const unpacked=path.join(temporary,'unpacked');await extract(file,unpacked);
        const folder=await packageRoot(unpacked);
        if(fs.existsSync(path.join(folder,'package.json'))) {
          const pkg=JSON.parse(await fsp.readFile(path.join(folder,'package.json'),'utf8'));
          if(Object.keys(pkg.dependencies||{}).length || Object.keys(pkg.optionalDependencies||{}).length)
            await run(process.execPath,[getNpm(),'install','--prefix',folder,'--omit=dev','--no-audit','--no-fund','--legacy-peer-deps'],{cwd,env,signal,timeout:90000});
        }
        check(signal);
        const root=path.join(input.local?path.join(cwd,'.pi'):agentDir,'umeko-packages');await fsp.mkdir(root,{recursive:true});
        keep=await fsp.mkdtemp(path.join(root,createHash('sha256').update(source).digest('hex').slice(0,12)+'-'));
        // rename stays on the same agent volume for global installs; project
        // archives can cross filesystems, so cp is deliberately used here.
        await fsp.cp(folder,keep,{recursive:true,dereference:false});
        onProgress({message:'离线包已校验并展开，正在通过内嵌 Pi 安装…',stage:'offline',round});
        const result=await native(keep,{...env,npm_config_offline:'true'});keep='';return result;
      } catch(error) {
        check(signal);recordFailure(error,profile);
        if(localArchive)throw Error('Pi 安装失败：'+safeMessage(error.message));
      } finally {
        if(keep)await fsp.rm(keep,{recursive:true,force:true,maxRetries:3,retryDelay:100});
        await fsp.rm(temporary,{recursive:true,force:true,maxRetries:3,retryDelay:100});
      }
    }
    const last=failures.at(-1);if(!last)throw Error('不支持这个 Pi 安装来源');
    if(definitive.length)throw Error('Pi 安装失败：'+safeMessage(definitive.at(-1).message));
    if(!failures.some(retryable))throw Error('Pi 安装失败：'+safeMessage(last.message));
    const seconds=Math.min(30,2**Math.min(round,5));
    onProgress({message:`连接暂不可用，${seconds} 秒后重试；可随时取消。${safeMessage(last.message).slice(-160)}`,stage:'waiting',round});
    if(input.maxRounds && round>=input.maxRounds)throw last; // bounded fixtures; UI continues until cancelled.
    await sleep(seconds*1000);
  }
}
if(process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  const controller=new AbortController();let started=false,finished=false;
  const emit=value=>process.stdout.write(JSON.stringify(value)+'\n');
  const lines=createInterface({input:process.stdin});
  const cancel=()=>controller.abort();
  lines.on('close',()=>{if(started && !finished)cancel();});process.on('SIGTERM',cancel);process.on('SIGINT',cancel);
  lines.on('line',line=>{
    if(started){try{if(JSON.parse(line).cancel)cancel();}catch{};return;}
    started=true;
    let input;try{if(Buffer.byteLength(line)>32768)throw Error('安装请求过大');input=JSON.parse(line);}catch(error){emit({type:'result',ok:false,error:safeMessage(error.message)});lines.close();process.stdin.pause();return;}
    installPackage(input,{signal:controller.signal,onProgress:progress=>emit({type:'progress',...progress})})
      .then(output=>emit({type:'result',ok:true,output:safeMessage(output)}),error=>{emit({type:'result',ok:false,cancelled:controller.signal.aborted,error:safeMessage(error.message)});process.exitCode=1;})
      .finally(()=>{finished=true;lines.close();process.stdin.pause();});
  });
}
