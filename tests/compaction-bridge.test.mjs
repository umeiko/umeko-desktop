import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { createInterface } from "node:readline";
import { once } from "node:events";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, copyFileSync, rmSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const release = join(root,"runtime/releases/coding-1.3.0");
const profile = process.env.UMEKO_COMPACTION_TEST_ROOT || "C:/UmekoTests/pr3-direction-20261029";

async function fixture(t, {autoCompaction=false, hook="", legacy=false, summaryError=false}={}) {
  mkdirSync(profile,{recursive:true});
  const temp = mkdtempSync(join(profile,"bridge-"));
  const agentDir = join(temp,"agent");
  mkdirSync(join(agentDir,"extensions"),{recursive:true});
  writeFileSync(join(agentDir,"settings.json"),JSON.stringify({compaction:{reserveTokens:16384,keepRecentTokens:100}}));
  writeFileSync(join(agentDir,"extensions/probe.js"),`export default pi => {
    pi.registerCommand("probe-compaction", {description:"test settings",handler:async (_args,ctx) => ctx.ui.notify(JSON.stringify({model:ctx.model.id,compaction:pi.getSettings().compaction}))});
    ${hook}
  };`);
  for (const name of readdirSync(join(root,"runtime")).filter(name=>/\.(mjs|json)$/.test(name)))
    copyFileSync(join(root,"runtime",name),join(release,name));
  const calls = [];
  const server = createServer(async (req,res) => {
    let raw=""; for await (const chunk of req) raw+=chunk;
    const body=JSON.parse(raw); calls.push(body);
    const summary = !body.tools?.length;
    if(summary&&summaryError){res.writeHead(400,{"Content-Type":"application/json"});res.end(JSON.stringify({error:{message:"fixture compaction failure",type:"invalid_request_error"}}));return;}
    const content = summary ? "NATIVE_SUMMARY_FIXTURE" : "fixture answer";
    const input = summary ? 100 : body.model === "small" ? 50000 : 1800;
    const common = {id:"fixture",object:"chat.completion.chunk",created:1,model:body.model};
    res.writeHead(200,{"Content-Type":"text/event-stream"});
    res.end(`data: ${JSON.stringify({...common,choices:[{index:0,delta:{role:"assistant",content},finish_reason:null}]})}\n\ndata: ${JSON.stringify({...common,choices:[{index:0,delta:{},finish_reason:"stop"}],usage:{prompt_tokens:input,completion_tokens:5,total_tokens:input+5}})}\n\ndata: [DONE]\n\n`);
  });
  server.listen(0,"127.0.0.1"); await once(server,"listening");
  let process, lines, stderr="";
  const start=() => {
    const preload=globalThis.process.env.UMEKO_WINDOWS_HIDE_PRELOAD;
    process=spawn(globalThis.process.execPath,[...(preload?["--import",preload]:[]),join(release,"bridge.mjs")],{stdio:["pipe","pipe","pipe"],windowsHide:true});
    process.stderr.on("data",chunk=>stderr+=chunk);
    lines=createInterface({input:process.stdout})[Symbol.asyncIterator]();
  };
  const send=payload=>process.stdin.write(JSON.stringify(payload)+"\n");
  const command=async (payload,{errors=false}={}) => {
    send(payload); const events=[];
    for (;;) {
      let timer;
      const next=await Promise.race([lines.next(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error("Bridge timed out: "+stderr)),20000);timer.unref();})]);
      clearTimeout(timer);
      assert.ok(!next.done,"Bridge exited: "+stderr);
      const event=JSON.parse(next.value); events.push(event);
      if(event.type==="done")break;
    }
    if(!errors)assert.deepEqual(events.filter(e=>e.type==="error"),[],JSON.stringify(events));
    return events;
  };
  const stop=async()=>{if(process.exitCode===null){send({type:"shutdown"});await once(process,"exit");}};
  start();
  t.after(async()=>{await stop();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));rmSync(temp,{recursive:true,force:true});});
  const init={type:"inspect",gateway:`http://127.0.0.1:${server.address().port}/`,token:"fixture-only",workspace:temp,defaultCwd:temp,agentDir,sessionDir:join(temp,"sessions"),
    models:[{id:"wide",contextWindow:128000},{id:"small",contextWindow:64000}],model:"wide",agent:{autoCompaction}};
  if(legacy){
    init.sessionFile=join(temp,"legacy.jsonl");
    const stamp="2026-10-27T00:00:00.000Z";
    const entries=[{type:"session",version:3,id:"legacy-fixture",timestamp:stamp,cwd:temp},
      {type:"message",id:"old-user",parentId:null,timestamp:stamp,message:{role:"user",content:"legacy question",timestamp:1000}},
      {type:"custom",customType:"umeko-compaction",id:"old-receipt",parentId:"old-user",timestamp:stamp,data:{version:1,mode:"manual",before:200,after:100,afterEstimated:true}}];
    writeFileSync(init.sessionFile,entries.map(JSON.stringify).join("\n")+"\n");
  }
  return {calls,command,init,restart:async()=>{await stop();start();}};
}

function lifecycle(events, mode, terminal) {
  const transitions=events.filter(e=>e.type==="compaction_event");
  assert.deepEqual(transitions.map(e=>e.state),["running",terminal]);
  assert.equal(transitions[0].mode,mode);assert.equal(transitions[1].mode,mode);
  assert.equal(transitions[0].eventId,transitions[1].eventId);
  assert.notEqual(transitions[0].entryId,transitions[1].entryId);
  assert.ok(!events.some(e=>e.type==="message"&&e.customType==="umeko-compaction"),"Timeline emitted an extra assistant message");
  return transitions;
}

