import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {mkdtemp, readdir, readFile, realpath, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createGenerationExtension} from '../runtime/generation.mjs';
import {createToolPermissionExtension} from '../runtime/tool-permissions.mjs';
import {chatboxItems} from '../runtime/chatbox.mjs';
import {toolSelection, excludedSessionTools} from '../runtime/session-capabilities.mjs';

// Loopback gateway fixtures only: no real model, shell, background job or media
// application is started. Abort races that a real fetch prevents use stubs.
const video = {data:Buffer.from('fixture mp4 bytes').toString('base64'),mimeType:'video/mp4',extension:'mp4'};
const result = {provider:'Actual video provider',model:'actual-video-model',items:[video]};
const line = event => JSON.stringify(event)+'\n';
const progress = (status, value) => ({type:'progress',id:'video-job-1',status,progress:value});
const finished = () => ({type:'result',result});
const deferred = () => {let resolve; const promise=new Promise(done=>{resolve=done;});return {promise,resolve};};

async function fixture(t,{generation={video:{provider:'Video account',model:'video-model'}},mode='auto',approved=true,language='en',serve,fetchImpl}={}) {
  const cwd=await realpath(await mkdtemp(join(tmpdir(),'umeko-video-generation-')));
  const requests=[],confirmations=[],updates=[],entries=[],tools=[];
  const server=http.createServer(async(req,res)=>{
    try {
      const chunks=[]; for await(const chunk of req) chunks.push(chunk);
      const request={url:req.url,authorization:req.headers.authorization,body:JSON.parse(Buffer.concat(chunks).toString())};
      requests.push(request);
      res.writeHead(200,{'Content-Type':'application/x-ndjson'});
      if(serve)await serve({req,res,request});
      else res.end(line(progress('queued',0))+line(progress('in_progress',60))+line(progress('completed',100))+line(finished()));
    } catch(error) {res.destroy(error);}
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(async()=>{
    server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
    await rm(cwd,{recursive:true,force:true});
  });
  const config={generation,gateway:`http://127.0.0.1:${server.address().port}/`,token:'fixture-video-token',language};
  let gate;
  const pi={registerTool:tool=>tools.push(tool),appendEntry:(...entry)=>entries.push(entry),getAllTools:()=>tools,
    on:(event,handler)=>{assert.equal(event,'tool_call');gate=handler;}};
  createToolPermissionExtension({getPolicy:()=>({mode,language,generation:config.generation})})(pi);
  createGenerationExtension({getConfig:()=>config,...(fetchImpl?{fetchImpl}:{})})(pi);
  const ctx={cwd,hasUI:true,ui:{confirm:async(...args)=>{confirmations.push(args);return approved;}}};
  const run=async(params={prompt:'A plum tree in the breeze'},{signal=new AbortController().signal,onUpdate,context=ctx,id='video-call'}={})=>{
    const tool=tools.find(tool=>tool.name==='video_gen');assert.ok(tool,'registered video_gen');
    const verdict=await gate({toolName:'video_gen',input:params},context);
    if(verdict?.block)throw new Error(verdict.reason);
    return tool.execute(id,params,signal,update=>{updates.push(update);onUpdate?.(update);},context);
  };
  return {cwd,requests,confirmations,updates,entries,tools,config,ctx,run};
}

test('video_gen registers only for complete video configuration and follows existing loadout controls',async t=>{
  for(const generation of [{},{video:null},{video:{provider:'Video',model:''}},{video:{provider:'',model:'model'}},
    {image:{provider:'Image',model:'model'},speech:{provider:'Speech',model:'model'}}]) {
    const f=await fixture(t,{generation});assert.equal(f.tools.some(tool=>tool.name==='video_gen'),false);
  }
  const f=await fixture(t);
  assert.deepEqual(f.tools.map(tool=>tool.name),['video_gen']);
  const tool={...f.tools[0],source:'builtin:generation'};
  assert.equal(toolSelection({preset:'full'},tool),true);
  assert.equal(toolSelection({preset:'minimal'},tool),false);
  assert.ok(excludedSessionTools({preset:'custom',custom:{base:'full',tools:{video_gen:false}}}).includes('video_gen'));
  assert.equal(tool.parameters.properties.seconds.type,'string');
  assert.equal(tool.parameters.properties.seconds.pattern,'^[1-9][0-9]*$');
  assert.equal(tool.parameters.properties.size.pattern,'^[1-9][0-9]*x[1-9][0-9]*$');
});

for(const mode of ['auto','ask'])test(`${mode}: one approval shows video provider/model and the loopback gateway receives video parameters`,async t=>{
  const f=await fixture(t,{mode});
  const output=await f.run({prompt:'A plum tree in the breeze',seconds:'8',size:'1280x720',output_filename:'plum.mp4'});
  assert.equal(f.confirmations.length,1);
  assert.match(f.confirmations[0][1],/Video account \/ video-model/);
  assert.match(f.confirmations[0][1],/generate video/);
  assert.equal(f.requests.length,1);
  assert.equal(f.requests[0].url,'/umeko/generate');
  assert.equal(f.requests[0].authorization,'Bearer fixture-video-token');
  assert.deepEqual(f.requests[0].body,{kind:'video',prompt:'A plum tree in the breeze',seconds:'8',size:'1280x720'});
  assert.deepEqual(f.updates.map(update=>update.details.video),[
    {id:'video-job-1',status:'queued',progress:0},{id:'video-job-1',status:'in_progress',progress:60},
    {id:'video-job-1',status:'completed',progress:100}]);
  assert.deepEqual(f.updates.map(update=>update.content[0].text),['Queued 0%','Generating 60%','Completed 100%']);
  const summary=JSON.parse(output.content[0].text);
  assert.equal(summary.provider,'Actual video provider');assert.equal(summary.model,'actual-video-model');
  assert.deepEqual(summary.paths,[join(f.cwd,'plum.mp4')]);
  assert.equal(await readFile(summary.paths[0],'utf8'),'fixture mp4 bytes');
  assert.equal(chatboxItems('video_gen',output)[0].kind,'file');
  assert.equal(JSON.stringify(output).includes(video.data),false,'no media bytes in model-visible content/details');
});

for(const mode of ['auto','ask'])test(`${mode}: denial sends zero gateway requests and saves no file`,async t=>{
  const f=await fixture(t,{mode,approved:false});
  await assert.rejects(f.run(),/User denied/);
  assert.equal(f.confirmations.length,1);assert.equal(f.requests.length,0);
  assert.deepEqual(await readdir(f.cwd),[]);assert.deepEqual(f.entries,[]);
});

test('headless video calls cannot bypass approval',async t=>{
  const f=await fixture(t);
  await assert.rejects(f.run(undefined,{context:{cwd:f.cwd,hasUI:false}}),/approval UI is unavailable/);
  assert.equal(f.requests.length,0);assert.equal(f.confirmations.length,0);
});

test('Chinese progress and confirmation use configuration language',async t=>{
  const f=await fixture(t,{language:'zh'});await f.run();
  assert.match(f.confirmations[0][1],/生成视频/);
  assert.deepEqual(f.updates.map(update=>update.content[0].text),['排队中 0%','生成中 60%','已完成 100%']);
});

test('MP4 collision saves a new file and nested/history delivery contains only local file references',async t=>{
  const f=await fixture(t);await writeFile(join(f.cwd,'movie.mp4'),'existing user file');
  const output=await f.run({prompt:'A tree',output_filename:'movie.mp4'},{id:'parent/nested-video'});
  const items=chatboxItems('video_gen',output);
  assert.equal(items[0].path,join(f.cwd,'movie-2.mp4'));assert.equal(items[0].kind,'file');
  assert.equal(await readFile(join(f.cwd,'movie.mp4'),'utf8'),'existing user file');
  assert.equal(await readFile(items[0].path,'utf8'),'fixture mp4 bytes');
  const restored=JSON.parse(JSON.stringify(output));
  assert.deepEqual(chatboxItems('video_gen',restored),items);
  assert.deepEqual(chatboxItems('video_gen',{...restored,isError:true}),[]);
  assert.deepEqual(f.entries,[['umeko-chatbox',{version:1,toolCallId:'parent/nested-video',items}]]);
});

test('invalid video arguments fail before making a request',async t=>{
  const f=await fixture(t);
  for(const seconds of [0,8,'0','-1','1.5','01','8s',''])
    await assert.rejects(f.run({prompt:'A tree',seconds}),/seconds/);
  for(const size of ['0x720','1280X720','1280','auto',1280])
    await assert.rejects(f.run({prompt:'A tree',size}),/size/);
  for(const output_filename of ['../outside.mp4','C:\\outside.mp4','folder/movie.mp4','NUL.mp4','movie.webm','movie.png'])
    await assert.rejects(f.run({prompt:'A tree',output_filename}),/filename/);
  for(const prompt of ['', '   ', undefined])await assert.rejects(f.run({prompt}),/prompt/);
  assert.equal(f.requests.length,0);assert.deepEqual(await readdir(f.cwd),[]);
});

test('split NDJSON chunks and final line without newline are consumed',async t=>{
  const first=line(progress('queued',0));
  const f=await fixture(t,{serve:({res})=>{res.write(first.slice(0,13));res.write(first.slice(13));res.end(JSON.stringify(finished()));}});
  const output=await f.run();assert.equal(chatboxItems('video_gen',output).length,1);
  assert.equal(f.updates[0].details.video.status,'queued');
});

test('streamed provider errors retain progress and never save artifacts',async t=>{
  const f=await fixture(t,{serve:({res})=>res.end(line(progress('failed',20))+line({type:'error',error:{message:'Fixture provider refused video'}}))});
  await assert.rejects(f.run(),/Fixture provider refused video/);
  assert.equal(f.updates[0].content[0].text,'Failed 20%');
  assert.equal(f.requests.length,1);assert.deepEqual(await readdir(f.cwd),[]);assert.deepEqual(f.entries,[]);
});

test('mid-stream cancellation closes the local stream and no video is saved',async t=>{
  const closed=deferred();
  const f=await fixture(t,{serve:({res})=>{res.on('close',closed.resolve);res.write(line(progress('in_progress',25)));}});
  const controller=new AbortController();
  const running=f.run(undefined,{signal:controller.signal,onUpdate:()=>controller.abort(new Error('fixture cancelled mid-stream'))});
  await assert.rejects(running,/fixture cancelled mid-stream/);await closed.promise;
  assert.equal(f.requests.length,1);assert.deepEqual(await readdir(f.cwd),[]);assert.deepEqual(f.entries,[]);
});

test('cancellation while awaiting the next chunk interrupts the read',async t=>{
  const first=deferred(),closed=deferred();
  const f=await fixture(t,{serve:({res})=>{res.on('close',closed.resolve);res.write(line(progress('queued',0)));}});
  const controller=new AbortController();
  const running=f.run(undefined,{signal:controller.signal,onUpdate:first.resolve});
  await first.promise;controller.abort(new Error('fixture cancelled pending read'));
  await assert.rejects(running,/fixture cancelled pending read/);await closed.promise;
  assert.deepEqual(await readdir(f.cwd),[]);assert.deepEqual(f.entries,[]);
});

test('a late result in the same chunk after cancellation is ignored',async t=>{
  const f=await fixture(t,{serve:({res})=>res.end(line(progress('in_progress',50))+line(finished()))});
  const controller=new AbortController();
  await assert.rejects(f.run(undefined,{signal:controller.signal,onUpdate:()=>controller.abort(new Error('fixture late result cancelled'))}),/fixture late result cancelled/);
  assert.equal(f.updates.length,1);assert.deepEqual(await readdir(f.cwd),[]);assert.deepEqual(f.entries,[]);
});

test('pre-aborted calls and a fetch that returns after abort cannot save results',async t=>{
  const before=new AbortController();before.abort(new Error('fixture pre-aborted'));
  const f=await fixture(t);await assert.rejects(f.run(undefined,{signal:before.signal}),/fixture pre-aborted/);
  assert.equal(f.requests.length,0);
  const late=new AbortController();
  const stub=await fixture(t,{fetchImpl:async()=>{late.abort(new Error('fixture aborted before response'));return new Response(line(finished()));}});
  await assert.rejects(stub.run(undefined,{signal:late.signal}),/fixture aborted before response/);
  assert.deepEqual(await readdir(stub.cwd),[]);assert.deepEqual(stub.entries,[]);
});

test('abort at stream EOF after its result prevents late saves',async t=>{
  const controller=new AbortController();let readCount=0;
  const f=await fixture(t,{fetchImpl:async()=>({ok:true,body:{getReader:()=>({
    async read(){if(readCount++===0)return {done:false,value:new TextEncoder().encode(line(finished()))};
      controller.abort(new Error('fixture cancelled at EOF'));return {done:true};},
    cancel:async()=>{},releaseLock:()=>{},
  })}})});
  await assert.rejects(f.run(undefined,{signal:controller.signal}),/fixture cancelled at EOF/);
  assert.deepEqual(await readdir(f.cwd),[]);assert.deepEqual(f.entries,[]);
});

test('stream truncation, invalid MP4 and invalid events fail without delivery',async t=>{
  for(const events of [
    [progress('queued',0)],
    [{type:'result',result:{...result,items:[{...video,mimeType:'image/png',extension:'png'}]}}],
    [{type:'result',result:{...result,items:[{...video,data:'not base64'}]}}],
    [{type:'unknown'}],
  ]) {
    const f=await fixture(t,{serve:({res})=>res.end(events.map(line).join(''))});
    await assert.rejects(f.run(),/without a video result|unsupported media format|invalid or oversized|unknown video event/);
    assert.deepEqual(await readdir(f.cwd),[]);assert.deepEqual(f.entries,[]);
  }
});

test('clearing video configuration after registration blocks requests',async t=>{
  const f=await fixture(t);f.config.generation.video=null;
  await assert.rejects(f.run(),/no longer configured/);assert.equal(f.requests.length,0);
});
