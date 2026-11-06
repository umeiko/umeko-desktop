import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFile, spawn } from 'node:child_process';
import { promisify } from 'node:util';
import { DshAcpBridge, projectTool, advertisedModelValue, resolveSdkEntry } from '../runtime/dsh-acp-bridge.mjs';

const runtime = fileURLToPath(new URL('./fixtures/fake-acp.mjs', import.meta.url));
async function setup(t, onEvent = () => {}) {
  const home = await mkdtemp(join(tmpdir(), 'umeko-acp-test-'));
  const events = [];
  const bridge = new DshAcpBridge({ emit: event => { events.push(event); onEvent(event, bridge); } });
  t.after(async () => { await bridge.shutdown(); await rm(home, { recursive: true, force: true }); });
  return { bridge, events, spec: { runtime, home, workspace: home, action: 'open' } };
}

test('own-config inherits native home and overlays without replacing initial model or reasoning', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'umeko-own-acp-test-'));
  const nativeRuntime = join(directory, 'native-acp.mjs');
  await writeFile(nativeRuntime, `
    import { createInterface } from 'node:readline';
    let model = 'native:custom-model', effort = 'native:default';
    const options = () => [
      { id: 'model', name: 'Model', type: 'select', currentValue: model,
        options: [{ name: 'Native model', value: 'native:custom-model' }, { name: 'Other native model', value: 'native:other-model' }] },
      { id: 'reasoning_effort', name: 'Reasoning', type: 'select', currentValue: effort,
        options: [{ name: 'Native default', value: 'native:default' }, { name: 'High', value: 'high' }] },
    ];
    createInterface({ input: process.stdin }).on('line', line => {
      const message = JSON.parse(line);
      let result;
      if (message.method === 'initialize') result = { protocolVersion: 1, agentCapabilities: {}, authMethods: [] };
      else if (message.method === 'session/new') result = { sessionId: 'own-session', configOptions: options() };
      else if (message.method === 'session/set_config_option') {
        if (message.params.configId === 'model') model = message.params.value;
        if (message.params.configId === 'reasoning_effort') effort = message.params.value;
        result = { configOptions: options() };
      } else result = {};
      if (message.id !== undefined) process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: message.id, result }) + '\\n');
    });
  `);
  const environment = { ...process.env, DSH_HOME: join(directory, 'native-home'),
    HOME: join(directory, 'native-os-home'), USERPROFILE: join(directory, 'native-user-profile') };
  const overlays = [join(directory, 'policy.yml'), join(directory, 'session-root.yml')];
  const launches = [], events = [];
  const bridge = new DshAcpBridge({ env: environment, emit: event => events.push(event),
    spawnProcess: (command, args, options) => {
      launches.push({ command, args, options });
      return spawn(command, args, options);
    } });
  t.after(async () => { await bridge.shutdown(); await rm(directory, { recursive: true, force: true }); });
  const writes = [];
  const setConfig = bridge.setConfig.bind(bridge);
  bridge.setConfig = (config, emit) => { writes.push(config); return setConfig(config, emit); };
  await bridge.start({ runtime: nativeRuntime, workspace: directory, useOwnConfig: true,
    patchFiles: overlays, model: { provider: 'umeko', id: 'must-not-select' }, reasoningEffort: 'high', action: 'open' });
  assert.deepEqual(launches[0].args, [nativeRuntime, '--profile', 'acp', '--patch', overlays[0], '--patch', overlays[1]]);
  assert.deepEqual(launches[0].options.env, environment);
  assert.notEqual(launches[0].options.env, environment);
  assert.equal(launches[0].options.windowsHide, true);
  assert.deepEqual(writes, []);
  const native = events.find(event => event.type === 'dsh_session').configOptions;
  assert.equal(native[0].currentValue, 'native:custom-model');
  assert.equal(native[0].options[0].name, 'Native model');
  assert.equal(native[1].currentValue, 'native:default');
  await bridge.setConfig({ configId: 'model', value: 'native:other-model' });
  await bridge.setConfig({ configId: 'reasoning_effort', value: 'high' });
  assert.equal(bridge.configOptions[0].currentValue, 'native:other-model');
  assert.equal(bridge.configOptions[1].currentValue, 'high');
});

