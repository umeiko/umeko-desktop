import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { createInterface } from "node:readline";
import { once } from "node:events";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, copyFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const release = join(root,"runtime/releases/coding-1.3.0");

async function fixture(t, autoCompaction = false) {
  const temp = mkdtempSync(join(tmpdir(),"umeko-compaction-"));
  const agentDir = join(temp,"agent");
  mkdirSync(join(agentDir,"extensions"),{recursive:true});
  writeFileSync(join(agentDir,"settings.json"),JSON.stringify({compaction:{reserveTokens:16384,keepRecentTokens:100}}));
  writeFileSync(join(agentDir,"extensions/probe.js"),`export default pi => pi.registerCommand("probe-compaction", {
    description:"test settings",handler:async (_args,ctx) => ctx.ui.notify(JSON.stringify({model:ctx.model.id,compaction:pi.getSettings().compaction}))
  });`);
  for (const name of ["bridge.mjs","compaction-settings.mjs"]) copyFileSync(join(root,"runtime",name),join(release,name));
  const calls = [];
  const server = createServer(async (req,res) => {
    let raw=""; for await (const chunk of req) raw+=chunk;
    const body=JSON.parse(raw); calls.push(body);
    const summary = !body.tools?.length;
    const content = summary ? "PRIVATE_SUMMARY_FIXTURE" : "fixture answer";
    const common = {id:"fixture",object:"chat.completion.chunk",created:1,model:body.model};
    res.writeHead(200,{"Content-Type":"text/event-stream"});
    res.end(`data: ${JSON.stringify({...common,choices:[{index:0,delta:{role:"assistant",content},finish_reason:null}]})}\n\ndata: ${JSON.stringify({...common,choices:[{index:0,delta:{},finish_reason:"stop"}],usage:{prompt_tokens:summary?100:1800,completion_tokens:5,total_tokens:summary?105:1805}})}\n\ndata: [DONE]\n\n`);
  });
  server.listen(0,"127.0.0.1"); await once(server,"listening");
  let process, lines, stderr="";
  const start=() => {
    process=spawn(globalThis.process.execPath,[join(release,"bridge.mjs")],{stdio:["pipe","pipe","pipe"],windowsHide:true});
    process.stderr.on("data",chunk=>stderr+=chunk);
    lines=createInterface({input:process.stdout})[Symbol.asyncIterator]();
  };
  const send=payload=>process.stdin.write(JSON.stringify(payload)+"\n");
  const command=async payload => {
    send(payload); const events=[];
    for (;;) {
      const next=await Promise.race([lines.next(),new Promise((_,reject)=>{const timer=setTimeout(()=>reject(new Error("Bridge timed out: "+stderr)),20000);timer.unref();})]);
      assert.ok(!next.done,"Bridge exited: "+stderr);
      const event=JSON.parse(next.value); events.push(event);
      if(event.type==="done")break;
    }
    assert.deepEqual(events.filter(e=>e.type==="error"),[],JSON.stringify(events));
    return events;
  };
  const stop=async()=>{ if(process.exitCode===null){send({type:"shutdown"});await once(process,"exit");} };
  start();
  t.after(async()=>{await stop();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));rmSync(temp,{recursive:true,force:true});});
  const init={type:"inspect",gateway:`http://127.0.0.1:${server.address().port}/`,token:"fixture-only",workspace:temp,defaultCwd:temp,agentDir,sessionDir:join(temp,"sessions"),
    models:[{id:"small",contextWindow:128000,compactionThreshold:1024},{id:"native",contextWindow:128000,compactionThreshold:null}],model:"small",agent:{autoCompaction}};
  return {calls,command,init,restart:async()=>{await stop();start();}};
}

