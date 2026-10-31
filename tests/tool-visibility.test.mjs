import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtempSync,mkdirSync,writeFileSync,rmSync,existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createServer} from 'node:http';
import {blockedToolNames} from '../runtime/tool-visibility.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
test('tool denial accepts exact names only, not wildcards or invalid settings',()=>{
 assert.deepEqual(blockedToolNames(['write','write','mcp__demo__find','*','foo?','bad name',null]),['write','mcp__demo__find']);
 assert.deepEqual(blockedToolNames({write:false}),[]);
});

test('real Pi excludes native, Umeko and deferred tools across reload, nested calls and isolated conversations', {timeout:90000},async()=>{
 const temp=mkdtempSync(join(tmpdir(),'umeko-visibility-'));
 const cwd=join(temp,'workspace'),agentDir=join(temp,'agent'),sessionDir=join(temp,'sessions'),marker=join(temp,'ran');
 for(const dir of [cwd,agentDir,sessionDir])mkdirSync(dir);
 const extension=join(temp,'fixture.mjs');
 writeFileSync(extension,`import {writeFileSync} from 'node:fs';export default pi=>{pi.registerTool({name:'fixture_secret',label:'Secret',description:'Uniquely hidden visibility fixture',exposure:'deferred',parameters:{type:'object',properties:{}},execute:async()=>{writeFileSync(${JSON.stringify(marker)},'bad');return {content:[{type:'text',text:'executed'}]}}});pi.registerTool({name:'fixture_public',label:'Public',description:'Visible example',parameters:{type:'object',properties:{}},execute:async()=>({content:[{type:'text',text:'ok'}]})});}`);
 writeFileSync(join(agentDir,'settings.json'),JSON.stringify({extensions:[extension]}));
 let nextCall=null;const requests=[];
 const server=createServer(async(req,res)=>{
  let raw='';for await(const chunk of req)raw+=chunk;const body=JSON.parse(raw);requests.push(body);
  const call=nextCall;nextCall=null;
  const delta=call ? {role:'assistant',tool_calls:[{index:0,id:'call-'+requests.length,type:'function',function:{name:call.name,arguments:JSON.stringify(call.args)}}]} : {role:'assistant',content:'done'};
  const common={id:'test',object:'chat.completion.chunk',created:1,model:'fixture'};
  res.writeHead(200,{'Content-Type':'text/event-stream'});res.end(`data: ${JSON.stringify({...common,choices:[{index:0,delta,finish_reason:null}]})}\n\ndata: ${JSON.stringify({...common,choices:[{index:0,delta:{},finish_reason:call?'tool_calls':'stop'}]})}\n\ndata: [DONE]\n\n`);
 });
 await new Promise(done=>server.listen(0,'127.0.0.1',done));
 const children=[];
 function start(blockedTools,sessionFile) {
  const events=[];let buffer='',stderr='';
  const child=spawn(process.execPath,[join(root,'runtime/releases/coding-1.3.0/bridge.mjs')],{cwd,stdio:['pipe','pipe','pipe']});children.push(child);
  child.stderr.on('data',data=>stderr+=data);
  child.stdout.on('data',data=>{buffer+=data;let i;while((i=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,i);buffer=buffer.slice(i+1);if(line)events.push(JSON.parse(line));}});
  const send=input=>child.stdin.write(JSON.stringify(input)+'\n');
  async function command(input) {const n=events.filter(e=>e.type==='done').length;send(input);const end=Date.now()+40000;while(events.filter(e=>e.type==='done').length===n){if(Date.now()>end||child.exitCode!==null)throw new Error(stderr+' '+JSON.stringify(events.slice(-4)));await new Promise(done=>setTimeout(done,15));}assert.equal(events.filter(e=>e.type==='error').length,0,JSON.stringify(events.slice(-5)));return events.filter(e=>e.type==='state').at(-1);}
  return {child,events,command,load:()=>command({type:'load',workspace:cwd,defaultCwd:cwd,agentDir,sessionDir,sessionFile,blockedTools,model:'fixture',models:[{id:'fixture'}],agent:{},gateway:`http://127.0.0.1:${server.address().port}/`,token:'local'})};
 }
 try {
  const denied=['write','umeko_desktop','fixture_secret'];const a=start(denied);let state=await a.load();
  for(const name of denied){assert.equal(state.resources.allTools.find(t=>t.name===name)?.visible,false,name);assert.ok(!state.resources.tools.includes(name));}
  assert.ok(state.resources.allTools.find(t=>t.name==='fixture_public').visible);
  nextCall={name:'tool_search',args:{query:'Uniquely hidden visibility fixture',limit:20}};
  state=await a.command({type:'prompt',text:'search'});
  const searchResult=a.events.find(e=>e.type==='tool'&&e.name==='tool_search'&&e.state==='done');
  assert.ok(searchResult);assert.ok(!searchResult.result.includes('fixture_secret'),searchResult.result);
  nextCall={name:'codemode',args:{code:'return {listed:ALL_TOOLS.map(t=>t.name), result:await tools.fixture_secret({})};'}};
  await a.command({type:'prompt',text:'try nested hidden tool'});
  assert.equal(existsSync(marker),false);
  assert.ok(a.events.some(e=>e.type==='tool'&&e.name==='codemode'&&(e.state==='error'||e.result?.match(/not|unknown|undefined/i))));
  state=await a.command({type:'reload'});
  assert.ok(!state.resources.tools.includes('write'));
  nextCall={name:'fixture_secret',args:{}};
  state=await a.command({type:'prompt',text:'try old tool call'});
  assert.equal(existsSync(marker),false);
  for(const request of requests) {
   const serialized=JSON.stringify(request.tools || []);
   for(const name of denied)assert.ok(!serialized.includes('"name":"'+name+'"'),name);
  }
  // Same workspace and package, independent policy. No global settings edited.
  const b=start([]);const normal=await b.load();
  for(const name of denied) assert.equal(normal.resources.allTools.find(t=>t.name===name)?.visible,true,name);
  assert.ok(normal.resources.tools.includes('write'));
  // Loading the original transcript still excludes the tools, including /reload.
  const resumed=start(denied,state.session.file);const reopened=await resumed.load();
  assert.equal(reopened.session.id,state.session.id);
  assert.equal(reopened.resources.allTools.find(t=>t.name==='fixture_secret').visible,false);
 } finally {
  await Promise.all(children.map(child=>new Promise(done=>{if(child.exitCode!==null)return done();child.once('close',done);child.stdin.end();setTimeout(()=>child.kill(),2500).unref();})));
  server.closeAllConnections();await new Promise(done=>server.close(done));rmSync(temp,{recursive:true,force:true});
 }
});

