import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {coordinatorToolGate,coordinatorExtension} from '../runtime/umeko-control.mjs';
test('coordinator gate only admits the bridge and safe discovery calls',()=>{
 for(const operation of ['agent_bus.overview','agent_bus.dispatch','agent_bus.requests','agent_bus.reply','agent_bus.create','agent_bus.creation_status','agent_bus.connections','agent_bus.set_connection','help','models.list'])assert.equal(coordinatorToolGate({toolName:'umeko_desktop',input:{operation}}),undefined);
 for(const operation of ['batch','sessions.send','widgets.call','appearance.fontScale','providers.save','jobs.get'])assert.equal(coordinatorToolGate({toolName:'umeko_desktop',input:{operation}}).block,true);
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
