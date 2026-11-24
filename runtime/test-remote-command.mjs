import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';
import { createRemoteCommands } from './remote-command.mjs';

// Real native worker + local filesystem implementation of the official RPCs.
// No SSH, local service or installed remote dependency is required.
const home = await fs.mkdtemp(path.join(os.tmpdir(), 'umeko remote 命令-test-'));
await fs.mkdir(path.join(home, 'work dir'));
const handles = new Map();
const launchers = [];
let processStarts = 0;
let generation = 1;
let expireNextBlock = false;
let interruptLaunch = true;
let interruptInputReady = true;
const launchRequests = new Map();
let modelBootstrapFailure = false;
let bootstrapReads = 0;
const connection = {
  config: { platform: process.platform === 'win32' ? 'windows' : 'linux' },
  get sessionId() { return `server-session-${generation}`; },
  async ready() {
    // Official wire shape, including a Windows detected shell that differs from
    // the PowerShell command semantics required by the remote tool.
    return { cwd: pathToFileURL(home).href, userHomeDir: pathToFileURL(home).href, shell: { name: process.platform === 'win32' ? 'cmd' : 'sh', path: process.platform === 'win32' ? 'file:///C:/Windows/System32/cmd.exe' : 'file:///bin/sh' } };
  },
  async rpc(method, params, options) {
    const local = params.path && fileURLToPath(params.path);
    switch (method) {
      case 'fs/createDirectory': assert.equal(options.retry, true); await fs.mkdir(local, { recursive: params.recursive }); return {};
      case 'fs/writeFile': {
        assert.equal(options.retry, true);
        await fs.writeFile(local, Buffer.from(params.dataBase64, 'base64'));
        if (interruptInputReady && /input-1\.ready$/.test(local)) {
          interruptInputReady = false;
          throw Object.assign(new Error('injected stdin publication acknowledgement loss'), { transport: true });
        }
        return {};
      }
      case 'fs/readFile': return { dataBase64: (await fs.readFile(local)).toString('base64') };
      case 'fs/open': assert.equal(Buffer.byteLength(params.handleId), 32); handles.set(params.handleId, await fs.open(local, 'r')); return { handleId: params.handleId };
      case 'fs/readBlock': {
        if (expireNextBlock) {
          expireNextBlock = false;
          throw Object.assign(new Error('Remote session expired; reopen the process or file handle'), { code: 'REMOTE_SESSION_CHANGED' });
        }
        const buffer = Buffer.alloc(params.len);
        const { bytesRead } = await handles.get(params.handleId).read(buffer, 0, params.len, params.offset);
        return { chunk: buffer.subarray(0, bytesRead).toString('base64'), eof: bytesRead < params.len };
      }
      case 'fs/close': await handles.get(params.handleId).close(); handles.delete(params.handleId); return {};
      case 'process/start': {
        assert.equal(options.retry, false);
        assert.deepEqual(params.envPolicy, { inherit: 'all', ignoreDefaultExcludes: false, exclude: [], set: {}, includeOnly: [] });
        if (launchRequests.has(params.processId)) assert.deepEqual(params, launchRequests.get(params.processId));
        else launchRequests.set(params.processId, structuredClone(params));
        processStarts++;
        if (modelBootstrapFailure) return { processId: params.processId };
        // Replay the exact request in another native process, as if the initial
        // acknowledgement were lost and the server session had expired.
        for (let count = 0; count < 2; count++) {
          const child = spawn(params.argv[0], params.argv.slice(1), { cwd: fileURLToPath(params.cwd), env: process.env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
          child.stdout.on('data', data => console.error('launcher stdout:', data.toString()));
          child.stderr.on('data', data => console.error('launcher stderr:', data.toString()));
          child.on('exit', code => console.error('launcher exit:', code));
          launchers.push(child);
          child.on('error', error => console.error(error));
        }
        if (interruptLaunch) {
          interruptLaunch = false;
          generation++;
          throw Object.assign(new Error('injected launcher acknowledgement loss'), { transport: true });
        }
        return { processId: params.processId };
      }
      case 'process/read': {
        if (modelBootstrapFailure) {
          bootstrapReads++;
          if (bootstrapReads === 1) return { chunks: [{ seq: 0, stream: 'stderr', chunk: Buffer.from('loader diagnostic 8009001d').toString('base64') }], nextSeq: 0, exited: false, exitCode: null };
          assert.equal(params.afterSeq, 0);
          return { chunks: [], nextSeq: 0, exited: true, exitCode: 1 };
        }
        return { chunks: [], exited: false, exitCode: null };
      }
      default: throw new Error(`Unexpected RPC ${method}`);
    }
  },
};

let allOutput = '';
const backend = createRemoteCommands(connection);
const win = process.platform === 'win32';
const command = win
  ? `Add-Content -LiteralPath '${home.replaceAll("'", "''")}\\starts.txt' -Value 'start'; Write-Output ('cwd:' + (Get-Location).Path); Write-Output 'ready'; $line = [Console]::ReadLine(); Write-Output ('got:' + $line); Start-Sleep -Milliseconds 400; Write-Output 'done'`
  : `printf 'start\\n' >> '${home}/starts.txt'; printf 'cwd:%s\\n' "$PWD"; printf 'ready\\n'; IFS= read -r line; printf 'got:%s\\n' "$line"; sleep 0.4; printf 'done\\n'`;

let result = await backend.execute({ action: 'run', command, cwd: './work dir', yieldMs: 1000, maxOutputBytes: 7 });
const sessionId = result.sessionId;
allOutput += result.output;
const deadline = Date.now() + 20000;
while (!allOutput.includes('ready') && Date.now() < deadline) {
  result = await backend.execute({ action: 'read', sessionId, yieldMs: 500, maxOutputBytes: 7 });
  allOutput += result.output;
}
assert.match(allOutput, /ready/);
// Destroying/expiring the managed launcher is the important boundary. All
// following RPC calls are in a new simulated executor session.
generation++;
expireNextBlock = true;
for (const child of launchers) { if (child.exitCode === null) child.kill(); }
await delay(150);
await assert.rejects(backend.execute({ action: 'write', sessionId, input: 'hello 世界\n', yieldMs: 500, maxOutputBytes: 7 }), error => error.transport && error.sessionId === sessionId);
result = await backend.execute({ action: 'write', sessionId, input: 'hello 世界\n', yieldMs: 500, maxOutputBytes: 7 });
allOutput += result.output;
while ((result.status === 'running' || result.output.length > 0) && Date.now() < deadline) {
  result = await backend.execute({ action: 'read', sessionId, yieldMs: 500, maxOutputBytes: 7 });
  allOutput += result.output;
}
assert.equal(result.exitCode, 0);
assert.match(allOutput, /got:hello 世界/);
assert.match(allOutput, /done/);
assert.ok(allOutput.includes(`cwd:${path.join(home, 'work dir')}`));
assert.equal((await fs.readFile(path.join(home, 'starts.txt'), 'utf8')).trim(), 'start');
assert.equal(processStarts, 2);
assert.equal(handles.size, 0);
assert.equal(result.cursor, Buffer.byteLength(allOutput));
assert.equal(await fs.readFile(path.join(home, ...(win ? ['AppData', 'Local', 'Temp'] : ['.cache']), 'umeko-remote-commands', sessionId, 'input-1.data'), 'utf8'), 'hello 世界\n');
await assert.rejects(fs.access(path.join(home, ...(win ? ['AppData', 'Local', 'Temp'] : ['.cache']), 'umeko-remote-commands', sessionId, 'input-2.data')), error => error.code === 'ENOENT');
console.log(JSON.stringify({ test: 'native detached command, duplicate launch, executor-session replacement, stdin, UTF8 byte cursor', platform: process.platform, output: allOutput, cursor: result.cursor, processStarts, exitCode: result.exitCode, fixture: home }));

// A caller stops at terminal status: all retained output must have been delivered
// before that status, even when the command exited before the first read.
const bulkText = `bulk:${'文'.repeat(80)}:end`;
const bulkCommand = win ? `[Console]::Out.Write('${bulkText}')` : `printf '%s' '${bulkText}'`;
result = await backend.execute({ action: 'run', command: bulkCommand, cwd: '~/work dir', yieldMs: 1000, maxOutputBytes: 32 });
const bulkSession = result.sessionId;
assert.equal(result.status, 'running');
assert.equal(result.exitCode, null);
let bulkOutput = result.output;
while (result.status === 'running' && Date.now() < deadline) {
  result = await backend.execute({ action: 'read', sessionId: bulkSession, yieldMs: 500, maxOutputBytes: 32 });
  bulkOutput += result.output;
}
assert.equal(result.status, 'completed');
assert.equal(result.exitCode, 0);
assert.equal(bulkOutput, bulkText);
assert.equal(result.cursor, Buffer.byteLength(bulkText));
if (win) await assert.rejects(backend.execute({ action: 'run', command: "Write-Output 'unused'", cwd: 'C:relative' }), /Drive-relative/);
console.log(JSON.stringify({ test: 'terminal status drains retained multiblock output', bytes: result.cursor, status: result.status }));

// Exercise the explicit kill action against only this owned finite fixture.
result = await backend.execute({ action: 'run', command: win ? "Write-Output 'kill-ready'; Start-Sleep -Seconds 30" : "printf 'kill-ready\\n'; sleep 30", yieldMs: 1000 });
const killSessionId = result.sessionId;
let killOutput = result.output;
while (!killOutput.includes('kill-ready') && Date.now() < deadline) {
  result = await backend.execute({ action: 'read', sessionId: killSessionId, yieldMs: 500 });
  killOutput += result.output;
}
assert.match(killOutput, /kill-ready/);
result = await backend.execute({ action: 'kill', sessionId: killSessionId, yieldMs: 1000 });
while (result.status === 'running' && Date.now() < deadline) result = await backend.execute({ action: 'read', sessionId: killSessionId, yieldMs: 500 });
assert.equal(result.status, 'failed');
assert.notEqual(result.exitCode, 0);
console.log(JSON.stringify({ test: 'kill owned durable native command', status: result.status, exitCode: result.exitCode }));

modelBootstrapFailure = true;
await assert.rejects(backend.execute({ action: 'run', command: win ? "Write-Output 'never-started'" : "printf 'never-started'", yieldMs: 1000 }), /Remote command launcher failed: loader diagnostic 8009001d/);
assert.equal(bootstrapReads, 2);
console.log(JSON.stringify({ test: 'early launcher stderr then nonzero exit', reads: bootstrapReads, detected: true }));
