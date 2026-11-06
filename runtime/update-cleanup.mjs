// Called by a successfully started application, never by the installer launch button.
import fs from 'node:fs/promises';
import path from 'node:path';

const uuid = '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}';
const packageName = /^Umeko-\d+\.\d+\.\d+-(?:windows|macos|linux)-(?:x64|arm64)-[a-f0-9]{7,40}(?:-\d+)?\.(?:zip|tar(?:-\d+)?\.gz)$/;
const read = async file => JSON.parse(await fs.readFile(file,'utf8'));
const entries = directory => fs.readdir(directory,{withFileTypes:true}).catch(error=>{if(error.code==='ENOENT')return [];throw error;});
const inside = (root,file) => {const rel=path.relative(root,file);return rel!=='' && rel!=='..' && !rel.startsWith('..'+path.sep) && !path.isAbsolute(rel);};
const overlaps = (a,b) => a===b || inside(a,b) || inside(b,a);
const alive = pid => {if(!Number.isSafeInteger(pid)||pid<=0)return false;try{process.kill(pid,0);return true;}catch(e){return e.code!=='ESRCH';}};

async function canonical(file) {
  try {return await fs.realpath(file);}
  catch(error) {if(error.code!=='ENOENT')throw error;const parent=path.dirname(file);if(parent===file)throw error;return path.join(await canonical(parent),path.basename(file));}
}

export async function cleanupStartup(context, options={}) {
  const remove=options.remove || (file=>fs.rm(file,{recursive:true,force:true,maxRetries:1,retryDelay:300}));
  const log=options.log || (value=>process.stderr.write(JSON.stringify(value)+'\n'));
  const report={removed:[],failed:[],refused:[]}, cutoff=options.cutoff ?? Date.now();
  const note=(kind,file,error)=>{report[kind].push(file);log({kind,path:file,...(error?{message:error.message}:{})});};
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
    const protectedPaths=[], handledBackups=new Set();
    const isProtected=file=>protectedPaths.some(p=>overlaps(p,file));
    async function erase(file, root, pattern) {
      const target=path.resolve(file);
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
        if(await canonical(job.installDir)!==install || await canonical(job.cache)!==directory)continue;
        let result;try {result=await read(file+'.result');}catch(error){if(error.code!=='ENOENT')throw error;}
        // A running download/preparer belongs to another current attempt.
        if(alive(job.parentPid) && !result) {
          for(const value of [directory,job.archive,job.stage])if(value)protectedPaths.push(path.resolve(value));
          continue;
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
        if(!old.version || old.system!==info.system || old.architecture!==info.architecture)continue;
        await fs.access(path.join(backup,path.relative(install,executable)));
        handledBackups.add(backup);
        await erase(backup,parent,backupName);
      } catch(error) {note('failed',backup,error);}
    }
    for(const item of jobs) {
      const {job,result,file,directory}=item;
      let done=true;
      if(result?.backup)done=handledBackups.has(path.resolve(result.backup)) ? ![...report.failed,...report.refused].includes(path.resolve(result.backup)) : await erase(result.backup,parent,backupName);
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
    const lock=path.join(parent,'.'+path.basename(install)+'.update-lock');
    let installing=false;try{await fs.access(lock);installing=true;}catch(error){if(error.code!=='ENOENT')throw error;}
    if(!installing)for(const entry of await entries(parent))if(entry.isDirectory() && /^\.umeko-stage-[A-Za-z0-9]{6}$/.test(entry.name))await erase(path.join(parent,entry.name),parent,/^\.umeko-stage-[A-Za-z0-9]{6}$/);
    const parts=path.join(downloads,'.umeko-downloads');let downloading=false;
    for(const entry of await entries(parts)) {
      if(!entry.isDirectory() || !/^[a-f0-9]{64}$/.test(entry.name))continue;
      const directory=path.join(parts,entry.name);
      try {
        let locked=false;try{locked=alive((await read(path.join(directory,'lock.json'))).pid);}catch(error){if(error.code!=='ENOENT')throw error;}
        if(locked){downloading=true;continue;}
        if((await fs.stat(directory)).mtimeMs>=cutoff)continue;
        await erase(directory,parts,/^[a-f0-9]{64}$/);
      } catch(error) {note('failed',directory,error);}
    }
    if(!downloading) {
      for(const entry of await entries(downloads))if(entry.isFile() && packageName.test(entry.name)) {
        const file=path.join(downloads,entry.name);
        if((await fs.stat(file)).mtimeMs<cutoff)await erase(file,downloads,packageName);
      }
      if(temporary)for(const entry of await entries(temporary))if(entry.isDirectory() && /^umeko-download-job-[a-z0-9_-]{8}$/.test(entry.name)) {
        const directory=path.join(temporary,entry.name);
        try {
          const job=await read(path.join(directory,'job.json'));
          if(await canonical(job.cache)===downloads && (await fs.stat(directory)).mtimeMs<cutoff)await erase(directory,temporary,/^umeko-download-job-[a-z0-9_-]{8}$/);
        } catch(error) {note('failed',directory,error);}
      }
    }
  } catch(error) {note('failed',context.installDir,error);}
  return report;
}
