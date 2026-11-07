// Called by a successfully started application, never by the installer launch button.
import fs from 'node:fs/promises';
import {createReadStream} from 'node:fs';
import {createHash, randomUUID} from 'node:crypto';
import path from 'node:path';

const uuid = '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}';
const packageName = /^(?:Umeko-\d+\.\d+\.\d+-(?:windows|macos|linux)-(?:x64|arm64)-[a-f0-9]{7,40}|UmekoCpp-v\d+\.\d+\.\d+(?:-minimal)?-(?:windows|macos|linux)-(?:x64|arm64))(?:-\d+)?\.(?:zip|tar(?:-\d+)?\.gz)$/;
const retention = 7 * 24 * 60 * 60 * 1000;
const read = async file => JSON.parse(await fs.readFile(file,'utf8'));
const entries = directory => fs.readdir(directory,{withFileTypes:true}).catch(error=>{if(error.code==='ENOENT')return [];throw error;});
const inside = (root,file) => {const rel=path.relative(root,file);return rel!=='' && rel!=='..' && !rel.startsWith('..'+path.sep) && !path.isAbsolute(rel);};
const overlaps = (a,b) => a===b || inside(a,b) || inside(b,a);
const alive = pid => {if(!Number.isSafeInteger(pid)||pid<=0)return false;try{process.kill(pid,0);return true;}catch(e){return e.code!=='ESRCH';}};
const versionParts = value => /^v?(\d+)\.(\d+)\.(\d+)(?:-minimal)?$/.exec(String(value))?.slice(1).map(Number);
function noNewer(candidate, current) {
  const a=versionParts(candidate), b=versionParts(current);
  if(!a || !b)return false;
  for(let i=0;i<3;i++)if(a[i]!==b[i])return a[i]<b[i];
  return true;
}
async function digest(file) {
  const hash=createHash('sha256');
  for await(const chunk of createReadStream(file))hash.update(chunk);
  return hash.digest('hex');
}
async function lastActivity(directory, ignore=[]) {
  const times=await Promise.all([directory,...(await fs.readdir(directory)).filter(name=>!ignore.includes(name)).map(name=>path.join(directory,name))]
    .map(file=>fs.lstat(file).then(stat=>stat.mtimeMs)));
  return Math.max(...times);
}
function matchingArchive(name, context, info) {
  const repo=context.repo || 'umeko-desktop';
  const match=repo==='umeko-desktop' ? /^Umeko-(\d+\.\d+\.\d+)-((?:windows|macos|linux)-(?:x64|arm64))-[a-f0-9]{7,40}(?:-\d+)?\.(?:zip|tar(?:-\d+)?\.gz)$/.exec(name) :
    /^UmekoCpp-v(\d+\.\d+\.\d+)(-minimal)?-((?:windows|macos|linux)-(?:x64|arm64))(?:-\d+)?\.(?:zip|tar(?:-\d+)?\.gz)$/.exec(name);
  if(!match || !noNewer(match[1],info.version))return false;
  const architecture=({AMD64:'x64',amd64:'x64',x86_64:'x64',x64:'x64',aarch64:'arm64',ARM64:'arm64',arm64:'arm64'})[info.architecture];
  const platform=({Windows:'windows',Darwin:'macos',Linux:'linux'}[info.system])+'-'+architecture;
  return repo==='umeko-desktop' ? match[2]===platform : match[3]===platform && !!match[2]===(info.edition==='minimal');
}

async function canonical(file) {
  try {return await fs.realpath(file);}
  catch(error) {if(error.code!=='ENOENT')throw error;const parent=path.dirname(file);if(parent===file)throw error;return path.join(await canonical(parent),path.basename(file));}
}

