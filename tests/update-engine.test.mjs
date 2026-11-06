import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createHash, randomUUID} from 'node:crypto';
import {deflateRawSync, gzipSync, crc32} from 'node:zlib';
import {Readable} from 'node:stream';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {fileURLToPath} from 'node:url';
import {selectAsset, download, install, prepare, platformKey, safeName} from '../runtime/update-engine.mjs';
import {cleanupStartup} from '../runtime/update-cleanup.mjs';

const sha = b => createHash('sha256').update(b).digest('hex');
const repo = 'umeko-desktop-cpp', version = 'v0.3.0';
const url = name => `https://github.com/umeiko/${repo}/releases/download/${version}/${name}`;
const exe = process.platform === 'win32' ? 'UmekoCpp.exe' : 'UmekoCpp';
const system = {linux:'Linux',darwin:'Darwin',win32:'Windows'}[process.platform];
const info = {version:'0.3.0',system,architecture:process.arch};
function zip(entries) {
  const parts=[], central=[]; let offset=0;
  for (const e of entries) {
    const name=Buffer.from(e.name), raw=Buffer.from(e.raw || ''), data=deflateRawSync(raw), mode=e.mode || 0o100644;
    const h=Buffer.alloc(30); h.writeUInt32LE(0x04034b50); h.writeUInt16LE(20,4); h.writeUInt16LE(8,8);
    h.writeUInt32LE(crc32(raw),14); h.writeUInt32LE(data.length,18); h.writeUInt32LE(raw.length,22); h.writeUInt16LE(name.length,26);
    const c=Buffer.alloc(46); c.writeUInt32LE(0x02014b50); c.writeUInt16LE(0x314,4); c.writeUInt16LE(20,6); c.writeUInt16LE(8,10);
    c.writeUInt32LE(crc32(raw),16); c.writeUInt32LE(data.length,20); c.writeUInt32LE(raw.length,24); c.writeUInt16LE(name.length,28);
    c.writeUInt32LE((mode<<16)>>>0,38); c.writeUInt32LE(offset,42);
    parts.push(h,name,data); central.push(c,name); offset+=h.length+name.length+data.length;
  }
  const cd=Buffer.concat(central), end=Buffer.alloc(22); end.writeUInt32LE(0x06054b50); end.writeUInt16LE(entries.length,8); end.writeUInt16LE(entries.length,10); end.writeUInt32LE(cd.length,12); end.writeUInt32LE(offset,16);
  return Buffer.concat([...parts,cd,end]);
}
function tar(entries) {
  const parts=[];
  for (const e of entries) {
    const h=Buffer.alloc(512), raw=Buffer.from(e.raw||''); h.write(e.name,0,100);
    const oct=(n,start,length)=>h.write(n.toString(8).padStart(length-1,'0')+'\0',start,length);
    oct(e.mode||0o755,100,8); oct(0,108,8); oct(0,116,8); oct(e.target?0:raw.length,124,12); oct(0,136,12);
    h.fill(32,148,156); h[156]=(e.target?'2':'0').charCodeAt(0); if(e.target)h.write(e.target,157,100); h.write('ustar\0',257);
    oct(h.reduce((a,b)=>a+b,0),148,8); parts.push(h);
    if(!e.target)parts.push(raw,Buffer.alloc((512-raw.length%512)%512));
  }
  return gzipSync(Buffer.concat([...parts,Buffer.alloc(1024)]));
}
const entries = (extra=[]) => [
  {name:'UmekoCpp/'+exe,raw:'new app',mode:0o100755},
  {name:'UmekoCpp/build-info.json',raw:JSON.stringify(info)},
  {name:'UmekoCpp/runtime/update-engine.mjs',raw:'// updater'},
  {name:'UmekoCpp/runtime/node/'+(process.platform==='win32'?'node.exe':'bin/node'),raw:'node',mode:0o100755},
  ...extra,
];
async function fixture(t, bytes, suffix='.zip') {
  const base=await fs.mkdtemp(path.join(os.tmpdir(),'umeko-update-test-'));t.after(()=>fs.rm(base,{recursive:true,force:true}));
  const installDir=path.join(base,'installed'); await fs.mkdir(installDir); await fs.writeFile(path.join(installDir,exe),'old app');
  const archive=path.join(base,'update'+suffix);await fs.writeFile(archive,bytes);
  const child=spawn(process.execPath,['-e','']); await once(child,'exit');
  const job={installDir,executable:path.join(installDir,exe),archive,sha256:sha(bytes),version,payloadRelative:'UmekoCpp',resourceRelative:'',parentPid:child.pid};
  const jobFile=path.join(base,'job.json');await fs.writeFile(jobFile,JSON.stringify(job));await fs.writeFile(jobFile+'.commit','{}');return {base,job,jobFile};
}

