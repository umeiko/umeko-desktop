import './tool-permissions-windowless.cjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {classifyCommand, classifyPath, createToolPermissionExtension,
  childPermissionPolicy, childPermissionUI} from '../runtime/tool-permissions.mjs';

// These fixtures are passed only to the classifier/gate; no tool executes them.
const context={cwd:'C:/workspace',home:'C:/Users/fixture',dataDir:'C:/umeko-data'};
const fixtures=[
  {toolName:'bash',input:{command:'rm -rf C:/umeko-data'},category:1},
  {toolName:'bash',input:{command:'diskpart'},category:2},
  {toolName:'bash',input:{command:'shutdown /s /t 0'},category:3},
  {toolName:'bash',input:{command:'reg add HKLM\\Software\\Fixture /v fixture /d 1'},category:4},
  {toolName:'bash',input:{command:'chmod -R 777 /etc'},category:5},
  {toolName:'bash',input:{command:'git push --force origin main'},category:6},
  {toolName:'write',input:{path:'C:/Windows/fixture.txt',content:'fixture'},category:7},
];

function harness(initial={}, {dangerous=true,approve=false}={}) {
 let policy={mode:'auto',language:'en',...context,...initial},handler;
 const calls=[];
 createToolPermissionExtension({getPolicy:()=>policy})({on:(name,fn)=>{
   assert.equal(name,'tool_call');handler=fn;
 }});
 const ui={confirm:async(title,detail)=>{calls.push({kind:'normal',title,detail});return approve;}};
 if(dangerous)ui.confirmDangerous=async(title,detail,category)=>{calls.push({kind:'danger',title,detail,category});return approve;};
 return {calls,ui,call:(event)=>handler(event,{cwd:context.cwd,hasUI:true,ui}),
   update:patch=>{policy={...policy,...patch};}};
}

test('real classifier covers the existing seven categories',()=>{
 for(const row of fixtures) {
   const hit=row.toolName==='write'?classifyPath(row.input.path,context):classifyCommand(row.input.command,context);
   assert.equal(hit?.category,row.category);
 }
});

test('only an explicit boolean authorizes the whole chat',async()=>{
 for(const value of [undefined,false,1,'true',[1,2,3,4,5,6,7],{}]) {
   const h=harness({dangerousAllowed:value});
   assert.equal((await h.call(fixtures[0])).block,true);
 }
});

for(const fixture of fixtures) {
 test(`approval from category ${fixture.category} covers every dangerous operation and can be revoked`,async()=>{
   const h=harness({dangerousAllowed:false});
   assert.equal((await h.call(fixture)).block,true);
   assert.equal(h.calls.at(-1).category,fixture.category);
   h.update({dangerousAllowed:true});
   for(const other of fixtures)assert.equal(await h.call(other),undefined);
   assert.equal(h.calls.length,1);
   h.update({dangerousAllowed:false});
   for(const other of fixtures)assert.equal((await h.call(other)).block,true);
   assert.equal(h.calls.length,8);
 });
 test(`ask mode still prompts after category ${fixture.category} is granted`,async()=>{
   const h=harness({mode:'ask',dangerousAllowed:true});
   assert.equal((await h.call(fixture)).block,true);
   assert.equal(h.calls.length,1);
   assert.equal(h.calls[0].kind,'normal');
   assert.match(h.calls[0].detail,/Ask mode requires approval/);
 });
}

test('ungranted danger merges the ask-mode prompt and uses optional danger metadata once',async()=>{
 const h=harness({mode:'ask'},{approve:true});
 assert.equal(await h.call(fixtures[0]),undefined);
 assert.equal(h.calls.length,1);
 assert.equal(h.calls[0].category,1);
});

test('chat authorization does not bypass ordinary ask or generation confirmations',async()=>{
 const h=harness({mode:'ask',dangerousAllowed:true});
 for(const event of [{toolName:'write',input:{path:'notes.txt',content:'test'}},
   {toolName:'bash',input:{command:'echo fixture'}},{toolName:'image_gen',input:{prompt:'fixture'}}]) {
   assert.equal((await h.call(event)).block,true);
 }
 assert.deepEqual(h.calls.map(row=>row.kind),['normal','normal','normal']);
 h.update({mode:'auto'});
 assert.equal(await h.call({toolName:'write',input:{path:'notes.txt',content:'test'}}),undefined);
 assert.equal(await h.call({toolName:'read',input:{path:'C:/Windows/fixture.txt'}}),undefined);
 assert.equal(h.calls.length,3);
});