export async function cleanupStartup(context, options={}) {
  const remove=options.remove || (file=>fs.rm(file,{recursive:true,force:true,maxRetries:1,retryDelay:300}));
  const log=options.log || (value=>process.stderr.write(JSON.stringify(value)+'\n'));
  const report={removed:[],failed:[],refused:[]}, cutoff=options.cutoff ?? Date.now();
  const staleCutoff=options.cutoff ?? Date.now()-retention;
  const note=(kind,file,error)=>{report[kind].push(file);log({kind,path:file,...(error?{message:error.message}:{})});};
  let installLock;
  try {
    const install=await fs.realpath(context.installDir), profile=await canonical(context.profileDir);
    const updates=await canonical(context.updatesDir), downloads=await canonical(context.downloadsDir);
    const temporary=context.tempDir ? await canonical(context.tempDir) : null;
    const executable=await fs.realpath(context.executable);
    const resources=path.resolve(install,context.resourceRelative);
    if((resources!==install&&!inside(install,resources)) || !inside(install,executable))throw Error('更新清理的安装路径无效');
    const info=await read(path.join(resources,'build-info.json'));
    if(String(info.version).replace(/^v/,'')!==String(context.version).replace(/^v/,''))throw Error('更新清理的启动版本不匹配');
    if(overlaps(install,profile)||overlaps(updates,profile)||overlaps(downloads,profile)||overlaps(updates,install)||overlaps(downloads,install))throw Error('更新清理目录与程序或用户数据重叠');
    const parent=path.dirname(install), backupName=new RegExp('^'+path.basename(install).replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'\\.previous-'+uuid+'$');
    // Share install()'s lock for the entire sweep, including backup/job deletion.
    const lock=path.join(parent,'.'+path.basename(install)+'.update-lock');
    try{await fs.mkdir(lock);installLock=lock;}catch(error){if(error.code==='EEXIST')return report;throw error;}
    const current=await read(path.join(resources,'build-info.json'));
    if(current.version!==info.version || current.edition!==info.edition)return report;
    const protectedPaths=[], handledBackups=new Set();
    const isProtected=file=>protectedPaths.some(p=>overlaps(p,file));
    async function erase(file, root, pattern) {
      // Normalize parent aliases without following a symlink at the deletion leaf.
      const target=path.join(await canonical(path.dirname(path.resolve(file))),path.basename(file));
      if(path.dirname(target)!==root || !pattern.test(path.basename(target)) || isProtected(target) || overlaps(target,profile)||overlaps(target,install)) {note('refused',target);return false;}
      try {
        const stat=await fs.lstat(target);
        // Refuse directory aliases, including Windows junctions, even inside a trusted namespace.
        if(stat.isSymbolicLink() || path.dirname(await canonical(target))!==root)throw Error('拒绝更新目录之外的路径');
        await remove(target);note('removed',target);return true;
      } catch(error) {if(error.code==='ENOENT')return true;note('failed',target,error);return false;}
    }
    const jobs=[];
    for(const entry of await entries(updates)) {
      if(!entry.isDirectory() || !/^[a-f0-9]{32}$/.test(entry.name))continue;
      const directory=path.join(updates,entry.name), file=path.join(directory,'job.json');
      try {
        if(path.dirname(await canonical(directory))!==updates)throw Error('安装任务路径无效');
        const job=await read(file);
        if(job.profileDir)protectedPaths.push(await canonical(job.profileDir));
        if(await canonical(job.installDir)!==install || await canonical(job.cache)!==directory) {
          for(const value of [job.archive,job.stage])if(value)protectedPaths.push(await canonical(value));
          continue;
        }
        let result;try {result=await read(file+'.result');}catch(error){if(error.code!=='ENOENT')throw error;}
        // Preserve a package changed since installation, even when its name is recognized.
        if(job.archive && /^[a-f0-9]{64}$/.test(job.sha256 || '')) {
          try {
            const stat=await fs.lstat(job.archive);
            if(!stat.isFile() || stat.isSymbolicLink() || await digest(job.archive)!==job.sha256)protectedPaths.push(await canonical(job.archive));
          }catch(error){if(error.code!=='ENOENT')throw error;}
        }
        let ready;try{ready=await read(file+'.ready');}catch(error){if(error.code!=='ENOENT')throw error;}
        // A completed replacement can still have a live installer holding its helper files.
        if(alive(job.parentPid) || alive(ready?.pid) || !noNewer(job.version,info.version) ||
            job.edition && job.edition!==info.edition || job.repo && context.repo && job.repo!==context.repo ||
            !result && await lastActivity(directory)>=staleCutoff) {
          for(const value of [directory,job.archive,job.stage,result?.backup])if(value)protectedPaths.push(await canonical(value));
          continue;
        }
        if(result && (!result.installDir || await canonical(result.installDir)!==install || result.version!==job.version)) {
          if(result.backup)note('refused',await canonical(result.backup));
          throw Error('安装结果与任务不匹配');
        }
        jobs.push({directory,file,job,result});
      } catch(error) {note('failed',directory,error);}
    }
    // Old cleaners removed job records but left these uniquely named program backups.
    for(const entry of await entries(parent)) {
      if(!entry.isDirectory() || !backupName.test(entry.name))continue;
      const backup=path.join(parent,entry.name);
      try {
        const old=await read(path.join(backup,context.resourceRelative,'build-info.json'));
        if(!noNewer(old.version,info.version) || old.system!==info.system || old.architecture!==info.architecture || old.edition!==info.edition)continue;
        await fs.access(path.join(backup,path.relative(install,executable)));
        handledBackups.add(backup);
        await erase(backup,parent,backupName);
      } catch(error) {note('failed',backup,error);}
    }
    for(const item of jobs) {
      const {job,result,file,directory}=item;
      let done=true;
      if(result?.backup) {
        const backup=path.join(await canonical(path.dirname(path.resolve(result.backup))),path.basename(result.backup));
        if(handledBackups.has(backup))done=![...report.failed,...report.refused].includes(backup);
        else if(path.dirname(backup)===parent && backupName.test(path.basename(backup))) {
          // A receipt cannot override the metadata/edition checks of the backup sweep.
          try{await fs.lstat(backup);note('refused',backup);done=false;}catch(error){if(error.code!=='ENOENT')throw error;}
        } else done=await erase(backup,parent,backupName);
      }
      if(job.stage)done=await erase(job.stage,parent,/^\.umeko-stage-[A-Za-z0-9]{6}$/) && done;
      // A failed removal keeps its receipt for the next successful startup.
      if(done)done=await erase(directory,updates,/^[a-f0-9]{32}$/);
      if(!done) {
        // Recursive deletion may remove the JSON before encountering a locked
        // helper DLL. Restore the small receipt so the next start can retry.
        try {
          await fs.mkdir(directory,{recursive:true});
          await fs.writeFile(file,JSON.stringify(job),{mode:0o600});
          if(result)await fs.writeFile(file+'.result',JSON.stringify(result),{mode:0o600});
          await fs.writeFile(file+'.started',JSON.stringify(context),{mode:0o600});
        } catch(error) {note('failed',file,error);}
      }
    }
    // Historical interrupted extraction had no receipt. Only the engine's own
    // six-character staging namespace is eligible, and never an active install.
    const siblings=await entries(parent);
    const otherInstalling=siblings.some(entry=>entry.isDirectory() && entry.name!==path.basename(installLock) && /^\..+\.update-lock$/.test(entry.name));
    if(!otherInstalling)for(const entry of siblings)if(entry.isDirectory() && /^\.umeko-stage-[A-Za-z0-9]{6}$/.test(entry.name))await erase(path.join(parent,entry.name),parent,/^\.umeko-stage-[A-Za-z0-9]{6}$/);
    const parts=path.join(downloads,'.umeko-downloads');let downloading=false;
    try{if((await fs.lstat(parts)).isSymbolicLink())throw Error('下载缓存目录无效');}catch(error){if(error.code!=='ENOENT')throw error;}
    for(const entry of await entries(parts)) {
      if(!entry.isDirectory() || !/^[a-f0-9]{64}$/.test(entry.name))continue;
      const directory=path.join(parts,entry.name);
      try {
        let locked=false;try{locked=alive((await read(path.join(directory,'lock.json'))).pid);}catch(error){if(error.code!=='ENOENT')throw error;}
        if(locked){downloading=true;continue;}
        if(await lastActivity(directory)>=staleCutoff)continue;
        // Claim download()'s exclusive lock and recheck activity after acquiring it.
        const lockFile=path.join(directory,'lock.json'), token=randomUUID();
        try{const previous=await fs.readFile(lockFile,'utf8');const owner=JSON.parse(previous);
          if(!Number.isSafeInteger(owner.pid)||owner.pid<=0||alive(owner.pid)){downloading=true;continue;}
          if(await fs.readFile(lockFile,'utf8')!==previous)continue;
          await fs.unlink(lockFile);
        }catch(error){if(error.code!=='ENOENT')throw error;}
        let handle;try{handle=await fs.open(lockFile,'wx',0o600);}catch(error){if(error.code==='EEXIST'){downloading=true;continue;}throw error;}
        try {
          await handle.writeFile(JSON.stringify({pid:process.pid,token}));await handle.close();handle=null;
          const recent=await Promise.all((await fs.readdir(directory)).filter(name=>name!=='lock.json').map(name=>fs.lstat(path.join(directory,name)).then(stat=>stat.mtimeMs>=staleCutoff)));
          if(!recent.some(Boolean))await erase(directory,parts,/^[a-f0-9]{64}$/);
        }finally{
          await handle?.close();
          try{if((await read(lockFile)).token===token)await fs.unlink(lockFile);}catch(error){if(error.code!=='ENOENT')throw error;}
        }
      } catch(error) {note('failed',directory,error);}
    }
    if(!downloading) {
      for(const entry of await entries(downloads))if(entry.isFile() && matchingArchive(entry.name,context,info)) {
        const file=path.join(downloads,entry.name);
        if((await fs.stat(file)).mtimeMs<cutoff)await erase(file,downloads,packageName);
      }
      if(temporary)for(const entry of await entries(temporary))if(entry.isDirectory() && /^umeko-download-job-[a-z0-9_-]{8}$/.test(entry.name)) {
        const directory=path.join(temporary,entry.name);
        try {
          const job=await read(path.join(directory,'job.json'));
          if(await canonical(job.cache)===downloads && !alive(job.parentPid) && await lastActivity(directory)<staleCutoff)await erase(directory,temporary,/^umeko-download-job-[a-z0-9_-]{8}$/);
        } catch(error) {note('failed',directory,error);}
      }
    }
  } catch(error) {note('failed',context.installDir,error);}
  finally {if(installLock)await fs.rmdir(installLock).catch(error=>{note('failed',installLock,error);});}
  return report;
}