test('macOS updates keep selecting ZIP when a drag-install DMG is also published', () => {
  const target = 'macos-arm64';
  const name = `UmekoCpp-${version}-${target}.zip`;
  const asset = {name,size:42,browser_download_url:url(name),digest:'sha256:'+'a'.repeat(64)};
  const dmg = {...asset,name:name.replace('.zip','.dmg'),browser_download_url:url(name.replace('.zip','.dmg'))};
  assert.equal(selectAsset([dmg,asset],repo,version,target).name,name);
});

test('select only the correct repository, stable edition, OS and architecture with checksum',()=>{
  for(const target of ['windows-x64','linux-x64','macos-arm64','macos-x64']) {
    const suffix=target.startsWith('linux')?'.tar.gz':'.zip';
    for(const r of ['umeko-desktop-cpp','umeko-desktop']) {
      const name=r===repo?`UmekoCpp-${version}-${target}${suffix}`:`Umeko-0.3.0-${target}-123abcd${suffix}`;
      const a={name,size:100,browser_download_url:`https://github.com/umeiko/${r}/releases/download/${version}/${name}`,digest:'sha256:'+'f'.repeat(64)};
      assert.equal(selectAsset([a],r,version,target).name,name);
      assert.throws(()=>selectAsset([{...a,browser_download_url:'https://evil.invalid/a'}],r,version,target));
      assert.throws(()=>selectAsset([{...a,digest:''}],r,version,target));
      assert.throws(()=>selectAsset([a,a],r,version,target));
    }
  }
});
test('download streams to a partial file and promotes only after SHA and size pass',async t=>{
  const bytes=Buffer.from('download fixture'), {base}=await fixture(t,bytes);
  const name=`UmekoCpp-${version}-${platformKey()}.zip`,asset={name,url:url(name),bytes:bytes.length,sha256:sha(bytes)};
  await download({repo,version,asset,cache:base},async()=>Readable.from([bytes.subarray(0,3),bytes.subarray(3)]));
  assert.deepEqual(await fs.readFile(path.join(base,name)),bytes);
  await fs.rm(path.join(base,name));
  await assert.rejects(download({repo,version,asset:{...asset,sha256:'0'.repeat(64)},cache:base},async()=>Readable.from([bytes])),/校验失败/);
  await assert.rejects(fs.stat(path.join(base,name)));await assert.rejects(fs.stat(path.join(base,name+'.part')));
  await assert.rejects(download({repo,version,asset:{...asset,bytes:1},cache:base},async()=>Readable.from([bytes])),/大小/);
});
test('checksum sidecar must name the selected file',async t=>{
  const bytes=Buffer.from('body'),{base}=await fixture(t,bytes),name='fixture.zip';
  const asset={name,url:url(name),bytes:4,checksumUrl:url(name+'.sha256')};
  await assert.rejects(download({repo,version,asset,cache:base},async()=>Readable.from([sha(bytes)+'  wrong.zip\n'])),/内容无效/);
  await download({repo,version,asset,cache:base},async u=>Readable.from([u.endsWith('.sha256')?sha(bytes)+'  '+name+'\n':bytes]));
  assert.deepEqual(await fs.readFile(path.join(base,name)),bytes);
});
for(const format of ['zip','tar']) test(`${format} installs a staged payload and preserves an old-version backup`,async t=>{
  const data=format==='zip'?zip(entries()):tar(entries()),{job,jobFile}=await fixture(t,data,format==='zip'?'.zip':'.tar.gz');
  await install(job,jobFile);
  assert.equal(await fs.readFile(job.executable,'utf8'),'new app');
  const result=JSON.parse(await fs.readFile(jobFile+'.result','utf8'));
  assert.equal(await fs.readFile(path.join(result.backup,exe),'utf8'),'old app');
});
test('changed archive never modifies the existing installation',async t=>{
  const {job,jobFile}=await fixture(t,zip(entries()));job.sha256='0'.repeat(64);
  await assert.rejects(install(job,jobFile),/SHA-256/);
  assert.equal(await fs.readFile(job.executable,'utf8'),'old app');
});
test('upstream collision-renamed tar downloads retain their original archive format',async t=>{
  const {job,jobFile}=await fixture(t,tar(entries()),'.tar-1.gz');
  job.archiveName='UmekoCpp-v0.3.0-linux-x64.tar.gz';
  await install(job,jobFile);
  assert.equal(await fs.readFile(job.executable,'utf8'),'new app');
});
test('minimal release tags install only the matching minimal edition',async t=>{
  for (const edition of ['minimal','standard']) {
    const files=entries().map(e=>e.name.endsWith('build-info.json')?{...e,raw:JSON.stringify({...info,edition})}:e);
    const {job,jobFile}=await fixture(t,zip(files));
    job.version='v0.3.0-minimal';job.edition='minimal';
    if(edition==='minimal') {
      await install(job,jobFile);
      assert.equal(await fs.readFile(job.executable,'utf8'),'new app');
    } else {
      await assert.rejects(install(job,jobFile),/类型不匹配/);
      assert.equal(await fs.readFile(job.executable,'utf8'),'old app');
    }
  }
});
test('malicious paths and symlinks cannot escape or redirect extraction',async t=>{
  for(const bad of ['../outside','/outside','C:/outside','a/../../outside','a\\..\\outside','a./outside'])assert.throws(()=>safeName(bad));
  for(const extra of [[{name:'../outside',raw:'bad'}],[{name:'UmekoCpp/link',raw:'../../outside',mode:0o120777}],
    [{name:'UmekoCpp/link',raw:'runtime',mode:0o120777},{name:'UmekoCpp/link/injected',raw:'bad'}]]) {
    const {job,jobFile,base}=await fixture(t,zip(entries(extra)));
    await assert.rejects(install(job,jobFile));
    assert.equal(await fs.readFile(job.executable,'utf8'),'old app');
    await assert.rejects(fs.stat(path.join(base,'outside')));
  }
});
test('wrong payload version and missing runtime are rejected before replacement',async t=>{
  for(const files of [entries().filter(e=>!e.name.includes('/runtime/node/')),entries().map(e=>e.name.endsWith('build-info.json')?{...e,raw:JSON.stringify({...info,version:'99.0.0'})}:e)]) {
    const {job,jobFile}=await fixture(t,zip(files));await assert.rejects(install(job,jobFile));
    assert.equal(await fs.readFile(job.executable,'utf8'),'old app');
  }
});
test('replacement failure rolls back the existing directory',async t=>{
  const {job,jobFile}=await fixture(t,zip(entries()));
  const destination=await fs.realpath(job.installDir);
  const rename=fs.rename;
  fs.rename=async(source,target)=>{if(source.includes('.umeko-stage-')&&target===destination)throw Error('injected replacement failure');return rename(source,target);};
  try {await assert.rejects(install(job,jobFile),/injected/);} finally {fs.rename=rename;}
  assert.equal(await fs.readFile(job.executable,'utf8'),'old app');
});
test('prepare copies the helper executable and runtime outside the install directory',async t=>{
  const {job,jobFile}=await fixture(t,zip(entries()));
  await fs.writeFile(path.join(job.installDir,'build-info.json'),JSON.stringify(info));
  await prepare(job,jobFile);
  const prepared=JSON.parse(await fs.readFile(jobFile,'utf8'));
  assert.ok(!prepared.helperExe.startsWith(job.installDir+path.sep));
  assert.equal(await fs.readFile(prepared.helperExe,'utf8'),'old app');
});

