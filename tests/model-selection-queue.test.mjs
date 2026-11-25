import test from "node:test";
import assert from "node:assert/strict";
import {createInputQueue} from "../runtime/input-queue.mjs";

function fixture() {
  let release;
  const gate=new Promise(resolve=>{release=resolve;});
  const calls=[],native=[],returned=[],publications=[],aborted=[],edited=[];
  let followUps=[],steering=[],queue;
  const session={
    model:{id:"choice-a"},isIdle:false,
    getSteeringMessages:()=>steering,
    getFollowUpMessages:()=>followUps,
    clearQueue(){followUps=[];steering=[];queue.sync(steering,followUps);},
    async followUp(text,images){native.push({text,images});followUps.push(text);queue.sync(steering,followUps);},
    async steer(text){steering.push(text);queue.sync(steering,followUps);},
    async abort(){aborted.push(session.model.id);release();},
  };
  queue=createInputQueue({getSession:()=>session,isRunning:()=>true,
    onQueue:(_steering,_followUp,items)=>publications.push(items),
    onReturned:items=>returned.push(...items),onEdited:item=>edited.push(item)});
  const first={id:"first",text:"Running turn",model:"choice-a",reasoningEffort:"off"};
  const run=queue.run(first,async input=>{
    calls.push(input);
    session.model={id:input.model};
    if (input===first) await gate;
  });
  return {queue,run,release,calls,native,returned,publications,aborted,edited};
}

test("model-changing follow-ups preserve FIFO request snapshots after the running turn",async()=>{
  const f=fixture();
  const second={type:"follow-up",messageId:"second",text:"Use the new choice",
    model:"choice-b",reasoningEffort:"high",images:[{type:"image",data:"fixture-image"}]};
  const third={type:"follow-up",messageId:"third",text:"Return to the first choice",
    model:"choice-a",reasoningEffort:"off"};
  try {
    await f.queue.submit(second);
    await f.queue.submit(third);
    assert.equal(f.calls.length,1);
    assert.deepEqual(f.native,[]);
    assert.deepEqual(f.queue.items.map(({id,text,mode})=>({id,text,mode})),[
      {id:"second",text:second.text,mode:"followUp"},
      {id:"third",text:third.text,mode:"followUp"},
    ]);
    assert.deepEqual(f.publications.at(-1).map(item=>item.id),["second","third"]);
    f.release();
    await f.run;
    assert.deepEqual(f.calls.map(({model,reasoningEffort})=>({model,reasoningEffort})),[
      {model:"choice-a",reasoningEffort:"off"},
      {model:"choice-b",reasoningEffort:"high"},
      {model:"choice-a",reasoningEffort:"off"},
    ]);
    assert.equal(f.calls[1].text,second.text);
    assert.deepEqual(f.calls[1].images,second.images);
    assert.equal(f.calls[2].text,third.text);
    assert.deepEqual(f.queue.items,[]);
  } finally {
    f.release();
    await f.run;
  }
});

test("cancel returns deferred model snapshots and completes the current turn alone",async()=>{
  const f=fixture();
  try {
    await f.queue.submit({type:"follow-up",messageId:"deferred",text:"Keep this queued input",
      model:"choice-b",reasoningEffort:"high"});
    f.queue.cancel();
    f.release();
    await f.run;
    assert.equal(f.calls.length,1);
    assert.deepEqual(f.queue.items,[]);
    assert.deepEqual(f.returned.map(({id,text,model,reasoningEffort})=>({id,text,model,reasoningEffort})),[
      {id:"deferred",text:"Keep this queued input",model:"choice-b",reasoningEffort:"high"},
    ]);
    assert.deepEqual(f.native,[]);
  } finally {
    f.release();
    await f.run;
  }
});

test("priority model change runs before an earlier follow-up with its original model snapshot",async()=>{
  const f=fixture();
  try {
    await f.queue.submit({type:"follow-up",messageId:"normal",text:"Earlier normal input",
      model:"choice-a",reasoningEffort:"off"});
    assert.equal(f.native.length,1);
    await f.queue.submit({type:"steer",messageId:"priority",text:"Priority input",
      model:"choice-b",reasoningEffort:"high"});
    await f.run;
    assert.deepEqual(f.aborted,["choice-a"]);
    assert.equal(f.native.length,1);
    assert.deepEqual(f.calls.map(({text,model,reasoningEffort})=>({text,model,reasoningEffort})),[
      {text:"Running turn",model:"choice-a",reasoningEffort:"off"},
      {text:"Priority input",model:"choice-b",reasoningEffort:"high"},
      {text:"Earlier normal input",model:"choice-a",reasoningEffort:"off"},
    ]);
    assert.deepEqual(f.queue.items,[]);
  } finally {
    f.release();
    await f.run;
  }
});

test("editing and deleting deferred inputs retain the remaining FIFO model snapshots",async()=>{
  const f=fixture();
  try {
    for (const [id,model] of [["edit","choice-b"],["delete","choice-c"],
                              ["keep-first","choice-b"],["keep-second","choice-c"]]) {
      await f.queue.submit({type:"follow-up",messageId:id,text:id,model,reasoningEffort:"high"});
    }
    await f.queue.submit({type:"edit-queue",id:"edit"});
    await f.queue.submit({type:"delete-queue",id:"delete"});
    assert.deepEqual(f.edited.map(({id,model,reasoningEffort})=>({id,model,reasoningEffort})),[
      {id:"edit",model:"choice-b",reasoningEffort:"high"},
    ]);
    assert.deepEqual(f.queue.items.map(item=>item.id),["keep-first","keep-second"]);
    assert.deepEqual(f.native,[]);
    f.release();
    await f.run;
    assert.deepEqual(f.calls.slice(1).map(({text,model,reasoningEffort})=>({text,model,reasoningEffort})),[
      {text:"keep-first",model:"choice-b",reasoningEffort:"high"},
      {text:"keep-second",model:"choice-c",reasoningEffort:"high"},
    ]);
  } finally {
    f.release();
    await f.run;
  }
});
