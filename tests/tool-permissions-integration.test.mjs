import './tool-permissions-windowless.cjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { mkdtempSync,mkdirSync,existsSync,readFileSync,writeFileSync,rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { createToolPermissionExtension } from '../runtime/tool-permissions.mjs';
import { createSubagentExtension } from '../runtime/subagents.mjs';
import { createBackgroundJobsExtension } from '../runtime/background-jobs.mjs';

// No external model: this deterministic loopback provider emits real tool calls
// and receives the native Pi tool results through its next provider request.
const Pi=await import('../runtime/node_modules/@earendil-works/pi-coding-agent/dist/index.js');
const Facade=await import('../runtime/subagent-sdk.mjs');
const {AuthStorage}=await import('../runtime/node_modules/@earendil-works/pi-coding-agent/dist/core/auth-storage.js');
const {createJiti}=await import('../runtime/node_modules/jiti/lib/jiti.mjs');
const hostKey=Symbol.for('umeko:tool-permission-host');
const processKey=Symbol.for('umeko:test:before-process');
const textOf=message=>typeof message.content==='string'?message.content:JSON.stringify(message.content);

async function harness({turns,policy={mode:'ask',language:'en'},approve,extensions=[],facade=false,child=false,agentDefinitions={}}={}){
 const dir=mkdtempSync(join(tmpdir(),'umeko-permission-behavior-')),agentDir=join(dir,'agent');mkdirSync(agentDir);
 if(Object.keys(agentDefinitions).length){mkdirSync(join(agentDir,'agents'));for(const [name,text] of Object.entries(agentDefinitions))writeFileSync(join(agentDir,'agents',name+'.md'),text);}
 const confirmations=[],notifications=[],providerResults=[],events=[];let requestCount=0,modelRuntime,session;
 const ui={confirm:async(title,message)=>{confirmations.push({title,message});return approve===true;},notify:(text,type)=>notifications.push({text,type})};
 const previousHost=globalThis[hostKey],previousProcess=globalThis[processKey];
 const previousCwd=process.cwd(),previousAgentDir=process.env.PI_CODING_AGENT_DIR;
 // If the permission gate regresses, dangerous fixtures still never reach an
 // OS process. The test fails if this last-resort test guard is ever reached.
 let dangerousProcessAttempts=0;
 globalThis[processKey]=(_name,args)=>{if(JSON.stringify(args).includes('git push --force origin main')){dangerousProcessAttempts++;throw new Error('TEST: dangerous fixture must never reach process launch');}};
 if(facade||child)globalThis[hostKey]={getPolicy:()=>policy,ui:approve===undefined?undefined:ui};
 if(child){process.chdir(dir);process.env.PI_CODING_AGENT_DIR=agentDir;}
 const server=http.createServer(async(req,res)=>{
   const chunks=[];for await(const c of req)chunks.push(c);
   const body=JSON.parse(Buffer.concat(chunks).toString());
   providerResults.push(...(body.messages||[]).filter(m=>m.role==='tool').map(textOf));
   const row=turns[requestCount++];
   const common={id:`local-${requestCount}`,object:'chat.completion.chunk',created:1,model:'permission-test'};
   const delta=row?{role:'assistant',tool_calls:[{index:0,id:`call-${requestCount}`,type:'function',function:{name:row.name,arguments:JSON.stringify(typeof row.args==='function'?row.args(dir):row.args)}}]}:{role:'assistant',content:'Local permission scenario finished'};
   res.writeHead(200,{'Content-Type':'text/event-stream'});
   res.end(`data: ${JSON.stringify({...common,choices:[{index:0,delta,finish_reason:null}]})}\n\ndata: ${JSON.stringify({...common,choices:[{index:0,delta:{},finish_reason:row?'tool_calls':'stop'}]})}\n\ndata: [DONE]\n\n`);
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const settings=()=>Pi.SettingsManager.inMemory({retry:{enabled:false,provider:{maxRetries:0}},compaction:{enabled:false},cacheWarming:'off'});
 try{
   modelRuntime=await Pi.ModelRuntime.create({credentials:AuthStorage.inMemory(),modelsPath:null,allowModelNetwork:false,refreshOnCreate:false});
   modelRuntime.registerProvider('umeko-permission-local',{api:'openai-completions',baseUrl:`http://127.0.0.1:${server.address().port}/v1`,apiKey:'local-test-only',models:[{id:'permission-test',name:'permission-test',api:'openai-completions',reasoning:false,input:['text'],contextWindow:128000,maxTokens:256,cost:{input:0,output:0,cacheRead:0,cacheWrite:0},compat:{supportsDeveloperRole:false,supportsStore:false}}]});
   await modelRuntime.refresh({allowNetwork:false});
   const API=facade?Facade:Pi;
   const factories=[...(facade?[]:[{name:'permission-test',hidden:true,replaceable:false,factory:createToolPermissionExtension({getPolicy:()=>policy})}]),...extensions];
   const loader=new API.DefaultResourceLoader({cwd:dir,agentDir,settingsManager:settings(),noExtensions:true,noSkills:true,noPromptTemplates:true,noThemes:true,noContextFiles:true,additionalExtensionPaths:factories.filter(f=>f.builtin).map(f=>`builtin:${f.name}`),extensionFactories:factories});
   await loader.reload();assert.deepEqual(loader.getExtensions().errors,[]);
   ({session}=await API.createAgentSession({cwd:dir,agentDir,modelRuntime,settingsManager:settings(),resourceLoader:loader,sessionManager:Pi.SessionManager.create(dir,join(dir,'sessions')),model:modelRuntime.getModel('umeko-permission-local','permission-test'),tools:['read','bash','edit','write','background_job','nested_fixture','subagent',...(process.platform==='win32'?['powershell']:[])]}));
   await session.bindExtensions(approve===undefined?{}:{uiContext:ui,mode:'rpc'});
   session.subscribe(event=>{if(event.type==='tool_execution_end')events.push({name:event.toolName,isError:event.isError,text:JSON.stringify(event.result),parent:event.parentToolCallId});});
   return {dir,agentDir,session,policy,confirmations,notifications,providerResults,events,modelRuntime,requestCount:()=>requestCount,dangerousAttempts:()=>dangerousProcessAttempts,async close(){await session?.extensionRunner.emit({type:'session_shutdown'});await session?.dispose();await modelRuntime?.dispose?.();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));if(child){process.chdir(previousCwd);if(previousAgentDir===undefined)delete process.env.PI_CODING_AGENT_DIR;else process.env.PI_CODING_AGENT_DIR=previousAgentDir;}if(previousHost===undefined)delete globalThis[hostKey];else globalThis[hostKey]=previousHost;if(previousProcess===undefined)delete globalThis[processKey];else globalThis[processKey]=previousProcess;rmSync(dir,{recursive:true,force:true});}};
 }catch(error){await session?.dispose();await modelRuntime?.dispose?.();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));if(child){process.chdir(previousCwd);if(previousAgentDir===undefined)delete process.env.PI_CODING_AGENT_DIR;else process.env.PI_CODING_AGENT_DIR=previousAgentDir;}if(previousHost===undefined)delete globalThis[hostKey];else globalThis[hostKey]=previousHost;if(previousProcess===undefined)delete globalThis[processKey];else globalThis[processKey]=previousProcess;rmSync(dir,{recursive:true,force:true});throw error;}
}

