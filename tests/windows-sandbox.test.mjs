import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { sandboxCommand, sandboxFailure, trackLocalMcpTransport } from '../runtime/windows-sandbox.mjs';

function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'umeko-sandbox-unit-'));
  t.after(() => rmSync(root, { recursive: true }));
  const workspace = join(root, 'workspace');
  const launcher = join(root, 'umeko-sandbox.exe');
  mkdirSync(workspace);
  writeFileSync(launcher, 'fixture; never executed');
  return { workspace, cwd: workspace, file: 'bash.exe', args: ['-c', 'echo "hello"'],
    env: { PATH: 'test' }, policy: { enabled: true, elevated: true, allowNetwork: false,
      home: join(root, 'state'), temp: join(root, 'temp'), launcher } };
}

test('off preserves the original executable, argv and environment', t => {
  const input = fixture(t);
  const { file, args, env } = input;
  assert.deepEqual(sandboxCommand({ ...input, policy: { enabled: false } }, { platform: 'win32' }),
    { file, args, env, level: 'off' });
  assert.deepEqual(sandboxCommand(input, { platform: 'linux' }), { file, args, env, level: 'off' });
});

test('enabled wraps argv without evaluating shell text and rejects paths outside the workspace', t => {
  const input = fixture(t);
  const options = { platform: 'win32' };
  const launch = sandboxCommand(input, options);
  assert.equal(launch.file, input.policy.launcher);
  assert.deepEqual(launch.args.slice(-4), ['block', input.file, ...input.args]);
  assert.equal(launch.level, 'elevated');
  assert.throws(() => sandboxCommand({ ...input, cwd: '..' }, options), /inside the current workspace/);
  assert.throws(() => sandboxCommand({ ...input, file: 'wsl.exe' }, options), /use Git Bash/);
  input.policy.launcher += '.missing';
  assert.throws(() => sandboxCommand(input, options), /launcher is missing/);
});

test('standard-user profile runs with file isolation and reports network fallback', t => {
  const input = fixture(t);
  const options = { platform: 'win32' };
  input.policy.elevated = false;
  const fallback = sandboxCommand(input, options);
  assert.equal(fallback.level, 'non-elevated');
  assert.equal(fallback.allowNetwork, true);
  assert.deepEqual(fallback.args.slice(-4), ['allow', input.file, ...input.args]);
  assert.match(fallback.notice, /Network blocking is not active until you complete administrator setup/);
  assert.doesNotMatch(sandboxFailure(fallback.level, fallback.allowNetwork, 'failed to connect'), /network access was blocked/i);
  input.policy.allowNetwork = true;
  assert.equal(sandboxCommand(input, options).notice, undefined);
  assert.match(sandboxFailure('elevated', false, '[WinError 10013]'), /block network access/);
  assert.match(sandboxFailure('non-elevated', true, 'PermissionError: [Errno 13] Permission denied'), /workspace/);
  assert.match(sandboxFailure('non-elevated', true, "fatal error - couldn't create signal pipe, Win32 error 5"), /set shell to powershell in background_job/);
  assert.equal(sandboxFailure('off', true, 'Permission denied'), undefined);
});

test('standard-user Git Bash uses the packaged runtime inside the same native sandbox', t => {
  const input = fixture(t);
  const options = { platform: 'win32' };
  const root = join(input.workspace, '..', 'git');
  const bash = join(root, 'bin', 'bash.exe');
  mkdirSync(join(root, 'bin'), { recursive: true });
  writeFileSync(bash, 'fixture; never executed');
  const elevated = sandboxCommand(input, options);
  assert.equal(elevated.args.at(-3), input.file);
  input.policy.elevated = false;
  input.env = { Path: 'original' };
  const standard = sandboxCommand(input, options);
  assert.equal(standard.file, input.policy.launcher);
  assert.equal(standard.level, 'non-elevated');
  assert.deepEqual(standard.args.slice(-4), ['allow', bash, ...input.args]);
  assert.deepEqual(standard.env.Path.split(';'), [join(root, 'usr', 'bin'), join(root, 'mingw64', 'bin'), 'original']);
  assert.equal(sandboxCommand({ ...input, file: 'powershell.exe' }, options).args.at(-3), 'powershell.exe');
});

test('closing a local MCP transport prevents stale traffic immediately', async () => {
  const active = new Set();
  const calls = [];
  let finishClose;
  const transport = trackLocalMcpTransport({
    async start() { calls.push('start'); },
    async send(message) { calls.push(message); },
    close() { return new Promise(resolve => { finishClose = resolve; }); },
  }, active);
  await transport.start();
  await transport.send('first');
  const closing = transport.close();
  await assert.rejects(transport.send('stale'), /Reconnect/);
  await assert.rejects(transport.start(), /Reconnect/);
  finishClose();
  await closing;
  assert.equal(active.size, 0);
  assert.deepEqual(calls, ['start', 'first']);
});
