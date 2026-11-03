import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, readdir, readFile, realpath, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createGenerationExtension} from '../runtime/generation.mjs';
import {createToolPermissionExtension} from '../runtime/tool-permissions.mjs';
import {chatboxItems} from '../runtime/chatbox.mjs';
import {toolSelection, excludedSessionTools} from '../runtime/session-capabilities.mjs';

const image = {data: Buffer.from('fixture image').toString('base64'), mimeType:'image/png', extension:'png'};
const speech = {data: Buffer.from('fixture speech').toString('base64'), mimeType:'audio/mpeg', extension:'mp3'};
async function fixture(t, {generation={image:{provider:'Image account',model:'image-model'},speech:{provider:'Voice account',model:'voice-model'}}, mode='auto', approved=true, fetchImpl}={}) {
  const cwd=await realpath(await mkdtemp(join(tmpdir(),'umeko-generation-')));
  t.after(()=>rm(cwd,{recursive:true,force:true}));
  const tools=[], entries=[], requests=[], confirmations=[];
  const config={generation,gateway:'http://127.0.0.1:12345/',token:'fixture-private-token'};
  let gate;
  const pi={registerTool:tool=>tools.push(tool),appendEntry:(...entry)=>entries.push(entry),
    getAllTools:()=>tools,on:(event,handler)=>{assert.equal(event,'tool_call');gate=handler;}};
  createToolPermissionExtension({getPolicy:()=>({mode,language:'en',generation})})(pi);
  createGenerationExtension({getConfig:()=>config,fetchImpl:async(url,options)=>{
    requests.push({url:String(url),options,body:JSON.parse(options.body)});
    if(fetchImpl)return fetchImpl(url,options);
    return new Response(JSON.stringify({provider:'Actual account',model:'actual-model',items:[JSON.parse(options.body).kind==='image'?image:speech]}),{status:200});
  }})(pi);
  const ctx={cwd,hasUI:true,model:{input:['text']},ui:{confirm:async(...args)=>{confirmations.push(args);return approved;}}};
  const run=async(name,params,{signal=new AbortController().signal,context=ctx,id='call-1'}={})=>{
    const tool=tools.find(tool=>tool.name===name);assert.ok(tool,'registered '+name);
    const verdict=await gate({toolName:name,input:params},context);
    if(verdict?.block)throw new Error(verdict.reason);
    return tool.execute(id,params,signal,()=>{},context);
  };
  return {cwd,tools,entries,requests,confirmations,config,ctx,run};
}

test('only configured generation modalities register, and loadout controls apply',async t=>{
  const none=await fixture(t,{generation:{image:null,speech:null}});
  assert.deepEqual(none.tools,[]);
  const imageOnly=await fixture(t,{generation:{image:{provider:'Image',model:'selected'},speech:{provider:'Speech',model:''}}});
  assert.deepEqual(imageOnly.tools.map(tool=>tool.name),['image_gen']);
  const tool={...imageOnly.tools[0],source:'builtin:generation'};
  assert.equal(toolSelection({preset:'full'},tool),true);
  assert.equal(toolSelection({preset:'minimal'},tool),false);
  const disabled={preset:'custom',custom:{base:'full',tools:{image_gen:false}}};
  assert.ok(excludedSessionTools(disabled).includes('image_gen'));
});

for(const mode of ['auto','ask'])test(`${mode}: the registered permission gate confirms once before generation`,async t=>{
  const f=await fixture(t,{mode});
  const result=await f.run('image_gen',{prompt:'Draw a small plum',size:'1024x1024',count:1,output_filename:'plum.png'},{id:'parent/nested-call'});
  assert.equal(f.confirmations.length,1);
  assert.match(f.confirmations[0][1],/Image account \/ image-model/);
  assert.match(f.confirmations[0][1],/Draw a small plum/);
  assert.equal(f.requests.length,1);
  assert.equal(f.requests[0].url,'http://127.0.0.1:12345/umeko/generate');
  assert.equal(f.requests[0].options.headers.Authorization,'Bearer fixture-private-token');
  assert.deepEqual(f.requests[0].body,{kind:'image',prompt:'Draw a small plum',size:'1024x1024',count:1,format:'png'});
  const summary=JSON.parse(result.content[0].text);
  assert.deepEqual(summary.paths,[join(f.cwd,'plum.png')]);
  assert.equal(summary.provider,'Actual account');
  assert.equal(summary.model,'actual-model');
  assert.equal(await readFile(summary.paths[0],'utf8'),'fixture image');
  assert.equal(chatboxItems('image_gen',result)[0].kind,'image');
  assert.deepEqual(f.entries,[['umeko-chatbox',{version:1,toolCallId:'parent/nested-call',items:result.details.umekoChatbox.items}]]);
  assert.deepEqual(result.content.map(block=>block.type),['text']);
  assert.ok(!JSON.stringify(result).includes(image.data),'no base64 bytes in text or details');
});

