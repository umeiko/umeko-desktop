import test from 'node:test';
import assert from 'node:assert/strict';
import {createAuxiliaryVision} from '../runtime/auxiliary-vision.mjs';

const image={type:'image',data:Buffer.from('fixture image').toString('base64'),mimeType:'image/png'};
const config=()=>({gateway:'http://127.0.0.1:8787/',token:'private-token',models:[{id:'text',input:['text']},{id:'native',input:['text','image']}],
  auxiliaryVision:{providerId:'vision-provider',model:'eyes',modelName:'vision-upstream-model',providerName:'Vision',label:'Vision / eyes',autoAnalyze:true,toolEnabled:true}});
const reply=text=>new Response('data: '+JSON.stringify({choices:[{delta:{content:text}}]})+'\n\ndata: [DONE]\n\n');
function fixture(entries = []) {
  const value=config(),events=[],requests=[];
  const host=createAuxiliaryVision({getConfig:()=>value,emit:event=>events.push(event),fetchImpl:async(url,options)=>{
    requests.push({url:String(url),...options,body:JSON.parse(options.body)});return reply('The screenshot says ERROR 123.');
  }});
  let context;
  const manager = {getBranch:()=>entries,getSessionId:()=> 'fixture'};
  host.contextExtension({on:(name,handler)=>{if(name==='context')context=handler;},appendEntry:(customType,data)=>entries.push({type:'custom',id:'receipt-'+entries.length,customType,data:structuredClone(data)})});
  return {value,events,requests,host,entries,context:(event,ctx={})=>context(event,{sessionManager:manager,...ctx})};
}
test('automatic projection keeps the transcript intact, caches observations and pins provider identity',async()=>{
  const f=fixture(),messages=[{role:'user',content:[{type:'text',text:'What error is shown?'},image]}];
  const original=structuredClone(messages);
  const output=await f.context({messages},{model:{id:'text'},abort:()=>assert.fail('unexpected abort')});
  assert.deepEqual(messages,original);
  assert.equal(output.messages[0].content.filter(block=>block.type==='image').length,0);
  assert.match(output.messages[0].content[1].text,/ERROR 123/);
  assert.equal(f.requests.length,1);
  assert.equal(f.requests[0].body._umeko_provider,'vision-provider');
  assert.equal(f.requests[0].body.model,'eyes');
  assert.equal(f.requests[0].body.tools,undefined);
  assert.equal(f.events[0].name,'analyze_image');assert.equal(f.events[0].state,'running');assert.equal(f.events.at(-1).state,'done');
  assert.equal(f.events[0].args.model,'vision-upstream-model');assert.equal(f.events[0].args.provider,'Vision');assert.equal(f.entries.length,1);
  await f.context({messages},{model:{id:'text'}});assert.equal(f.requests.length,1);
  for (let turn=0;turn<4;turn++) {
    const followup=await f.context({messages:[...messages,{role:'assistant',content:[{type:'text',text:'answer'}]},{role:'user',content:[{type:'text',text:'Follow up '+turn}]}]},{model:{id:'text'}});
    assert.match(JSON.stringify(followup),/ERROR 123/);
  }
  assert.equal(f.requests.length,1,'Follow-ups and tool-loop context rebuilds must reuse the first observation');
  assert.equal(f.entries.length,1,'Reusing history must not add another tool row');
  const restored=fixture(f.entries);
  const historical=await restored.context({messages:[...messages,{role:'user',content:[{type:'text',text:'After reopening the app'}]}]},{model:{id:'text'}});
  assert.match(JSON.stringify(historical),/ERROR 123/);assert.equal(restored.requests.length,0,'A fresh runtime recovers observations from its active native branch');
  await f.context({messages:[{role:'user',content:[{type:'text',text:'Read the footer'},image]}]},{model:{id:'text'}});
  assert.equal(f.requests.length,2,'A different task must not reuse an unrelated description');
});
test('partial pruning, additional attachments and automatic-off do not resend an observed image',async()=>{
  const f=fixture(),second={...image,data:Buffer.from('second image').toString('base64')};
  const original={role:'user',timestamp:123,content:[{type:'text',text:'Compare'},image,second]};
  await f.context({messages:[original]},{model:{id:'text'}});
  const pruned={...original,content:[original.content[0],{type:'text',text:'[Image removed from context to save space.]'},second]};
  await f.context({messages:[pruned,{role:'user',content:[{type:'text',text:'Another question'}]}]},{model:{id:'text'}});
  assert.equal(f.requests.length,1,'A partially retained attachment batch keeps its previous observations');
  const allPruned={...original,content:[original.content[0],{type:'text',text:'[Image removed from context to save space.]'},{type:'text',text:'[Image removed from context to save space.]'}]};
  const historical=await f.context({messages:[allPruned,{role:'user',content:[{type:'text',text:'A much later question'}]}]},{model:{id:'text'}});
  assert.match(JSON.stringify(historical),/ERROR 123/,'Saved observations remain available when recent-image pruning removes the original image blocks');
  assert.equal(f.requests.length,1);
  await f.context({messages:[pruned,{role:'user',timestamp:234,content:[{type:'text',text:'New attachment'},image]}]},{model:{id:'text'}});
  assert.equal(f.requests.length,2);
  assert.equal(f.requests[1].body.messages[1].content.filter(block=>block.type==='image_url').length,1,'Only the new attachment reaches the helper');
  f.value.auxiliaryVision.autoAnalyze=false;
  const output=await f.context({messages:[original,{role:'user',timestamp:345,content:[{type:'text',text:'Not automatic'},image]}]},{model:{id:'text'}});
  assert.equal(f.requests.length,2);
  assert.ok(!output.messages.some(row=>row.content.some(block=>block.type==='image')));
  assert.match(JSON.stringify(output),/ERROR 123/);
});
test('native vision, unset helper and automatic-off preserve the existing request path',async()=>{
  for(const mode of ['native','unset','manual']) {
    const f=fixture();if(mode==='unset')f.value.auxiliaryVision={};if(mode==='manual')f.value.auxiliaryVision.autoAnalyze=false;
    const result=await f.context({messages:[{role:'user',content:[image]}]},{model:{id:mode==='native'?'native':'text'}});
    if(mode==='manual')assert.ok(!result.messages[0].content.some(block=>block.type==='image'));
    else assert.equal(result,undefined);
    assert.equal(f.requests.length,0);
  }
});
test('tool toggle is independent of automatic analysis and has a real schema',()=>{
  const f=fixture(),tools=[];
  f.value.auxiliaryVision.autoAnalyze=false;
  f.host.toolExtension({registerTool:tool=>tools.push(tool)});
  assert.deepEqual(tools.map(tool=>tool.name),['analyze_image']);
  f.value.auxiliaryVision.toolEnabled=false;
  f.host.toolExtension({registerTool:()=>assert.fail('disabled tool registered')});
});
test('failed or incomplete analysis aborts the turn and preserves a failed tool receipt',async()=>{
  const value=config(),events=[];let aborted=false;
  const host=createAuxiliaryVision({getConfig:()=>value,emit:event=>events.push(event),fetchImpl:async()=>new Response('data: '+JSON.stringify({choices:[{delta:{content:'partial'}}]})+'\n\n')});
  const entries=[];
  let handler;host.contextExtension({on:(_name,callback)=>handler=callback,appendEntry:(customType,data)=>entries.push({customType,data})});
  await assert.rejects(handler({messages:[{role:'user',content:[image]}]},{model:{id:'text'},sessionManager:{getBranch:()=>[],getSessionId:()=> 'failed'},abort:()=>aborted=true}),/without a complete/);
  assert.equal(aborted,true);assert.equal(events.filter(event=>event.type==='tool').at(-1).state,'error');
  assert.equal(entries[0].data.tool.state,'error');
});
test('already cancelled requests never contact a model',async()=>{
  const f=fixture(),cancel=new AbortController();cancel.abort();
  await assert.rejects(f.host.analyze([image],'describe',cancel.signal));
  assert.equal(f.requests.length,0);
});
test('changing the upstream model behind an alias cannot reuse another model result',async()=>{
  const f=fixture();
  await f.host.analyze([image],'Describe');
  f.value.auxiliaryVision.modelName='another-upstream-model';
  const result=await f.host.analyze([image],'Describe');
  assert.equal(f.requests.length,2);
  assert.equal(result.label,'another-upstream-model');
});