test('own-config default remains managed and requires its home', async t => {
  const { bridge, spec } = await setup(t);
  await assert.rejects(bridge.connect({ runtime, workspace: spec.workspace }), /独立目录/);
  const environment = { ...process.env, DSH_HOME: 'inherited-home', HOME: 'inherited-os-home', USERPROFILE: 'inherited-user-profile' };
  bridge.env = environment;
  let launch;
  bridge.spawnProcess = (command, args, options) => {
    launch = { command, args, options };
    return spawn(command, args, options);
  };
  await bridge.start(spec);
  assert.equal(launch.options.env.DSH_HOME, resolve(spec.home));
  assert.equal(launch.options.env.HOME, environment.HOME);
  assert.equal(launch.options.env.USERPROFILE, environment.USERPROFILE);
  assert.equal(launch.options.windowsHide, true);
  assert.equal(bridge.configOptions[0].currentValue, 'opaque:model:first');
});

test('ACP lifecycle projects text, thoughts, merged tools, usage and opaque config', async t => {
  const { bridge, events, spec } = await setup(t);
  await bridge.start(spec);
  assert.equal(events[0].type, 'dsh_session');
  assert.equal(events[1].type, 'dsh_ready');
  await bridge.prompt('hello');
  assert.ok(events.some(event => event.type === 'delta' && event.text === 'hello'));
  assert.ok(events.some(event => event.type === 'thinking_delta' && event.text === 'thinking'));
  assert.deepEqual(events.find(event => event.type === 'tool' && event.state === 'done'), { type: 'tool', id: 'read-1', name: 'read', args: { path: 'input.txt' }, state: 'done', result: 'file content' });
  assert.deepEqual(events.find(event => event.type === 'context_usage').usage, { tokens: 25, contextWindow: 100, percent: 25 });
  await bridge.setConfig({ configId: 'model', value: 'opaque:model:second' });
  assert.equal(events.at(-1).configOptions[0].currentValue, 'opaque:model:second');
  assert.equal(events.find(event => event.type === 'dsh_done').stopReason, 'end_turn');
});

test('permission UI selects only offered one-shot choices', async t => {
  const { bridge, events, spec } = await setup(t, (event, instance) => {
    if (event.type === 'ui_request') instance.respond({ id: event.id, value: false });
  });
  await bridge.start(spec);
  await bridge.prompt('permission');
  assert.ok(events.some(event => event.type === 'delta' && event.text === 'permission:deny'));
  let response;
  const pending = bridge.permission({ toolCall: {}, options: [{ optionId: 'always', kind: 'allow_always' }] });
  const id = [...bridge.permissions.keys()][0];
  bridge.respond({ id, value: true });
  response = await pending;
  assert.deepEqual(response, { outcome: { outcome: 'cancelled' } });
});

test('cancel settles active prompt and clears unresolved permissions', async t => {
  const { bridge, events, spec } = await setup(t);
  await bridge.start(spec);
  const pending = bridge.prompt('wait');
  await assert.rejects(bridge.prompt('concurrent'), /上一条/);
  const permission = bridge.permission({ toolCall: {}, options: [] });
  await bridge.cancel();
  await pending;
  assert.deepEqual(await permission, { outcome: { outcome: 'cancelled' } });
  assert.equal(events.at(-1).stopReason, 'cancelled');
});

test('reopening passes stored session id through resume', async t => {
  const { bridge, events, spec } = await setup(t);
  await bridge.start({ ...spec, sessionId: 'saved-session' });
  assert.equal(events[0].sessionId, 'saved-session');
  await bridge.prompt('after resume');
  assert.ok(events.some(event => event.type === 'delta' && event.text === 'after resume'));
});

test('host interruption is a separate standard block before unchanged user text', async t => {
  const { bridge, events, spec } = await setup(t);
  await bridge.start(spec);
  const notice = '[The user stopped the previous request]';
  await bridge.prompt('prompt-blocks', [], notice);
  assert.deepEqual(JSON.parse(events.find(event => event.type === 'delta').text), [
    { type: 'text', text: notice + '\n\n' }, { type: 'text', text: 'prompt-blocks' },
  ]);
  events.length = 0;
  await bridge.prompt('prompt-blocks');
  assert.deepEqual(JSON.parse(events.find(event => event.type === 'delta').text), [
    { type: 'text', text: 'prompt-blocks' },
  ]);
});