test('an uncommitted or cancelled handoff never replaces the application',async t=>{
  for(const cancelled of [false,true]) {
    const {job,jobFile}=await fixture(t,zip(entries()));
    if(cancelled)await fs.writeFile(jobFile+'.cancel','{}'); else await fs.rm(jobFile+'.commit');
    await assert.rejects(install(job,jobFile),/未修改现有版本/);
    assert.equal(await fs.readFile(job.executable,'utf8'),'old app');
  }
});
test('framework-style internal symlinks survive installation', {skip:process.platform==='win32'}, async t=>{
  for(const format of ['zip','tar']) {
    const extra=format==='zip'?[{name:'UmekoCpp/node-link',raw:'runtime/node',mode:0o120777}]:[{name:'UmekoCpp/node-link',target:'runtime/node'}];
    const {job,jobFile}=await fixture(t,format==='zip'?zip(entries(extra)):tar(entries(extra)),format==='zip'?'.zip':'.tar.gz');
    await install(job,jobFile);
    assert.equal(await fs.readlink(path.join(job.installDir,'node-link')),'runtime/node');
  }
});
test('existing installation paths through a directory alias are canonicalized', {skip:process.platform==='win32'}, async t=>{
  const {job,jobFile,base}=await fixture(t,zip(entries()));
  const alias=path.join(base,'installed-alias');
  await fs.symlink(job.installDir,alias);
  job.executable=path.join(alias,exe);
  await install(job,jobFile);
  assert.equal(await fs.readFile(job.executable,'utf8'),'new app');
});

