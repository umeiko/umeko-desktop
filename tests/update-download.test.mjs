import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import http from 'node:http';
import {once} from 'node:events';
import {createHash} from 'node:crypto';
import {download,updateRequest} from '../runtime/update-engine.mjs';

const sha=b=>createHash('sha256').update(b).digest('hex');
async function fixture(t, handler, bytes=Buffer.alloc(900000,31)) {
  const cache=await fs.mkdtemp(path.join(os.tmpdir(),'umeko-resume-'));
  t.after(()=>fs.rm(cache,{recursive:true,force:true}));
  const calls=[];
  const server=http.createServer((req,res)=>{calls.push(req.headers.range);handler(req,res,bytes,calls);});
  server.listen(0,'127.0.0.1');await once(server,'listening');
  t.after(()=>new Promise(resolve=>{server.close(resolve);server.closeAllConnections();}));
  const asset={name:'fixture.zip',url:'https://github.com/umeiko/umeko-desktop-cpp/releases/download/v1.0.0/fixture.zip',bytes:bytes.length,sha256:sha(bytes)};
  const job={repo:'umeko-desktop-cpp',version:'v1.0.0',cache,asset,connections:3,retryDelay:1,maxAttempts:3};
  const fetch=(_,options)=>new Promise((resolve,reject)=>{const req=http.get(`http://127.0.0.1:${server.address().port}`,options,resolve);req.on('error',reject);});
  return {job,fetch,calls,bytes,cache,part:path.join(cache,'.umeko-downloads',asset.sha256)};
}
function range(req,res,bytes) {
  const [,start,end]=/^bytes=(\d+)-(\d+)$/.exec(req.headers.range);
  res.writeHead(206,{'Content-Range':`bytes ${start}-${end}/${bytes.length}`,'Content-Length':Number(end)-Number(start)+1});
  return bytes.subarray(Number(start),Number(end)+1);
}
test('three ranged transfers assemble the exact pinned archive',async t=>{
  const f=await fixture(t,(q,s,b)=>s.end(range(q,s,b)));
  await download(f.job,f.fetch);
  assert.equal(f.calls.length,3);
  assert.deepEqual(await fs.readFile(path.join(f.cache,'fixture.zip')),f.bytes);
  assert.equal(await fs.stat(f.part).then(()=>true,()=>false),false);
});
test('truncated network streams reconnect at saved offsets instead of becoming SHA errors',async t=>{
  let dropped=false,savedBeforeDrop=false;
  const f=await fixture(t,(q,s,b)=>{
    const body=range(q,s,b);
    if(!dropped){
      dropped=true;s.write(body.subarray(0,40000));
      // A flushed socket write does not mean the client has saved its bytes.
      // Interrupt only after the partial really exists, including on busy CI.
      void (async()=>{
        const deadline=Date.now()+5000;
        while(Date.now()<deadline){
          if(await fs.stat(path.join(f.part,'part-0')).then(x=>x.size===40000,()=>false)){
            savedBeforeDrop=true;break;
          }
          await new Promise(resolve=>setTimeout(resolve,5));
        }
        s.destroy();
      })();
    }
    else s.end(body);
  });
  await download(f.job,f.fetch);
  assert.ok(savedBeforeDrop,'fixture must save 40000 bytes before interrupting the network stream');
  assert.ok(f.calls.includes('bytes=40000-299999'),f.calls.join(','));
  assert.deepEqual(await fs.readFile(path.join(f.cache,'fixture.zip')),f.bytes);
});
test('pause, process restart, and automatic-retry exhaustion preserve partials',async t=>{
  let stall=true;
  const f=await fixture(t,(q,s,b)=>{const body=range(q,s,b);if(stall){s.write(body.subarray(0,30000));setTimeout(()=>s.destroy(),30);}else s.end(body);});
  const signal=new AbortController();
  const pending=download(f.job,f.fetch,{signal:signal.signal});
  // Wait for bytes actually on disk rather than racing a fixed network delay.
  for(let i=0;i<100;i++){if(await fs.stat(path.join(f.part,'part-0')).then(x=>x.size>0,()=>false))break;await new Promise(r=>setTimeout(r,5));}
  signal.abort();
  await assert.rejects(pending,e=>e.code==='PAUSED'&&e.downloadState.received>0);
  const size=(await fs.stat(path.join(f.part,'part-0'))).size;
  assert.ok(size>0);
  await assert.rejects(download({...f.job,maxAttempts:1},f.fetch),e=>e.downloadState.resumable && e.code!=='HASH');
  const saved=(await fs.stat(path.join(f.part,'part-0'))).size;
  assert.ok(saved>=size);
  stall=false;const before=f.calls.length;
  await download(f.job,f.fetch);
  assert.ok(f.calls.slice(before).includes(`bytes=${saved}-299999`));
  assert.deepEqual(await fs.readFile(path.join(f.cache,'fixture.zip')),f.bytes);
});
test('servers ignoring Range fall back safely; resume never appends a 200 response',async t=>{
  const f=await fixture(t,(_q,s,b)=>{s.writeHead(200,{'Content-Length':b.length});s.end(b);});
  await fs.mkdir(f.part,{recursive:true});await fs.writeFile(path.join(f.part,'part-0'),f.bytes.subarray(0,20));
  await download(f.job,f.fetch);
  assert.equal(f.calls.length,2);
  const archive=path.join(f.cache,'fixture.zip');assert.deepEqual(await fs.readFile(archive),f.bytes);
  await fs.rm(archive);await fs.mkdir(f.part,{recursive:true});await fs.writeFile(path.join(f.part,'full.part'),f.bytes.subarray(0,123));
  await download(f.job,f.fetch);
  assert.equal(f.calls.at(-1),`bytes=123-${f.bytes.length-1}`);
  assert.deepEqual(await fs.readFile(archive),f.bytes);
});
test('bad ranges, HTTP failures, and real hash mismatches remain distinct',async t=>{
  for(const mode of ['range','404','hash']){
    const f=await fixture(t,(q,s,b)=>{
      if(mode==='404'){s.writeHead(404);s.end();return;}
      const body=range(q,s,b);
      s.end(mode==='hash'?Buffer.alloc(body.length,99):body);
    });
    const fetch=mode==='range'?async(...args)=>{const res=await f.fetch(...args);res.headers['content-range']='bytes 1-2/3';return res;}:f.fetch;
    await assert.rejects(download(f.job,fetch),e=>e.code===({range:'RANGE','404':'HTTP_404',hash:'HASH'}[mode]));
    assert.equal(await fs.stat(path.join(f.cache,'fixture.zip')).then(()=>true,()=>false),false);
    if(mode==='404')assert.equal(f.calls.length,1);
    if(mode==='hash')assert.equal(await fs.stat(path.join(f.part,'part-0')).then(()=>true,()=>false),false);
  }
});
test('verified cached archives avoid network; unrelated files and symlink targets survive',async t=>{
  const f=await fixture(t,(q,s,b)=>s.end(range(q,s,b)));
  const existing=path.join(f.cache,'fixture.zip');await fs.writeFile(existing,'user file');
  await download(f.job,f.fetch);
  assert.equal(await fs.readFile(existing,'utf8'),'user file');
  await download(f.job,()=>{throw Error('must reuse verified cache');});
  const other=path.join(f.cache,'outside');await fs.mkdir(other);
  await fs.rm(path.join(f.cache,'fixture-1.zip'));
  if(process.platform!=='win32'){
    await fs.symlink(other,f.part,'dir');
    await assert.rejects(download(f.job,f.fetch),/缓存目录/);
    assert.deepEqual(await fs.readdir(other),[]);
  }
});
test('HTTPS requests use an HTTP CONNECT proxy, preserve credentials and Range, and never silently bypass it',async t=>{
  const calls=[];
  const server=http.createServer();server.on('connect',(req,socket)=>{calls.push(req);socket.end('HTTP/1.1 407 Proxy Authentication Required\r\nContent-Length: 0\r\n\r\n');});
  server.listen(0,'127.0.0.1');await once(server,'listening');t.after(()=>new Promise(resolve=>server.close(resolve)));
  await assert.rejects(updateRequest('https://github.com/umeiko/fixture',{proxy:`http://user:secret@127.0.0.1:${server.address().port}`,headers:{Range:'bytes=3-9'}}),e=>e.code==='PROXY'&&e.message.includes('407'));
  assert.equal(calls.length,1);assert.equal(calls[0].url,'github.com:443');
  assert.equal(calls[0].headers['proxy-authorization'],'Basic '+Buffer.from('user:secret').toString('base64'));
});