test('community subagents inherit exclusions and retain their stricter read-only allowlist',async()=>{
 const temp=mkdtempSync(join(tmpdir(),'umeko-child-visibility-'));
 const Pi=await import('../runtime/node_modules/@earendil-works/pi-coding-agent/dist/index.js');
 const facade=await import('../runtime/subagent-sdk.mjs');
 const {AuthStorage}=await import('../runtime/node_modules/@earendil-works/pi-coding-agent/dist/core/auth-storage.js');
 const previous=globalThis[Symbol.for('umeko:tool-visibility-host')];
 let session,models;
 try {
  models=await Pi.ModelRuntime.create({credentials:AuthStorage.inMemory(),modelsPath:null,allowModelNetwork:false,refreshOnCreate:false});
  globalThis[Symbol.for('umeko:tool-visibility-host')]={getBlockedTools:()=>['read','bash']};
  const settings=Pi.SettingsManager.inMemory({defaultTools:['read','grep','find','ls']});
  const loader=new facade.DefaultResourceLoader({cwd:temp,agentDir:temp,settingsManager:settings,noExtensions:true,noContextFiles:true,noSkills:true,noThemes:true,noPromptTemplates:true});
  await loader.reload();
  ({session}=await facade.createAgentSession({cwd:temp,agentDir:temp,settingsManager:settings,resourceLoader:loader,modelRuntime:models,sessionManager:Pi.SessionManager.inMemory(temp),tools:['read','grep','find','ls'],excludeTools:['find']}));
  assert.deepEqual(session.getAllTools().map(t=>t.name).sort(),['grep','ls']);
  session.setActiveToolsByName(['read','write','find','bash','grep','ls']);
  assert.deepEqual(session.getActiveToolNames().sort(),['grep','ls']);
  await session.reload();
  assert.deepEqual(session.getAllTools().map(t=>t.name).sort(),['grep','ls']);
 } finally {globalThis[Symbol.for('umeko:tool-visibility-host')]=previous;session?.dispose();rmSync(temp,{recursive:true,force:true});}
});