test('actual Pi ask approval executes a harmless native bash operation',{timeout:30000},async()=>{
 const h=await harness({turns:[{name:'bash',args:{command:'printf approved > approved-marker.txt'}}],approve:true});
 try{await h.session.prompt('Run the local fixture.');assert.equal(readFileSync(join(h.dir,'approved-marker.txt'),'utf8'),'approved');assert.equal(h.confirmations.length,1);assert.ok(h.events.some(e=>e.name==='bash'&&!e.isError));assert.ok(h.providerResults.some(t=>!t.includes('User denied execution')));}finally{await h.close();}
});

test('actual Pi denial prevents native bash side effect and reaches provider context',{timeout:30000},async()=>{
 const h=await harness({turns:[{name:'bash',args:{command:'printf denied > denied-marker.txt'}}],approve:false});
 try{await h.session.prompt('Run the local fixture.');assert.equal(existsSync(join(h.dir,'denied-marker.txt')),false);assert.equal(h.confirmations.length,1);assert.ok(h.providerResults.some(t=>/User denied execution/.test(t)));assert.ok(h.events.some(e=>e.name==='bash'&&e.isError));}finally{await h.close();}
});

test('actual Pi denies a background start before any job or file is created',{timeout:30000},async()=>{
 const adapter=createBackgroundJobsExtension();
 const h=await harness({turns:[{name:'background_job',args:{action:'start',command:'printf denied > background-denied-marker.txt'}}],approve:false,
   extensions:[{name:'background-jobs',builtin:true,factory:adapter.extension}]});
 try{
   await h.session.prompt('Run the local background fixture.');
   assert.equal(existsSync(join(h.dir,'background-denied-marker.txt')),false);
   assert.equal(h.confirmations.length,1);
   assert.ok(h.events.some(e=>e.name==='background_job'&&e.isError));
   assert.ok(h.providerResults.some(t=>/User denied execution/.test(t)));
 }finally{await h.close();}
});

