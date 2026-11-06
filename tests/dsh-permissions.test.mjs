import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { apply, inject, needsToolApproval, hasNativeEscalation, toolPermissionDecision, installPermissionModeChannel } from '../runtime/dsh-permissions.mjs';

const exec = (name, args = {}) => ({ name, arguments: args, callId: 'call', agent: { session: { id: 'session' } } });

test('ask gates core mutation and shell tools while auto leaves native policy', () => {
  for (const name of ['write', 'edit', 'apply_patch', 'pwsh', 'bash', 'shell']) {
    assert.equal(toolPermissionDecision('ask', exec(name), undefined, 'workspace-write').kind, 'ask');
    assert.equal(toolPermissionDecision('auto', exec(name), undefined, 'workspace-write').kind, 'allow');
  }
  for (const name of ['read', 'read_image', 'grep', 'glob', 'find', 'ls', 'search', 'list_directory']) {
    assert.equal(needsToolApproval(name), false);
    assert.equal(toolPermissionDecision('ask', exec(name), undefined, 'workspace-write').kind, 'allow');
  }
});

test('only affirmative mutation annotations extend the core classification', () => {
  assert.equal(needsToolApproval('custom_tool'), false);
  assert.equal(needsToolApproval('custom_tool', { annotations: { readOnlyHint: true } }), false);
  assert.equal(needsToolApproval('custom_tool', { annotations: { readOnlyHint: false } }), true);
  assert.equal(needsToolApproval('custom_tool', { annotations: { destructiveHint: true } }), true);
  assert.equal(needsToolApproval('read', { annotations: { destructiveHint: true } }), false);
});

test('valid strictly wider native escalation receives exactly the native approval gate', () => {
  for (const name of ['write', 'edit', 'apply_patch', 'pwsh', 'bash', 'shell']) {
    const request = exec(name, { sandbox_permissions: 'danger-full-access', justification: 'Requested write outside authorized roots' });
    assert.equal(hasNativeEscalation(request, 'workspace-write'), true);
    assert.equal(toolPermissionDecision('ask', request, undefined, 'workspace-write').kind, 'allow');
  }
  assert.equal(hasNativeEscalation(exec('write', { sandbox_permissions: 'workspace-write', justification: 'same mode' }), 'workspace-write'), false);
  assert.equal(hasNativeEscalation(exec('write', { sandbox_permissions: 'danger-full-access', justification: ' ' }), 'workspace-write'), false);
  assert.equal(hasNativeEscalation(exec('custom_tool', { sandbox_permissions: 'danger-full-access', justification: 'not a native tool' }), 'workspace-write'), false);
});

test('pre-existing deny, cancel and ask decisions survive unchanged', () => {
  for (const previous of [{ kind: 'deny', reason: 'other policy' }, { kind: 'cancel' }, { kind: 'ask', reason: 'another approval' }]) {
    assert.equal(toolPermissionDecision('ask', exec('write'), undefined, 'workspace-write', previous), previous);
  }
});

test('IPC applies mode before acknowledgment, rejects invalid values and removes listeners', () => {
  const host = new EventEmitter(), sent = [];
  let mode = 'auto', unreferenced = false;
  host.connected = true;
  host.channel = { unref() { unreferenced = true; } };
  host.send = message => sent.push(message);
  const dispose = installPermissionModeChannel(host, () => mode, value => { mode = value; });
  host.emit('message', { type: 'umeko_tool_permission_mode', id: 'switch', value: 'ask' });
  assert.equal(mode, 'ask');
  assert.deepEqual(sent[0], { type: 'umeko_tool_permission_mode_applied', id: 'switch', mode: 'ask' });
  host.emit('message', { type: 'umeko_tool_permission_mode', id: 'invalid', value: 'full-access' });
  assert.equal(mode, 'ask');
  assert.equal(sent[1].error, 'unsupported_permission_mode');
  assert.equal(unreferenced, true);
  dispose();
  assert.equal(host.listenerCount('message'), 0);
});

test('official hook reads latest IPC mode after other pre-execute policies settle', async () => {
  const handlers = new Map(), disposers = [];
  const ctx = {
    tools: { get: () => undefined }, sandboxPolicy: { resolve: () => ({ mode: 'workspace-write' }) },
    permissionPresets: { set: () => {} },
    on: (event, handler) => handlers.set(event, handler), effect: setup => disposers.push(setup()),
  };
  assert.deepEqual(inject, ['tools', 'approval', 'sandboxPolicy', 'permissionPresets']);
  apply(ctx, { mode: 'auto' });
  try {
    const decide = handlers.get('tools/pre-execute');
    let release;
    const pending = decide(exec('write'), () => new Promise(resolve => { release = resolve; }));
    process.emit('message', { type: 'umeko_tool_permission_mode', id: 'live', value: 'ask' });
    release({ kind: 'allow' });
    assert.equal((await pending).kind, 'ask');
    process.emit('message', { type: 'umeko_tool_permission_mode', id: 'live2', value: 'auto' });
    assert.equal((await decide(exec('write'), async () => ({ kind: 'allow' }))).kind, 'allow');
  } finally { for (const dispose of disposers) dispose(); }
});

test('created and resumed agents align their standing preset before first tool admission', async () => {
  const handlers = new Map(), disposers = [], changed = [];
  const session = { id: 'resumed', savedMode: 'read-only' };
  const ctx = {
    tools: { get: () => undefined },
    sandboxPolicy: { resolve: () => ({ mode: session.savedMode }) },
    permissionPresets: { set: (target, preset) => { changed.push({ target, preset }); session.savedMode = preset; } },
    on: (event, handler) => handlers.set(event, handler), effect: setup => disposers.push(setup()),
  };
  apply(ctx, { mode: 'auto' });
  try {
    await handlers.get('agent/created')({ agent: { session }, source: 'resume' });
    assert.equal(changed[0].target, session);
    assert.equal(changed[0].preset, 'workspace-write');
    assert.equal(session.savedMode, 'workspace-write');
    assert.equal((await handlers.get('tools/pre-execute')({ ...exec('write'), agent: { session } }, async () => ({ kind: 'allow' }))).kind, 'allow');
  } finally { for (const dispose of disposers) dispose(); }
});
