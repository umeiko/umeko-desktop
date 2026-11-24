import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { createRemoteEnvironments } from "./remote-environments.mjs";
import { RemoteConnection } from "./remote-transport.mjs";

const settings = { name: "build", host: "ssh-build", platform: "linux" };
const sshClient = path.resolve("ssh-client-for-test");
const sshError = "posix_spawnp: No such file or directory";
const message = `OpenSSH failed: ${sshError}`;

function registry(events = [], getConfig) {
  return createRemoteEnvironments({
    request: async () => ({ ok: true, environments: [settings] }),
    emit: event => events.push(event), getConfig,
  });
}

test("SSH test exposes the chosen executable and actual failure; state events retain retry detail", async context => {
  context.mock.method(RemoteConnection.prototype, "waitForReady", async function () {
    this.options.onState("connecting", { sshClient });
    this.options.onState("reconnecting", { message, sshError, attempt: 1, retryAfterMs: 60000, nextRetryAt: 1700000060000 });
    this.options.onState("error", { message, sshError });
    throw new Error(message);
  });
  const events = [], environments = registry(events);
  try {
    assert.deepEqual(await environments.test({ name: settings.name }), { ok: false, error: message, sshClient, sshError });
    assert.deepEqual(events[1], { type: "remote_environment_state", ...settings,
      state: "reconnecting", sshClient, message, sshError, attempt: 1, retryAfterMs: 60000, nextRetryAt: 1700000060000 });
    assert.equal(events[2].sshError, sshError);
    assert.equal(events[2].retryAfterMs, undefined);
  } finally { environments.dispose(); }
});

test("successful recovery returns client and removes obsolete SSH diagnostics", async context => {
  context.mock.method(RemoteConnection.prototype, "waitForReady", async function () {
    this.options.onState("reconnecting", { sshClient, message, sshError, attempt: 1, retryAfterMs: 60000 });
    this.options.onState("connected", {});
    return { cwd: "file:///work" };
  });
  const events = [], environments = registry(events);
  try {
    assert.deepEqual(await environments.test({ name: settings.name }), {
      ok: true, operation: "remote-environments.test", name: settings.name, state: "connected",
      platform: settings.platform, cwd: "file:///work", sshClient,
    });
    assert.deepEqual(events.at(-1), { type: "remote_environment_state", ...settings, state: "connected", sshClient });
  } finally { environments.dispose(); }
});

test("connection test reports waiting and recovery through Pi updates without temporary SSH errors", async context => {
  const signal = new AbortController().signal;
  context.mock.method(RemoteConnection.prototype, "waitForReady", async function (receivedSignal) {
    assert.equal(receivedSignal, signal);
    this.options.onState("reconnecting", { sshClient, message, sshError, attempt: 2, retryAfterMs: 60000,
      nextRetryAt: 1700000060000, outageStartedAt: 1700000000000 });
    this.options.onState("connected", { recovered: true, resumed: true, attempt: 2, outageStartedAt: 1700000000000 });
    return { cwd: "file:///work" };
  });
  const updates = [], environments = registry();
  try {
    assert.equal((await environments.test({ name: settings.name }, signal, update => updates.push(update))).ok, true);
    assert.deepEqual(updates.map(update => update.details.state), ["reconnecting", "connected"]);
    assert.equal(updates[0].details.nextRetryAt, 1700000060000);
    assert.equal(updates[1].details.resumed, true);
    assert.ok(updates.every(update => !update.isError && !update.details.sshError && !update.content[0].text.includes(sshError)));
  } finally { environments.dispose(); }
});

test("pending command calls receive reconnection progress and stop receiving it after completion", async context => {
  let connection;
  context.mock.method(RemoteConnection.prototype, "waitForReady", async function () {
    connection = this;
    this.options.onState("reconnecting", { attempt: 1, retryAfterMs: 60000, nextRetryAt: 1700000060000, message, sshError });
    this.options.onState("connected", { recovered: true, resumed: true });
    return { platformOs: "linux", userHomeDir: "file:///home/test", cwd: "file:///work" };
  });
  // Command readiness delegates to the bounded transport wait; keep this test
  // independent from the transport implementation and remote execution protocol.
  context.mock.method(RemoteConnection.prototype, "ready", async function () { return this.waitForReady(); });
  const tools = [], updates = [], environments = registry();
  environments.extension({ registerTool: tool => tools.push(tool) });
  try {
    await assert.rejects(tools.find(tool => tool.name === "remote_command").execute("call", {
      environment: settings.name, action: "read", sessionId: "unknown",
    }, undefined, update => updates.push(update), { cwd: process.cwd() }), /sessionId/);
    assert.deepEqual(updates.map(update => update.details.state), ["reconnecting", "connected"]);
    connection.options.onState("reconnecting", { attempt: 2, retryAfterMs: 60000 });
    assert.equal(updates.length, 2);
  } finally { environments.dispose(); }
});

test("file tools report reconnect progress alongside their ordinary result", async context => {
  context.mock.method(RemoteConnection.prototype, "waitForReady", async function () {
    this.options.onState("reconnecting", { attempt: 3, retryAfterMs: 60000, nextRetryAt: 1700000060000 });
    this.options.onState("connected", { recovered: true, resumed: false });
    return { platformOs: "linux", userHomeDir: "file:///home/test", cwd: "file:///work" };
  });
  context.mock.method(RemoteConnection.prototype, "ready", async function () { return this.waitForReady(); });
  context.mock.method(RemoteConnection.prototype, "rpc", async method => {
    if (method === "fs/getMetadata") return { isDirectory: true };
    if (method === "fs/readDirectory") return { entries: [] };
    throw new Error(`Unexpected RPC ${method}`);
  });
  const tools = [], updates = [], environments = registry();
  environments.extension({ registerTool: tool => tools.push(tool) });
  try {
    const result = await tools.find(tool => tool.name === "remote_files").execute("call", {
      environment: settings.name, action: "list", path: "/work",
    }, undefined, update => updates.push(update), { cwd: process.cwd() });
    assert.equal(result.isError, false);
    assert.deepEqual(result.details.entries, []);
    assert.deepEqual(updates.map(update => update.details.state), ["reconnecting", "connected"]);
    assert.equal(updates[1].details.resumed, false);
  } finally { environments.dispose(); }
});

test("expired connection test preserves SSH and retry fields in its error result", async context => {
  const detail = { code: "REMOTE_RECONNECT_TIMEOUT", state: "reconnecting", attempt: 10,
    nextRetryAt: 1700000660000, outageStartedAt: 1700000000000, sshClient, sshError };
  context.mock.method(RemoteConnection.prototype, "waitForReady", async function () {
    throw Object.assign(new Error("SSH reconnect wait expired"), detail);
  });
  const environments = registry();
  try {
    assert.deepEqual(await environments.test({ name: settings.name }), {
      ok: false, error: "SSH reconnect wait expired", ...detail,
    });
  } finally { environments.dispose(); }
});

test("invalid input and connection setup errors still return ordinary error results", async () => {
  const environments = registry([], () => ({ remoteTestSshCommand: [] }));
  for (const args of [null, undefined, {}, { name: "build", extra: true }]) {
    assert.deepEqual(await environments.test(args), { ok: false, error: "Provide the name of a configured remote environment." });
  }
  assert.deepEqual(await environments.test({ name: "build" }), { ok: false, error: "Invalid SSH command" });
  assert.match((await environments.test({ name: "missing" })).error, /Unknown remote environment/);
  environments.dispose();
});
