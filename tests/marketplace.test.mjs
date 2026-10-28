import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, rmSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { createMarketplace } from '../runtime/releases/coding-1.3.0/marketplace.mjs';
import { createPiCommandController } from '../runtime/releases/coding-1.3.0/pi-commands.mjs';
import { packageSource } from '../runtime/releases/coding-1.3.0/package-source.mjs';
import * as Pi from '../runtime/releases/coding-1.3.0/node_modules/@earendil-works/pi-coding-agent/dist/index.js';

function fixture() {
 const root=mkdtempSync(join(tmpdir(),'umeko-market-'));
 const cwd=join(root,'project'),agentDir=join(root,'agent'),source=join(root,'extension');
 for(const p of [cwd,agentDir,source])mkdirSync(p);
 writeFileSync(join(source,'package.json'),JSON.stringify({name:'market-fixture',version:'1.2.3',type:'module',pi:{extensions:['./index.js']}}));
 writeFileSync(join(source,'index.js'),'export default pi => {};');
 const events=[], session={isIdle:false,sessionManager:{getSessionId:()=> 'same-session',getSessionFile:()=>join(root,'session.jsonl'),getCwd:()=>cwd,appendCustomEntry:()=>{}},extensionRunner:{getCommand:()=>null}};
 const config={workspace:cwd,agentDir,agent:{}};
 const controller=createPiCommandController({Pi,getRuntime:()=>({session}),getConfig:()=>config,reload:async()=>{},notify:()=>{},emit:event=>events.push(event)});
 return {root,cwd,agentDir,source,events,config,controller,session};
}

test('run_pi_command defaults to ask, decline never installs, automatic installs and queues reload',async()=>{
 const f=fixture();
 try {
  const command='pi install '+JSON.stringify(f.source.replaceAll('\\','/'));
  let confirms=0;
  const ctx={ui:{confirm:async(title,detail)=>{
   confirms++;
   assert.equal(title,'安装 Pi 扩展包？');
   const request=JSON.parse(detail).umekoPackageInstall;
   assert.equal(request.source,f.source.replaceAll('\\','/'));
   assert.equal(request.reason,'Installed for the current task');
   assert.deepEqual(request.audit,{summary:'Not audited'});
   return false;
  }}};
  const registered=[];f.controller.extension({registerTool:tool=>registered.push(tool)});
  const declined=await registered[0].execute('decline',{command},undefined,undefined,ctx);
  assert.equal(JSON.parse(declined.content[0].text).status,'declined');
  assert.equal(confirms,1);assert.equal(existsSync(join(f.agentDir,'settings.json')),false);assert.equal(f.events.length,0);
  f.config.agent.installPermission='automatic';
  const installed=await registered[0].execute('auto',{command},undefined,undefined,ctx);
  assert.equal(confirms,1);assert.equal(JSON.parse(installed.content[0].text).reload,'queued');
  assert.match(readFileSync(join(f.agentDir,'settings.json'),'utf8'),/extension/);
  const entry=f.events.find(e=>e.type==='package_install');
  assert.equal(entry.package,'market-fixture');assert.equal(entry.version,'1.2.3');
  assert.equal(entry.session,'same-session');assert.equal(entry.installedBy,'agent');assert.ok(entry.reason&&entry.audit&&entry.time&&entry.source);
  f.session.isIdle=true;assert.equal((await f.controller.flush())[0].command,'/reload');
 } finally {rmSync(f.root,{recursive:true,force:true});}
});

test('marketplace_install delegates the pinned source, reason and confirmation context to the same gate',async()=>{
 const f=fixture();
 try {
  const registered=[],commands=[];let confirms=0,auditCalls=0;
  const registry={getPackageDetail:async(name,version)=>({name,version,keywords:['pi-package']}),fullAudit:async()=>{auditCalls++;return {summary:'Metadata and source notes',version:'1.2.3'};}};
  const market=createMarketplace({getConfig:()=>f.config,registryFactory:()=>registry,runPiCommand:(command,options)=>{
   commands.push({command,options});
   // The shared controller refuses before it reaches the native CLI.
   return f.controller.run(command,options);
  }});
  market.extension({registerTool:t=>registered.push(t)});
  const tool=registered.find(t=>t.name==='marketplace_install');
  const ctx={ui:{confirm:async()=>{confirms++;return false;}}};
  const value=await tool.execute('install',{name:'market-fixture',version:'1.2.3',reason:'Read the requested document'},undefined,undefined,ctx);
  assert.equal(JSON.parse(value.content[0].text).status,'declined');assert.equal(confirms,1);
  assert.equal(commands[0].command,'pi install npm:market-fixture@1.2.3');
  assert.equal(commands[0].options.ctx,ctx);assert.equal(commands[0].options.reason,'Read the requested document');
  assert.equal(existsSync(join(f.agentDir,'settings.json')),false);
  await registered.find(t=>t.name==='marketplace_audit').execute('audit',{name:'market-fixture',version:'1.2.3'},undefined,undefined,ctx);
  assert.equal(auditCalls,1,'Reuse the existing audit for the exact version');
  const auto=[];f.config.agent.installPermission='automatic';
  const automatic=createMarketplace({getConfig:()=>f.config,registryFactory:()=>registry,runPiCommand:async(command,options)=>{auto.push({command,options});return {status:'completed',reload:'queued'};}});
  const tools=[];automatic.extension({registerTool:t=>tools.push(t)});
  await tools.find(t=>t.name==='marketplace_install').execute('auto',{name:'market-fixture',version:'1.2.3',reason:'Continue'},undefined,undefined,ctx);
  assert.equal(confirms,1);assert.equal(auto.length,1);assert.equal(auto[0].options.ctx,ctx);
 } finally {rmSync(f.root,{recursive:true,force:true});}
});

test('tool usage identity comes from Pi sourceInfo and its package manifest',()=>{
 const f=fixture();
 try {
  const path=join(f.source,'index.js'),source='npm:market-fixture@1.2.3';
  const session={getAllTools:()=>[{name:'third_party',sourceInfo:{path,source,origin:'package',baseDir:f.source}},{name:'read',sourceInfo:{path:'builtin:read'}}],resourceLoader:{resourceMetadataByPath:new Map([[path,{source,origin:'package',packageRoot:f.source}]])}};
  assert.deepEqual(packageSource(session,'third_party'),{package:'market-fixture',version:'1.2.3',source,path,packageRoot:f.source});
  assert.equal(packageSource(session,'read'),null);assert.equal(packageSource(session,'unknown'),null);
 } finally {rmSync(f.root,{recursive:true,force:true});}
});