async function cleanupFixture(t) {
  // Failure-injection hooks and reported paths must use the same spelling on
  // Windows (os.tmpdir() can contain an 8.3 alias). Separate cases retain aliases.
  const base=await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(),'umeko-cleanup-test-')));
  t.after(()=>fs.rm(base,{recursive:true,force:true}));
  const installDir=path.join(base,'Umeko'), updatesDir=path.join(base,'cache','updates');
  const cache=path.join(updatesDir,'a'.repeat(32)), downloadsDir=path.join(base,'downloads','Umeko');
  const profileDir=path.join(base,'profile'), backup=installDir+'.previous-12345678-1234-1234-1234-123456789abc';
  for(const dir of [installDir,cache,downloadsDir,profileDir,backup])await fs.mkdir(dir,{recursive:true});
  for(const dir of [installDir,backup]) {
    await fs.writeFile(path.join(dir,'build-info.json'),JSON.stringify({...info,version:'0.3.0'}));
    await fs.writeFile(path.join(dir,exe),dir===installDir?'current':'rollback');
  }
  await fs.writeFile(path.join(profileDir,'settings.json'),'user data');
  const archive=path.join(downloadsDir,`Umeko-0.3.0-${platformKey()}-123abcd.zip`);
  await fs.writeFile(archive,'downloaded package');
  const job={installDir,executable:path.join(installDir,exe),cache,archive,resourceRelative:'',version:'v0.3.0',profileDir};
  const jobFile=path.join(cache,'job.json');
  await fs.writeFile(jobFile,JSON.stringify(job));
  await fs.writeFile(jobFile+'.result',JSON.stringify({installDir,backup,version:job.version}));
  const child=spawn(process.execPath,['-e',''],{windowsHide:true});await once(child,'exit');
  await fs.writeFile(jobFile+'.ready',JSON.stringify({pid:child.pid}));
  const context={installDir,executable:job.executable,resourceRelative:'',version:job.version,profileDir,updatesDir,downloadsDir};
  await fs.writeFile(jobFile+'.started',JSON.stringify(context));
  return {base,job,jobFile,backup,context};
}

test('successful startup removes the package and old program as well as installer cache',async t=>{
  const {job,jobFile,backup}=await cleanupFixture(t);
  const worker=spawn(process.execPath,[path.resolve('runtime/update-engine.mjs'),'cleanup',jobFile],{windowsHide:true});
  let error='';worker.stderr.on('data',chunk=>error+=chunk);
  const [code]=await once(worker,'exit');assert.equal(code,0,error);
  await assert.rejects(fs.stat(backup),{code:'ENOENT'});
  await assert.rejects(fs.stat(job.archive),{code:'ENOENT'});
  await assert.rejects(fs.stat(job.cache),{code:'ENOENT'});
  assert.equal(await fs.readFile(path.join(job.profileDir,'settings.json'),'utf8'),'user data');
});

test('installer launch without successful application startup keeps rollback and its receipt',async t=>{
  const {job,jobFile,backup}=await cleanupFixture(t);
  await fs.rm(jobFile+'.started');
  const worker=spawn(process.execPath,[path.resolve('runtime/update-engine.mjs'),'cleanup',jobFile],{windowsHide:true});
  const [code]=await once(worker,'exit');assert.equal(code,0);
  assert.equal(await fs.readFile(path.join(backup,exe),'utf8'),'rollback');
  await fs.access(job.archive);await fs.access(jobFile+'.result');
});

test('first successful start removes legacy orphans, staging and stale partials only',async t=>{
  const {job,context,backup}=await cleanupFixture(t);
  await fs.rm(job.cache,{recursive:true}); // Old installer already removed its receipt.
  const stage=path.join(context.installDir,'..','.umeko-stage-Ab1234');
  const stale=path.join(context.downloadsDir,'.umeko-downloads','b'.repeat(64));
  const active=path.join(context.downloadsDir,'.umeko-downloads','c'.repeat(64));
  const recent=path.join(context.downloadsDir,'.umeko-downloads','d'.repeat(64));
  for(const directory of [stage,stale,active,recent])await fs.mkdir(directory,{recursive:true});
  await fs.writeFile(path.join(stale,'full.part'),'old partial');
  await fs.writeFile(path.join(active,'lock.json'),JSON.stringify({pid:process.pid}));
  await fs.utimes(recent,new Date(Date.now()+60000),new Date(Date.now()+60000));
  const unrelated=path.join(context.downloadsDir,'my-document.zip');await fs.writeFile(unrelated,'user file');
  const logs=[];const result=await cleanupStartup(context,{cutoff:Date.now()+1,log:entry=>logs.push(entry)});
  assert.deepEqual(result.failed,[]);
  await assert.rejects(fs.stat(backup),{code:'ENOENT'});
  await assert.rejects(fs.stat(stage),{code:'ENOENT'});
  await assert.rejects(fs.stat(stale),{code:'ENOENT'});
  await fs.access(active);await fs.access(recent);await fs.access(unrelated);
  // An active download conservatively defers package deletion to the next start.
  await fs.access(job.archive);
  assert.equal(await fs.readFile(path.join(context.profileDir,'settings.json'),'utf8'),'user data');
});

