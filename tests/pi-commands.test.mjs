import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { commandWords, addMcpFromInput, createPiCommandController } from '../runtime/releases/coding-1.3.0/pi-commands.mjs';

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
