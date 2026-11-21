import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { commandWords, addMcpFromInput, createPiCommandController } from '../runtime/releases/coding-1.5.2/pi-commands.mjs';

test('Pi command tokenizer preserves quoted literals and never evaluates a shell', () => {
  assert.deepEqual(commandWords('pi mcp add test --env "KEY=${TOKEN}" -- node "a file.mjs"'), ['pi','mcp','add','test','--env','KEY=${TOKEN}','--','node','a file.mjs']);
  assert.deepEqual(commandWords('pi install "C:\\work\\package"'), ['pi','install','C:\\work\\package']);
  for (const command of ['pi list; echo nope', 'pi list | cat', 'pi list\npi install bad', 'pi install $(touch bad)', 'pi install "broken']) assert.throws(() => commandWords(command));
});

test('MCP command and JSON additions use the selected native scope and preserve existing servers', async () => {
  const root = mkdtempSync(join(tmpdir(),'umeko-mcp-add-'));
  const cwd = join(root,'project'), agentDir = join(root,'agent');
  mkdirSync(cwd);mkdirSync(agentDir);
  try {
    writeFileSync(join(agentDir,'mcp.json'), JSON.stringify({ autoEnableCodemode:false, mcpServers:{ previous:{url:'https://previous.invalid/mcp'} } }));
    await addMcpFromInput({cwd,agentDir,local:false,text:'pi mcp add added --local --url https://new.invalid/mcp'});
    let config = JSON.parse(readFileSync(join(agentDir,'mcp.json')));
    assert.equal(config.mcpServers.added.url,'https://new.invalid/mcp');
    assert.ok(config.mcpServers.previous);assert.equal(config.autoEnableCodemode,false);
    assert.equal(existsSync(join(cwd,'.pi/mcp.json')),false);
    await addMcpFromInput({cwd,agentDir,local:true,text:'pi mcp add tools -- node "file with space.mjs" --local'});
    config=JSON.parse(readFileSync(join(cwd,'.pi/mcp.json')));
    assert.deepEqual(config.mcpServers.tools.args,['file with space.mjs','--local']);
    await addMcpFromInput({cwd,agentDir,local:true,text:JSON.stringify({mcpServers:{another:{url:'https://other.invalid/mcp'}}})});
    const previous=readFileSync(join(cwd,'.pi/mcp.json'),'utf8');
    assert.ok(JSON.parse(previous).mcpServers.tools);
    await assert.rejects(addMcpFromInput({cwd,agentDir,local:true,text:JSON.stringify({mcpServers:{bad:{command:42},good:{url:'https://good.invalid'}}})}));
    assert.equal(readFileSync(join(cwd,'.pi/mcp.json'),'utf8'),previous);
    await assert.rejects(addMcpFromInput({cwd,agentDir,local:false,text:'pi install unrelated'}));
  } finally {rmSync(root,{recursive:true,force:true});}
});

test('reload and compaction requested by a tool wait for the same native session to finish', async () => {
  const calls=[], entries=[], notices=[];
  const session={isIdle:false,sessionManager:{getSessionId:()=> 'current-session',getSessionFile:()=>'/current/history.jsonl',getCwd:()=>'/current/workspace',appendCustomEntry:(kind,data)=>entries.push({kind,data})},extensionRunner:{getRegisteredCommands:()=>[],getCommand:()=>null},getContextUsage:()=>({tokens:42}),compact:async instructions=>{calls.push(['compact',instructions]);return {tokensBefore:42};}};
  const controller=createPiCommandController({getRuntime:()=>({session}),getConfig:()=>({agentDir:'/current/agent'}),reload:async target=>{assert.equal(target,session);calls.push(['reload']);},notify:message=>notices.push(message)});
  const queued=await controller.run('/reload',{toolCallId:'reload-call'});
  assert.equal(queued.status,'queued');assert.equal(queued.sessionId,'current-session');assert.equal(calls.length,0);
  await controller.run('/compact preserve decisions',{toolCallId:'compact-call'});
  session.isIdle=true;await controller.flush();
  assert.deepEqual(calls,[['reload'],['compact','preserve decisions']]);
  assert.equal(entries.length,2);assert.ok(entries.every(e=>e.data.status==='completed'));
  assert.equal(notices.length,2);
  assert.equal((await controller.run('/session')).workspace,'/current/workspace');
  await assert.rejects(controller.run('/imaginary-command'));
});