test('partial tool failure keeps original arguments and name', () => {
  const { event } = projectTool({ toolCallId: 'x', title: 'write', rawInput: { path: 'x' } }, { toolCallId: 'x', status: 'failed', rawOutput: 'denied' });
  assert.deepEqual(event, { type: 'tool', id: 'x', name: 'write', args: { path: 'x' }, state: 'error', result: 'denied' });
});

test('model lookup returns an advertised grouped value without manufacturing a choice', () => {
  const value = '["umeko","deepseek-custom"]';
  const choices = [{ id: 'model', options: [{ group: 'umeko', name: 'Umeko', options: [{ name: 'DeepSeek', value }] }] }];
  assert.equal(advertisedModelValue(choices, { provider: 'umeko', id: 'deepseek-custom' }), value);
  assert.equal(advertisedModelValue(choices, { provider: 'umeko', id: 'unknown' }), undefined);
});

test('health CLI emits one initialize result then closes the child', async t => {
  const { spec } = await setup(t);
  const bridgePath = fileURLToPath(new URL('../runtime/dsh-acp-bridge.mjs', import.meta.url));
  const { stdout, stderr } = await promisify(execFile)(process.execPath, [bridgePath, '--health', '--dsh-bin', runtime, '--dsh-home', spec.home], { windowsHide: true, timeout: 10000 });
  const lines = stdout.trim().split('\n').map(line => JSON.parse(line));
  assert.equal(lines.length, 1);
  assert.equal(lines[0].type, 'health');
  assert.equal(lines[0].ok, true);
  assert.equal(lines[0].result.agentInfo.name, 'fake-dsh');
  assert.equal(stderr, '');
});

test('failed initialization emits a terminal event and waits for child exit', async t => {
  const { bridge, events, spec } = await setup(t);
  bridge.env = { ...bridge.env, FAKE_ACP_INITIALIZE_FAILURE: '1' };
  await assert.rejects(bridge.start(spec));
  assert.equal(bridge.busy, false);
  assert.equal(bridge.exitObserved, true);
  assert.equal(events.filter(event => event.type === 'dsh_done').length, 1);
  assert.equal(events.at(-1).stopReason, 'error');
  assert.ok(events.some(event => event.type === 'error' && event.message.includes('启动会话失败')));
});

test('cancel during initialize prevents the initial prompt from starting', async t => {
  const { bridge, events, spec } = await setup(t);
  bridge.env = { ...bridge.env, FAKE_ACP_INITIALIZE_DELAY: '30' };
  const starting = bridge.start({ ...spec, action: 'prompt', text: 'must not send' });
  await bridge.cancel();
  await starting;
  assert.equal(events.at(-1).stopReason, 'cancelled');
  assert.equal(events.some(event => event.type === 'delta'), false);
});

test('adjacent configuration controls settle before the following prompt', async t => {
  const { bridge, events, spec } = await setup(t);
  await bridge.start(spec);
  const first = bridge.setConfig({ configId: 'model', value: 'opaque:model:second' });
  const second = bridge.setConfig({ configId: 'model', value: 'opaque:model:first' });
  await bridge.prompt('model-state');
  await Promise.all([first, second]);
  assert.equal(events.filter(event => event.type === 'dsh_config').length, 2);
  assert.ok(events.some(event => event.type === 'delta' && event.text === 'opaque:model:first'));
});

test('child crash terminates the active prompt and clears busy state', async t => {
  const { bridge, events, spec } = await setup(t);
  await bridge.start(spec);
  await assert.rejects(bridge.prompt('crash'));
  assert.equal(bridge.busy, false);
  assert.equal(events.at(-1).stopReason, 'error');
  assert.equal(events.filter(event => event.type === 'dsh_done' && event.stopReason === 'error').length, 1);
});

