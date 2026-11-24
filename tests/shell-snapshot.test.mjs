import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";
import { test } from "node:test";
import { createShellSnapshots, parseCapturedEnvironment, preferRealExecutables } from "../runtime/shell-snapshot.mjs";

test("a shell snapshot reads exported values and does not retain secrets or mutable shell state", () => {
  const output = "profile banner\n\0UMEKO_SHELL_ENV\0PATH=a\0VALUE=one=two\nthree\0TEST_API_KEY=secret\0PWD=old\0PI_SESSION_ID=other\0";
  assert.deepEqual({ ...parseCapturedEnvironment(output) }, { PATH: "a", VALUE: "one=two\nthree" });
  assert.throws(() => parseCapturedEnvironment("failure"), /Missing shell environment/);
});

test("a session falls back to its own inherited environment, refreshes, and retains bundled tools", async () => {
  const snapshots = createShellSnapshots({ getShellConfig: () => null, getPowerShellConfig: () => null, bundledBin: "bundled-tools" });
  const key = "UMEKO_SNAPSHOT_TEST_VALUE";
  try {
    process.env[key] = "first";
    const original = await snapshots.environment("bash", "first", { PI_SESSION_ID: "first" });
    assert.equal(original[key], "first");
    assert.equal(original.PI_SESSION_ID, "first");
    assert.equal(Object.entries(original).find(([name]) => name.toUpperCase() === "PATH")[1].split(delimiter)[0], "bundled-tools");
    process.env[key] = "second";
    assert.equal((await snapshots.environment("bash", "first"))[key], "first");
    assert.equal((await snapshots.environment("bash", "second"))[key], "second");
    assert.equal((await snapshots.refresh("first")).bash, "inherited");
    assert.equal((await snapshots.environment("bash", "first"))[key], "second");
  } finally {
    delete process.env[key];
  }
});

test("Windows PATH puts a real executable before a conflicting Store alias", { skip: process.platform !== "win32" }, async () => {
  const root = await mkdtemp(join(tmpdir(), "umeko-shell-path-"));
  const aliases = join(root, "Microsoft", "WindowsApps");
  const real = join(root, "Python");
  try {
    await mkdir(aliases, { recursive: true });
    await mkdir(real);
    await writeFile(join(aliases, "python.exe"), "");
    assert.deepEqual(preferRealExecutables([aliases, real]), [aliases, real]);
    await writeFile(join(real, "python.exe"), "installed");
    assert.deepEqual(preferRealExecutables([aliases, real]), [real, aliases]);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