test("manual lifecycle preserves native settings, summary, original position, resume and v1 receipt", async t=>{
  const f=await fixture(t,{legacy:true});
  const initial=await f.command(f.init);
  assert.equal(initial.find(e=>e.type==="state").messages.find(m=>m.entryId==="old-receipt").text,"已压缩：200 → 100 tokens");
  const probe=async model=>{const events=await f.command({type:"mcp-command",text:"/probe-compaction",model});return JSON.parse(events.find(e=>e.type==="notice"&&e.message.startsWith("{")).message);};
  for(const model of ["wide","small"]){
    const settings=await probe(model);
    assert.equal(settings.model,model);
    assert.deepEqual(settings.compaction,{reserveTokens:16384,keepRecentTokens:100,enabled:false});
  }
  await f.command({type:"prompt",text:"older history ".repeat(1000),model:"wide"});
  await f.command({type:"prompt",text:"recent history ".repeat(80)});
  const output=await f.command({type:"compact",customInstructions:"PRESERVE_EXACT_COMPACTION_MARKER"});
  const [start,result]=lifecycle(output,"manual","success");
  assert.ok(result.before>0&&result.after>0);assert.equal(result.afterEstimated,true);
  assert.equal(result.summary,"NATIVE_SUMMARY_FIXTURE");assert.equal(result.error,"");
  assert.ok(f.calls.filter(c=>!c.tools?.length).some(c=>JSON.stringify(c.messages).includes("PRESERVE_EXACT_COMPACTION_MARKER")));
  const state=output.find(e=>e.type==="state");
  const rows=state.messages.filter(m=>m.compaction?.eventId===result.eventId);
  assert.equal(rows.length,1);assert.equal(rows[0].entryId,start.entryId);assert.equal(rows[0].timestamp,start.timestamp);
  assert.equal(rows[0].text,"");assert.equal(rows[0].compaction.state,"success");assert.equal(rows[0].compaction.summary,result.summary);
  const entries=readFileSync(state.session.file,"utf8").trim().split("\n").map(JSON.parse);
  const persisted=entries.filter(e=>e.data?.eventId===result.eventId);
  assert.equal(persisted.length,2);assert.ok(persisted.every(e=>e.type==="custom"));
  assert.ok(entries.findIndex(e=>e.id===start.entryId)<entries.findIndex(e=>e.type==="compaction"));
  assert.equal(f.calls.find(c=>c.tools?.length).max_tokens,32768);
  await f.command({type:"prompt",text:"after compaction"});
  assert.ok(!JSON.stringify(f.calls).includes(result.eventId),"Timeline metadata leaked into model context");
  await f.restart();
  const resumed=await f.command({...f.init,sessionFile:state.session.file});
  const replay=resumed.find(e=>e.type==="state").messages.find(m=>m.compaction?.eventId===result.eventId);
  assert.equal(replay.entryId,start.entryId);assert.equal(replay.compaction.state,"success");
  assert.deepEqual((await probe("small")).compaction,{reserveTokens:16384,keepRecentTokens:100,enabled:false});
});

test("manual too-small failure gets one terminal lifecycle without a model call", async t=>{
  const f=await fixture(t);await f.command(f.init);
  const events=await f.command({type:"compact"},{errors:true});
  const [,failure]=lifecycle(events,"manual","failure");
  assert.match(failure.error,/Nothing to compact/);assert.equal(failure.summary,"");assert.equal(failure.after,null);
  assert.equal(events.filter(e=>e.type==="error").length,1);assert.equal(f.calls.length,0);
});

test("automatic lifecycle follows native effective window and adds no model input", async t=>{
  const f=await fixture(t,{autoCompaction:true});await f.command(f.init);
  const native=await f.command({type:"prompt",model:"wide",text:"older automatic history ".repeat(1000)});
  assert.ok(!native.some(e=>e.type==="compaction_event"),"Obsolete threshold still changes native auto policy");
  const events=await f.command({type:"prompt",model:"small",text:"recent automatic history ".repeat(80)});
  const [start,result]=lifecycle(events,"auto","success");
  assert.ok(result.before>0&&result.after>0);assert.match(result.summary,/NATIVE_SUMMARY_FIXTURE$/);
  assert.equal(f.calls.filter(c=>c.tools?.length).length,2,"Timeline triggered an extra model reply");
  assert.equal(f.calls.filter(c=>!c.tools?.length).length,1,"Timeline caused repeated summarization");
  assert.ok(!JSON.stringify(f.calls).includes(result.eventId));
  const rows=events.find(e=>e.type==="state").messages.filter(m=>m.compaction?.eventId===result.eventId);
  assert.equal(rows.length,1);assert.equal(rows[0].entryId,start.entryId);
  const entries=readFileSync(events.find(e=>e.type==="state").session.file,"utf8").trim().split("\n").map(JSON.parse);
  assert.equal(result.summary,entries.findLast(e=>e.type==="compaction").summary);
});

for(const failure of ["cancel","error"]){
  test(`automatic ${failure} produces a visible failure lifecycle`,async t=>{
    const hook=failure==="cancel"?'pi.on("session_before_compact",()=>({cancel:true}));':"";
    const f=await fixture(t,{autoCompaction:true,hook,summaryError:failure==="error"});await f.command(f.init);
    await f.command({type:"prompt",text:"older history ".repeat(1000)});
    const events=await f.command({type:"prompt",model:"small",text:"recent history ".repeat(80)});
    const [,result]=lifecycle(events,"auto","failure");
    assert.match(result.error,failure==="cancel"?/cancelled/:/fixture compaction failure/);
    assert.equal(result.summary,"");assert.equal(f.calls.filter(c=>!c.tools?.length).length,failure==="cancel"?0:1);
    assert.equal(events.find(e=>e.type==="state").messages.find(m=>m.compaction?.eventId===result.eventId).compaction.state,"failure");
  });
}
