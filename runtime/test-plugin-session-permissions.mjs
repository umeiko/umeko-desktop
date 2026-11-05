import assert from 'node:assert/strict';
import test from 'node:test';
import {childPermissionPolicy, createToolPermissionExtension} from './tool-permissions.mjs';

function fixture(policy, approved = false) {
  let handler;
  const confirmations = [];
  const pi = {
    on(name, callback) { assert.equal(name, 'tool_call'); handler = callback; },
    getAllTools() { return [{name: 'custom_read', annotations: {readOnlyHint: true}}]; },
  };
  createToolPermissionExtension({getPolicy: () => policy})(pi);
  const context = {cwd: process.cwd(), hasUI: true,
    ui: {confirm: async (...args) => { confirmations.push(args); return approved; }}};
  return {call: event => handler(event, context), confirmations};
}

test('the desktop list blocks read, administration and readOnly tools before shortcuts', async () => {
  const check = fixture({mode: 'auto', allowedTools: []});
  for (const toolName of ['read', 'grep', 'find', 'ls', 'umeko_desktop', 'pi', 'pi_commands', 'custom_read']) {
    const result = await check.call({toolName, input: {}, annotations: {readOnlyHint: true}});
    assert.equal(result.block, true, toolName);
    assert.match(result.reason, /desktop plugin session profile/);
  }
  assert.equal(check.confirmations.length, 0);
});

test('children retain the exact parent ceiling and ordinary ask policy without dangerous approval', async () => {
  const parent = {mode: 'ask', allowedTools: ['read'], dangerousAllowed: true, language: 'en'};
  const child = childPermissionPolicy(parent);
  assert.deepEqual(child.allowedTools, ['read']);
  assert.equal(child.mode, 'ask');
  assert.equal(Object.hasOwn(child, 'dangerousAllowed'), false);
  const check = fixture(child);
  assert.equal(await check.call({toolName: 'read', input: {path: 'fixture.txt'}}), undefined);
  assert.equal((await check.call({toolName: 'write', input: {path: 'fixture.txt'}})).block, true);
  assert.equal(check.confirmations.length, 0);
});

test('an allowed write still uses the normal confirm decision', async () => {
  for (const approved of [false, true]) {
    const check = fixture({mode: 'ask', allowedTools: ['write']}, approved);
    const result = await check.call({toolName: 'write', input: {path: 'plugin-fixture.txt', content: 'fixture'}});
    assert.equal(check.confirmations.length, 1);
    if (approved) assert.equal(result, undefined);
    else {
      assert.equal(result.block, true);
      assert.match(result.reason, /User denied/);
    }
  }
});

test('the execution gate reads the current ceiling on every call', async () => {
  const policy = {mode: 'auto', allowedTools: ['read', 'write']};
  const check = fixture(policy);
  assert.equal(await check.call({toolName: 'write', input: {path: 'plugin-fixture.txt'}}), undefined);
  policy.allowedTools = ['read'];
  assert.equal((await check.call({toolName: 'write', input: {path: 'plugin-fixture.txt'}})).block, true);
});
