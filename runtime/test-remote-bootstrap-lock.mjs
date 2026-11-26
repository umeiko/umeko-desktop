import test from 'node:test';
import assert from 'node:assert/strict';
import { execFile, spawn } from 'node:child_process';
import { once } from 'node:events';
import { promisify } from 'node:util';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { withBootstrapLock } from './remote-bootstrap-lock.mjs';

const run = promisify(execFile);
const windows = process.platform === 'win32';
const execute = script => windows
  ? run('powershell.exe', ['-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', Buffer.from("$ProgressPreference='SilentlyContinue';\n" + script, 'utf16le').toString('base64')], { windowsHide: true })
  : run('/bin/sh', ['-c', script]);
const platform = windows ? 'windows' : 'linux';
const quote = value => windows ? `'${value.replaceAll("'", "''")}'` : `'${value.replaceAll("'", "'\\''")}'`;

test('bootstrap wrappers keep the native lock outside detached descendants', () => {
  const linux = withBootstrapLock('linux', "/home/user's root", 'printf body');
  assert.match(linux, /flock -x -w 60 9/);
  assert.match(linux, /sh -c 'printf body' 9>&-/);
  assert.match(linux, /bootstrap\.lock/);
  const win = withBootstrapLock('windows', 'C:\\Users\\name\\root', '[Console]::WriteLine("body")');
  assert.match(win, /Global\\UmekoRemoteBootstrap-/);
  assert.match(win, /WaitOne\(60000\)/);
  assert.match(win, /catch \[Threading\.AbandonedMutexException\]/);
  assert.match(win, /finally \{[\s\S]*ReleaseMutex\(\)[\s\S]*Dispose\(\)/);
  assert.throws(() => withBootstrapLock('macos', '/tmp/root', ''), /Unsupported/);
});

test('native bootstrap lock serializes two clients and preserves body output', { skip: !windows && process.platform !== 'linux' }, async t => {
  const root = await mkdtemp(join(tmpdir(), 'umeko-bootstrap-lock-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const state = join(root, 'state');
  await writeFile(state, '0');
  const body = windows
    ? `$n=[int][IO.File]::ReadAllText(${quote(state)});Start-Sleep -Milliseconds 150;[IO.File]::WriteAllText(${quote(state)},[string]($n+1));[Console]::WriteLine('body')`
    : `n=$(cat ${quote(state)}); sleep 0.15; printf '%s' "$((n+1))" > ${quote(state)}; printf 'body\\n'`;
  const results = await Promise.all([execute(withBootstrapLock(platform, root, body)), execute(withBootstrapLock(platform, root, body))]);
  assert.equal(await readFile(state, 'utf8'), '2');
  assert.deepEqual(results.map(result => result.stdout.trim()), ['body', 'body']);
  for (const result of results) assert.equal(result.stderr, '');
});

test('native bootstrap lock releases after body failure', { skip: !windows && process.platform !== 'linux' }, async t => {
  const root = await mkdtemp(join(tmpdir(), 'umeko-bootstrap-failure-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await assert.rejects(execute(withBootstrapLock(platform, root, 'exit 7')), error => error.code === 7);
  const result = await execute(withBootstrapLock(platform, root, windows ? "[Console]::WriteLine('next')" : "printf 'next\\n'"));
  assert.equal(result.stdout.trim(), 'next');
});

test('Windows wrapper preserves a failing native command status and output', { skip: !windows }, async t => {
  const root = await mkdtemp(join(tmpdir(), 'umeko-bootstrap-native-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await assert.rejects(execute(withBootstrapLock('windows', root, "[Console]::WriteLine('native'); & $env:ComSpec /d /c 'exit 9'")), error => error.code === 9 && error.stdout.trim() === 'native');
});

test('native bootstrap lock releases when its owner dies', { skip: !windows && process.platform !== 'linux' }, async t => {
  const root = await mkdtemp(join(tmpdir(), 'umeko-bootstrap-owner-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const body = windows ? "[Console]::WriteLine('held');Start-Sleep -Seconds 30" : "printf 'held\\n'; read -r ignored";
  const script = withBootstrapLock(platform, root, body);
  const owner = windows
    ? spawn('powershell.exe', ['-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', Buffer.from("$ProgressPreference='SilentlyContinue';\n" + script, 'utf16le').toString('base64')], { windowsHide: true })
    : spawn('/bin/sh', ['-c', script]);
  t.after(() => { owner.kill(); owner.stdin.destroy(); owner.stdout.destroy(); owner.stderr.destroy(); });
  const exited = once(owner, 'exit');
  await new Promise((resolve, reject) => {
    let output = '';
    const timer = setTimeout(() => reject(new Error('Lock owner did not enter the body')), 10000);
    owner.once('error', error => { clearTimeout(timer); reject(error); });
    owner.stdout.on('data', chunk => { output += chunk; if (output.includes('held')) { clearTimeout(timer); resolve(); } });
  });
  owner.kill();
  await exited;
  const result = await execute(withBootstrapLock(platform, root, windows ? "[Console]::WriteLine('recovered')" : "printf 'recovered\\n'"));
  assert.equal(result.stdout.trim(), 'recovered');
});
