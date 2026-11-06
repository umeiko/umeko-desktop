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

const sha = b => createHash('sha256').update(b).digest('hex');
const repo = 'umeko-desktop-cpp', version = 'v0.3.0';
const url = name => `https://github.com/umeiko/${repo}/releases/download/${version}/${name}`;
const exe = process.platform === 'win32' ? 'UmekoCpp.exe' : 'UmekoCpp';
const system = {linux:'Linux',darwin:'Darwin',win32:'Windows'}[process.platform];
const info = {version:'0.3.0',system,architecture:process.arch};

async function cleanupFixture(t) {
  const base=await fs.mkdtemp(path.join(os.tmpdir(),'umeko-cleanup-test-'));
  t.after(()=>fs.rm(base,{recursive:true,force:true}));
  const installDir=path.join(base,'installed'), cache=path.join(base,'updates',randomUUID().replaceAll('-',''));
  const downloads=path.join(base,'Downloads','Umeko');
  for(const directory of [installDir,cache,downloads])await fs.mkdir(directory,{recursive:true});
  await fs.writeFile(path.join(installDir,'build-info.json'),JSON.stringify(info));
  await fs.writeFile(path.join(installDir,exe),'new app');
  const archive=path.join(downloads,`UmekoCpp-${version}-${platformKey()}.zip`);
  await fs.writeFile(archive,'package');
  const backup=installDir+'.previous-'+randomUUID();
  await fs.cp(installDir,backup,{recursive:true});
  await fs.writeFile(path.join(backup,exe),'old app');
  const child=spawn(process.execPath,['-e','']);await once(child,'exit');
  const job={repo,version,cache,installDir,executable:path.join(installDir,exe),resourceRelative:'',archive,
    sha256:sha(Buffer.from('package')),parentPid:child.pid};
  const jobFile=path.join(cache,'job.json');
  await fs.writeFile(jobFile,JSON.stringify(job));
  await fs.writeFile(jobFile+'.ready',JSON.stringify({pid:child.pid}));
  await fs.writeFile(jobFile+'.result',JSON.stringify({backup,installDir,version}));
  const run=async()=>{
    const worker=spawn(process.execPath,[fileURLToPath(new URL('../runtime/update-engine.mjs',import.meta.url)),'cleanup',jobFile],{stdio:'pipe'});
    let output='';worker.stdout.on('data',data=>output+=data);worker.stderr.on('data',data=>output+=data);
    const [code]=await once(worker,'exit');assert.equal(code,0,output);
  };
  return {base,job,jobFile,backup,downloads,run};
}

test('successful update cleanup removes the old bundle and downloaded package',async t=>{
  const f=await cleanupFixture(t);
  await f.run();
  for(const item of [f.backup,f.job.archive,f.job.cache])assert.equal(await fs.stat(item).then(()=>true,()=>false),false,item);
  assert.equal(await fs.readFile(f.job.executable,'utf8'),'new app');
});

test('real package installation keeps rollback files until post-launch cleanup',async t=>{
  const f=await cleanupFixture(t), bytes=zip(entries());
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
    const f=await cleanupFixture(t);f.job.repo=repository;
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
    const f=await cleanupFixture(t);
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
  const f=await cleanupFixture(t);
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
  const f=await cleanupFixture(t), root=path.join(f.downloads,'.umeko-downloads');
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
  const f=await cleanupFixture(t), root=path.dirname(f.job.cache), locations={};
  const old=new Date(Date.now()-8*24*60*60*1000);
  for(const kind of ['successful','abandoned','recent','active','other-install']) {
    const directory=path.join(root,randomUUID().replaceAll('-',''));locations[kind]=directory;
    await fs.mkdir(directory);await fs.writeFile(path.join(directory,'installer-runtime'),'copied app');
    const job={...f.job,cache:directory,version:'v0.2.0',...(kind==='other-install'?{installDir:path.join(f.base,'other')}:{})};
    const file=path.join(directory,'job.json');await fs.writeFile(file,JSON.stringify(job));
    if(kind==='successful')await fs.writeFile(file+'.result',JSON.stringify({installDir:job.installDir,version:job.version}));
    if(kind==='active')await fs.writeFile(file+'.ready',JSON.stringify({pid:process.pid}));
    if(['abandoned','active','other-install'].includes(kind))for(const name of await fs.readdir(directory))await fs.utimes(path.join(directory,name),old,old);
  }
  await f.run();
  for(const kind of ['successful','abandoned'])assert.equal(await fs.stat(locations[kind]).then(()=>true,()=>false),false,kind);
  for(const kind of ['recent','active','other-install'])assert.equal(await fs.readFile(path.join(locations[kind],'installer-runtime'),'utf8'),'copied app',kind);
});
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