test('actual Pi approval starts the unchanged harmless background command',{timeout:30000},async()=>{
 const adapter=createBackgroundJobsExtension();
 const h=await harness({turns:[{name:'background_job',args:{action:'start',command:'printf approved > background-approved-marker.txt'}}],approve:true,
   extensions:[{name:'background-jobs',builtin:true,factory:adapter.extension}]});
 let manager;
 try{
   await h.session.prompt('Run the approved local background fixture.');
   manager=await adapter.getManager();const jobs=manager.list();assert.equal(jobs.length,1);
   assert.equal((await manager.wait(jobs[0].id,{timeoutMs:10000})).exitCode,0);
   assert.equal(readFileSync(join(h.dir,'background-approved-marker.txt'),'utf8'),'approved');
   assert.equal(h.confirmations.length,1);
   assert.ok(h.events.some(e=>e.name==='background_job'&&!e.isError));
 }finally{await h.close();if(manager)rmSync(manager.directory,{recursive:true,force:true});}
});

test('actual Pi headless native write is blocked without approval UI',{timeout:30000},async()=>{
 const h=await harness({turns:[{name:'write',args:{path:'headless-marker.txt',content:'never'}}]});
 try{await h.session.prompt('Write the local fixture.');assert.equal(existsSync(join(h.dir,'headless-marker.txt')),false);assert.ok(h.providerResults.some(t=>/approval UI is unavailable/.test(t)));}finally{await h.close();}
});

test('actual Pi session reads runtime permission mode on each tool call',{timeout:30000},async()=>{
 const h=await harness({policy:{mode:'auto',language:'en'},approve:false,turns:[{name:'write',args:{path:'auto-marker.txt',content:'auto'}},null,{name:'write',args:{path:'ask-marker.txt',content:'never'}}]});
 try{await h.session.prompt('First local fixture.');assert.equal(readFileSync(join(h.dir,'auto-marker.txt'),'utf8'),'auto');assert.equal(h.confirmations.length,0);h.policy.mode='ask';await h.session.prompt('Second local fixture.');assert.equal(existsSync(join(h.dir,'ask-marker.txt')),false);assert.equal(h.confirmations.length,1);assert.ok(h.providerResults.some(t=>/User denied execution/.test(t)));}finally{await h.close();}
});

test('actual nested ctx.executeTool native write follows the same gate',{timeout:30000},async()=>{
 const nested={name:'nested-fixture',factory:pi=>pi.registerTool({name:'nested_fixture',label:'Nested fixture',description:'Call a harmless native write via the supported nested tool API',annotations:{readOnlyHint:true},parameters:{type:'object',properties:{},additionalProperties:false},async execute(_id,_args,_signal,_update,ctx){const outcome=await ctx.executeTool('write',{path:'nested-marker.txt',content:'never'});return {...outcome.result,isError:outcome.isError};}})};
 const h=await harness({turns:[{name:'nested_fixture',args:{}}],extensions:[nested],approve:false});
 try{await h.session.prompt('Nested local fixture.');assert.equal(existsSync(join(h.dir,'nested-marker.txt')),false);assert.equal(h.confirmations.length,1);assert.ok(h.events.some(e=>e.name==='write'&&e.isError&&e.parent));assert.ok(h.providerResults.some(t=>/User denied execution/.test(t)));}finally{await h.close();}
});

test('actual Pi permission classifier exception blocks native execution visibly',{timeout:30000},async()=>{
 const injected={name:'injected-failure',factory:createToolPermissionExtension({getPolicy:()=>({mode:'auto',language:'en'}),classify:()=>{throw new Error('injected-classifier-failure');}})};
 const h=await harness({policy:{mode:'auto',language:'en'},turns:[{name:'bash',args:{command:'printf never > throw-marker.txt'}}],extensions:[injected],approve:true});
 try{await h.session.prompt('Error local fixture.');assert.equal(existsSync(join(h.dir,'throw-marker.txt')),false);assert.ok(h.notifications.some(n=>/injected-classifier-failure/.test(n.text)));assert.ok(h.providerResults.some(t=>/Permission check failed.*injected-classifier-failure/.test(t)));}finally{await h.close();}
});

test('actual native powershell tool is intercepted before its harmless write',{timeout:30000,skip:process.platform!=='win32'},async()=>{
 const h=await harness({turns:[{name:'powershell',args:{command:"Set-Content -Path 'powershell-marker.txt' -Value never"}}],approve:false});
 try{await h.session.prompt('PowerShell local fixture.');assert.equal(existsSync(join(h.dir,'powershell-marker.txt')),false);assert.equal(h.confirmations.length,1);assert.ok(h.events.some(e=>e.name==='powershell'&&e.isError));assert.ok(h.providerResults.some(t=>/User denied execution/.test(t)));}finally{await h.close();}
});

