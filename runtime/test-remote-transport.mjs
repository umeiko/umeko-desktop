import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { inflateRawSync } from "node:zlib";
import fs from "node:fs/promises";
import { mkdtemp, readFile, rmdir, unlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { WebSocketServer } from "ws";
import { RemoteConnection, RemoteRpcError, sshArguments, discoveryScript, listenerScript } from "./remote-transport.mjs";
import { withBootstrapLock } from "./remote-bootstrap-lock.mjs";

const info = { cwd: "file:///C:/Users/test", userHomeDir: "file:///C:/Users/test", platformOs: "windows", shell: { name: "powershell", path: "powershell.exe" } };
class FakeSocket extends EventEmitter {
  readyState = 1;
  send(text, callback) { this.sent.push(JSON.parse(text)); callback?.(); }
  sent = [];
  terminate() { this.readyState = 3; this.emit("close"); }
}
class FakeConnection extends RemoteConnection {
  constructor(responses = []) { super({ host: "existing-alias", platform: "windows" }, { sshCommand: process.execPath }); this.responses = responses; this.calls = []; }
  async _bootstrap() { return { port: 41000, token: "x".repeat(48) }; }
  async _forward() { return 41001; }
  async _openSocket() { this.socket = new FakeSocket(); }
  async _request(method, serialized, signal) {
    if (signal?.aborted) throw Object.assign(new Error("cancelled"), { name: "AbortError" });
    this.calls.push({ method, params: serialized === undefined ? undefined : JSON.parse(serialized) });
    if (method === "initialize") {
      const response = this.responses.shift();
      if (response instanceof Error) throw response;
      return response || { sessionId: "session-one", environmentInfo: info };
    }
    return this.respond?.(method, serialized) ?? { ok: true };
  }
}

test("existing OpenSSH configuration stays authoritative and unsafe aliases are rejected", () => {
  const args = sshArguments("existing-alias");
  assert.ok(args.includes("StrictHostKeyChecking=yes"));
  assert.ok(args.includes("BatchMode=yes"));
  assert.ok(!args.some(arg => arg.startsWith("IdentityFile=") || arg.startsWith("ProxyJump=")));
  for (const host of ["-oProxyCommand=evil", "alias\ncommand", "alias;evil", "user@host $(bad)"]) assert.throws(() => sshArguments(host));
});

test("a new SSH connection picks up the current session shell environment", async t => {
  t.mock.method(fs, "stat", async () => ({ isFile: () => true }));
  t.mock.method(fs, "access", async () => {});
  const first = join(tmpdir(), "first-shell", "usr", "bin");
  const refreshed = join(tmpdir(), "refreshed-shell", "usr", "bin");
  const executable = process.platform === "win32" ? "ssh.exe" : "ssh";
  let shellEnvironment = { PATH: first };
  const connection = new RemoteConnection({ host: "existing-alias", platform: "windows" }, {
    getSshEnvironment: async () => shellEnvironment,
  });
  t.after(() => connection.close());
  await connection._selectSsh();
  assert.equal(connection.sshClient, join(first, executable));
  shellEnvironment = { PATH: refreshed };
  await connection._selectSsh();
  assert.equal(connection.sshClient, join(refreshed, executable));
  assert.equal(connection.sshEnv, shellEnvironment);
});

test("bootstrap is home-only, private, detached, and authenticates a PID-owned listener", () => {
  const win = discoveryScript("windows") + listenerScript("windows", "C:\\Users\\test\\.local\\share\\umeko\\remote-exec", "C:\\Users\\test\\.local\\share\\umeko\\remote-exec\\codex-exec-server.exe");
  assert.match(win, /SetAccessRuleProtection/);
  assert.match(win, /0x01000210/);
  assert.match(win, /netstat.exe -ano -p tcp/);
  assert.doesNotMatch(win, /Get-CimInstance|Get-NetTCPConnection|Invoke-CimMethod/);
  assert.match(win, /--ws-auth capability-token --ws-token-file/);
  assert.doesNotMatch(win, /\.umeko|Stop-Service|Restart-Service|Stop-Process|taskkill/i);
  const linux = discoveryScript("linux") + listenerScript("linux", "/home/test/.local/share/umeko/remote-exec", "/home/test/.local/share/umeko/remote-exec/codex-exec-server");
  assert.match(linux, /nohup/);
  assert.match(linux, /\/proc\/net\/tcp/);
  assert.match(linux, /umask 077/);
});

test("expired retained session creates a fresh generation and notifies the caller", async () => {
  const connection = new FakeConnection([
    { sessionId: "old", environmentInfo: info },
    new RemoteRpcError({ code: -32600, message: "unknown session id old" }),
    { sessionId: "new", environmentInfo: info },
  ]);
  const states = []; connection.options.onState = (state, detail) => states.push([state, detail]);
  await connection.ready();
  connection._drop(); await connection.ready();
  assert.equal(connection.sessionId, "new");
  assert.equal(connection.sessionGeneration, 2);
  assert.deepEqual(connection.calls.filter(call => call.method === "initialize").map(call => call.params), [
    { clientName: "umeko-remote" }, { clientName: "umeko-remote", resumeSessionId: "old" }, { clientName: "umeko-remote" },
  ]);
  assert.equal(states.at(-1)[1].resumed, false);
  connection.close(); assert.equal(states.at(-1)[0], "disconnected");
});

test("idempotent replay keeps exact parameters despite caller mutation", async () => {
  const connection = new FakeConnection(); const params = { path: "file:///before" }; let count = 0;
  connection.respond = async () => { if (!count++) { params.path = "file:///after"; connection._drop(); throw Object.assign(new Error("lost"), { transport: true }); } return { ok: true }; };
  await connection.rpc("fs/readFile", params);
  assert.deepEqual(connection.calls.filter(call => call.method === "fs/readFile").map(call => call.params), [{ path: "file:///before" }, { path: "file:///before" }]);
  connection.close();
});

test("writes and process starts are never replayed after uncertain delivery", async () => {
  for (const method of ["process/start", "process/write", "fs/writeFile", "fs/writeBlock", "fs/remove"]) {
    const connection = new FakeConnection(); connection.respond = () => { throw Object.assign(new Error("lost"), { transport: true }); };
    await assert.rejects(connection.rpc(method, { same: true }), /lost/);
    assert.equal(connection.calls.filter(call => call.method === method).length, 1); connection.close();
  }
});

test("handle reads fail explicitly after session expiry instead of reusing invalid handles", async () => {
  const connection = new FakeConnection([{ sessionId: "old", environmentInfo: info }, { sessionId: "new", environmentInfo: info }]);
  connection.respond = () => { connection._drop(); throw Object.assign(new Error("lost"), { transport: true }); };
  await assert.rejects(connection.rpc("fs/readBlock", { handleId: "handle" }), { code: "REMOTE_SESSION_CHANGED" }); connection.close();
});

test("retry:false and pre-aborted requests do not replay or connect unnecessarily", async () => {
  const connection = new FakeConnection(); connection.respond = () => { throw Object.assign(new Error("lost"), { transport: true }); };
  try {
    await assert.rejects(connection.rpc("fs/readFile", {}, { retry: false }), /lost/);
    await connection.ready();
    const calls = connection.calls.length; const controller = new AbortController(); controller.abort();
    await assert.rejects(connection.rpc("fs/readFile", {}, { signal: controller.signal }), { name: "AbortError" });
    assert.equal(connection.calls.filter(call => call.method === "fs/readFile").length, 1);
    assert.equal(connection.calls.length, calls);
  } finally { connection.close(); }
});

test("real RPC envelopes dispatch notifications and cancel pending requests locally", async () => {
  const events = []; const connection = new RemoteConnection({ host: "existing-alias", platform: "linux" }, { onNotification: (...args) => events.push(args) });
  connection.socket = new FakeSocket();
  const controller = new AbortController(); const request = connection._request("process/start", JSON.stringify({ processId: "one" }), controller.signal);
  assert.deepEqual(connection.socket.sent[0], { id: 1, method: "process/start", params: { processId: "one" } });
  assert.equal(connection.socket.sent[0].jsonrpc, undefined);
  controller.abort(); await assert.rejects(request, { name: "AbortError" });
  assert.equal(connection.pending.size, 0); connection.close();
});

test("explicit idempotent file writes replay exact captured parameters", async () => {
  const connection = new FakeConnection(); let count = 0;
  connection.respond = () => { if (!count++) { connection._drop(); throw Object.assign(new Error("lost"), { transport: true }); } return { ok: true }; };
  await connection.rpc("fs/writeFile", { path: "file:///note", contents: "same" }, { retry: true });
  assert.deepEqual(connection.calls.filter(call => call.method === "fs/writeFile").map(call => call.params), [
    { path: "file:///note", contents: "same" }, { path: "file:///note", contents: "same" },
  ]); connection.close();
});

test("authenticated live loopback WS performs handshake, RPC and notification routing", async () => {
  const token = "test-only-bearer-" + "x".repeat(32);
  const seen = [], notifications = [];
  const server = new WebSocketServer({ host: "127.0.0.1", port: 0, verifyClient: request => request.req.headers.authorization === `Bearer ${token}` });
  await new Promise(resolve => server.once("listening", resolve));
  server.on("connection", socket => socket.on("message", bytes => {
    const message = JSON.parse(bytes.toString()); seen.push(message);
    if (message.method === "initialize") socket.send(JSON.stringify({ id: message.id, result: { sessionId: "live", environmentInfo: info } }));
    if (message.method === "environment/info") {
      socket.send(JSON.stringify({ method: "process/output", params: { processId: "owned", chunk: "eA==", seq: 1, stream: "stdout" } }));
      socket.send(JSON.stringify({ id: message.id, result: info }));
    }
  }));
  const connection = new RemoteConnection({ host: "existing-alias", platform: "windows" }, { sshCommand: process.execPath, onNotification: (...args) => notifications.push(args) });
  connection._bootstrap = async () => ({ port: server.address().port, token });
  connection._forward = async port => port;
  try {
    assert.deepEqual(await connection.ready(), info);
    assert.deepEqual(await connection.rpc("environment/info", {}), info);
    assert.deepEqual(seen.map(message => message.method), ["initialize", "initialized", "environment/info"]);
    assert.equal(notifications[0][0], "process/output");
  } finally { connection.close(); await new Promise(resolve => server.close(resolve)); }
});

test("WS bearer rejection stops immediately with a secret-free fatal error", async () => {
  const server = new WebSocketServer({ host: "127.0.0.1", port: 0, verifyClient: () => false });
  await new Promise(resolve => server.once("listening", resolve));
  const connection = new RemoteConnection({ host: "existing-alias", platform: "windows" });
  try {
    await assert.rejects(connection._openSocket(server.address().port, "private-test-bearer"), error => error.fatal === true && !error.message.includes("private-test-bearer"));
  } finally { connection.close(); await new Promise(resolve => server.close(resolve)); }
});

test("Windows bootstrap sends a short inline command without waiting for SSH stdin", async () => {
  const connection = new RemoteConnection({ host: "existing-alias", platform: "windows" });
  const child = new EventEmitter(); child.stdout = new PassThrough(); child.stderr = new PassThrough(); child.stdin = new PassThrough(); child.kill = () => {};
  let args, received = "";
  child.stdin.on("data", chunk => { received += chunk.toString(); });
  child.stdin.on("finish", () => { child.stdout.write("result\n"); child.emit("close", 0); });
  connection._spawn = value => { args = value; return child; };
  const root = "C:\\Users\\test\\.local\\share\\umeko\\remote-exec\\rust-v0.172.0\\x64";
  const source = withBootstrapLock("windows", root, listenerScript("windows", root, root + "\\codex-exec-server.exe"));
  assert.equal(await connection._ssh(source), "result");
  assert.ok(args.join(" ").length < 8191);
  assert.equal(args[0], "-n");
  assert.equal(received, "");
  const decoder = Buffer.from(args.at(-1).split(" ").at(-1), "base64").toString("utf16le");
  const payload = decoder.match(/FromBase64String\('([^']+)'\)/)?.[1];
  assert.equal(inflateRawSync(Buffer.from(payload, "base64")).toString(), source);
  connection.close();
});

test("failed SSH reports its own stderr and selected executable without bootstrap output", async () => {
  const states = [];
  const connection = new RemoteConnection({ host: "existing-alias", platform: "windows" }, {
    sshCommand: process.execPath, onState: (state, detail) => states.push({ state, ...detail }),
  });
  const child = new EventEmitter();
  child.stdout = new PassThrough(); child.stderr = new PassThrough(); child.stdin = new PassThrough(); child.kill = () => {};
  child.stdin.on("finish", () => {
    child.stdout.write('{"token":"test-bearer"}');
    child.stderr.write("debug1: verbose configuration details\nposix_spawnp: No such file or directory\nConnection closed by UNKNOWN port 65535\n");
    child.emit("close", 255);
  });
  connection._spawn = () => child;
  try {
    await assert.rejects(connection.ready(), error => error.sshClient === process.execPath && error.fatal &&
      error.sshError === "posix_spawnp: No such file or directory\nConnection closed by UNKNOWN port 65535" &&
      !error.message.includes("test-bearer") && !error.message.includes("verbose configuration"));
    assert.equal(states.at(-1).state, "error");
    assert.equal(states.at(-1).sshClient, process.execPath);
    assert.match(states.at(-1).sshError, /posix_spawnp/);
  } finally { connection.close(); }
});

test("a Windows SFTP relay reset retries even when the exit code is not 255", async () => {
  const connection = new RemoteConnection({ host: "existing-alias", platform: "windows" });
  const child = new EventEmitter();
  child.stdout = new PassThrough(); child.stderr = new PassThrough(); child.stdin = new PassThrough(); child.kill = () => {};
  child.stdin.on("finish", () => {
    child.stderr.write("FATAL: send() failed, 10054\nclient_loop: send disconnect: Broken pipe\n");
    child.emit("close", 3328);
  });
  try {
    await assert.rejects(connection._readChild(child, { label: "OpenSSH SFTP upload", timeout: 1000, sftp: true }),
      error => error.transport && !error.fatal && error.sshError.includes("10054"));
  } finally { connection.close(); }
});

test("executor bootstrap starts a new upload, then resumes the same staging file", async () => {
  const manifest = JSON.parse(await readFile(new URL("./remote-exec-assets.json", import.meta.url), "utf8"));
  const directory = await mkdtemp(join(tmpdir(), "umeko-ssh-asset-test-"));
  const asset = join(directory, manifest.assets["windows-x64"].name);
  const connection = new RemoteConnection({ host: "existing-alias", platform: "windows" }, { assetsDir: directory });
  const root = "C:\\Users\\test\\remote";
  const binary = `${root}\\codex-exec-server.exe`;
  const staging = [], uploads = [];
  const listener = { port: 41000, token: "x".repeat(48) };
  connection._ssh = async source => {
    if (!source.includes("$arch=")) return JSON.stringify(listener);
    staging.push(source.match(/'upload-([a-f0-9]+)'/)?.[1]);
    return JSON.stringify({ arch: "x64", root, binary, present: false, staged: staging.length > 1 });
  };
  connection._sftpUpload = async (local, remote, { resume }) => {
    assert.equal(local, asset);
    uploads.push({ remote, resume });
    if (!resume) throw Object.assign(new Error("Connection reset"), { transport: true });
  };
  try {
    await writeFile(asset, "synthetic payload");
    await assert.rejects(connection._bootstrap(), /Connection reset/);
    assert.deepEqual(await connection._bootstrap(), listener);
    assert.ok(staging[0]);
    assert.deepEqual(staging, [staging[0], staging[0]]);
    assert.deepEqual(uploads, [false, true].map(resume => ({ remote: `${root}/upload-${staging[0]}`, resume })));
  } finally {
    connection.close();
    await unlink(asset);
    await rmdir(directory);
  }
});

test("request cancellation interrupts waiting for shared recovery without stopping the connection", async () => {
  const connection = new FakeConnection(); let release;
  connection._bootstrap = () => new Promise(resolve => { release = resolve; });
  const controller = new AbortController(); const promise = connection.rpc("fs/readFile", {}, { signal: controller.signal });
  controller.abort(); await assert.rejects(promise, { name: "AbortError" });
  assert.equal(connection.closed, false); assert.equal(connection.calls.length, 0);
  release({ port: 41000, token: "x".repeat(48) });
  await connection.ready();
  connection.close();
});

test("a recovered link keeps retrying after three failures and caps the interval at one minute", async () => {
  const connection = new FakeConnection();
  const delays = [], states = [];
  connection.options.onState = (state, detail) => states.push({ state, ...detail });
  connection.options.reconnectSleep = async ms => { delays.push(ms); };
  await connection.ready();
  const outage = Object.assign(new Error("SSH command timed out"), {
    transport: true, sshError: "Connection timed out during banner exchange",
  });
  let attempts = 0;
  connection._bootstrap = async () => {
    if (attempts++ < 8) throw outage;
    return { port: 41000, token: "x".repeat(48) };
  };
  try {
    connection._drop();
    const waiting = ["fs/readFile", "environment/info"].map(method => connection.rpc(method, {}));
    await Promise.all(waiting);
    assert.equal(attempts, 9);
    assert.deepEqual(delays, [2000, 4000, 8000, 16000, 32000, 60000, 60000, 60000]);
    const retryStates = states.filter(state => state.retryAfterMs);
    assert.deepEqual(retryStates.map(state => state.attempt), [2, 3, 4, 5, 6, 7, 8, 9]);
    for (const state of retryStates) {
      assert.equal(state.outageStartedAt, retryStates[0].outageStartedAt);
      assert.ok(state.nextRetryAt >= state.outageStartedAt + state.retryAfterMs);
    }
    assert.equal(states.at(-1).recovered, true);
    assert.equal(states.at(-1).resumed, true);
    assert.equal(states.at(-1).outageStartedAt, retryStates[0].outageStartedAt);
  } finally { connection.close(); }
});

test("a tool wait ends with SSH stderr while background recovery and other waiters continue", async context => {
  context.mock.timers.enable({ apis: ["Date", "setTimeout"], now: 1000 });
  const connection = new FakeConnection();
  const diagnostic = "Connection timed out during banner exchange";
  let attempting, release;
  const reconnecting = new Promise(resolve => { attempting = resolve; });
  connection.options.reconnectSleep = async () => {};
  let attempts = 0;
  connection._bootstrap = async () => {
    if (attempts++ === 0) throw Object.assign(new Error(diagnostic), { transport: true, sshError: diagnostic });
    await new Promise(resolve => { release = resolve; attempting(); });
    return { port: 41000, token: "x".repeat(48) };
  };
  try {
    const pending = connection.waitForReady();
    await reconnecting;
    context.mock.timers.tick(10 * 60_000);
    await assert.rejects(pending, {
      code: "REMOTE_RECONNECT_TIMEOUT", state: "reconnecting", attempt: 2, sshError: diagnostic,
    });
    assert.equal(connection.waiters.size, 0);
    assert.equal(connection.state, "reconnecting");
    assert.ok(connection.connecting);
    const next = connection.waitForReady();
    release();
    assert.deepEqual(await next, info);
    assert.equal(connection.state, "connected");
  } finally { connection.close(); }
});

test("closing an environment interrupts retry backoff and releases its tool waiters", async () => {
  const connection = new FakeConnection();
  let backingOff;
  const announced = new Promise(resolve => { backingOff = resolve; });
  connection.options.onState = (_state, detail) => { if (detail.retryAfterMs) backingOff(); };
  connection._bootstrap = async () => { throw Object.assign(new Error("connection reset"), { transport: true }); };
  const pending = connection.waitForReady();
  await announced;
  const recovery = connection.connecting;
  connection.close();
  await assert.rejects(pending, { name: "AbortError" });
  await assert.rejects(recovery, { name: "AbortError" });
  assert.equal(connection.waiters.size, 0);
  assert.equal(connection.state, "disconnected");
});

test("already attached recovery keeps the same resume ID through detach skew", async context => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  const connection = new FakeConnection([
    { sessionId: "retained", environmentInfo: info },
    new RemoteRpcError({ code: -32600, message: "session retained is already attached to another connection" }),
    { sessionId: "retained", environmentInfo: info },
  ]);
  let retrying; const announced = new Promise(resolve => { retrying = resolve; });
  connection.options.onState = (_state, detail) => { if (detail.retryAfterMs) retrying(); };
  try {
    await connection.ready(); connection._drop(); const recovery = connection.ready();
    await announced; context.mock.timers.tick(2000); await recovery;
    assert.equal(connection.sessionGeneration, 1);
    assert.deepEqual(connection.calls.filter(call => call.method === "initialize").map(call => call.params.resumeSessionId), [undefined, "retained", "retained"]);
  } finally { connection.close(); }
});

test("tunnel readiness is confirmed by the owning OpenSSH child before bearer use", async () => {
  const connection = new RemoteConnection({ host: "existing-alias", platform: "linux" }); let captured;
  connection._spawn = args => {
    captured = args;
    const child = new EventEmitter(); child.stdin = new PassThrough(); child.stdout = new PassThrough(); child.stderr = new PassThrough(); child.exitCode = null; child.signalCode = null; child.kill = () => {};
    const localPort = args[args.indexOf("-L") + 1].split(":")[1];
    process.nextTick(() => child.stderr.write(`debug1: Local forwarding listening on 127.0.0.1 port ${localPort}.\n`));
    return child;
  };
  try {
    const port = await connection._forward(40000);
    assert.ok(port > 0); assert.ok(captured.includes("-v")); assert.ok(captured.includes("ExitOnForwardFailure=yes"));
    assert.ok(captured.includes("ClearAllForwardings=no"));
  } finally { connection.close(); }
});
