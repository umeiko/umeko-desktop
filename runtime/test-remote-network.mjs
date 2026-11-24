import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { test } from "node:test";
import { networkTestScript, remoteForwardStatus, remoteOutbound } from "./remote-network.mjs";
import { commandProxyEnvironment, commandProxySetup, prepareRemoteShellProcess } from "./remote-network-command.mjs";

test("configured HTTP proxy uses the selected endpoint without starting a direct proxy", async () => {
  const route = await remoteOutbound({ proxy: "http://127.0.0.1:12345" }, {});
  assert.deepEqual(route, { host: "127.0.0.1", port: 12345, outbound: "configured" });
  await assert.rejects(() => remoteOutbound({ proxy: "file:///tmp/proxy" }, {}), /代理地址或协议无效/);
});

test("OpenSSH allocated port belongs to the requested listener", () => {
  const route = { host: "127.0.0.1", port: 12345 };
  assert.equal(remoteForwardStatus("debug1: SSH\nAllocated port 46327 for remote forward to 127.0.0.1:12345\r\n", route), 46327);
  assert.equal(remoteForwardStatus("Allocated port 46327 for remote forward to 127.0.0.1:12346\n", route), undefined);
  assert.equal(remoteForwardStatus("Error: remote port forwarding failed for listen port 0\n", route), false);
});

test("probe uses the command environment and URL tests keep shell metacharacters as data", () => {
  const script = networkTestScript("linux", "https://example.com/?name=';false", 46327);
  assert.match(script, /--proxy' 'http:\/\/127\.0\.0\.1:46327'/);
  assert.match(script, /localhost,127\.0\.0\.1,::1/);
  const probe = networkTestScript("windows", "https://example.com", null, true);
  assert.doesNotMatch(probe, /'--(?:proxy|noproxy)'/);
  assert.match(probe, /\$env:HTTPS_PROXY/);
  assert.match(probe, /'--output' 'NUL'.*'--fail'/);
  assert.doesNotMatch(probe, /'--head'/);
  assert.throws(() => networkTestScript("linux", "file:///etc/hosts"), /HTTP/);
});

test("command egress has both Linux proxy cases, pip and npm overrides, and loopback exceptions", () => {
  const env = commandProxyEnvironment(46327, false, "/bin/bash");
  for (const key of ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "PIP_PROXY", "npm_config_proxy", "npm_config_https_proxy"]) {
    assert.equal(env[key], "http://127.0.0.1:46327");
  }
  assert.equal(env.no_proxy, "localhost,127.0.0.1,::1");
  assert.equal(env.NO_PROXY, env.no_proxy);
  assert.deepEqual(commandProxyEnvironment(undefined, false, "/bin/bash"), {});
});

test("POSIX setup appends a Git override without discarding existing entries", { skip: process.platform === "win32" }, () => {
  const env = { ...process.env, ...commandProxyEnvironment(46327, false, "/bin/sh"),
    GIT_CONFIG_COUNT: "1", GIT_CONFIG_KEY_0: "core.editor", GIT_CONFIG_VALUE_0: "nano" };
  const setup = commandProxySetup(false, "/bin/sh");
  const printed = execFileSync("/bin/sh", ["-c", setup + "printf '%s\\n' \"$GIT_CONFIG_COUNT\" \"$GIT_CONFIG_KEY_0\" \"$GIT_CONFIG_KEY_1\" \"$GIT_CONFIG_VALUE_1\""], { env, encoding: "utf8" });
  assert.equal(printed, "2\ncore.editor\nhttp.proxy\nhttp://127.0.0.1:46327\n");
});

test("streaming workspace bash gets shell setup and preserves unrelated process settings", () => {
  const original = { argv: ["/bin/bash", "-c", "sudo apt-get install -y sl"], cwd: "/work", env: { CUSTOM: "1" }, tty: false };
  const params = prepareRemoteShellProcess(original, 46327, false);
  assert.equal(params.env.http_proxy, "http://127.0.0.1:46327");
  assert.equal(params.env.CUSTOM, "1");
  assert.equal(params.cwd, "/work");
  assert.ok(params.argv[2].endsWith(original.argv[2]));
  assert.match(params.argv[2], /Acquire::https::Proxy/);
  assert.equal(prepareRemoteShellProcess(original, 0, false), original);
  assert.equal(prepareRemoteShellProcess(params, 46327, false), params);
});

test("Windows workspace Git Bash and encoded PowerShell retain their shell and command", () => {
  const bash = prepareRemoteShellProcess({ argv: ["C:\\Program Files\\Git\\bin\\bash.exe", "-c", "pip install six"] }, 46327, true);
  assert.equal(bash.env.PIP_PROXY, "http://127.0.0.1:46327");
  assert.match(bash.argv[2], /export http_proxy/);
  assert.ok(bash.argv[2].endsWith("pip install six"));
  const command = Buffer.from("git clone https://example.com/a.git", "utf16le").toString("base64");
  const ps = prepareRemoteShellProcess({ argv: ["powershell.exe", "-NoProfile", "-EncodedCommand", command] }, 46327, true);
  assert.match(Buffer.from(ps.argv.at(-1), "base64").toString("utf16le"), /GIT_CONFIG_COUNT.*\n[\s\S]+git clone/);
});