test('cleanup refuses user-data overlap and receipts pointing outside updater folders',async t=>{
  const {job,jobFile,context,backup,base}=await cleanupFixture(t);
  const outside=path.join(base,'documents');await fs.mkdir(outside);await fs.writeFile(path.join(outside,'session.json'),'session');
  const result=await cleanupStartup({...context,profileDir:context.updatesDir},{log:()=>{}});
  assert.equal(result.failed.length,1);await fs.access(backup);
  await fs.writeFile(jobFile,JSON.stringify({...job,stage:outside}));
  await fs.writeFile(jobFile+'.result',JSON.stringify({backup:outside}));
  const guarded=await cleanupStartup(context,{cutoff:Date.now()+1,log:()=>{}});
  assert.ok(guarded.refused.includes(outside));
  assert.equal(await fs.readFile(path.join(outside,'session.json'),'utf8'),'session');
  await fs.access(jobFile); // Unsafe receipt remains available for diagnosis.
  await fs.access(job.executable);
});

test('directory aliases cannot redirect cleanup into another directory',async t=>{
  const {context,job,backup,base}=await cleanupFixture(t);
  const outside=path.join(base,'outside');await fs.mkdir(outside);await fs.writeFile(path.join(outside,'settings.json'),'keep');
  await fs.rm(backup,{recursive:true});
  await fs.symlink(outside,backup,process.platform==='win32'?'junction':'dir');
  await cleanupStartup(context,{log:()=>{}});
  assert.equal(await fs.readFile(path.join(outside,'settings.json'),'utf8'),'keep');
  await fs.access(job.executable);
});

test('a locked old program is logged, retained and retried on the next successful start',async t=>{
  const {context,backup,jobFile}=await cleanupFixture(t);
  const logs=[];
  const result=await cleanupStartup(context,{cutoff:Date.now()+1,log:entry=>logs.push(entry),remove:async file=>{
    if(file===backup)throw Object.assign(Error('file in use'),{code:'EBUSY'});
    await fs.rm(file,{recursive:true,force:true});
  }});
  assert.ok(result.failed.includes(backup));assert.ok(logs.some(entry=>entry.message==='file in use'));
  await fs.access(jobFile+'.result');await fs.access(backup);
  const retried=await cleanupStartup(context,{cutoff:Date.now()+1,log:()=>{}});
  assert.deepEqual(retried.failed,[]);await assert.rejects(fs.stat(backup),{code:'ENOENT'});
});

test('partially removed installer cache retains its receipt for the next start',async t=>{
  const {context,job,jobFile}=await cleanupFixture(t);
  const result=await cleanupStartup(context,{cutoff:Date.now()+1,log:()=>{},remove:async file=>{
    if(file===job.cache){await fs.rm(jobFile);throw Object.assign(Error('helper in use'),{code:'EBUSY'});}
    await fs.rm(file,{recursive:true,force:true});
  }});
  assert.ok(result.failed.includes(job.cache));
  assert.equal(JSON.parse(await fs.readFile(jobFile,'utf8')).installDir,job.installDir);
  await cleanupStartup(context,{cutoff:Date.now()+1,log:()=>{}});
  await assert.rejects(fs.stat(job.cache),{code:'ENOENT'});
});

test('packaged application data inside the install directory prevents replacement',async t=>{
  const {job,jobFile}=await fixture(t,zip(entries()));
  job.profileDir=path.join(job.installDir,'profile');
  await assert.rejects(prepare(job,jobFile),/用户数据/);
  assert.equal(await fs.readFile(job.executable,'utf8'),'old app');
});