test("real bridge forwards compact instructions, persists numeric receipt, switches and resumes native model policy", async t=>{
  const f=await fixture(t);
  await f.command(f.init);
  const probe=async model=>{const events=await f.command({type:"mcp-command",text:"/probe-compaction",model});const notice=events.find(e=>e.type==="notice"&&e.message.startsWith("{"));assert.ok(notice,JSON.stringify(events));return JSON.parse(notice.message);};
  const small=await probe("small");
  assert.deepEqual(small.compaction.modelOverrides["umeko/small"],{reserveTokens:126976,keepRecentTokens:100});
  assert.equal(small.compaction.reserveTokens,16384);
  assert.equal((await probe("native")).model,"native");
  await f.command({type:"prompt",text:"older history ".repeat(1000),model:"small"});
  await f.command({type:"prompt",text:"recent history ".repeat(80)});
  const output=await f.command({type:"compact",customInstructions:"PRESERVE_EXACT_COMPACTION_MARKER"});
  const result=output.find(e=>e.type==="compaction_result");
  assert.ok(result,"Missing structured compaction result");
  assert.equal(result.mode,"manual");
  assert.ok(result.before>0&&result.after>0);
  assert.equal(result.afterEstimated,true);
  const summaryCalls=f.calls.filter(c=>!c.tools?.length);
  assert.ok(summaryCalls.some(c=>JSON.stringify(c.messages).includes("PRESERVE_EXACT_COMPACTION_MARKER")),"Compaction instructions did not reach native summarizer");
  const state=output.find(e=>e.type==="state");
  const row=state.messages.find(m=>m.customType==="umeko-compaction");
  assert.equal(row.text,`已压缩：${result.before} → ${result.after} tokens`);
  assert.equal(row.role,"assistant");
  assert.ok(!JSON.stringify(state.messages).includes("PRIVATE_SUMMARY_FIXTURE"));
  const entries=readFileSync(state.session.file,"utf8").trim().split("\n").map(JSON.parse);
  const receipt=entries.find(e=>e.customType==="umeko-compaction");
  assert.equal(receipt.type,"custom");
  assert.equal(receipt.data.before,result.before);assert.equal(receipt.data.after,result.after);
  assert.ok(!JSON.stringify(receipt).includes("PRIVATE_SUMMARY_FIXTURE"));
  assert.equal(f.calls.find(c=>c.tools?.length).max_tokens,32768,"Compaction setting altered output cap");
  await f.restart();
  const resumed=await f.command({...f.init,sessionFile:state.session.file});
  assert.ok(resumed.find(e=>e.type==="state").messages.some(m=>m.customType==="umeko-compaction"));
  assert.equal((await probe("small")).compaction.modelOverrides["umeko/small"].reserveTokens,126976);
  assert.equal((await probe("native")).compaction.reserveTokens,16384);
});

test("model switch enables the native automatic threshold and summary-free numeric receipt", async t=>{
  const f=await fixture(t,true);
  await f.command(f.init);
  const native=await f.command({type:"prompt",model:"native",text:"older automatic history ".repeat(1000)});
  assert.ok(!native.some(e=>e.type==="compaction_result"),"Empty threshold should retain native policy");
  const events=await f.command({type:"prompt",model:"small",text:"recent automatic history ".repeat(80)});
  const result=events.find(e=>e.type==="compaction_result"&&e.mode==="auto");
  assert.ok(result,"Configured low threshold did not trigger native automatic compaction");
  assert.ok(result.before>0&&result.after>0);
  assert.equal(f.calls.filter(c=>c.tools?.length).length,2,"Local compaction receipt triggered an extra model reply");
  assert.equal(f.calls.filter(c=>!c.tools?.length).length,1,"Receipt caused repeated summarization");
  assert.ok(!JSON.stringify(f.calls).includes("已压缩："),"Local receipt leaked into model context");
  const state=events.find(e=>e.type==="state");
  assert.ok(state.messages.some(m=>m.customType==="umeko-compaction"&&m.compaction.mode==="auto"));
  assert.ok(!JSON.stringify(state.messages).includes("PRIVATE_SUMMARY_FIXTURE"));
});
