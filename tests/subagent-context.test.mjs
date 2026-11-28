import test from 'node:test';
import assert from 'node:assert/strict';
import {createSubagentExtension} from '../runtime/subagents.mjs';

const observedSession = id => {
  const listeners = new Set(), receipts = [];
  return {
    receipts,
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    dispatch(event) { for (const fn of listeners) fn(event); },
    sessionManager: {
      getSessionFile: () => '',
      getSessionId: () => id,
      getCwd: () => '/tmp',
      appendCustomEntry(type, data) { receipts.push({type,data}); return 'receipt-'+receipts.length; },
    },
  };
};

const setup = async () => {
  const events=[], calls=[], sessions=new Map();
  const make=id=>({messages:[{role:'user',content:'History '+id}], model:{id:'model-'+id}, isStreaming:false,getSteeringMessages:()=>[],getFollowUpMessages:()=>[],clearQueue:()=>({steering:[],followUp:[]}),
    ...observedSession(id),getActiveToolNames:()=>[],
    getContextUsage:()=>({tokens:id==='a'?1200:3200,contextWindow:10000,percent:id==='a'?12:32}),
    prompt:async()=>{throw new Error('Opening and compacting a child must never prompt it');},
    compact:async()=>{calls.push(id);},dispose:async()=>{}});
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

test('manual no-op compactions do not masquerade as provider failures', async()=>{
  const {adapter,events,sessions}=await setup();
  try {
    await adapter.command({action:'watch',id:'a'});
    await new Promise(r=>setImmediate(r));
    const child=sessions.get('a');
    for (const [message, skipReason] of [
      ['Nothing to compact (session too small)', 'too-short'],
      ['Already compacted', 'already-compacted'],
      ['fixture rejected compaction input', undefined]
    ]) {
      child.compact=async()=>{
        child.dispatch({type:'compaction_start',reason:'manual'});
        child.dispatch({type:'compaction_end',reason:'manual',errorMessage:'Compaction failed: '+message,aborted:false});
        throw new Error(message);
      };
      await adapter.command({action:'compact',id:'a',requestId:message});
      const [{data:start},{data:end}]=child.receipts.slice(-2);
      assert.equal(start.eventId,end.eventId);
      assert.equal(start.state,'running');
      assert.equal(end.state,skipReason?'skipped':'failure');
      assert.equal(end.skipReason,skipReason);
      assert.equal(end.error,skipReason?'':'Compaction failed: '+message);
      assert.equal(events.find(e=>e.requestId===message).ok,!!skipReason);
    }
    assert.equal(child.receipts.length,6);
  } finally {adapter.dispose();}
});
test('native compaction persists to its own transcript before a child is identified', async()=>{
  const {adapter,events}=await setup();
  try {
    const child={...observedSession('unbound'), prompt:async()=>{}, clearQueue:()=>({steering:[],followUp:[]}), getContextUsage:()=>({tokens:1200})};
    const hook=globalThis[Symbol.for('umeko:subagent-session')];
    assert.equal(typeof hook,'function');
    hook(child); hook(child);
    child.dispatch({type:'compaction_start',reason:'threshold'});
    child.dispatch({type:'compaction_end',reason:'threshold',result:{tokensBefore:1200,estimatedTokensAfter:500,summary:'checkpoint'},aborted:false});
    assert.deepEqual(child.receipts.map(x=>x.data.state),['running','success']);
    assert.equal(child.receipts[0].data.eventId,child.receipts[1].data.eventId);
    assert.equal(events.filter(e=>e.type==='subagent_event').length,0);
  } finally {adapter.dispose();}
});
test('sibling progress cannot detach the native child compaction observer', async()=>{
  const handlers=new Map(), events=[];
  const records=['first','sibling'].map(id=>({id,status:'running',outputFile:'/native/'+id}));
  const make=id=>{
    const session=observedSession(id);
    session.sessionManager.getSessionFile=()=>'/native/'+id;
    return Object.assign(session,{messages:[],prompt:async()=>{},getContextUsage:()=>({tokens:1800}),
      getActiveToolNames:()=>[],getSteeringMessages:()=>[],getFollowUpMessages:()=>[],clearQueue:()=>({steering:[],followUp:[]})});
  };
  const first=make('first'), sibling=make('sibling');
  const observe=session=>globalThis[Symbol.for('umeko:subagent-session')](session);
  let wrapped;
  const adapter=createSubagentExtension({emit:event=>events.push(event),loadPackage:async()=>({
    getService:()=>({listAgents:()=>records,getRecord:id=>records.find(record=>record.id===id)}),
    factory:async pi=>pi.registerTool({name:'subagent',execute:async()=>{
      handlers.get('subagents:started')({id:'first'});
      handlers.get('subagents:update')({id:'sibling',message:'Sibling progress in the original async scope'});
      observe(first);
      return {content:[]};
    }})
  })});
  await adapter.extension({events:{on:(kind,fn)=>{handlers.set(kind,fn);return ()=>handlers.delete(kind);}},
    on(){},appendEntry(){},registerTool(tool){wrapped=tool;}});
  try {
    await wrapped.execute('first-call',{},undefined,undefined,{});
    observe(sibling);
    await adapter.command({action:'watch',id:'first'});
    first.dispatch({type:'compaction_start',reason:'threshold'});
    first.dispatch({type:'compaction_end',reason:'threshold',result:{tokensBefore:1800,estimatedTokensAfter:650,summary:'checkpoint'},aborted:false});
    assert.deepEqual(first.receipts.map(receipt=>receipt.data.state),['running','success']);
    assert.equal(first.receipts[0].data.eventId,first.receipts[1].data.eventId);
    assert.deepEqual(sibling.receipts,[]);
    assert.deepEqual(events.filter(e=>e.type==='subagent_event').map(e=>[e.id,e.event.state]),
      [['first','running'],['first','success']]);
  } finally {adapter.dispose();}
});