async function cleanup113Fixture(t) {
  const base=await fs.mkdtemp(path.join(os.tmpdir(),'umeko-cleanup-test-'));
  t.after(()=>fs.rm(base,{recursive:true,force:true}));
  const installDir=path.join(base,'installed'), cache=path.join(base,'updates',randomUUID().replaceAll('-',''));
  const downloads=path.join(base,'Downloads','Umeko');
  const profileDir=path.join(base,'profile');
  for(const directory of [installDir,cache,downloads,profileDir])await fs.mkdir(directory,{recursive:true});
  await fs.writeFile(path.join(installDir,'build-info.json'),JSON.stringify(info));
  await fs.writeFile(path.join(installDir,exe),'new app');
  const archive=path.join(downloads,`UmekoCpp-${version}-${platformKey()}.zip`);
  await fs.writeFile(archive,'package');
  const backup=installDir+'.previous-'+randomUUID();
  await fs.cp(installDir,backup,{recursive:true});
  await fs.writeFile(path.join(backup,exe),'old app');
  const child=spawn(process.execPath,['-e','']);await once(child,'exit');
  const job={repo,version,cache,installDir,executable:path.join(installDir,exe),resourceRelative:'',archive,
    sha256:sha(Buffer.from('package')),parentPid:child.pid,profileDir};
  const jobFile=path.join(cache,'job.json');
  await fs.writeFile(jobFile,JSON.stringify(job));
  await fs.writeFile(jobFile+'.ready',JSON.stringify({pid:child.pid}));
  await fs.writeFile(jobFile+'.result',JSON.stringify({backup,installDir,version}));
  const run=async()=>{
    await fs.writeFile(jobFile+'.started',JSON.stringify({...job,updatesDir:path.dirname(cache),downloadsDir:downloads}));
    const worker=spawn(process.execPath,[fileURLToPath(new URL('../runtime/update-engine.mjs',import.meta.url)),'cleanup',jobFile],{stdio:'pipe'});
    let output='';worker.stdout.on('data',data=>output+=data);worker.stderr.on('data',data=>output+=data);
    const [code]=await once(worker,'exit');assert.equal(code,0,output);
  };
  return {base,job,jobFile,backup,downloads,run};
}

test('successful update cleanup removes the old bundle and downloaded package',async t=>{
  const f=await cleanup113Fixture(t);
  await f.run();
  for(const item of [f.backup,f.job.archive,f.job.cache])assert.equal(await fs.stat(item).then(()=>true,()=>false),false,item);
  assert.equal(await fs.readFile(f.job.executable,'utf8'),'new app');
});

test('real package installation keeps rollback files until post-launch cleanup',async t=>{
  const f=await cleanup113Fixture(t), bytes=zip(entries());
  f.job.payloadRelative='UmekoCpp';f.job.sha256=sha(bytes);
  await fs.writeFile(f.job.archive,bytes);await fs.writeFile(f.jobFile,JSON.stringify(f.job));
  await fs.writeFile(f.jobFile+'.commit','{}');
  await install(f.job,f.jobFile);
  const result=JSON.parse(await fs.readFile(f.jobFile+'.result','utf8'));
  assert.ok((await fs.stat(result.backup)).isDirectory());assert.ok((await fs.stat(f.job.archive)).isFile());
  await f.run();
  for(const item of [result.backup,f.backup,f.job.archive,f.job.cache])assert.equal(await fs.stat(item).then(()=>true,()=>false),false,item);
  assert.equal(await fs.readFile(f.job.executable,'utf8'),'new app');
});

test('cleanup prunes historical packages only for the same edition and platform',async t=>{
  for (const repository of ['umeko-desktop','umeko-desktop-cpp']) {
    const f=await cleanup113Fixture(t);f.job.repo=repository;
    await fs.writeFile(f.jobFile,JSON.stringify(f.job));
    const name=(release,target=platformKey())=>repository==='umeko-desktop' ?
      `Umeko-${release}-${target}-abcdef0.zip` : `UmekoCpp-v${release}-${target}.zip`;
    const obsolete=[name('0.1.0'),name('0.2.0').replace('.zip','-2.zip'),name('0.2.0').replace('.zip','.tar-1.gz')];
    const keep=[name('0.4.0'),name('0.2.0',platformKey()==='linux-arm64'?'windows-x64':'linux-arm64'),
      'report.zip','UmekoCpp-v0.2.0-minimal-'+platformKey()+'.zip',
      repository==='umeko-desktop'?'UmekoCpp-v0.2.0-'+platformKey()+'.zip':'Umeko-0.2.0-'+platformKey()+'-abcdef0.zip'];
    for(const file of [...obsolete,...keep])await fs.writeFile(path.join(f.downloads,file),'old package');
    const older=f.job.installDir+'.previous-'+randomUUID(), newer=f.job.installDir+'.previous-'+randomUUID();
    for(const directory of [older,newer])await fs.cp(f.backup,directory,{recursive:true});
    await fs.writeFile(path.join(older,'build-info.json'),JSON.stringify({...info,version:'0.1.0'}));
    await fs.writeFile(path.join(newer,'build-info.json'),JSON.stringify({...info,version:'0.4.0'}));
    const unrelated=f.job.installDir+'.previous-not-an-update';await fs.mkdir(unrelated);
    await f.run();
    for(const file of obsolete)assert.equal(await fs.stat(path.join(f.downloads,file)).then(()=>true,()=>false),false,file);
    for(const file of keep)assert.equal(await fs.readFile(path.join(f.downloads,file),'utf8'),'old package',file);
    assert.equal(await fs.stat(older).then(()=>true,()=>false),false);
    assert.ok((await fs.stat(newer)).isDirectory());assert.ok((await fs.stat(unrelated)).isDirectory());
  }
});

