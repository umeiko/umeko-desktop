import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import https from 'node:https';
import http from 'node:http';
import {createHash} from 'node:crypto';
import {once} from 'node:events';
import {networkProfiles,profileEnvironment,installPackage,downloadArchive,runProcess,safeMessage} from '../runtime/package-install.mjs';
import {extractPackageArchive} from '../runtime/update-engine.mjs';
import {deflateRawSync,gzipSync,crc32} from 'node:zlib';

async function fixture(t){const root=await fs.mkdtemp(path.join(os.tmpdir(),'umeko-package-'));t.after(()=>fs.rm(root,{recursive:true,force:true,maxRetries:5,retryDelay:100}));await fs.mkdir(path.join(root,'workspace'));await fs.writeFile(path.join(root,'custom.pem'),'fixture CA');return {root,input:{release:root,cwd:path.join(root,'workspace'),agentDir:path.join(root,'agent'),source:'npm:fixture',proxy:'http://fixture:1234',caFile:path.join(root,'custom.pem'),maxRounds:1}};}
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
test('route and CA combinations are complete and always validate TLS',()=>{
  const profiles=networkProfiles('http://proxy:80','/custom.pem');assert.equal(profiles.length,4);
  assert.equal(networkProfiles('','').length,1);
  const base={HTTPS_PROXY:'http://old:1',NODE_TLS_REJECT_UNAUTHORIZED:'0',GIT_SSL_NO_VERIFY:'true',NODE_EXTRA_CA_CERTS:'/old.pem',npm_config_cafile:'/old.pem',npm_config_strict_ssl:'false',GIT_CONFIG_COUNT:'1',GIT_CONFIG_KEY_0:'credential.helper',GIT_CONFIG_VALUE_0:'store'};
  for(const profile of profiles){const env=profileEnvironment(base,profile);assert.equal(env.npm_config_strict_ssl,'true');assert.equal(env.NODE_TLS_REJECT_UNAUTHORIZED,undefined);assert.equal(env.GIT_SSL_NO_VERIFY,undefined);assert.equal(env.GIT_CONFIG_KEY_0,'credential.helper');assert.equal(env.npm_config_proxy,profile.proxy);assert.equal(env.npm_config_cafile,profile.caFile);assert.equal(env.NODE_EXTRA_CA_CERTS,profile.caFile || undefined);}
  assert.equal(base.npm_config_strict_ssl,'false');
  assert.doesNotMatch(safeMessage('https://user:secret@proxy/ Authorization: Bearer private-secret token=my-token'),/secret|my-token/);
});
test('all native combinations fail, then cached package download enables an offline native install',async t=>{
  const {input}=await fixture(t),calls=[],progress=[];
  const run=async(program,args,options)=>{
    calls.push({args,env:options.env});
    if(args[0].replaceAll('\\','/').endsWith('/pi-coding-agent/dist/cli.js')) {if(options.env.npm_config_offline==='true')return 'Installed fixture';throw Error('ECONNRESET network unavailable');}
    if(args[1]==='pack'){const folder=args[args.indexOf('--pack-destination')+1];await fs.writeFile(path.join(folder,'fixture.tgz'),'fixture');return JSON.stringify([{filename:'fixture.tgz'}]);}
    return '';
  };
  assert.equal(await installPackage(input,{run,onProgress:row=>progress.push(row)}),'Installed fixture');
  const native=calls.filter(row=>row.args[0].replaceAll('\\','/').endsWith('/pi-coding-agent/dist/cli.js'));assert.equal(native.length,5);
  assert.deepEqual(native.slice(0,4).map(row=>[row.env.npm_config_proxy,row.env.npm_config_cafile]),networkProfiles(input.proxy,input.caFile).map(row=>[row.proxy,row.caFile]));
  assert.ok(progress.some(row=>row.stage==='download'));assert.ok(progress.some(row=>row.stage==='offline'));
});
test('missing packages stop after trying combinations, transient failures back off and can be cancelled',async t=>{
  const {input}=await fixture(t);let calls=0,sleeps=0;
  await assert.rejects(installPackage(input,{run:async()=>{calls++;throw Error('npm ERR! E404 package not found');},sleep:async()=>sleeps++}),/E404/);
  assert.equal(calls,12);assert.equal(sleeps,0);
  const controller=new AbortController();delete input.maxRounds;
  // A broken proxy must not turn a definitive direct registry error into an
  // endless retry loop. All native and offline combinations still get tried.
  calls=0;
  await assert.rejects(installPackage(input,{run:async(_program,_args,{env})=>{calls++;throw Error(env.npm_config_proxy?'ENOTFOUND proxy unavailable':'npm ERR! E404 package not found');},sleep:async()=>{throw Error('must not retry a definitive failure');}}),/E404/);
  assert.equal(calls,12);
  await assert.rejects(installPackage(input,{run:async()=>{throw Error('ETIMEDOUT');},signal:controller.signal,sleep:async()=>{controller.abort();throw Object.assign(Error('cancelled'),{code:'ABORT_ERR'});}}),/cancelled/);
});
test('an explicit custom CA validates HTTPS but no-CA and wrong-CA attempts remain rejected',async t=>{
  const {root}=await fixture(t),fixtureRoot=new URL('./fixtures/update-tls/',import.meta.url);
  const key=await fs.readFile(new URL('server-key.pem',fixtureRoot)),cert=await fs.readFile(new URL('server.pem',fixtureRoot));
  const server=https.createServer({key,cert},(_req,res)=>res.end('archive-fixture')),sockets=new Set();server.on('connection',socket=>{sockets.add(socket);socket.on('close',()=>sockets.delete(socket));});server.listen(0,'127.0.0.1');await once(server,'listening');
  t.after(()=>new Promise(resolve=>{server.close(resolve);for(const socket of sockets)socket.destroy();}));
  const url=`https://127.0.0.1:${server.address().port}/package.zip`;
  await assert.rejects(downloadArchive(url,path.join(root,'bad.zip'),{proxy:'',caFile:''}));
  await assert.rejects(downloadArchive(url,path.join(root,'wrong-ca.zip'),{proxy:'',caFile:path.resolve('tests/fixtures/update-tls/untrusted.pem')}));
  await assert.rejects(downloadArchive(url,path.join(root,'wrong-integrity.zip'),{proxy:'',caFile:path.resolve('tests/fixtures/update-tls/ca.pem')},{integrity:'sha512-'+Buffer.alloc(64).toString('base64')}),/EINTEGRITY/);
  await downloadArchive(url,path.join(root,'good.zip'),{proxy:'',caFile:path.resolve('tests/fixtures/update-tls/ca.pem')});
  assert.equal(await fs.readFile(path.join(root,'good.zip'),'utf8'),'archive-fixture');
});
test('ZIP package installation persists a local package and traversal stays rejected',async t=>{
  const {root,input}=await fixture(t);input.proxy='';input.caFile='';input.local=true;input.source=path.join(root,'offline.zip');
  await fs.writeFile(input.source,zip([{name:'plugin/package.json',raw:JSON.stringify({name:'offline-fixture',pi:{extensions:['index.js']}})},{name:'plugin/index.js',raw:'throw Error("never execute during install")'}]));
  let installed='';const run=async(_program,args)=>{if(args[1]==='install'){installed=args[2];return 'Installed offline-fixture';}return 'null';};
  assert.match(await installPackage(input,{run}),/Installed/);
  assert.ok(installed.startsWith(path.join(input.cwd,'.pi','umeko-packages')));
  assert.equal(await fs.readFile(path.join(installed,'index.js'),'utf8'),'throw Error("never execute during install")');
  assert.ok((await fs.readdir(path.join(input.agentDir,'umeko-install-cache'))).every(name=>!name.startsWith('preparing-')));
  const archive=path.join(root,'escape.zip');await fs.writeFile(archive,zip([{name:'../outside',raw:'bad'}]));
  await assert.rejects(extractPackageArchive(archive,path.join(root,'bad-unpacked')));
  await assert.rejects(fs.stat(path.join(root,'outside')));
});
test('cancellation terminates only the owned installer and its descendant',async t=>{
  const {root}=await fixture(t),marker=path.join(root,'survived'),controller=new AbortController();
  const descendant=`setTimeout(()=>require('fs').writeFileSync(${JSON.stringify(marker)},'bad'),1200)`;
  const code=`require('child_process').spawn(process.execPath,['-e',${JSON.stringify(descendant)}]);setTimeout(()=>{},10000)`;
  const promise=runProcess(process.execPath,['-e',code],{cwd:root,env:process.env,signal:controller.signal});
  setTimeout(()=>controller.abort(),150);
  await assert.rejects(promise,/取消/);await new Promise(resolve=>setTimeout(resolve,1400));
  await assert.rejects(fs.stat(marker));
});

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