test('denial prevents both the provider call and filesystem output',async t=>{
  const f=await fixture(t,{mode:'ask',approved:false});
  await assert.rejects(f.run('voice_gen',{text:'Hello'}),/denied/);
  assert.equal(f.confirmations.length,1);
  assert.equal(f.requests.length,0);
  assert.deepEqual(await readdir(f.cwd),[]);
});

test('speech produces a chat file reference, forwards options, and never overwrites',async t=>{
  const f=await fixture(t);
  await writeFile(join(f.cwd,'hello.mp3'),'user file');
  const result=await f.run('voice_gen',{text:'Hello there',voice:'test-voice',format:'mp3',speed:1.2,output_filename:'hello.mp3'});
  const path=JSON.parse(result.content[0].text).paths[0];
  assert.equal(path,join(f.cwd,'hello-2.mp3'));
  assert.equal(await readFile(join(f.cwd,'hello.mp3'),'utf8'),'user file');
  assert.equal(await readFile(path,'utf8'),'fixture speech');
  assert.equal(chatboxItems('voice_gen',result)[0].kind,'file');
  assert.deepEqual(f.requests[0].body,{kind:'speech',text:'Hello there',voice:'test-voice',format:'mp3',speed:1.2});
  assert.match(f.confirmations[0][1],/Voice account \/ voice-model/);
});

test('unsafe filenames and conflicting extensions fail before the gateway request',async t=>{
  const f=await fixture(t);
  for(const output_filename of ['../escape.png','C:\\outside.png','folder/file.png','NUL.png','.hidden','bad:stream.png','trailing.','image.exe'])
    await assert.rejects(f.run('image_gen',{prompt:'test',output_filename}),/filename/);
  await assert.rejects(f.run('image_gen',{prompt:'test',format:'webp',output_filename:'image.png'}),/match/);
  assert.equal(f.requests.length,0);
  assert.deepEqual(await readdir(f.cwd),[]);
});

test('batch output uses exclusive suffixes and vision models still receive paths only',async t=>{
  const f=await fixture(t,{fetchImpl:async()=>new Response(JSON.stringify({items:[image,image],provider:'Image',model:'batch'}))});
  const result=await f.run('image_gen',{prompt:'pair',count:2,output_filename:'pair.png'},{context:{...f.ctx,model:{input:['text','image']}}});
  assert.deepEqual(JSON.parse(result.content[0].text).paths,[join(f.cwd,'pair.png'),join(f.cwd,'pair-2.png')]);
  assert.equal(chatboxItems('image_gen',result).length,2);
  assert.deepEqual(result.content.map(block=>block.type),['text']);
});

test('AbortSignal cancels the gateway request and creates no output',async t=>{
  let started;
  const ready=new Promise(resolve=>started=resolve);
  const f=await fixture(t,{fetchImpl:async(_url,{signal})=>new Promise((_resolve,reject)=>{
    started();signal.addEventListener('abort',()=>reject(signal.reason),{once:true});
  })});
  const controller=new AbortController();
  const running=f.run('image_gen',{prompt:'cancel me'},{signal:controller.signal});
  await ready;controller.abort(new Error('fixture cancelled'));
  await assert.rejects(running,/fixture cancelled/);
  assert.equal(f.requests[0].options.signal,controller.signal);
  assert.deepEqual(await readdir(f.cwd),[]);
  assert.deepEqual(f.entries,[]);
});

test('gateway errors remain tool errors and malformed media never creates files',async t=>{
  const failed=await fixture(t,{fetchImpl:async()=>new Response(JSON.stringify({error:{message:'Provider refused fixture'}}),{status:400})});
  await assert.rejects(failed.run('image_gen',{prompt:'test'}),/Provider refused fixture/);
  const malformed=await fixture(t,{fetchImpl:async()=>new Response(JSON.stringify({items:[{...image,extension:'exe'}]}))});
  await assert.rejects(malformed.run('image_gen',{prompt:'test'}),/unsupported/);
  assert.deepEqual(await readdir(malformed.cwd),[]);
});
