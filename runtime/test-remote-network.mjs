import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { test } from "node:test";
import { networkTestScript, remoteForwardStatus, remoteOutbound } from "./remote-network.mjs";
import { commandProxyEnvironment, commandProxySetup } from "./remote-network-command.mjs";

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

test("probe ignores stale proxies and URL tests keep shell metacharacters as data", () => {
  const script = networkTestScript("linux", "https://example.com/?name=';false", 46327);
  assert.match(script, /--proxy' 'http:\/\/127\.0\.0\.1:46327'/);
  assert.match(script, /localhost,127\.0\.0\.1,::1/);
  assert.match(networkTestScript("windows", "https://example.com", null, true), /'--noproxy' '\*'/);
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
