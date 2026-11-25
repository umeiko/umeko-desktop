import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createUmekoControl, umekoHelp, UMEKO_PROMPT } from '../runtime/releases/coding-1.5.2/umeko-control.mjs';

test('the desktop tool routes environment refresh and command rules locally', async () => {
  let desktop;
  const control = createUmekoControl({
    emit() { assert.fail('Both operations belong to the bridge'); },
    refreshShellEnvironment: ctx => ({session: ctx.sessionManager.getSessionId()}),
    getCommandRulesContext: () => ({}),
  });
  control.extension({ registerTool: tool => { desktop = tool; }, registerCommand() {} });
  const ctx = {sessionManager: {getSessionId: () => 'test-session'}};
  const call = async operation => JSON.parse((await desktop.execute('test', {operation}, undefined, undefined, ctx)).content[0].text);
  assert.deepEqual(await call('shell.refreshEnvironment'), {ok: true, session: 'test-session'});
  assert.deepEqual(await call('command_rules.list'), {ok: true, operation: 'command_rules.list', rules: []});
});

test('pi.run is session-local, validates arguments and rechecks access at execution', async () => {
  let tool, allowed = true;
  const context = {}, signal = new AbortController().signal;
  const control = createUmekoControl({ emit() { assert.fail('pi.run must stay in the embedded runtime'); } });
  control.extension({ registerTool: value => { tool = value; }, registerCommand() {} }, {
    canRunPiCommand: () => allowed,
    runPiCommand: async (command, options, caller) => {
      assert.equal(command, '/reload');
      assert.deepEqual(options, { signal, toolCallId: 'call', scope: 'project' });
      assert.equal(caller, context);
      return { status: 'queued' };
    },
  });
  const call = arguments_ => tool.execute('call', { operation: 'pi.run', arguments: arguments_ }, signal, undefined, context);
  const queued = await call({ command: '/reload', scope: 'project' });
  assert.deepEqual(JSON.parse(queued.content[0].text), { ok: true, status: 'queued' });
  assert.equal((await call({ command: '/reload', scope: 'foreign' })).isError, true);
  assert.equal((await call({ command: '/reload', sessionId: 'another-chat' })).isError, true);
  allowed = false;
  assert.match((await call({ command: '/reload' })).content[0].text, /disabled in this session/);
  assert.equal(JSON.parse((await tool.execute('help', { operation: 'help' })).content[0].text).ok, true);
});

test('one desktop tool and a directory-only help keep management instructions on demand', async () => {
  const tools = [], commands = [], control = createUmekoControl({ emit() { throw new Error('help must be local'); } });
  control.extension({ registerTool: tool => tools.push(tool), registerCommand: (name, body) => commands.push({ name, body }) });
  assert.deepEqual(tools.map(tool => tool.name), ['umeko_desktop']);
  assert.deepEqual(commands.map(command => command.name), ['help']);
  const result = await tools[0].execute('help', { operation: 'help' });
  const help = JSON.parse(result.content[0].text);
  assert.ok(existsSync(help.entry)); assert.ok(existsSync(help.docsRoot));
  assert.equal(Object.hasOwn(help, 'commands'), false);
  assert.match(UMEKO_PROMPT, /Pi provider configuration does not apply/);
  assert.match(UMEKO_PROMPT, /umeko-desk.*临时文件.*\.\/\.umeko/);
  for (const text of [UMEKO_PROMPT, tools[0].description]) {
    assert.doesNotMatch(text, /agent_bus|global.subagent|coordinator|requestKey/i);
    assert.match(text, /widgets\.docs/);
  }
  assert.equal(help.topics.agents, 'global-agents.md');
  assert.ok(readFileSync(help.entry, 'utf8').includes('providers.md'));
});

test('desktop requests correlate out-of-order replies and retain explicit failures', async () => {
  const emitted = [], control = createUmekoControl({ emit: event => emitted.push(event) });
  const first = control.request('providers.list'), second = control.request('themes.select', { id: 'dark' });
  assert.equal(emitted.length, 2); assert.notEqual(emitted[0].id, emitted[1].id);
  control.response({ id: emitted[1].id, result: { ok: false, error: 'not allowed' } });
  control.response({ id: emitted[0].id, result: { ok: true, providers: [] } });
  assert.deepEqual(await first, { ok: true, providers: [] });
  assert.equal((await second).ok, false);
  control.response({ id: emitted[0].id, result: { ok: true } });
});

test('Widget help queries the live desktop and the public tool keeps one name',async()=>{
  const events=[],control=createUmekoControl({emit:event=>events.push(event)});
  assert.equal(umekoHelp().topics.provider,'provider-plugins.md');
  assert.equal(umekoHelp().topics.widget,'widget-plugins.md');
  const result=control.request('help',{topic:'widget'});
  assert.equal(events[0].operation,'help');assert.equal(events[0].arguments.topic,'widget');
  control.response({id:events[0].id,result:{ok:true,activeWidgets:[{id:'file-tree',summary:'browse files',document:'AGENT.md'}]}});
  assert.equal((await result).activeWidgets[0].id,'file-tree');
  assert.match(UMEKO_PROMPT,/widgets\.docs/);assert.match(UMEKO_PROMPT,/umeko_desktop/);
});

test('cancel, timeout and shutdown release outstanding desktop requests', async () => {
  const controller = new AbortController();
  const control = createUmekoControl({ emit() {}, timeoutMs: 30 });
  const aborted = control.request('settings.get', {}, controller.signal);
  controller.abort(); await assert.rejects(aborted, /cancelled/);
  await assert.rejects(control.request('status.get'), /did not acknowledge/);
  const closed = control.request('themes.list'); control.clear();
  await assert.rejects(closed, /connection closed/);
});