test('packaged runtime resolves SDK from its prepared release dependency tree', async t => {
  const home = await mkdtemp(join(tmpdir(), 'umeko-acp-packaged-'));
  t.after(() => rm(home, { recursive: true, force: true }));
  const sdk = join(home, 'runtime', 'releases', 'coding-1.3.0', 'node_modules', '@agentclientprotocol', 'sdk');
  await mkdir(sdk, { recursive: true });
  await writeFile(join(sdk, 'package.json'), JSON.stringify({ name: '@agentclientprotocol/sdk', type: 'module', exports: './acp.js' }));
  await writeFile(join(sdk, 'acp.js'), 'export {};\n');
  assert.equal(resolveSdkEntry(join(home, 'runtime')), join(sdk, 'acp.js'));
});

test('permission-partial preserves cached tool details, explanations and one-shot choices', async () => {
  const events = [];
  const bridge = new DshAcpBridge({ emit: event => events.push(event) });
  bridge.tools.set('write-notes', {
    toolCallId: 'write-notes', title: 'Write notes file', rawInput: { path: 'out/notes.txt', content: 'notes' },
    content: [{ type: 'content', content: { type: 'text', text: 'Cached write explanation' } }],
  });
  const options = [{ optionId: 'offered-allow', name: 'Allow once', kind: 'allow_once' }, { optionId: 'offered-reject', name: 'Reject once', kind: 'reject_once' }];
  for (const value of [true, false]) {
    const pending = bridge.permission({
      sessionId: 'session',
      toolCall: { toolCallId: 'write-notes', title: '  ', rawInput: null,
        ...(value ? { content: [{ type: 'content', content: { type: 'text', text: 'Permission-specific write explanation' } }] } : {}) },
      options,
    });
    const event = events.at(-1);
    assert.equal(event.toolCallId, 'write-notes');
    assert.equal(event.backend, 'dsh');
    assert.equal(event.options, options);
    assert.match(event.detail, /Write notes file/);
    assert.match(event.detail, /out\/notes\.txt/);
    assert.match(event.detail, value ? /Permission-specific write explanation/ : /Cached write explanation/);
    // Structured copies for the readable dialog mirror what detail already carries.
    assert.equal(event.toolTitle, 'Write notes file');
    assert.deepEqual(event.rawInput, { path: 'out/notes.txt', content: 'notes' });
    assert.equal(event.toolContent, value ? 'Permission-specific write explanation' : 'Cached write explanation');
    bridge.respond({ id: event.id, value });
    assert.deepEqual(await pending, { outcome: { outcome: 'selected', optionId: value ? 'offered-allow' : 'offered-reject' } });
  }
});

test('permissions use private IPC for live mode changes without restarting ACP', async t => {
  const { bridge, events, spec } = await setup(t);
  await bridge.start({ ...spec, permissionMode: 'auto' });
  const pid = bridge.child.pid;
  await bridge.setPermissionMode('ask');
  await bridge.prompt('permission-mode');
  assert.ok(events.some(event => event.type === 'delta' && event.text === 'ask'));
  const pending = bridge.prompt('wait');
  await bridge.setPermissionMode('auto');
  await bridge.cancel();
  await pending;
  assert.equal(bridge.child.pid, pid);
  events.length = 0;
  await bridge.prompt('permission-mode');
  assert.ok(events.some(event => event.type === 'delta' && event.text === 'auto'));
  assert.equal(events.some(event => event.type === 'error'), false);
});

test('permissions changed during startup apply before the first prompt', async t => {
  const { bridge, events, spec } = await setup(t);
  bridge.env = { ...bridge.env, FAKE_ACP_INITIALIZE_DELAY: '30' };
  const starting = bridge.start({ ...spec, permissionMode: 'auto' });
  await bridge.setPermissionMode('ask');
  await starting;
  await bridge.prompt('permission-mode');
  assert.ok(events.some(event => event.type === 'delta' && event.text === 'ask'));
});

test('permissions failure closes the child instead of running under a stale policy', async t => {
  const { bridge, events, spec } = await setup(t);
  bridge.env = { ...bridge.env, FAKE_ACP_PERMISSION_FAILURE: '1' };
  await assert.rejects(bridge.start({ ...spec, permissionMode: 'ask' }));
  assert.equal(bridge.closing, true);
  assert.equal(bridge.exitObserved, true);
  assert.equal(events.filter(event => event.type === 'dsh_done').length, 1);
  assert.ok(events.some(event => event.type === 'error' && event.message.includes('权限同步失败')));
  assert.equal(events.some(event => event.type === 'delta'), false);
});