test('real community child birth inherits mandatory SDK facade gate',{timeout:90000},async()=>{
 const adapter=createSubagentExtension({emit:()=>{}});
 const h=await harness({facade:true,child:true,policy:{mode:'auto',language:'en'},approve:false,extensions:[{name:'subagents',builtin:true,factory:adapter.extension}],turns:[{name:'bash',args:{command:'git push --force origin main'}}]});
 try{
   const jiti=createJiti(new URL('../runtime/subagents.mjs',import.meta.url).href,{moduleCache:false,tryNative:false,fsCache:join(h.agentDir,'cache','permission-service')});
   const {getSubagentsService}=await jiti.import('@gotgenes/pi-subagents');const service=getSubagentsService();assert.ok(service);
   const id=service.spawn('general-purpose','Run the deterministic permission fixture.',{foreground:true});await service.waitForAll();
   const record=service.getRecord(id);assert.equal(record.status,'completed',record.error);assert.ok(h.confirmations.some(c=>c.message.includes('git push --force origin main')));assert.ok(h.providerResults.some(t=>/User denied execution/.test(t)));assert.equal(h.dangerousAttempts(),0);
 }finally{adapter.dispose();await h.close();}
});

test('real community child background starts inherit the parent permission policy',{timeout:90000},async()=>{
 const adapter=createSubagentExtension({emit:()=>{}});
 const jobs=createBackgroundJobsExtension();
 const h=await harness({facade:true,child:true,policy:{mode:'auto',language:'en'},approve:false,extensions:[{name:'subagents',builtin:true,factory:adapter.extension},{name:'background-jobs',builtin:true,factory:jobs.extension}],
   agentDefinitions:{'background-review':'---\nname: background-review\ndescription: Local background permission test\ntools: background_job\n---\nRun the local fixture.'},
   turns:[{name:'background_job',args:{action:'start',command:'git push --force origin main'}}]});
 try{
   const jiti=createJiti(new URL('../runtime/subagents.mjs',import.meta.url).href,{moduleCache:false,tryNative:false,fsCache:join(h.agentDir,'cache','permission-service')});
   const {getSubagentsService}=await jiti.import('@gotgenes/pi-subagents');const service=getSubagentsService();assert.ok(service);
   const id=service.spawn('background-review','Run the deterministic background permission fixture.',{foreground:true});await service.waitForAll();
   const record=service.getRecord(id);assert.equal(record.status,'completed',record.error);
   assert.ok(h.confirmations.some(c=>c.message.includes('git push --force origin main')),JSON.stringify({results:h.providerResults,result:record.result,prompts:h.confirmations}));
   assert.ok(h.providerResults.some(t=>/User denied execution/.test(t)));assert.equal(h.dangerousAttempts(),0);
 }finally{adapter.dispose();await h.close();}
});

test('restored native Pi session retains mandatory SDK facade gate',{timeout:30000},async()=>{
 const h=await harness({facade:true,approve:false,turns:[null,{name:'write',args:{path:'restored-marker.txt',content:'never'}}]});
 let restored;
 try{
   await h.session.prompt('Create the native session history fixture.');
   const loader=new Facade.DefaultResourceLoader({cwd:h.dir,agentDir:h.agentDir,settingsManager:Pi.SettingsManager.inMemory({}),noExtensions:true,noSkills:true,noPromptTemplates:true,noThemes:true,noContextFiles:true});
   await loader.reload();assert.deepEqual(loader.getExtensions().errors,[]);
   const saved=h.session.sessionManager.getSessionFile();assert.ok(saved);
   ({session:restored}=await Facade.createAgentSession({cwd:h.dir,agentDir:h.agentDir,modelRuntime:h.modelRuntime,settingsManager:Pi.SettingsManager.inMemory({retry:{enabled:false},compaction:{enabled:false},cacheWarming:'off'}),resourceLoader:loader,sessionManager:Pi.SessionManager.open(saved),model:h.modelRuntime.getModel('umeko-permission-local','permission-test')}));
   // Same empty binding used by the community child; host UI is relayed by facade.
   await restored.bindExtensions({});await restored.prompt('Run the restored local fixture.');
   assert.equal(existsSync(join(h.dir,'restored-marker.txt')),false);assert.equal(h.confirmations.length,1);assert.ok(h.providerResults.some(t=>/User denied execution/.test(t)));
 }finally{await restored?.extensionRunner.emit({type:'session_shutdown'});await restored?.dispose();await h.close();}
});
