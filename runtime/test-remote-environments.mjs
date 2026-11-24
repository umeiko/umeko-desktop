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
  context.mock.method(RemoteConnection.prototype, "ready", async function () {
    this.options.onState("connecting", { sshClient });
    this.options.onState("reconnecting", { message, sshError, attempt: 1, retryAfterMs: 60000 });
    this.options.onState("error", { message, sshError });
    throw new Error(message);
  });
  const events = [], environments = registry(events);
  try {
    assert.deepEqual(await environments.test({ name: settings.name }), { ok: false, error: message, sshClient, sshError });
    assert.deepEqual(events[1], { type: "remote_environment_state", ...settings,
      state: "reconnecting", sshClient, message, sshError, attempt: 1, retryAfterMs: 60000 });
    assert.equal(events[2].sshError, sshError);
    assert.equal(events[2].retryAfterMs, undefined);
  } finally { environments.dispose(); }
});

test("successful recovery returns client and removes obsolete SSH diagnostics", async context => {
  context.mock.method(RemoteConnection.prototype, "ready", async function () {
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

test("invalid input and connection setup errors still return ordinary error results", async () => {
  const environments = registry([], () => ({ remoteTestSshCommand: [] }));
  for (const args of [null, undefined, {}, { name: "build", extra: true }]) {
    assert.deepEqual(await environments.test(args), { ok: false, error: "Provide the name of a configured remote environment." });
  }
  assert.deepEqual(await environments.test({ name: "build" }), { ok: false, error: "Invalid SSH command" });
  assert.match((await environments.test({ name: "missing" })).error, /Unknown remote environment/);
  environments.dispose();
});
