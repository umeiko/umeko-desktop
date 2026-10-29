import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { mkdtempSync, mkdirSync, rmSync, existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createJiti } from "../runtime/node_modules/jiti/lib/jiti.mjs";
import * as Pi from "../runtime/node_modules/@earendil-works/pi-coding-agent/dist/index.js";
import { AuthStorage } from "../runtime/node_modules/@earendil-works/pi-coding-agent/dist/core/auth-storage.js";
import { createSubagentExtension, childMessages } from "../runtime/subagents.mjs";

const waitFor = async predicate => {
  const deadline = Date.now()+12000;
  while (!predicate()) {
    if (Date.now()>deadline) throw new Error("Timed out waiting for native child event");
    await new Promise(resolve=>setTimeout(resolve,10));
  }
};

test("native child streams, four slots, steering, stop, retained resume and cold native resume", {timeout:30000}, async () => {
  const directory = mkdtempSync(join(tmpdir(),"umeko-subagent-ui-"));
  const agentDir = join(directory,"agent"); mkdirSync(agentDir);
  const previousDirectory = process.cwd(), previousAgentDir = process.env.PI_CODING_AGENT_DIR;
  process.chdir(directory); process.env.PI_CODING_AGENT_DIR = agentDir;
  const events = [], requests = [], pending = [];
  const bundledCache = new URL("../runtime/node_modules/.cache/jiti/",import.meta.url);
  const cacheBefore = existsSync(bundledCache) ? readdirSync(bundledCache).sort() : [];
  const server = http.createServer(async (request,response) => {
    let raw=""; for await (const chunk of request) raw+=chunk;
    const body=JSON.parse(raw);
    const item={body,response,respond(text) {
      response.writeHead(200,{"Content-Type":"text/event-stream"});
      const base={id:"test",object:"chat.completion.chunk",created:1,model:"test"};
      for (const delta of [text.slice(0,3),text.slice(3)]) response.write(`data: ${JSON.stringify({...base,choices:[{index:0,delta:{role:"assistant",content:delta},finish_reason:null}]})}\n\n`);
      response.end(`data: ${JSON.stringify({...base,choices:[{index:0,delta:{},finish_reason:"stop"}]})}\n\ndata: [DONE]\n\n`);
    }};
    // A stopped foreground child notifies an idle parent as well. Acknowledge
    // that independent parent turn; the assertions below count child calls.
    if (body.messages.some(message=>message.role==="user" && JSON.stringify(message.content).includes("<task-notification>"))) { item.respond("Acknowledged"); return; }
    requests.push(body); pending.push(item);
  });
  await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));
  let session, modelRuntime, cold, restored;
  const adapter=createSubagentExtension({emit:event=>events.push(event)});
  try {
    modelRuntime=await Pi.ModelRuntime.create({credentials:AuthStorage.inMemory(),modelsPath:null,allowModelNetwork:false,refreshOnCreate:false});
    modelRuntime.registerProvider("umeko",{api:"openai-completions",baseUrl:`http://127.0.0.1:${server.address().port}/v1`,apiKey:"local-test",
      models:[{id:"test",name:"test",api:"openai-completions",reasoning:false,input:["text"],contextWindow:128000,maxTokens:128,
        cost:{input:0,output:0,cacheRead:0,cacheWrite:0},compat:{supportsDeveloperRole:false,supportsStore:false}}]});
    await modelRuntime.refresh({allowNetwork:false});
    const model=modelRuntime.getModel("umeko","test");
    const settings=Pi.SettingsManager.inMemory({compaction:{enabled:false},cacheWarming:"off"});
    const loader=new Pi.DefaultResourceLoader({cwd:directory,agentDir,settingsManager:settings,noExtensions:true,noSkills:true,noPromptTemplates:true,noThemes:true,noContextFiles:true,
      additionalExtensionPaths:["builtin:subagents"],extensionFactories:[{name:"subagents",builtin:true,factory:adapter.extension}]});
    await loader.reload();
    ({session}=await Pi.createAgentSession({cwd:directory,agentDir,modelRuntime,model,settingsManager:settings,resourceLoader:loader,sessionManager:Pi.SessionManager.create(directory,join(directory,"sessions"))}));
    await session.bindExtensions({});
    const jiti=createJiti(new URL("../runtime/subagents.mjs",import.meta.url).href,{moduleCache:false,fsCache:join(agentDir,"cache","test-service")});
    const {getSubagentsService}=await jiti.import("@gotgenes/pi-subagents");
    const service=getSubagentsService();
    const ids=Array.from({length:4},(_,i)=>service.spawn("general-purpose",`task-${i}: Return a short answer`,{maxTurns:3,foreground:true}));
    await adapter.command({action:"watch",id:ids[0]});
    await waitFor(()=>pending.length===4);
    assert.ok(existsSync(join(agentDir,"cache","umeko-subagents")),"community transpilation cache belongs in the user profile");
    assert.deepEqual(existsSync(bundledCache) ? readdirSync(bundledCache).sort() : [],cacheBefore,"loading extensions must not add files to a signed app bundle");
    const childEvents=events.filter(event=>event.subagent);
    const latest=new Map(childEvents.map(event=>[event.subagent.id,event.subagent]));
    assert.equal(new Set([...latest.values()].map(child=>child.avatarSlot)).size,4);
    assert.ok(events.some(event=>event.type==="subagent_event" && event.id===ids[0] && event.event.type==="user_start"),"native SDK observer must forward child user events");
    assert.ok(session.sessionManager.getBranch().some(entry=>entry.customType==="umeko-subagent-context"),"resolved prompt and tool policy must be durable");
    const blocked=await session.agent.state.tools.find(tool=>tool.name==="subagent").execute("fifth",{prompt:"fifth",subagent_type:"general-purpose",run_in_background:true},undefined,()=>{});
    assert.equal(blocked.isError,true); assert.equal(service.listAgents().length,4);
    await adapter.command({action:"send",id:ids[0],text:"steer-only-first",requestId:"steer"});
    assert.ok(events.some(event=>event.type==="subagent_command" && event.requestId==="steer" && event.ok));
    await adapter.command({action:"stop",id:ids[1]});
    await waitFor(()=>service.getRecord(ids[1]).status==="stopped");
    for (const item of pending.slice(0,4)) if (!JSON.stringify(item.body.messages).includes("task-1:")) item.respond("initial-answer");
    await waitFor(()=>pending.length>=5 || service.getRecord(ids[0]).status!=="running");
    assert.equal(pending.length,5,JSON.stringify({agents:service.listAgents().map(record=>({id:record.id,status:record.status,error:record.error,result:record.result})),requests:requests.map(body=>body.messages.slice(-2).map(message=>({role:message.role,content:JSON.stringify(message.content).slice(0,240)})))}));
    assert.match(JSON.stringify(pending[4].body.messages),/steer-only-first/);
    assert.equal(requests.slice(0,4).filter(body=>JSON.stringify(body.messages).includes("steer-only-first")).length,0);
    pending[4].respond("steered-answer");
    await service.waitForAll();
    assert.ok(events.some(event=>event.type==="subagent_event" && event.id===ids[0] && event.event.type==="delta"));
    assert.equal(service.getRecord(ids[0]).result,"steered-answer");
    const file=service.getRecord(ids[0]).outputFile;
    await adapter.command({action:"send",id:ids[0],text:"resume-existing-context",requestId:"resume"});
    await waitFor(()=>pending.length===6);
    assert.match(JSON.stringify(pending[5].body.messages),/steered-answer/);
    pending[5].respond("resumed-answer"); await service.waitForAll();
    assert.equal(service.getRecord(ids[0]).outputFile,file);
    const branch=session.sessionManager.getBranch();
    adapter.dispose();
    await session.extensionRunner.emit({type:"session_shutdown"});
    const coldEntries=[];
    cold=createSubagentExtension({emit:event=>events.push(event),loadPackage:async()=>({getService:()=>undefined,factory:()=>{}}),
      restoreSession:async(child,context)=>{
        assert.equal(child.outputFile,file);
        assert.ok(context.systemPrompt); assert.ok(Array.isArray(context.tools));
        const childLoader=new Pi.DefaultResourceLoader({cwd:directory,agentDir,settingsManager:settings,noExtensions:true,noSkills:true,noContextFiles:true,systemPrompt:context.systemPrompt});
        await childLoader.reload();
        ({session:restored}=await Pi.createAgentSession({cwd:directory,agentDir,modelRuntime,model,settingsManager:settings,resourceLoader:childLoader,
          sessionManager:Pi.SessionManager.open(file),tools:context.tools}));
        return restored;
      }});
    await cold.extension({events:{on:()=>()=>{}},on(){},appendEntry:(customType,data)=>coldEntries.push({type:"custom",customType,data})});
    cold.hydrate(branch);
    await cold.command({action:"watch",id:ids[0]});
    await cold.command({action:"send",id:ids[0],text:"wake-after-restart",requestId:"cold"});
    await waitFor(()=>pending.length===7);
    assert.match(JSON.stringify(pending[6].body.messages),/resumed-answer/);
    assert.match(JSON.stringify(pending[6].body.messages),/wake-after-restart/);
    pending[6].respond("cold-answer");
    await waitFor(()=>events.some(event=>event.subagent?.id===ids[0] && event.subagent.result==="cold-answer"));
    assert.equal(restored.sessionManager.getSessionFile(),file);
    assert.ok(coldEntries.some(entry=>entry.data.tool?.subagent.result==="cold-answer"));
    assert.equal(service.listAgents().length,0,"community shutdown should release all child instances");
  } finally {
    cold?.dispose(); adapter.dispose();
    await restored?.dispose?.(); await session?.dispose?.(); await modelRuntime?.dispose?.();
    server.closeAllConnections(); await new Promise(resolve=>server.close(resolve));
    process.chdir(previousDirectory);
    if (previousAgentDir===undefined) delete process.env.PI_CODING_AGENT_DIR; else process.env.PI_CODING_AGENT_DIR=previousAgentDir;
    rmSync(directory,{recursive:true,force:true});
  }
});

test("live snapshot bounds tool arguments and text without changing native history",()=>{
  const messages=[{role:"assistant",content:[{type:"text",text:"x".repeat(2*1024*1024)},{type:"toolCall",id:"w",name:"write",arguments:{content:"x".repeat(2*1024*1024)}}]}];
  const before=messages[0].content[0].text.length;
  const snapshot=childMessages({messages});
  assert.ok(JSON.stringify(snapshot).length<60000);
  assert.equal(snapshot.messages[0].tools[0].arguments.truncated,true);
  assert.equal(messages[0].content[0].text.length,before);
});