test('queued commands are cancelled and never applied to a different session', async () => {
  let id='first', calls=0;
  const session={isIdle:false,sessionManager:{getSessionId:()=>id,getCwd:()=>'/workspace',getSessionFile:()=>'/history'},extensionRunner:{getCommand:()=>null}};
  const controller=createPiCommandController({getRuntime:()=>({session}),getConfig:()=>({agentDir:'/agent'}),reload:async()=>calls++,notify:()=>{}});
  await controller.run('/reload');controller.clear();await controller.flush();assert.equal(calls,0);
  await controller.run('/reload');id='second';await controller.flush();assert.equal(calls,0);
});

// Exercise both public names through the same real dispatcher, never a shell or installer.
import { createUmekoControl } from '../runtime/releases/coding-1.5.2/umeko-control.mjs';
function aliasFixture() {
  const calls=[], entries=[], tools=[];
  let config={agentDir:'/synthetic/agent'}, id='owner';
  const manager={getSessionId:()=>id,getSessionFile:()=>'/synthetic/session',getCwd:()=>'/synthetic/workspace',
    appendCustomEntry:(kind,data)=>entries.push({kind,data})};
  const session={isIdle:true,sessionManager:manager,getAllTools:()=>[{name:'run_pi_command'}],
    getCallableToolNames:()=>['run_pi_command'],
    getContextUsage:()=>({tokens:42}),extensionRunner:{getCommand:()=>null}};
  const controller=createPiCommandController({getRuntime:()=>({session}),getConfig:()=>config,
    reload:async target=>{assert.equal(target,session);calls.push('reload');},notify:()=>{}});
  const control=createUmekoControl({emit:()=>assert.fail('Pi alias must never use desktop RPC'),
    runPiCommand:(...args)=>controller.runTool(...args)});
  const pi={registerTool:tool=>tools.push(tool),registerCommand:()=>{}};
  controller.extension(pi);control.extension(pi);
  const ctx={sessionManager:manager};
  const execute=(name,args,context=ctx,signal,id='fixture-id')=>tools.find(t=>t.name===name).execute(id,
    name==='umeko_desktop'?{operation:'pi.run',arguments:args}:args,signal,undefined,context);
  return {controller,session,calls,entries,execute,setConfig:value=>{config={agentDir:'/synthetic/agent',...value};},switch:()=>{id='other';}};
}

test('pi.run preserves legacy result, session and tool-call completion identity',async()=>{
 const f=aliasFixture();
 assert.deepEqual(await f.execute('umeko_desktop',{command:'/session'}),await f.execute('run_pi_command',{command:'/session'}));
 f.session.isIdle=false;
 const queued=await f.execute('umeko_desktop',{command:'/reload'});
 assert.equal(queued.details.umekoPiCommand.status,'queued');assert.deepEqual(f.calls,[]);
 f.session.isIdle=true;await f.controller.flush();
 assert.deepEqual(f.calls,['reload']);assert.equal(f.entries[0].data.toolCallId,'fixture-id');
 assert.equal(f.entries[0].data.status,'completed');
});

test('legacy deny, capability and plugin boundaries block both names without resetting config',async()=>{
 for(const config of [
  {blockedTools:['run_pi_command']},
  {piCapabilities:{preset:'custom',custom:{base:'full',tools:{run_pi_command:false}}}},
  {piCapabilities:{preset:'custom',custom:{base:'full',plugins:{'builtin:pi-commands':false}}}},
  {pluginSessionPolicy:{allowedTools:['umeko_desktop']}},
  {globalCoordinator:true},
 ]) {
  const before=JSON.stringify(config),f=aliasFixture();f.setConfig(config);
  for(const name of ['run_pi_command','umeko_desktop'])
   await assert.rejects(f.execute(name,{command:'/reload'}),/disabled/);
  assert.deepEqual(f.calls,[]);assert.equal(JSON.stringify(config),before);
 }
});

