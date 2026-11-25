import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {setImmediate as nextTurn} from 'node:timers/promises';
import {coordinatorToolGate,coordinatorExtension} from '../runtime/umeko-control.mjs';
import {createCoordinatorSkills,coordinatorSkillCatalog,coordinatorSkillPaths} from '../runtime/coordinator-skills.mjs';
import {mkdtempSync,mkdirSync,writeFileSync,rmSync,symlinkSync} from 'node:fs';
import {join,dirname} from 'node:path';
import {tmpdir} from 'node:os';

test('global Skills default to none, load only explicit choices, and survive native reload',async()=>{
 const Pi=await import('../runtime/node_modules/@earendil-works/pi-coding-agent/dist/index.js');
 const root=mkdtempSync(join(tmpdir(),'umeko-global-skills-'));
 try {
  const cwd=join(root,'work'),agentDir=join(root,'agent'),builtin=join(root,'builtin'),imported=join(agentDir,'skills');mkdirSync(cwd,{recursive:true});
  const skill=(base,name)=>{const path=join(base,name,'SKILL.md');mkdirSync(dirname(path),{recursive:true});writeFileSync(path,`---\nname: ${name}\ndescription: ${name} fixture\n---\nUse the selected instructions.`);return path;};
  skill(builtin,'bundled');skill(imported,'custom');skill(join(cwd,'.pi/skills'),'workspace-only');
  const input={globalCoordinator:true,cwd,agentDir,coordinatorSkillRoots:{builtin,imported},sessionSkills:{[join(imported,'custom/SKILL.md')]:true}};
  const load=async values=>{const controller=createCoordinatorSkills({...input,coordinatorSkills:values});const loader=new Pi.DefaultResourceLoader({cwd,agentDir,settingsManager:Pi.SettingsManager.inMemory({}),noExtensions:true,noContextFiles:true,noPromptTemplates:true,noThemes:true,...controller.resourceOptions});await loader.reload();return loader;};
  assert.deepEqual((await load(undefined)).getSkills().skills,[]);
  const loader=await load(['builtin:bundled']);assert.deepEqual(loader.getSkills().skills.map(row=>row.name),['bundled']);
  await loader.reload();assert.deepEqual(loader.getSkills().skills.map(row=>row.name),['bundled']);
  const second=await load(['imported:custom']);assert.deepEqual(second.getSkills().skills.map(row=>row.name),['custom']);
  assert.deepEqual(coordinatorSkillPaths({...input,coordinatorSkills:['builtin:../bundled','builtin:..','imported:/etc','forged:custom']}),[]);
  const catalog=coordinatorSkillCatalog(Pi,input);assert.deepEqual(catalog.skills.map(row=>row.id),['builtin:bundled','imported:custom']);
 } finally {rmSync(root,{recursive:true,force:true});}
});

