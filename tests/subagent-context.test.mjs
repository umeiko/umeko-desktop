import test from 'node:test';
import assert from 'node:assert/strict';
import {createSubagentExtension} from '../runtime/subagents.mjs';

const setup = async () => {
  const events=[], calls=[], sessions=new Map();
  const make=id=>({messages:[{role:'user',content:'History '+id}], model:{id:'model-'+id}, isStreaming:false,getSteeringMessages:()=>[],getFollowUpMessages:()=>[],clearQueue:()=>({steering:[],followUp:[]}),
    sessionManager:{getSessionFile:()=>'',getSessionId:()=>id,getCwd:()=>'/tmp'},getActiveToolNames:()=>[],
    getContextUsage:()=>({tokens:id==='a'?1200:3200,contextWindow:10000,percent:id==='a'?12:32}),
    prompt:async()=>{throw new Error('Opening and compacting a child must never prompt it');},
    subscribe:()=>()=>{},compact:async()=>{calls.push(id);},dispose:async()=>{}});
  const adapter=createSubagentExtension({emit:e=>events.push(e),loadPackage:async()=>({getService:()=>null,factory:()=>{}}),
    restoreSession:async row=>{const session=make(row.id);sessions.set(row.id,session);return session;}});
  await adapter.extension({events:{on:()=>()=>{}},on(){},appendEntry(){}});
  adapter.hydrate(['a','b','busy'].map(id=>({type:'custom',customType:'umeko-subagent',data:{version:1,tool:{id:'subagent:'+id,name:'subagent',subagent:{id,status:'completed',outputFile:'/native/'+id}}}})));
  return {adapter,events,calls,sessions};
};
test('context usage and compaction remain bound to the selected child, never its parent or sibling', async()=>{
  const {adapter,events,calls,sessions}=await setup();
  try {
    await adapter.command({action:'watch',id:'a'});
    await new Promise(r=>setImmediate(r));
    assert.equal(events.filter(e=>e.type==='subagent_usage').at(-1).usage.tokens,1200);
    await adapter.command({action:'watch',id:'b'});
    await new Promise(r=>setImmediate(r));
    assert.equal(events.filter(e=>e.type==='subagent_usage').at(-1).usage.percent,32);
    await adapter.command({action:'compact',id:'b',requestId:'compact-b'});
    assert.deepEqual(calls,['b']);
    assert.equal(events.find(e=>e.requestId==='compact-b').ok,true);
    sessions.get('b').isStreaming=true;
    await adapter.command({action:'compact',id:'b',requestId:'busy'});
    assert.deepEqual(calls,['b']);
    assert.equal(events.find(e=>e.requestId==='busy').ok,false);
    await adapter.command({action:'compact',id:'missing',requestId:'unknown'});
    assert.equal(events.find(e=>e.requestId==='unknown').ok,false);
    assert.deepEqual(calls,['b']);
  } finally {adapter.dispose();}
});
test('a native compaction failure is reported and clears busy state without a retry', async()=>{
  const {adapter,events,sessions}=await setup();
  try {
    await adapter.command({action:'watch',id:'a'});await new Promise(r=>setImmediate(r));
    let count=0;sessions.get('a').compact=async()=>{count++;throw new Error('native compaction failed');};
    await adapter.command({action:'compact',id:'a',requestId:'failure'});
    assert.equal(count,1);assert.equal(events.find(e=>e.requestId==='failure').ok,false);
    assert.match(events.find(e=>e.requestId==='failure').message,/native compaction failed/);
    assert.equal(events.filter(e=>e.type==='subagent_usage').at(-1).busy,false);
  } finally {adapter.dispose();}
});
