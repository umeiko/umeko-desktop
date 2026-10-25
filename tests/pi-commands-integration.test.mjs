import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdtempSync,mkdirSync,readFileSync,writeFileSync,rmSync,existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join,resolve,dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
test('real embedded Pi tool installs into its own profile, reloads the same session, and runs registered commands', {timeout:45000}, async()=>{
 const temp=mkdtempSync(join(tmpdir(),'umeko-pi-command-integration-'));
 const cwd=join(temp,'workspace'),agentDir=join(temp,'agent'),sessionDir=join(temp,'sessions'),source=join(temp,'extension');
 for(const p of [cwd,agentDir,sessionDir,source])mkdirSync(p);
 writeFileSync(join(agentDir,'settings.json'),JSON.stringify({compaction:{keepRecentTokens:128,reserveTokens:1024}}));
 writeFileSync(join(source,'package.json'),JSON.stringify({name:'umeko-command-fixture',type:'module',pi:{extensions:['./index.mjs']}}));
 writeFileSync(join(source,'index.mjs'),`export default pi=>{pi.registerCommand('command-fixture',{description:'Local fixture command',handler:async(args,ctx)=>ctx.ui.notify('fixture:'+args+':'+ctx.cwd)});pi.on('session_before_compact',event=>({compaction:{summary:'Preserve current task and decisions',firstKeptEntryId:event.preparation.firstKeptEntryId,tokensBefore:event.preparation.tokensBefore}}));};`);
 let command='/session',awaiting=true,requests=[],child,paused=false,releaseReply;
 const server=createServer(async(req,res)=>{
  let raw='';for await(const chunk of req)raw+=chunk;const body=JSON.parse(raw);requests.push(body);
  if(paused&&!awaiting)await new Promise(done=>{releaseReply=done;});
  if(res.destroyed)return;
  let message,finish;
  if(awaiting){awaiting=false;message={role:'assistant',content:null,tool_calls:[{index:0,id:'pi-command-'+requests.length,type:'function',function:{name:'run_pi_command',arguments:JSON.stringify({command})}}]};finish='tool_calls';}
  else {message={role:'assistant',content:'command response finished'};finish='stop';}
  res.writeHead(200,{'Content-Type':'text/event-stream'});
  const common={id:'fixture',object:'chat.completion.chunk',created:1,model:'fixture'};
  res.end(`data: ${JSON.stringify({...common,choices:[{index:0,delta:message,finish_reason:null}]})}\n\ndata: ${JSON.stringify({...common,choices:[{index:0,delta:{},finish_reason:finish}]})}\n\ndata: [DONE]\n\n`);
 });
 await new Promise(done=>server.listen(0,'127.0.0.1',done));
 const events=[];let stderr='',buffer='';
 child=spawn(process.execPath,[join(root,'runtime/releases/coding-1.3.0/bridge.mjs')],{cwd,stdio:['pipe','pipe','pipe']});
 child.stderr.on('data',data=>stderr+=data);
 child.stdout.on('data',data=>{buffer+=data;let i;while((i=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,i);buffer=buffer.slice(i+1);if(line)events.push(JSON.parse(line));}});
 const send=input=>child.stdin.write(JSON.stringify(input)+'\n');
 const wait=async predicate=>{const end=Date.now()+15000;while(Date.now()<end){if(predicate())return;await new Promise(done=>setTimeout(done,20));}throw new Error('Timed out: '+JSON.stringify(events.slice(-4))+' '+stderr);};
 try{
  const initial={type:'prompt',text:'Inspect this Pi',workspace:cwd,defaultCwd:cwd,agentDir,sessionDir,model:'fixture',models:[{id:'fixture',contextWindow:128000}],agent:{},gateway:`http://127.0.0.1:${server.address().port}/`,token:'local-fixture'};
  send(initial);await wait(()=>events.some(e=>e.type==='done'));
  const first=events.find(e=>e.type==='ready').session.id;
  const tool=events.find(e=>e.type==='tool'&&e.name==='run_pi_command'&&e.state==='done');
  assert.equal(JSON.parse(tool.result).sessionId,first);assert.equal(JSON.parse(tool.result).agentDir,agentDir);
  assert.ok(requests[0].messages.filter(m=>['system','developer'].includes(m.role)).some(m=>String(m.content).includes('embedded in Umeko Desktop')));
  let count=events.filter(e=>e.type==='done').length;
  command='pi install '+JSON.stringify(source);awaiting=true;
  send({type:'prompt',text:'Install local fixture'});await wait(()=>events.filter(e=>e.type==='done').length>count);
  assert.ok(existsSync(join(agentDir,'settings.json')));
  assert.ok(readFileSync(join(agentDir,'settings.json'),'utf8').includes('extension'), JSON.stringify(events.filter(e=>e.type==='tool')));

  let state=events.filter(e=>e.type==='state').at(-1);assert.equal(state.session.id,first);
  assert.ok(state.resources.commands.some(c=>c.name==='command-fixture'));
  assert.ok(state.resources.tools.includes('run_pi_command'));
  count=events.filter(e=>e.type==='done').length;command='/command-fixture hello';awaiting=true;
  send({type:'prompt',text:'Run registered command'});await wait(()=>events.filter(e=>e.type==='done').length>count);
  const feedback=requests.flatMap(request=>request.messages).map(message=>typeof message.content==='string'?message.content:(message.content||[]).map(part=>part.text||'').join('\n')).filter(text=>text.includes('Umeko runtime results for run_pi_command'));
  const reports=feedback.flatMap(text=>JSON.parse(text.slice(text.indexOf('Umeko runtime results for run_pi_command')).split('\n')[1]));
  assert.ok(reports.some(report=>report.command==='/command-fixture hello'&&report.result.output==='fixture:hello:'+cwd));
  const final=events.filter(e=>e.type==='state').at(-1);assert.equal(final.session.id,first);
  assert.ok(final.messages.some(m=>m.role==='user'&&m.text==='Inspect this Pi'));
  assert.equal(events.filter(e=>e.type==='error').length,0);
  assert.ok(events.filter(e=>e.type==='tool'&&e.name==='run_pi_command'&&e.state==='done').length>=3);
  count=events.filter(e=>e.type==='done').length;command='/compact preserve current task';awaiting=true;
  send({type:'prompt',text:'Compact this instance'});await wait(()=>events.filter(e=>e.type==='done').length>count);
  const compacted=events.filter(e=>e.type==='state').at(-1);assert.equal(compacted.session.id,first);
  assert.ok(readFileSync(compacted.session.file,'utf8').split('\n').filter(Boolean).map(line=>JSON.parse(line)).some(e=>e.type==='compaction'),JSON.stringify(events.slice(-6)));
  count=events.filter(e=>e.type==='done').length;command='pi mcp add fixture --url http://127.0.0.1:9/mcp --local';awaiting=true;
  send({type:'prompt',text:'Add project MCP'});await wait(()=>events.filter(e=>e.type==='done').length>count);
  assert.equal(JSON.parse(readFileSync(join(cwd,'.pi/mcp.json'))).mcpServers.fixture.url,'http://127.0.0.1:9/mcp');
  assert.equal(existsSync(join(agentDir,'mcp.json')),false);
  const entryCount=()=>readFileSync(compacted.session.file,'utf8').split('\n').filter(Boolean).map(line=>JSON.parse(line)).filter(e=>e.customType==='umeko-pi-command').length;
  const completed=entryCount();
  count=events.filter(e=>e.type==='done').length;command='/reload';awaiting=true;paused=true;
  send({type:'prompt',text:'Queue reload then stop'});await wait(()=>typeof releaseReply==='function');
  send({type:'abort'});await wait(()=>events.filter(e=>e.type==='done').length>count);
  releaseReply();paused=false;
  assert.equal(entryCount(),completed,'A stopped turn must not execute its queued reload or resume itself');
 }finally{
  releaseReply?.();child?.stdin.end();await new Promise(done=>{if(child.exitCode!==null)return done();child.once('close',done);setTimeout(()=>child.kill(),2000).unref();});
  server.closeAllConnections();await new Promise(done=>server.close(done));rmSync(temp,{recursive:true,force:true});
 }
});