test('coordinator Skill reader cannot expose workspace files, disabled Skills, or escaped links',async()=>{
 const root=mkdtempSync(join(tmpdir(),'umeko-global-reader-'));
 try {
  const builtin=join(root,'builtin'),folder=join(builtin,'allowed');mkdirSync(folder,{recursive:true});
  writeFileSync(join(folder,'SKILL.md'),'selected instructions');writeFileSync(join(root,'private.txt'),'do not expose');
  const controller=createCoordinatorSkills({globalCoordinator:true,coordinatorSkills:['builtin:allowed'],coordinatorSkillRoots:{builtin}}),tools=[];
  controller.extension({registerTool:tool=>tools.push(tool)});const reader=tools[0];
  assert.equal((await reader.execute('ok',{path:join(folder,'SKILL.md')})).content[0].text,'selected instructions');
  assert.equal((await reader.execute('outside',{path:join(root,'private.txt')})).isError,true);
  if(process.platform!=='win32'){symlinkSync(join(root,'private.txt'),join(folder,'escape.txt'));assert.equal((await reader.execute('link',{path:join(folder,'escape.txt')})).isError,true);}
  const disabled=[];createCoordinatorSkills({globalCoordinator:true,coordinatorSkillRoots:{builtin}}).extension({registerTool:t=>disabled.push(t)});
  assert.equal((await disabled[0].execute('disabled',{path:join(folder,'SKILL.md')})).isError,true);
  assert.equal(coordinatorToolGate({toolName:'read'},{skillReader:true}),undefined);
  assert.equal(coordinatorToolGate({toolName:'bash'},{skillReader:true}).block,true);
  assert.equal(coordinatorToolGate({toolName:'umeko_desktop',input:{operation:'agent_bus.create'}},{skillReader:true}).block,true);
 } finally {rmSync(root,{recursive:true,force:true});}
});
test('coordinator gate only admits the bridge and safe discovery calls',()=>{
 for(const operation of ['agent_bus.overview','agent_bus.dispatch','agent_bus.requests','agent_bus.reply','agent_bus.connections','agent_bus.set_connection','help','models.list'])assert.equal(coordinatorToolGate({toolName:'umeko_desktop',input:{operation}}),undefined);
 for(const operation of ['agent_bus.create','agent_bus.creation_status','batch','sessions.send','widgets.call','appearance.fontScale','providers.save','jobs.get'])assert.equal(coordinatorToolGate({toolName:'umeko_desktop',input:{operation}}).block,true);
 for(const toolName of ['bash','write','read','codemode','tool_search','run_pi_command','subagent'])assert.equal(coordinatorToolGate({toolName,input:{operation:'agent_bus.overview'}}).block,true);
});
test('the mandatory extension installs a pre-execution gate',()=>{
 const hooks=[];coordinatorExtension({on:(name,fn)=>hooks.push([name,fn])});assert.equal(hooks.length,1);assert.equal(hooks[0][0],'tool_call');assert.equal(hooks[0][1]({toolName:'bash'}).block,true);
});

test('native tools are opt-in per coordinator and cannot enable management or private tools',async()=>{
 const {coordinatorNativeTools}=await import('../runtime/umeko-control.mjs');
 const {CORE_TOOLS}=await import('../runtime/session-capabilities.mjs');
 assert.deepEqual(coordinatorNativeTools(['read','read','bash','subagent','send_to_user',null]),['read','bash']);
 for(const name of CORE_TOOLS) {
  assert.equal(coordinatorToolGate({toolName:name})?.block,true);
  assert.equal(coordinatorToolGate({toolName:name},{nativeTools:[name]}),undefined);
 }
 const options={nativeTools:[...CORE_TOOLS,'subagent','send_to_user','reminder','run_pi_command']};
 for(const toolName of ['subagent','codemode','tool_search','run_pi_command','send_to_user','reminder'])
  assert.equal(coordinatorToolGate({toolName},options)?.block,true);
 assert.equal(coordinatorToolGate({toolName:'umeko_desktop',input:{operation:'agent_bus.create'}},options)?.block,true);
 const registered=[];
 createCoordinatorSkills({globalCoordinator:true,coordinatorTools:['read']}).extension({registerTool:t=>registered.push(t)});
 assert.equal(registered.length,0,'An enabled native reader must retain Pi file/image behavior');
 const restricted=[];
 createCoordinatorSkills({globalCoordinator:true,coordinatorTools:['write']}).extension({registerTool:t=>restricted.push(t)});
 assert.deepEqual(restricted.map(t=>t.name),['read'],'Other tools do not broaden the Skill reader');
});

