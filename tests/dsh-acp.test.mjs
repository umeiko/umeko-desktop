import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFile } from 'node:child_process';
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
    bridge.respond({ id: event.id, value });
    assert.deepEqual(await pending, { outcome: { outcome: 'selected', optionId: value ? 'offered-allow' : 'offered-reject' } });
  }
});
