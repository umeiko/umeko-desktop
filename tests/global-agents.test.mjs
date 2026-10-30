import test from 'node:test';
import assert from 'node:assert/strict';
import {coordinatorToolGate,coordinatorExtension} from '../runtime/umeko-control.mjs';
test('coordinator gate only admits the bridge and safe discovery calls',()=>{
 for(const operation of ['agent_bus.overview','agent_bus.dispatch','agent_bus.requests','agent_bus.reply','agent_bus.create','agent_bus.creation_status','agent_bus.connections','agent_bus.set_connection','help','models.list'])assert.equal(coordinatorToolGate({toolName:'umeko_desktop',input:{operation}}),undefined);
 for(const operation of ['batch','sessions.send','widgets.call','appearance.fontScale','providers.save','jobs.get'])assert.equal(coordinatorToolGate({toolName:'umeko_desktop',input:{operation}}).block,true);
 for(const toolName of ['bash','write','read','codemode','tool_search','run_pi_command','subagent'])assert.equal(coordinatorToolGate({toolName,input:{operation:'agent_bus.overview'}}).block,true);
});
test('the mandatory extension installs a pre-execution gate',()=>{
 const hooks=[];coordinatorExtension({on:(name,fn)=>hooks.push([name,fn])});assert.equal(hooks.length,1);assert.equal(hooks[0][0],'tool_call');assert.equal(hooks[0][1]({toolName:'bash'}).block,true);
});
