import test from 'node:test';
import assert from 'node:assert/strict';
import {createWidgetMessages} from '../runtime/widget-messages.mjs';
const update=(suffix='a')=>({id:suffix.repeat(32),widgetId:'sample',name:'Sample',requestId:'request-one',message:'result ready',data:{count:3},wake:true});

test('Widget push uses native steering, preserves structured data and correlates delivery',async()=>{
  const sent=[],events=[];
  const session={isStreaming:true,async sendCustomMessage(message,options){sent.push({message,options});}};
  const channel=createWidgetMessages({getSession:()=>session,emit:event=>events.push(event)});
  await channel.deliver(update());
  assert.deepEqual(sent[0].options,{deliverAs:'steer',triggerTurn:true});
  assert.equal(sent[0].message.customType,'umeko-widget-update');
  assert.deepEqual(sent[0].message.details.data,{count:3});
  assert.equal(events.at(-1).status,'queued');
  channel.observe({type:'message_start',message:{role:'custom',...sent[0].message}});
  assert.equal(events.at(-1).status,'delivered');
  await channel.deliver(update());assert.equal(sent.length,1);
});

test('passive updates do not wake the model and failures have explicit receipts',async()=>{
  const sent=[],events=[];let fail=false;
  const channel=createWidgetMessages({getSession:()=>({async sendCustomMessage(message,options){if(fail)throw new Error('transport closed');sent.push(options);}}),emit:event=>events.push(event)});
  await channel.deliver({...update('b'),wake:false});assert.equal(sent[0].triggerTurn,false);
  fail=true;await assert.rejects(channel.deliver(update('c')),/transport closed/);
  assert.equal(events.at(-1).status,'failed');assert.match(events.at(-1).error,/transport closed/);
  await assert.rejects(channel.deliver({...update('d'),message:''}),/Invalid Widget/);
  assert.equal(sent.length,1);
});

import {createLoopReview} from '../runtime/widget-messages.mjs';
test('loop boundaries await snapshots, correlate replies, and include cancellation',async()=>{
  const handlers={},events=[];
  const review=createLoopReview({emit:event=>events.push(event),timeoutMs:1000});
  review.extension({on:(name,handler)=>handlers[name]=handler});
  let started=false;
  const start=handlers.agent_start().then(()=>started=true);
  await Promise.resolve();assert.equal(started,false);assert.equal(events[0].phase,'begin');
  review.response({id:'other'});assert.equal(started,false);
  review.response({id:events[0].id});await start;assert.equal(started,true);
  const finish=handlers.agent_end({messages:[{role:'assistant',stopReason:'aborted'}]});
  assert.equal(events[1].loopId,events[0].loopId);assert.equal(events[1].reason,'cancelled');
  review.response({id:events[1].id});await finish;
  await handlers.agent_end({messages:[]});assert.equal(events.length,2);
});
test('disconnected review hooks have a bounded wait and shutdown releases pending hooks',async()=>{
  const handlers={};const review=createLoopReview({emit:()=>{},timeoutMs:10});
  review.extension({on:(name,handler)=>handlers[name]=handler});
  await handlers.agent_start();const end=handlers.agent_end({messages:[]});review.clear();await end;
});
