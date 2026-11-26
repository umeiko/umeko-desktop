import test from "node:test";
import assert from "node:assert/strict";
import childProcess from "node:child_process";
import fs from "node:fs/promises";
import { selectSshClient } from "./remote-ssh-client.mjs";

const native = "C:\\shell\\ssh.exe";
const git = "C:\\Program Files\\Git\\usr\\bin\\ssh.exe";
const baseEnv = { Path: "C:\\shell;C:\\Windows\\System32\\OpenSSH", ProgramFiles: "C:\\Program Files" };

function fixture(t, { files = [native, git], configs = {}, fail } = {}) {
  const calls = [];
  t.mock.method(fs, "stat", async file => {
    if (!files.includes(file)) throw Object.assign(new Error("missing"), { code: "ENOENT" });
    return { isFile: () => true };
  });
  t.mock.method(fs, "access", async () => {});
  t.mock.method(childProcess, "execFile", (file, args, options, callback) => {
    calls.push({ file, args, options });
    assert.equal(args[0], "-G");
    assert.equal(options.shell, undefined);
    assert.equal(options.windowsHide, true);
    queueMicrotask(() => callback(fail || null, configs[args.at(-1)] || "hostname example.invalid\nidentityfile ~/.ssh/id_ed25519\n"));
  });
  return calls;
}

test("uses an absolute executable in the caller's PATH order and forwards its environment", async t => {
  const calls = fixture(t, { files: [native, "C:\\Windows\\System32\\OpenSSH\\ssh.exe", git] });
  assert.equal(await selectSshClient("target", { env: baseEnv, platform: "win32", userHome: "C:\\example" }), native);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.env, baseEnv);
  assert.equal(calls[0].file, native);
});

test("falls back for effective POSIX identity paths and POSIX ProxyCommand executables", async t => {
  const calls = fixture(t, { configs: {
    target: "identityfile /c/example/identity\n",
    proxy: "proxycommand /usr/bin/ssh -W %h:%p gateway\n",
  } });
  for (const host of ["target", "proxy"]) {
    assert.equal(await selectSshClient(host, { env: baseEnv, platform: "win32", userHome: "C:\\example" }), git);
  }
  assert.equal(calls.length, 2);
});

test("follows direct ssh proxy chains with their own config options without launching proxies", async t => {
  const calls = fixture(t, { configs: {
    target: 'proxycommand ssh -F "C:/example/config" -W %h:%p gateway\n',
    gateway: "proxycommand ssh -p 2222 -W %h:%p relay\n",
    relay: "identityfile /d/example/identity\n",
  } });
  assert.equal(await selectSshClient("target", { env: baseEnv, platform: "win32" }), git);
  assert.deepEqual(calls.map(call => call.args), [
    ["-G", "target"],
    ["-G", "-F", "C:/example/config", "gateway"],
    ["-G", "-p", "2222", "relay"],
  ]);
});

test("checks ProxyJump hosts and terminates cyclic chains", async t => {
  const calls = fixture(t, { configs: {
    target: "proxyjump demo@gateway:2222,relay\n",
    gateway: "proxycommand ssh -W %h:%p target\n",
    relay: "identityfile /c/example/identity\n",
  } });
  assert.equal(await selectSshClient("target", { env: baseEnv, platform: "win32" }), git);
  assert.deepEqual(calls.map(call => call.args), [["-G", "target"], ["-G", "-l", "demo", "-p", "2222", "gateway"], ["-G", "relay"]]);
});

test("discovers portable Git from PATH and retains an existing Git SSH preference", async t => {
  const portable = "D:\\tools\\Git\\usr\\bin\\ssh.exe";
  const files = [native, "D:\\tools\\Git\\cmd\\git.exe", portable];
  const calls = fixture(t, { files, configs: { target: "proxycommand ssh -i /c/example/identity gateway\n" } });
  assert.equal(await selectSshClient("target", { env: { PATH: "C:\\shell;D:\\tools\\Git\\cmd" }, platform: "win32" }), portable);
  assert.equal(await selectSshClient("target", { env: { PATH: '"D:\\tools\\Git\\usr\\bin";C:\\shell' }, platform: "win32" }), portable);
  assert.equal(calls.length, 1);
});

test("native Windows and UNC paths do not trigger Git fallback", async t => {
  fixture(t, { configs: { target: 'identityfile C:/example/identity\nidentityfile //server/example/identity\nproxycommand "C:/example/nc.exe" %h %p\n' } });
  assert.equal(await selectSshClient("target", { env: baseEnv, platform: "win32" }), native);
});

test("missing POSIX-capable SSH and invalid config produce actionable sanitized errors", async t => {
  fixture(t, { files: [native], configs: { target: "identityfile /c/example/identity\n" } });
  await assert.rejects(selectSshClient("target", { env: baseEnv, platform: "win32" }), /Install Git for Windows/);
  t.mock.restoreAll();
  fixture(t, { fail: new Error("private fixture diagnostic") });
  await assert.rejects(selectSshClient("target", { env: baseEnv, platform: "win32" }), error => /ssh -G/.test(error.message) && !/private fixture/.test(error.message));
});

test("Unix uses its shell PATH without config probes; absent SSH and invalid aliases fail before spawning", async t => {
  const calls = fixture(t, { files: ["/opt/example/bin/ssh"] });
  assert.equal(await selectSshClient("target", { env: { PATH: "/opt/example/bin:/usr/bin" }, platform: "linux" }), "/opt/example/bin/ssh");
  await assert.rejects(selectSshClient("target", { env: { PATH: "/missing" }, platform: "linux" }), /not found on PATH/);
  await assert.rejects(selectSshClient("-oProxyCommand=bad", { env: baseEnv, platform: "win32" }), /host alias/);
  assert.equal(calls.length, 0);
});