test('bus project search joins native Windows paths with saved project names',()=>{
 const qml=readFileSync(new URL('../umeko-plugins/global-agents/qml/Main.qml',import.meta.url),'utf8');
 const code=qml.slice(qml.indexOf('function bridgeTree('),qml.indexOf('function toggleProject('));
 const context=vm.createContext({Qt:{platform:{os:'windows'}}});
 vm.runInContext(code,context);
 const projects=[{path:'C:/Work/Project/',name:'Named acceptance project'}];
 const targets=[{id:'session:one',kind:'session',workspace:'c:\\Work\\Project',title:'First'},{id:'session:two',kind:'session',workspace:'C:/WORK/PROJECT',title:'Second'}];
 const rows=context.bridgeTree(projects,targets,'Named acceptance',{});
 assert.equal(rows.length,3);assert.equal(rows[0].title,'Named acceptance project');
 assert.equal(rows[0].key,'c:/work/project');assert.equal(rows[0].count,2);
 assert.deepEqual(Array.from(rows.slice(1),row=>row.id),['session:one','session:two']);
 assert.equal(context.bridgeTree(projects,targets,'',{'c:/work/project':true}).length,1);
 context.Qt.platform.os='linux';
 const sensitive=context.bridgeTree([{path:'/Work',name:'Upper'}],[{id:'a',kind:'session',workspace:'/Work'},{id:'b',kind:'session',workspace:'/work'}],'',{});
 assert.equal(sensitive.filter(row=>row.kind==='project').length,2);
});

// Dedicated speech must remain separate from the public coordinator management API.
test('only a host-bound pet assistant receives send_to_user and its hidden binding',async()=>{
 const {createUmekoControl,SEND_TO_USER}=await import('../runtime/umeko-control.mjs');
 const ordinary=[],tools=[],events=[];let binding='host-binding';
 createUmekoControl({emit(){}}).extension({registerCommand(){},registerTool:tool=>ordinary.push(tool)});
 assert.equal(ordinary.some(tool=>tool.name===SEND_TO_USER),false);
 const control=createUmekoControl({emit:event=>events.push(event),getPetAssistantBinding:()=>binding,waitForSpeech:async()=>{}});
 control.extension({registerCommand(){},registerTool:tool=>tools.push(tool)});
 const speech=tools.find(tool=>tool.name===SEND_TO_USER);
 assert.ok(speech);assert.deepEqual(Object.keys(speech.parameters.properties),['text']);
 assert.equal(coordinatorToolGate({toolName:SEND_TO_USER}).block,true);
 assert.equal(coordinatorToolGate({toolName:SEND_TO_USER},{petAssistant:true}),undefined);
 assert.equal(coordinatorToolGate({toolName:'umeko_desktop',input:{operation:'desktop_pet.send_to_user'}},{petAssistant:true}).block,true);
 const rejected=await speech.execute('too-long',{text:'字'.repeat(81)});
 assert.equal(rejected.isError,true);assert.equal(events.length,0);
 const pending=speech.execute('valid',{text:'👩‍💻'.repeat(80)});await nextTurn();
 assert.equal(events.length,1);assert.equal(events[0].operation,'desktop_pet.send_to_user');
 assert.equal(events[0].arguments.binding,binding);
 control.response({id:events[0].id,result:{ok:true,status:'shown'}});
 assert.equal((await pending).isError,false);
 binding='new-binding';
 const limited=speech.execute('limited',{text:'完成啦。'});await nextTurn();
 assert.equal(events[1].arguments.binding,'new-binding');
 control.response({id:events[1].id,result:{ok:false,status:'rate_limited',retry_after:30}});
 const result=await limited;assert.equal(result.isError,true);
 assert.equal(JSON.parse(result.content[0].text).status,'rate_limited');
 assert.equal(events.length,2,'The tool must not automatically retry rejected speech');
});

test('pet speech waits for reading, serializes parallel segments and cancels queued speech',async()=>{
 const {createUmekoControl}=await import('../runtime/umeko-control.mjs');
 const events=[],tools=[],waits=[],durations=[];
 const control=createUmekoControl({emit:event=>events.push(event),getPetAssistantBinding:()=> 'bound',
  waitForSpeech:async ms=>{durations.push(ms);await new Promise(resolve=>waits.push(resolve));}});
 control.extension({registerCommand(){},registerTool:tool=>tools.push(tool)});
 const speech=tools.find(tool=>tool.name==='send_to_user'),abort=new AbortController();
 let returned=false;
 const first=speech.execute('first',{text:'第一段'}).then(result=>{returned=true;return result;});
 const second=speech.execute('second',{text:'第二段'});
 const cancelled=speech.execute('cancelled',{text:'不应该显示'},abort.signal);
 await nextTurn();assert.equal(events.length,1);
 control.response({id:events[0].id,result:{ok:true,status:'shown',reading_ms:5200}});
 await nextTurn();assert.deepEqual(durations,[5200]);assert.equal(returned,false);assert.equal(events.length,1);
 abort.abort();await assert.rejects(cancelled,{name:'AbortError'});
 waits.shift()();await first;await nextTurn();assert.equal(events.length,2);assert.equal(events[1].arguments.text,'第二段');
 control.response({id:events[1].id,result:{ok:true,status:'shown',reading_ms:1800}});
 await nextTurn();assert.deepEqual(durations,[5200,1800]);waits.shift()();await second;await nextTurn();
 assert.equal(events.length,2);control.clear();
});