test('pi.run cannot inherit missing child capability or target another session',async()=>{
 const f=aliasFixture();
 for(const name of ['run_pi_command','umeko_desktop']) {
  await assert.rejects(f.execute(name,{command:'/reload'},{sessionManager:{getSessionId:()=> 'child'}}),/does not own/);
  await assert.rejects(f.execute(name,{command:'/reload'},{}),/does not own/);
 }
 f.session.getAllTools=()=>[{name:'umeko_desktop'}];
 f.session.getCallableToolNames=()=>['umeko_desktop'];
 await assert.rejects(f.execute('umeko_desktop',{command:'/reload'}),/disabled/);
 assert.deepEqual(f.calls,[]);
});

test('pi.run rejects ambiguous arguments, unknown commands and shell combinations before effects',async()=>{
 const f=aliasFixture();
 for(const args of [undefined,[],{}, {command:'/reload',scope:'elsewhere'},
  {command:'/reload',cwd:'/other'}, {command:'/reload',confirmed:true},
  {command:'/reload',scope:null}, {command:42}, {command:'pi list; echo no'},
  {command:'pi list | cat'}, {command:'pi install $(touch bad)'}, {command:'/unknown'},
  {command:'bash echo no'}]) {
  for(const name of ['run_pi_command','umeko_desktop']) await assert.rejects(f.execute(name,args));
 }
 assert.deepEqual(f.calls,[]);
});

test('queued alias is cancelled, owner checked and denied if legacy capability is revoked',async()=>{
 for(const action of ['clear','switch','deny','inactive']) {
  const f=aliasFixture();f.session.isIdle=false;
  await f.execute('umeko_desktop',{command:'/reload'});
  if(action==='clear')f.controller.clear();
  if(action==='switch')f.switch();
  if(action==='deny')f.setConfig({blockedTools:['run_pi_command']});
  if(action==='inactive')f.session.getCallableToolNames=()=>['umeko_desktop'];
  f.session.isIdle=true;await f.controller.flush();assert.deepEqual(f.calls,[]);
  if(['deny','inactive'].includes(action))assert.equal(f.entries[0].data.status,'failed');
 }
 const f=aliasFixture(),abort=new AbortController();abort.abort();
 await assert.rejects(f.execute('umeko_desktop',{command:'/reload'},undefined,abort.signal),/取消/);
 assert.deepEqual(f.calls,[]);
});

test('unconfigured desktop control fails closed rather than forwarding pi.run',async()=>{
 let tool;const control=createUmekoControl({emit:()=>assert.fail('no fallback')});
 control.extension({registerTool:value=>{tool=value;},registerCommand:()=>{}});
 await assert.rejects(tool.execute('id',{operation:'pi.run',arguments:{command:'/session'}}),/unavailable/);
});


test('registered but inactive legacy direct tool denies either route',async()=>{
 const f=aliasFixture();
 f.session.getCallableToolNames=()=>['umeko_desktop'];
 assert.ok(f.session.getAllTools().some(tool=>tool.name==='run_pi_command'));
 for(const name of ['run_pi_command','umeko_desktop'])
  await assert.rejects(f.execute(name,{command:'/reload'}),/disabled/);
 assert.deepEqual(f.calls,[]);
});

test('duplicate queued commands keep the first receipt without repeating the effect',async()=>{
 for(const [first,second] of [
  ['run_pi_command','umeko_desktop'],['umeko_desktop','run_pi_command'],
 ]) {
  const f=aliasFixture();f.session.isIdle=false;
  for(const [name,id] of [[first,'first-call'],[second,'second-call']])
   assert.equal((await f.execute(name,{command:'/reload'},undefined,undefined,id))
    .details.umekoPiCommand.status,'queued');
  f.session.isIdle=true;
  const reports=await f.controller.flush();
  assert.deepEqual(f.calls,['reload']);assert.equal(reports.length,1);
  assert.deepEqual(f.entries.map(entry=>entry.data.toolCallId),['first-call']);
 }
});
