import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { WebSocketServer } from "ws";
import { RemoteConnection, RemoteRpcError, sshArguments, discoveryScript, listenerScript } from "./remote-transport.mjs";

const info = { cwd: "file:///C:/Users/test", userHomeDir: "file:///C:/Users/test", platformOs: "windows", shell: { name: "powershell", path: "powershell.exe" } };
class FakeSocket extends EventEmitter {
  readyState = 1;
  send(text, callback) { this.sent.push(JSON.parse(text)); callback?.(); }
  sent = [];
  terminate() { this.readyState = 3; this.emit("close"); }
}
class FakeConnection extends RemoteConnection {
  constructor(responses = []) { super({ host: "existing-alias", platform: "windows" }); this.responses = responses; this.calls = []; }
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
  await assert.rejects(connection.rpc("fs/readFile", {}, { retry: false }), /lost/);
  const calls = connection.calls.length; const controller = new AbortController(); controller.abort();
  await assert.rejects(connection.rpc("fs/readFile", {}, { signal: controller.signal }), { name: "AbortError" });
  assert.equal(connection.calls.length, calls); connection.close();
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
  const connection = new RemoteConnection({ host: "existing-alias", platform: "windows" }, { onNotification: (...args) => notifications.push(args) });
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

test("streamed bootstrap keeps Windows SSH argv short and source off the command line", async () => {
  const connection = new RemoteConnection({ host: "existing-alias", platform: "windows" });
  const child = new EventEmitter(); child.stdout = new PassThrough(); child.stderr = new PassThrough(); child.stdin = new PassThrough(); child.kill = () => {};
  let args, received = "";
  child.stdin.on("data", chunk => { received += chunk.toString(); });
  child.stdin.on("finish", () => { child.stdout.write("result\n"); child.emit("exit", 0); });
  connection._spawn = value => { args = value; return child; };
  const source = listenerScript("windows", "C:\\Users\\test\\remote", "C:\\Users\\test\\remote\\codex-exec-server.exe");
  assert.equal(await connection._ssh(source), "result");
  assert.ok(args.join(" ").length < 1024);
  assert.equal(received, source + "\n");
  assert.ok(!args.join(" ").includes("UmekoRemoteExecutor")); connection.close();
});

test("request cancellation interrupts waiting for shared recovery without stopping the connection", async () => {
  const connection = new FakeConnection(); let release;
  connection.ready = () => new Promise(resolve => { release = resolve; });
  const controller = new AbortController(); const promise = connection.rpc("fs/readFile", {}, { signal: controller.signal });
  controller.abort(); await assert.rejects(promise, { name: "AbortError" });
  assert.equal(connection.closed, false); assert.equal(connection.calls.length, 0); release(info); connection.close();
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
    await announced; context.mock.timers.tick(60_000); await recovery;
    assert.equal(connection.sessionGeneration, 1);
    assert.deepEqual(connection.calls.filter(call => call.method === "initialize").map(call => call.params.resumeSessionId), [undefined, "retained", "retained"]);
  } finally { connection.close(); }
});

test("tunnel readiness is confirmed by the owning OpenSSH child before bearer use", async () => {
  const connection = new RemoteConnection({ host: "existing-alias", platform: "linux" }); let captured;
  connection._spawn = args => {
    captured = args;
    const child = new EventEmitter(); child.stdin = new PassThrough(); child.stdout = new PassThrough(); child.stderr = new PassThrough(); child.exitCode = null; child.kill = () => {};
    const localPort = args[args.indexOf("-L") + 1].split(":")[1];
    process.nextTick(() => child.stderr.write(`debug1: Local forwarding listening on 127.0.0.1 port ${localPort}.\n`));
    return child;
  };
  try {
    const port = await connection._forward(40000);
    assert.ok(port > 0); assert.ok(captured.includes("-v")); assert.ok(captured.includes("ExitOnForwardFailure=yes"));
  } finally { connection.close(); }
});