test('closing the bridge interrupts a real reading pause and allows a fresh connection',async()=>{
 const {createUmekoControl}=await import('../runtime/umeko-control.mjs');
 const events=[],tools=[];
 const control=createUmekoControl({emit:event=>events.push(event),getPetAssistantBinding:()=> 'bound'});
 control.extension({registerCommand(){},registerTool:tool=>tools.push(tool)});
 const speech=tools.find(tool=>tool.name==='send_to_user');
 const first=speech.execute('first',{text:'等待读完'});await nextTurn();
 control.response({id:events[0].id,result:{ok:true,status:'shown',reading_ms:12200}});
 await nextTurn();control.clear();await assert.rejects(first,{name:'AbortError'});
 const second=speech.execute('new',{text:'新的连接'});await nextTurn();assert.equal(events.length,2);
 control.response({id:events[1].id,result:{ok:false,status:'unavailable'}});assert.equal((await second).isError,true);
 control.clear();
});

 test('only the bound pet may use the scheduled-tasks Widget interface',()=>{
   for(const operation of ['widgets.docs','widgets.call']) {
     const event={toolName:'umeko_desktop',input:{operation,arguments:{id:'scheduled-tasks'}}};
     assert.equal(coordinatorToolGate(event,{petAssistant:true}),undefined);
     assert.equal(coordinatorToolGate(event)?.block,true);
     event.input.arguments.id='desktop-pet';
     assert.equal(coordinatorToolGate(event,{petAssistant:true})?.block,true);
   }
   assert.equal(coordinatorToolGate({toolName:'umeko_desktop',input:{operation:'widgets.result'}},{petAssistant:true}),undefined);
 });

 test('reminder tool is assigned only to the associated coordinator and preserves host identity',async()=>{
   const {createUmekoControl,REMINDER}=await import('../runtime/umeko-control.mjs');
   const tools=[],events=[];const control=createUmekoControl({emit:event=>events.push(event),getPetReminderBinding:()=> 'host-reminder-binding'});
   control.extension({registerCommand(){},registerTool:tool=>tools.push(tool)});
   const tool=tools.find(tool=>tool.name===REMINDER);assert.ok(tool);
   assert.equal(tool.parameters.properties.binding,undefined);
   assert.equal(coordinatorToolGate({toolName:REMINDER},{reminderAssistant:true}),undefined);
   assert.equal(coordinatorToolGate({toolName:REMINDER},{petAssistant:true})?.block,true);
   const request=tool.execute('create',{action:'create',title:'喝水',repeat:'daily',dueAt:'2030-01-01T09:00:00+08:00',timeZone:'Asia/Shanghai'});
   assert.equal(events[0].operation,'desktop_pet.reminder');
   assert.equal(events[0].arguments.binding,'host-reminder-binding');
   control.response({id:events[0].id,result:{ok:true,item:{title:'喝水'}}});
   assert.equal((await request).isError,false);
   assert.equal(tool.parameters.properties.completed.type,'boolean');
   const restore=tool.execute('restore',{action:'complete',id:'item-id',completed:false});
   assert.equal(events[1].arguments.completed,false);
   assert.equal(events[1].arguments.binding,'host-reminder-binding');
   control.response({id:events[1].id,result:{ok:true,item:{completed:false}}});
   assert.equal((await restore).isError,false);
 });