test('one chat authorization covers compound commands and literal shell wrappers',async()=>{
 const commands=[
   'rm -rf C:/umeko-data && shutdown /s /t 0',
   'shutdown /s /t 0; rm -rf C:/umeko-data',
   'bash -c "rm -rf C:/umeko-data; shutdown /s /t 0"',
   'git push --force origin main | shutdown /s /t 0',
   'rm -rf C:/umeko-data\nchmod -R 777 /etc',
 ];
 const h=harness({dangerousAllowed:false});
 for(const command of commands)assert.equal((await h.call({toolName:'bash',input:{command}})).block,true);
 const count=h.calls.length;
 h.update({dangerousAllowed:true});
 for(const command of commands)assert.equal(await h.call({toolName:'bash',input:{command}}),undefined);
 assert.equal(h.calls.length,count);
 h.update({dangerousAllowed:false});
 for(const command of commands)assert.equal((await h.call({toolName:'bash',input:{command}})).block,true);
});

test('generic UI remains compatible and does not mutate grants after approval',async()=>{
 const h=harness({dangerousAllowed:false},{dangerous:false,approve:true});
 assert.equal(await h.call(fixtures[0]),undefined);
 assert.equal(await h.call(fixtures[0]),undefined);
 assert.deepEqual(h.calls.map(row=>row.kind),['normal','normal']);
});

test('child policy and UI retain normal settings but strip chat authorization and grant action',async()=>{
 const parentPolicy={mode:'auto',language:'zh',...context,dangerousAllowed:true};
 const calls=[];
 const parentUI={confirm:async(...args)=>{calls.push(args);return false;},confirmDangerous:()=>{throw Error('child exposed grant UI');},notify:()=>{}};
 const policy=childPermissionPolicy(parentPolicy),ui=childPermissionUI(parentUI);
 assert.equal('dangerousAllowed' in policy,false);
 assert.equal('confirmDangerous' in ui,false);
 assert.equal(ui.confirm,parentUI.confirm);
 assert.equal(policy.mode,'auto');assert.equal(policy.language,'zh');
 assert.equal(parentPolicy.dangerousAllowed,true);
 let handler;createToolPermissionExtension({getPolicy:()=>policy})({on:(_name,fn)=>{handler=fn;}});
 assert.equal((await handler(fixtures[0],{cwd:context.cwd,hasUI:true,ui})).block,true);
 assert.equal(calls.length,1);
});

test('actual child facade binds ordinary confirmation and denies despite parent authorization',async()=>{
 const Pi=await import('../runtime/node_modules/@earendil-works/pi-coding-agent/dist/index.js');
 const facade=await import('../runtime/subagent-sdk.mjs');
 const {AuthStorage}=await import('../runtime/node_modules/@earendil-works/pi-coding-agent/dist/core/auth-storage.js');
 const directory=mkdtempSync(join(tmpdir(),'umeko-session-danger-child-'));
 const hostKey=Symbol.for('umeko:tool-permission-host'),previous=globalThis[hostKey];
 let session,models,normalCalls=0,dangerCalls=0;
 try {
   globalThis[hostKey]={getPolicy:()=>({mode:'auto',...context,dangerousAllowed:true}),
     ui:{confirm:async()=>{normalCalls++;return false;},confirmDangerous:async()=>{dangerCalls++;return true;},notify:()=>{}}};
   models=await Pi.ModelRuntime.create({credentials:AuthStorage.inMemory(),modelsPath:null,allowModelNetwork:false,refreshOnCreate:false});
   const settings=Pi.SettingsManager.inMemory({cacheWarming:'off'});
   const loader=new facade.DefaultResourceLoader({cwd:directory,agentDir:directory,settingsManager:settings,
     noExtensions:true,noContextFiles:true,noSkills:true,noThemes:true,noPromptTemplates:true});
   await loader.reload();assert.deepEqual(loader.getExtensions().errors,[]);
   ({session}=await facade.createAgentSession({cwd:directory,agentDir:directory,settingsManager:settings,
     resourceLoader:loader,modelRuntime:models,sessionManager:Pi.SessionManager.inMemory(directory),tools:['bash']}));
   // This is the empty binding used by the community child; the facade supplies its filtered host UI.
   await session.bindExtensions({});
   assert.equal(session.extensionRunner.getUIContext().confirmDangerous,undefined);
   for(const fixture of fixtures) {
     const result=await session.extensionRunner.emitToolCall({type:'tool_call',toolCallId:`fixture-${fixture.category}`,...fixture});
     assert.equal(result?.block,true,`child category ${fixture.category}`);
   }
   assert.equal(normalCalls,7);assert.equal(dangerCalls,0);
 } finally {
   await session?.dispose();await models?.dispose?.();
   if(previous===undefined)delete globalThis[hostKey];else globalThis[hostKey]=previous;
   rmSync(directory,{recursive:true,force:true});
 }
});