test('real npm download/cache fallback finishes with a fully offline native Pi install', {timeout:30000},async t=>{
  const {root,input}=await fixture(t);input.proxy='';input.caFile='';input.source='npm:@fixture/offline@1.0.0';input.release=path.resolve('runtime/releases/coding-1.3.0');
  const manifest={name:'@fixture/offline',version:'1.0.0',pi:{extensions:['index.js']}};
  const bytes=tar([{name:'package/package.json',raw:JSON.stringify(manifest)},{name:'package/index.js',raw:'throw Error("no imports during install")'}]);
  let onlineRequests=0,offlineRequests=0,offline=false,port;
  const server=http.createServer((req,res)=>{
    onlineRequests++;if(offline)offlineRequests++;
    if(req.url.includes('.tgz')){res.setHeader('Content-Type','application/octet-stream');res.end(bytes);return;}
    const dist={tarball:`http://127.0.0.1:${port}/fixture.tgz`,shasum:createHash('sha1').update(bytes).digest('hex'),integrity:'sha512-'+createHash('sha512').update(bytes).digest('base64')};
    res.setHeader('Content-Type','application/json');res.end(JSON.stringify({name:manifest.name,'dist-tags':{latest:'1.0.0'},versions:{'1.0.0':{...manifest,dist}}}));
  });
  server.listen(0,'127.0.0.1');await once(server,'listening');port=server.address().port;
  t.after(()=>new Promise(resolve=>server.close(resolve)));
  const userconfig=path.join(root,'empty.npmrc');await fs.writeFile(userconfig,'');
  input.environment={npm_config_registry:`http://127.0.0.1:${port}`,npm_config_userconfig:userconfig};
  const run=async(program,args,options)=>{
    if(args[0].replaceAll('\\','/').endsWith('/pi-coding-agent/dist/cli.js')) {
      if(options.env.npm_config_offline!=='true')throw Error('ECONNRESET native download interrupted');
      offline=true;
    }
    return runProcess(program,args,options);
  };
  assert.match(await installPackage(input,{run}),/Installed/);
  assert.ok(onlineRequests>0);assert.equal(offlineRequests,0);
  const settings=JSON.parse(await fs.readFile(path.join(input.agentDir,'settings.json'),'utf8'));
  assert.deepEqual(settings.packages,[input.source]);
});
