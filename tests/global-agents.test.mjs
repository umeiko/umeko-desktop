import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {coordinatorToolGate,coordinatorExtension} from '../runtime/umeko-control.mjs';
test('coordinator gate only admits the bridge and safe discovery calls',()=>{
 for(const operation of ['agent_bus.overview','agent_bus.dispatch','agent_bus.requests','agent_bus.reply','agent_bus.connections','agent_bus.set_connection','help','models.list'])assert.equal(coordinatorToolGate({toolName:'umeko_desktop',input:{operation}}),undefined);
 for(const operation of ['agent_bus.create','agent_bus.creation_status','batch','sessions.send','widgets.call','appearance.fontScale','providers.save','jobs.get'])assert.equal(coordinatorToolGate({toolName:'umeko_desktop',input:{operation}}).block,true);
 for(const toolName of ['bash','write','read','codemode','tool_search','run_pi_command','subagent'])assert.equal(coordinatorToolGate({toolName,input:{operation:'agent_bus.overview'}}).block,true);
});
test('the mandatory extension installs a pre-execution gate',()=>{
 const hooks=[];coordinatorExtension({on:(name,fn)=>hooks.push([name,fn])});assert.equal(hooks.length,1);assert.equal(hooks[0][0],'tool_call');assert.equal(hooks[0][1]({toolName:'bash'}).block,true);
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
 const control=createUmekoControl({emit:event=>events.push(event),getPetAssistantBinding:()=>binding});
 control.extension({registerCommand(){},registerTool:tool=>tools.push(tool)});
 const speech=tools.find(tool=>tool.name===SEND_TO_USER);
 assert.ok(speech);assert.deepEqual(Object.keys(speech.parameters.properties),['text']);
 assert.equal(coordinatorToolGate({toolName:SEND_TO_USER}).block,true);
 assert.equal(coordinatorToolGate({toolName:SEND_TO_USER},{petAssistant:true}),undefined);
 assert.equal(coordinatorToolGate({toolName:'umeko_desktop',input:{operation:'desktop_pet.send_to_user'}},{petAssistant:true}).block,true);
 const rejected=await speech.execute('too-long',{text:'字'.repeat(81)});
 assert.equal(rejected.isError,true);assert.equal(events.length,0);
 const pending=speech.execute('valid',{text:'👩‍💻'.repeat(80)});
 assert.equal(events.length,1);assert.equal(events[0].operation,'desktop_pet.send_to_user');
 assert.equal(events[0].arguments.binding,binding);
 control.response({id:events[0].id,result:{ok:true,status:'shown'}});
 assert.equal((await pending).isError,false);
 binding='new-binding';
 const limited=speech.execute('limited',{text:'完成啦。'});
 assert.equal(events[1].arguments.binding,'new-binding');
 control.response({id:events[1].id,result:{ok:false,status:'rate_limited',retry_after:30}});
 const result=await limited;assert.equal(result.isError,true);
 assert.equal(JSON.parse(result.content[0].text).status,'rate_limited');
 assert.equal(events.length,2,'The tool must not automatically retry rejected speech');
});
