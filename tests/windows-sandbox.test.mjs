import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { createSandboxPreparation, resolveLocalBash, sandboxCommand, sandboxFailure, windowsShellHints } from '../runtime/windows-sandbox.mjs';
import { registerCoworkLocalTools } from '../runtime/cowork-local.mjs';

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

test('both Windows sandbox levels use the packaged Git Bash', t => {
  const input = fixture(t);
  const options = { platform: 'win32' };
  const root = join(input.workspace, '..', 'git');
  const bash = join(root, 'usr', 'bin', 'bash.exe');
  mkdirSync(join(root, 'usr', 'bin'), { recursive: true });
  writeFileSync(bash, 'fixture; never executed');
  input.policy.gitRoot = root;
  input.policy.gitReady = true;
  const elevated = sandboxCommand(input, options);
  assert.equal(elevated.args.at(-3), bash);
  input.policy.elevated = false;
  input.env = { Path: 'original' };
  const standard = sandboxCommand(input, options);
  assert.equal(standard.file, input.policy.launcher);
  assert.equal(standard.level, 'non-elevated');
  assert.deepEqual(standard.args.slice(-4), ['allow', bash, ...input.args]);
  assert.deepEqual(standard.env.Path.split(';'), [join(root, 'usr', 'bin'), join(root, 'ucrt64', 'bin'), 'original']);
  assert.equal(sandboxCommand({ ...input, file: 'powershell.exe' }, options).args.at(-3), 'powershell.exe');
});

function preparationFixture(t) {
  const { policy } = fixture(t);
  const gitRoot = join(policy.home, 'git');
  const archive = join(policy.launcher, '..', 'git.tar.xz');
  writeFileSync(archive, 'fixture; real extraction is tested separately');
  let state = { ...policy, gitRoot, archive, preparing: true, preparationAttempt: 0 };
  let requests = 0;
  const preparation = createSandboxPreparation({ platform: 'win32', getPolicy: () => state,
    request: () => requests++, language: () => 'zh' });
  const update = values => { state = { ...state, ...values }; preparation.changed(); };
  function ready(attempt) {
    const paths = ['bin/bash.exe', 'usr/bin/bash.exe', 'usr/bin/msys-2.0.dll', 'cmd/git.exe', 'ucrt64/bin/git.exe'];
    for (const path of paths) {
      mkdirSync(join(gitRoot, path, '..'), { recursive: true });
      writeFileSync(join(gitRoot, path), 'MZfixture');
    }
    writeFileSync(join(gitRoot, '.ready'), '9\n'.repeat(paths.length));
    update({ gitReady: true, preparationAttempt: attempt, preparing: false,
      preparationSeconds: 1.2, preparationFirstUse: attempt === 1 });
  }
  return { preparation, gitRoot, ready, update, requests: () => requests };
}

test('Windows uses packaged Bash if discovery finds another shell or no shell', async t => {
  const { policy } = fixture(t);
  const gitRoot = join(policy.home, 'git');
  const packaged = join(gitRoot, 'usr', 'bin', 'bash.exe');
  const external = join(policy.home, 'other', 'bash.exe');
  const prepareBundle = async () => ({ policy: { gitRoot } });
  for (const getShellConfig of [
    shell => shell ? { shell } : { shell: external },
    shell => { if (!shell) throw new Error('No bash'); return { shell }; },
  ]) {
    const options = { platform: 'win32', getShellConfig, policy: { bundledGitBash: true }, prepareBundle };
    assert.equal((await resolveLocalBash(options)).shell, packaged);
    assert.equal((await resolveLocalBash({ ...options, shellPath: external })).shell, external);
  }
  const input = { ...fixture(t), file: external, policy: { ...policy, gitRoot } };
  const launch = sandboxCommand(input, { platform: 'win32' });
  assert.equal(launch.level, 'elevated');
  assert.ok(launch.args.includes(packaged));
  assert.match(launch.env.PATH, /ucrt64/);
  const off = sandboxCommand({ ...input, file: packaged, policy: { ...input.policy, enabled: false } },
    { platform: 'win32' });
  assert.equal(off.file, packaged);
  assert.match(off.env.PATH, /ucrt64/);
  assert.match(windowsShellHints('powershell', { platform: 'win32' }), /use the bash tool/);
  assert.equal(windowsShellHints('bash', { platform: 'linux' }), '');
});

test('commands share preparation, cancel independently, and report elapsed time once', async t => {
  const { preparation, ready, requests } = preparationFixture(t);
  const abort = new AbortController();
  const cancelled = preparation.wait(abort.signal);
  const started = preparation.wait(undefined, { report: true });
  assert.equal(requests(), 1);
  abort.abort();
  await assert.rejects(cancelled, /aborted/);
  ready(1);
  assert.equal((await started).notice, '首次使用沙箱，已准备 Git Bash，用时 1.2 秒。');
  assert.equal((await preparation.wait(undefined, { report: true })).notice, undefined);
});

test('a missing executable triggers recovery and the next command retries after storage failure', async t => {
  const { preparation, ready, gitRoot, update, requests } = preparationFixture(t);
  ready(1);
  rmSync(join(gitRoot, 'usr', 'bin', 'bash.exe'));
  const failed = preparation.wait();
  assert.equal(requests(), 1);
  update({ gitReady: false, preparationError: 'Umeko will continue retrying automatically.', preparationAttempt: 4 });
  await assert.rejects(failed, /continue retrying automatically/);
  const recovered = preparation.wait();
  assert.equal(requests(), 2);
  ready(5);
  assert.equal((await recovered).policy.gitRoot, gitRoot);
});

test('Cowork local extraction uses the bridge preparation before launching its command', async t => {
  const { workspace } = fixture(t);
  const source = join(workspace, 'fixture.pdf');
  writeFileSync(source, 'fixture; process stdout is controlled');
  let tool;
  const signal = new AbortController().signal;
  registerCoworkLocalTools({ registerTool: value => { tool = value; } }, new Set(['read_pdf_text']), (request, toolSignal) => {
    assert.equal(request.cwd, workspace);
    assert.ok(request.args.includes(source));
    assert.equal(toolSignal, signal);
    return { file: process.execPath, args: ['-e', 'console.log("extracted")'] };
  });
  const result = await tool.execute('fixture', { path: source }, signal, undefined, { cwd: workspace });
  assert.equal(result.content[0].text, process.platform === 'darwin' ? 'extracted' : '--- Page 1 ---\nextracted');
});