test('failed, superseded, or concurrently installing updates do not trigger cleanup',async t=>{
  for(const situation of ['failed','superseded','locked']) {
    const f=await cleanup113Fixture(t);
    if(situation==='failed')await fs.rm(f.jobFile+'.result');
    if(situation==='superseded')await fs.writeFile(path.join(f.job.installDir,'build-info.json'),JSON.stringify({...info,version:'0.4.0'}));
    if(situation==='locked')await fs.mkdir(path.join(f.base,'.installed.update-lock'));
    await f.run();
    assert.equal(await fs.readFile(path.join(f.backup,exe),'utf8'),'old app');
    assert.equal(await fs.readFile(f.job.archive,'utf8'),'package');
    assert.ok((await fs.stat(f.job.cache)).isDirectory());
  }
});

test('cleanup keeps modified archives and never follows backup directory links',async t=>{
  const f=await cleanup113Fixture(t);
  await fs.writeFile(f.job.archive,'user replacement');
  const outside=path.join(f.base,'unrelated');await fs.cp(f.backup,outside,{recursive:true});
  const link=f.job.installDir+'.previous-'+randomUUID();
  await fs.symlink(outside,link,process.platform==='win32'?'junction':'dir');
  await f.run();
  assert.equal(await fs.readFile(f.job.archive,'utf8'),'user replacement');
  assert.equal(await fs.readFile(path.join(outside,exe),'utf8'),'old app');
  assert.ok((await fs.lstat(link)).isSymbolicLink());
});

test('cleanup removes abandoned partials but preserves recent pauses and active downloads',async t=>{
  const f=await cleanup113Fixture(t), root=path.join(f.downloads,'.umeko-downloads');
  const old=new Date(Date.now()-8*24*60*60*1000);
  const paths=[];
  for(const [index,kind] of ['abandoned','paused','active'].entries()) {
    const folder=path.join(root,String(index).repeat(64));paths.push(folder);
    await fs.mkdir(folder,{recursive:true});await fs.writeFile(path.join(folder,'full.part'),'partial');
    if(kind==='active')await fs.writeFile(path.join(folder,'lock.json'),JSON.stringify({pid:process.pid}));
    if(kind!=='paused')for(const file of [...(await fs.readdir(folder)).map(name=>path.join(folder,name)),folder])await fs.utimes(file,old,old);
  }
  await f.run();
  assert.equal(await fs.stat(paths[0]).then(()=>true,()=>false),false);
  for(const folder of paths.slice(1))assert.equal(await fs.readFile(path.join(folder,'full.part'),'utf8'),'partial');
});

test('cleanup bounds installer caches while retaining active jobs and recent failure logs',async t=>{
  const f=await cleanup113Fixture(t), root=path.dirname(f.job.cache), locations={};
  const old=new Date(Date.now()-8*24*60*60*1000);
  for(const kind of ['successful','abandoned','recent','active','other-install']) {
    const directory=path.join(root,randomUUID().replaceAll('-',''));locations[kind]=directory;
    await fs.mkdir(directory);await fs.writeFile(path.join(directory,'installer-runtime'),'copied app');
    const job={...f.job,cache:directory,version:'v0.2.0',...(kind==='other-install'?{installDir:path.join(f.base,'other')}:{})};
    const file=path.join(directory,'job.json');await fs.writeFile(file,JSON.stringify(job));
    if(kind==='successful')await fs.writeFile(file+'.result',JSON.stringify({installDir:job.installDir,version:job.version}));
    if(kind==='active')await fs.writeFile(file+'.ready',JSON.stringify({pid:process.pid}));
    if(['abandoned','active','other-install'].includes(kind))for(const file of [...(await fs.readdir(directory)).map(name=>path.join(directory,name)),directory])await fs.utimes(file,old,old);
  }
  await f.run();
  for(const kind of ['successful','abandoned'])assert.equal(await fs.stat(locations[kind]).then(()=>true,()=>false),false,kind);
  for(const kind of ['recent','active','other-install'])assert.equal(await fs.readFile(path.join(locations[kind],'installer-runtime'),'utf8'),'copied app',kind);
});

