import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import {existsSync,mkdtempSync,mkdirSync,readFileSync,writeFileSync} from "node:fs";
import {rm} from "node:fs/promises";
import {join} from "node:path";
import {tmpdir} from "node:os";
import {createJiti} from "../runtime/node_modules/jiti/lib/jiti.mjs";
import * as Pi from "../runtime/node_modules/@earendil-works/pi-coding-agent/dist/index.js";
import {AuthStorage} from "../runtime/node_modules/@earendil-works/pi-coding-agent/dist/core/auth-storage.js";
import {createSubagentExtension} from "../runtime/subagents.mjs";

const waitFor=async(predicate,label)=>{
  const deadline=Date.now()+10000;
  while (!predicate()) {
    if (Date.now()>deadline) throw new Error(label);
    await new Promise(resolve=>setTimeout(resolve,10));
  }
};

test("child queue edits/removal, immediate tool and model interruption, FIFO continuation, promotion, isolation and stop recovery",{timeout:45000},async()=>{
  const directory=mkdtempSync(join(tmpdir(),"umeko-child-queue-"));
  const agentDir=join(directory,"agent"); mkdirSync(agentDir);
  const previousDirectory=process.cwd(), previousAgentDir=process.env.PI_CODING_AGENT_DIR;
  process.chdir(directory); process.env.PI_CODING_AGENT_DIR=agentDir;
  const commandPid=join(directory,"fixture-command.pid");
  const longCommand=`node -e "const fs=require('node:fs');fs.writeFileSync('fixture-command.pid',String(process.pid));setInterval(()=>{if(fs.existsSync('fixture-command.stop'))process.exit(0)},25);setTimeout(()=>process.exit(0),30000)"`;
  const events=[], requests=[];
  const server=http.createServer(async(request,response)=>{
    let raw=""; for await (const chunk of request) raw+=chunk;
    const body=JSON.parse(raw);
    const item={body,response,respond(text,call=false){
      response.writeHead(200,{"Content-Type":"text/event-stream"});
      const common={id:"queue-test",object:"chat.completion.chunk",created:1,model:"test"};
      const delta=call ? {role:"assistant",content:null,tool_calls:[{index:0,id:"long-command",type:"function",function:{name:"bash",arguments:JSON.stringify({command:longCommand,timeout:40})}}]}
        : {role:"assistant",content:text};
      response.end(`data: ${JSON.stringify({...common,choices:[{index:0,delta,finish_reason:null}]})}\n\ndata: ${JSON.stringify({...common,choices:[{index:0,delta:{},finish_reason:call ? "tool_calls" : "stop"}]})}\n\ndata: [DONE]\n\n`);
    }};
    if (JSON.stringify(body.messages).includes("<task-notification>")) {item.respond("Acknowledged");return;}
    requests.push(item);
  });
  await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));
  let session,modelRuntime,service;
  const adapter=createSubagentExtension({emit:event=>events.push(event)});
  let sequence=0;
  const command=async input=>{
    const requestId="command-"+(++sequence);
    await adapter.command({...input,requestId});
    if (input.action==="watch") return;
    const reply=events.find(event=>event.type==="subagent_command" && event.requestId===requestId);
    assert.equal(reply?.ok,true,reply?.message || JSON.stringify(input));
  };
  const queue=id=>events.filter(event=>event.type==="subagent_queue" && event.id===id).at(-1)?.items || [];
  const lastUser=item=>JSON.stringify(item.body.messages.filter(message=>message.role==="user").at(-1)?.content);
  try {
    modelRuntime=await Pi.ModelRuntime.create({credentials:AuthStorage.inMemory(),modelsPath:null,allowModelNetwork:false,refreshOnCreate:false});
    modelRuntime.registerProvider("umeko",{api:"openai-completions",baseUrl:`http://127.0.0.1:${server.address().port}/v1`,apiKey:"local-test",
      models:[{id:"test",name:"test",api:"openai-completions",reasoning:false,input:["text"],contextWindow:128000,maxTokens:128,
        cost:{input:0,output:0,cacheRead:0,cacheWrite:0},compat:{supportsDeveloperRole:false,supportsStore:false}}]});
    await modelRuntime.refresh({allowNetwork:false});
    const settings=Pi.SettingsManager.inMemory({compaction:{enabled:false},cacheWarming:"off"});
    const loader=new Pi.DefaultResourceLoader({cwd:directory,agentDir,settingsManager:settings,noExtensions:true,noSkills:true,noContextFiles:true,
      additionalExtensionPaths:["builtin:subagents"],extensionFactories:[{name:"subagents",builtin:true,factory:adapter.extension}]});
    await loader.reload();
    ({session}=await Pi.createAgentSession({cwd:directory,agentDir,modelRuntime,model:modelRuntime.getModel("umeko","test"),settingsManager:settings,
      resourceLoader:loader,sessionManager:Pi.SessionManager.create(directory,join(directory,"sessions"))}));
    await session.bindExtensions({});
    const jiti=createJiti(new URL("../runtime/subagents.mjs",import.meta.url).href,{moduleCache:false,tryNative:false,fsCache:join(agentDir,"cache","test-service")});
    service=(await jiti.import("@gotgenes/pi-subagents")).getSubagentsService();
    const subject=service.spawn("general-purpose","QueueSubject: use the requested command",{foreground:false,maxTurns:12});
    const control=service.spawn("general-purpose","QueueControl: wait for an answer",{foreground:false,maxTurns:12});
    await command({action:"watch",id:subject});
    await waitFor(()=>requests.length===2,"Two child requests did not start");
    const first=requests.find(item=>lastUser(item).includes("QueueSubject"));
    const untouched=requests.find(item=>lastUser(item).includes("QueueControl"));
    first.respond("",true);
    await waitFor(()=>events.some(event=>event.type==="subagent_event" && event.id===subject && event.event.type==="tool" && event.event.state==="running"),"Long command did not start");
    await waitFor(()=>existsSync(commandPid),"Fixture command did not actually start");
    await command({action:"send",id:subject,text:"normal-A",mode:"followUp",messageId:"A"});
    await command({action:"send",id:subject,text:"delete-B",mode:"followUp",messageId:"B"});
    assert.deepEqual(queue(subject).map(item=>item.id),["A","B"]);
    assert.equal(requests.length,2,"A follow-up interrupted the running command");
    await command({action:"delete-queue",id:subject,queueId:"B"});
    await command({action:"edit-queue",id:subject,queueId:"A"});
    assert.equal(queue(subject).length,0);
    assert.ok(events.some(event=>event.type==="subagent_queue_edited" && event.id===subject && event.item.text==="normal-A"));
    await command({action:"send",id:subject,text:"edited-normal-A",mode:"followUp",messageId:"A-edited"});
    await command({action:"send",id:subject,text:"urgent-now",mode:"followUp",messageId:"urgent"});
    const started=Date.now();
    await command({action:"steer-queued",id:subject,queueId:"urgent"});
    await waitFor(()=>requests.length===3,"Priority input did not abort the long command");
    assert.ok(Date.now()-started<5000,"Priority input waited for the 30-second tool to finish");
    assert.match(lastUser(requests[2]),/urgent-now/);
    assert.doesNotMatch(lastUser(requests[2]),/edited-normal-A/);
    assert.deepEqual(queue(subject).map(item=>item.id),["A-edited"]);
    assert.equal(service.getRecord(subject).status,"running","Interrupted child appeared finished before handling priority input");
    assert.equal(service.getRecord(control).status,"running");
    assert.equal(untouched.response.destroyed,false,"Priority input aborted the other child");
    requests[2].respond("priority handled");
    await waitFor(()=>requests.length===4,"Remaining follow-up did not run after priority input");
    assert.match(lastUser(requests[3]),/edited-normal-A/);
    assert.equal(queue(subject).length,0);
    requests[3].respond("queued handled"); untouched.respond("control untouched");
    await service.waitForAll();
    assert.equal(service.getRecord(subject).result,"queued handled");
    assert.equal(service.getRecord(control).result,"control untouched");
    const file=service.getRecord(subject).outputFile;
    const history=readFileSync(file,"utf8");
    assert.ok(history.indexOf("urgent-now")<history.indexOf("edited-normal-A"));
    assert.ok(!history.includes("delete-B"));

    await command({action:"send",id:subject,text:"resume-for-interruption"});
    await waitFor(()=>requests.length===5,"Retained child did not resume");
    await command({action:"send",id:subject,text:"direct-priority",mode:"interrupt"});
    await waitFor(()=>requests.length===6,"Direct priority input did not interrupt the model request");
    assert.equal(requests[4].response.destroyed,true);
    assert.match(lastUser(requests[5]),/direct-priority/);
    await command({action:"send",id:subject,text:"promote-first",messageId:"promote",mode:"followUp"});
    await command({action:"promote-queue",id:subject});
    await waitFor(()=>requests.length===7,"Empty-input promotion did not select the first queue item");
    assert.match(lastUser(requests[6]),/promote-first/);
    requests[6].respond("promoted handled"); await service.waitForAll();
    await command({action:"send",id:subject,text:"resume-for-stop"});
    await waitFor(()=>requests.length===8,"Child did not resume before stop");
    await command({action:"send",id:subject,text:"return-after-stop",messageId:"returned",mode:"followUp"});
    await command({action:"stop",id:subject});
    await service.waitForAll();
    assert.equal(queue(subject).length,0);
    assert.ok(events.some(event=>event.type==="subagent_queue_returned" && event.id===subject && event.items.some(item=>item.id==="returned")));
    assert.equal(requests.length,8,"Stopped child resumed itself to consume a queued message");
    assert.equal(service.getRecord(subject).outputFile,file);
  } catch (error) { console.error(error); throw error; }
  finally {
    if (service) for (const record of service.listAgents()) service.abort(record.id);
    await service?.waitForAll();
    adapter.dispose(); await session?.extensionRunner.emit({type:"session_shutdown"});
    await session?.dispose?.(); await modelRuntime?.dispose?.();
    server.closeAllConnections(); await new Promise(resolve=>server.close(resolve));
    // The SDK can resolve an interrupted tool before every Windows descendant
    // has exited. Signal only this fixture's own sleeper, without killing any
    // unrelated processes or weakening the interruption-time assertions above.
    writeFileSync(join(directory,"fixture-command.stop"),"stop");
    if (process.platform==="win32" && existsSync(commandPid)) {
      const pid=Number(readFileSync(commandPid,"utf8"));
      assert.ok(Number.isSafeInteger(pid) && pid>0 && pid!==process.pid);
      await waitFor(()=>{
        try { process.kill(pid,0); return false; }
        catch (error) { if (error.code==="ESRCH") return true; throw error; }
      },"Fixture command did not release its Windows directory handle");
    }
    process.chdir(previousDirectory);
    if (previousAgentDir===undefined) delete process.env.PI_CODING_AGENT_DIR; else process.env.PI_CODING_AGENT_DIR=previousAgentDir;
    // Let pending Windows child-process close callbacks release cwd handles
    // between retries. Synchronous cleanup blocks those callbacks itself.
    await rm(directory,{recursive:true,force:true,maxRetries:12,retryDelay:100});
  }
});