test('cleanup preserves a live installer even after replacement completed',async t=>{
  const f=await cleanup113Fixture(t);
  await fs.writeFile(f.jobFile+'.ready',JSON.stringify({pid:process.pid}));
  await f.run();
  assert.equal(await fs.readFile(path.join(f.backup,exe),'utf8'),'old app');
  await fs.access(f.jobFile);await fs.access(f.job.archive);
});

test('cleanup receipts cannot override newer or other-edition backup metadata',async t=>{
  for(const metadata of [{...info,version:'0.4.0'},{...info,edition:'minimal'}]) {
    const f=await cleanup113Fixture(t);
    await fs.writeFile(path.join(f.backup,'build-info.json'),JSON.stringify(metadata));
    await f.run();
    assert.equal(await fs.readFile(path.join(f.backup,exe),'utf8'),'old app');
    await fs.access(f.jobFile+'.result');
  }
});

test('recent partial-file writes survive cleanup even with an old cache directory',async t=>{
  const f=await cleanup113Fixture(t), directory=path.join(f.downloads,'.umeko-downloads','f'.repeat(64));
  await fs.mkdir(directory,{recursive:true});await fs.writeFile(path.join(directory,'full.part'),'recent progress');
  const old=new Date(Date.now()-8*24*60*60*1000);await fs.utimes(directory,old,old);
  await f.run();
  assert.equal(await fs.readFile(path.join(directory,'full.part'),'utf8'),'recent progress');
});

test('cleanup keeps another installation staging while its update lock is held',async t=>{
  const f=await cleanup113Fixture(t), stage=path.join(f.base,'.umeko-stage-Ab1234');
  await fs.mkdir(stage);await fs.writeFile(path.join(stage,'payload'),'installing another app');
  await fs.mkdir(path.join(f.base,'.another.update-lock'));
  await f.run();
  assert.equal(await fs.readFile(path.join(stage,'payload'),'utf8'),'installing another app');
});

test('cleanup canonicalizes receipt aliases and still protects modified packages',async t=>{
  const f=await cleanup113Fixture(t), alias=f.base+'-alias';
  await fs.symlink(f.base,alias,process.platform==='win32'?'junction':'dir');
  t.after(()=>fs.rm(alias,{force:true,recursive:process.platform==='win32'}));
  for(const key of ['installDir','cache','archive','executable','profileDir'])f.job[key]=path.join(alias,path.relative(f.base,f.job[key]));
  await fs.writeFile(f.jobFile,JSON.stringify(f.job));
  await fs.writeFile(f.job.archive,'user replacement');
  await f.run();
  assert.equal(await fs.readFile(f.job.archive,'utf8'),'user replacement');
  await assert.rejects(fs.stat(f.backup),{code:'ENOENT'});
  await assert.rejects(fs.stat(f.job.cache),{code:'ENOENT'});
});

test('cleanup retains recent or active temporary download jobs and reclaims abandoned ones',async t=>{
  const f=await cleanup113Fixture(t), temporary=path.join(f.base,'temp');
  f.job.tempDir=temporary;await fs.mkdir(temporary);
  const locations={};
  for(const [kind,suffix] of [['recent','11111111'],['abandoned','22222222'],['active','33333333']]) {
    const directory=path.join(temporary,'umeko-download-job-'+suffix);locations[kind]=directory;
    await fs.mkdir(directory);await fs.writeFile(path.join(directory,'job.json'),JSON.stringify({cache:f.downloads,...(kind==='active'?{parentPid:process.pid}:{})}));
    if(kind!=='recent') {
      const old=new Date(Date.now()-8*24*60*60*1000);
      for(const file of [path.join(directory,'job.json'),directory])await fs.utimes(file,old,old);
    }
  }
  await f.run();
  await fs.access(path.join(locations.recent,'job.json'));await fs.access(path.join(locations.active,'job.json'));
  await assert.rejects(fs.stat(locations.abandoned),{code:'ENOENT'});
});
