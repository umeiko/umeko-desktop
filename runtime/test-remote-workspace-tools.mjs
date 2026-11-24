import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import * as piTools from "@earendil-works/pi-coding-agent";
import { createRemoteWorkspaceExtension } from "./remote-workspace-tools.mjs";
import { createRemoteEnvironments } from "./remote-environments.mjs";
import { DEFAULT_RECONNECT_DELAYS_MS, RemoteConnection } from "./remote-transport.mjs";
import { nativePathFromUri, normalizeRemotePath, remotePathToUri } from "./remote-paths.mjs";

function makeMemoryRemote({ platform = "linux", homeDir = "/home/dev", initialFiles = {}, processHandler } = {}) {
  const dirs = new Set([normalizeRemotePath(homeDir, platform)]);
  const files = new Map();
  const norm = p => normalizeRemotePath(p, platform);
  const ensureParents = filePath => {
    const sep = platform === "windows" ? "\\" : "/";
    const parts = norm(filePath).split(sep);
    let cur = platform === "windows" ? `${parts[0]}\\` : "";
    if (platform === "windows") dirs.add(cur);
    for (let i = platform === "windows" ? 1 : 0; i < parts.length - 1; i++) {
      if (!parts[i]) continue;
      cur = cur === "" ? `/${parts[i]}` : cur.endsWith(sep) ? `${cur}${parts[i]}` : `${cur}${sep}${parts[i]}`;
      dirs.add(norm(cur));
    }
  };
  for (const [k, v] of Object.entries(initialFiles)) {
    const p = norm(k);
    ensureParents(p);
    files.set(p, Buffer.isBuffer(v) ? v : Buffer.from(String(v), "utf8"));
  }
  let procSeq = 0;
  const procs = new Map();
  const processCalls = [];

  const connection = {
    state: "connected",
    async ready() {
      return {
        cwd: remotePathToUri(homeDir, platform),
        userHomeDir: remotePathToUri(homeDir, platform),
        platformOs: platform,
        shell: platform === "windows" ? { name: "powershell", path: "powershell.exe" } : { name: "bash", path: "/bin/bash" },
      };
    },
    async rpc(method, params = {}) {
      if (method === "fs/canonicalize") {
        const native = norm(nativePathFromUri(params.path, platform));
        if (!dirs.has(native) && !files.has(native)) throw new Error(`ENOENT: ${native}`);
        return { path: remotePathToUri(native, platform) };
      }
      if (method === "fs/getMetadata") {
        const native = norm(nativePathFromUri(params.path, platform));
        if (files.has(native)) return { isFile: true, isDirectory: false, isSymlink: false, size: files.get(native).length };
        if (dirs.has(native)) return { isFile: false, isDirectory: true, isSymlink: false, size: 0 };
        throw new Error(`ENOENT: no such file or directory: ${native}`);
      }
      if (method === "fs/readFile") {
        const native = norm(nativePathFromUri(params.path, platform));
        if (!files.has(native)) throw new Error(`ENOENT: ${native}`);
        return { dataBase64: files.get(native).toString("base64") };
      }
      if (method === "fs/writeFile") {
        const native = norm(nativePathFromUri(params.path, platform));
        ensureParents(native);
        files.set(native, Buffer.from(params.dataBase64, "base64"));
        return {};
      }
      if (method === "fs/createDirectory") {
        const native = norm(nativePathFromUri(params.path, platform));
        ensureParents(native + (platform === "windows" ? "\\_" : "/_"));
        dirs.add(native);
        return {};
      }
      if (method === "fs/readDirectory") {
        const native = norm(nativePathFromUri(params.path, platform));
        if (!dirs.has(native)) throw new Error(`ENOENT: ${native}`);
        const sep = platform === "windows" ? "\\" : "/";
        const prefix = native.endsWith(sep) ? native : native + sep;
        const found = new Map();
        for (const d of dirs) {
          if (d === native || !d.startsWith(prefix)) continue;
          const rest = d.slice(prefix.length);
          const head = rest.split(sep)[0];
          if (head && !found.has(head)) found.set(head, { fileName: head, isDirectory: true, isFile: false });
        }
        for (const f of files.keys()) {
          if (!f.startsWith(prefix)) continue;
          const rest = f.slice(prefix.length);
          const segs = rest.split(sep);
          if (segs.length === 1) found.set(segs[0], { fileName: segs[0], isDirectory: false, isFile: true });
          else if (!found.has(segs[0])) found.set(segs[0], { fileName: segs[0], isDirectory: true, isFile: false });
        }
        return { entries: [...found.values()] };
      }
      if (method === "fs/remove") {
        const native = norm(nativePathFromUri(params.path, platform));
        files.delete(native);
        dirs.delete(native);
        return {};
      }
      if (method === "process/start") {
        processCalls.push(params);
        const result = processHandler
          ? await processHandler(params)
          : { stdout: "", stderr: "", exitCode: 0 };
        const id = params.processId || `p-${++procSeq}`;
        procs.set(id, { ...result, read: false });
        return { processId: id };
      }
      if (method === "process/read") {
        const proc = procs.get(params.processId);
        if (!proc) return { chunks: [], nextSeq: 1, exited: true, exitCode: 0 };
        const chunks = [];
        if (!proc.read) {
          proc.read = true;
          if (proc.stdout) chunks.push({ stream: "stdout", chunk: Buffer.from(proc.stdout, "utf8").toString("base64"), seq: 1 });
          if (proc.stderr) chunks.push({ stream: "stderr", chunk: Buffer.from(proc.stderr, "utf8").toString("base64"), seq: 2 });
        }
        return { chunks, nextSeq: 3, exited: true, exitCode: proc.exitCode ?? 0 };
      }
      if (method === "process/terminate") return {};
      throw new Error(`Unexpected RPC: ${method}`);
    },
  };
  return { dirs, files, connection, processCalls, entry: { name: "srv", host: "dev-host", platform, connection, windowsBashPath: undefined } };
}

function mountExtension(remote, { remotePath, host = "dev-host", platform = "linux", localCwd }) {
  const registered = new Map();
  const events = new Map();
  const statusEvents = [];
  const pi = {
    registerTool: def => registered.set(def.name, def),
    on: (name, fn) => events.set(name, fn),
  };
  const ext = createRemoteWorkspaceExtension({
    remoteWorkspace: { environment: "srv", host, platform, remotePath },
    getEntry: async () => remote.entry,
    emit: ev => statusEvents.push(ev),
    localCwd,
    toolsApi: piTools,
  });
  ext(pi);
  return { registered, events, statusEvents };
}

test("all 7 Pi built-in tools, user_bash, and system prompt route to remote without touching local mirror", async () => {
  const localCwd = mkdtempSync(path.join(tmpdir(), "umeko-rw-mirror-"));
  try {
    const pngBytes = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
      "base64",
    );
    const remote = makeMemoryRemote({
      platform: "linux",
      homeDir: "/home/dev",
      initialFiles: {
        "/home/dev/app/hello.txt": "alpha\nbeta needle\ngamma\n",
        "/home/dev/app/sub/nested.js": "export const value = 'needle here';\n",
        "/home/dev/app/logo.png": pngBytes,
      },
      processHandler: params => {
        if (params.argv[0] === "rg") {
          const matchLine = JSON.stringify({
            type: "match",
            data: {
              path: { text: "./hello.txt" },
              line_number: 2,
              lines: { text: "beta needle\n" },
            },
          });
          return { stdout: matchLine + "\n", stderr: "", exitCode: 0 };
        }
        return { stdout: `RAN:${params.argv.join(" ")}@${params.cwd}\n`, stderr: "", exitCode: 0 };
      },
    });
    const { registered, events } = mountExtension(remote, {
      remotePath: "/home/dev/app",
      platform: "linux",
      localCwd,
    });
    for (const name of ["read", "write", "edit", "bash", "powershell", "ls", "find", "grep"]) {
      assert.ok(registered.has(name), `missing tool ${name}`);
    }

    // 1. read text + image mime sniff
    const readRes = await registered.get("read").execute("1", { path: "hello.txt" });
    assert.match(readRes.content[0].text, /beta needle/);
    const imgRes = await registered.get("read").execute("2", { path: "logo.png" });
    assert.ok(imgRes.content.some(c => c.type === "image" && c.mimeType === "image/png"));

    // 2. write
    await registered.get("write").execute("3", { path: "sub/created.txt", content: "created on remote\n" });
    assert.equal(remote.files.get("/home/dev/app/sub/created.txt").toString("utf8"), "created on remote\n");

    // 3. edit
    await registered.get("edit").execute("4", {
      path: "hello.txt",
      edits: [{ oldText: "beta needle", newText: "beta UPDATED" }],
    });
    assert.match(remote.files.get("/home/dev/app/hello.txt").toString("utf8"), /beta UPDATED/);

    // 4. bash (and user_bash !)
    const bashRes = await registered.get("bash").execute("5", { command: "echo hi" });
    assert.match(bashRes.content[0].text, /RAN:\/bin\/bash -c echo hi@file:\/\/\/home\/dev\/app/);
    const userBash = events.get("user_bash")({}, {});
    let captured = "";
    const ubRes = await userBash.operations.exec("pwd", localCwd, { onData: buf => { captured += buf.toString("utf8"); } });
    assert.equal(ubRes.exitCode, 0);
    assert.match(captured, /\/home\/dev\/app/);

    // 5. ls
    const lsRes = await registered.get("ls").execute("6", { path: "." });
    assert.match(lsRes.content[0].text, /hello\.txt/);
    assert.match(lsRes.content[0].text, /sub\//);

    // 6. find
    const findRes = await registered.get("find").execute("7", { pattern: "*.js" });
    assert.match(findRes.content[0].text, /sub\/nested\.js/);

    // 7. grep (Strategy A: remote rg)
    const grepRes = await registered.get("grep").execute("8", { pattern: "needle" });
    assert.match(grepRes.content[0].text, /hello\.txt:2: beta needle/);

    // before_agent_start rewrites cwd to remote host:remotePath
    const promptRes = await events.get("before_agent_start")({
      systemPrompt: `Intro\nCurrent working directory: ${localCwd}\nOutro`,
    });
    assert.match(promptRes.systemPrompt, /Current working directory: \/home\/dev\/app \(remote workspace dev-host:\/home\/dev\/app, platform: linux\)/);
    assert.doesNotMatch(promptRes.systemPrompt, new RegExp(localCwd.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  } finally {
    rmSync(localCwd, { recursive: true, force: true });
  }
});

test("grep falls back from rg to POSIX grep -rn and then to remote filesystem walk", async () => {
  const localCwd = mkdtempSync(path.join(tmpdir(), "umeko-rw-grep-"));
  try {
    // Strategy B: rg missing -> POSIX grep -rn
    const remoteGrep = makeMemoryRemote({
      platform: "linux",
      homeDir: "/home/dev",
      initialFiles: { "/home/dev/repo/a.txt": "line1\ntarget match\n" },
      processHandler: params => {
        if (params.argv[0] === "rg") throw new Error("ENOENT: rg not found");
        if (params.argv[0] === "grep") return { stdout: "./a.txt:2:target match\n", stderr: "", exitCode: 0 };
        return { stdout: "", stderr: "", exitCode: 1 };
      },
    });
    const m1 = mountExtension(remoteGrep, { remotePath: "/home/dev/repo", platform: "linux", localCwd });
    const resB = await m1.registered.get("grep").execute("g1", { pattern: "target" });
    assert.match(resB.content[0].text, /a\.txt:2: target match/);

    // Strategy C: Windows remote without rg -> remote fs walk
    const remoteWalk = makeMemoryRemote({
      platform: "windows",
      homeDir: "C:\\Users\\dev",
      initialFiles: {
        "C:\\work\\one.txt": "first\nNEEDLE line\nlast\n",
        "C:\\work\\bin.dat": Buffer.from([0, 1, 2, 3]),
      },
      processHandler: () => { throw new Error("ENOENT: rg not found"); },
    });
    const m2 = mountExtension(remoteWalk, { remotePath: "C:\\work", platform: "windows", localCwd });
    const resC = await m2.registered.get("grep").execute("g2", { pattern: "needle", ignoreCase: true, context: 1 });
    assert.match(resC.content[0].text, /one\.txt-1- first/);
    assert.match(resC.content[0].text, /one\.txt:2: NEEDLE line/);
    assert.match(resC.content[0].text, /one\.txt-3- last/);
  } finally {
    rmSync(localCwd, { recursive: true, force: true });
  }
});

test("remote-environments browse, mkdir, home, and Windows drive listing", async context => {
  const winRemote = makeMemoryRemote({
    platform: "windows",
    homeDir: "C:\\Users\\dev",
    initialFiles: { "C:\\work\\sub\\a.txt": "hi", "C:\\work\\file.txt": "rootfile" },
    processHandler: () => ({ stdout: "C:\\\r\nD:\\\r\n", stderr: "", exitCode: 0 }),
  });
  winRemote.dirs.add("C:\\work\\sub");
  winRemote.dirs.add("C:\\work\\empty");

  context.mock.method(RemoteConnection.prototype, "ready", async function () { return winRemote.connection.ready(); });
  context.mock.method(RemoteConnection.prototype, "rpc", async function (method, params) { return winRemote.connection.rpc(method, params); });

  const envs = createRemoteEnvironments({
    request: async () => ({ ok: true, environments: [{ name: "winbox", host: "win-host", platform: "windows" }] }),
    emit: () => {},
  });
  try {
    const home = await envs.home({ name: "winbox" });
    assert.equal(home.ok, true);
    assert.equal(home.home, "C:\\Users\\dev");

    // Empty path on Windows remote lists drives
    const drives = await envs.browse({ name: "winbox", path: "" });
    assert.equal(drives.ok, true);
    assert.deepEqual(drives.entries.map(e => e.name), ["C:\\", "D:\\"]);
    assert.equal(drives.isDriveList, true);

    // Browse directories only
    const listing = await envs.browse({ name: "winbox", path: "C:\\work" });
    assert.equal(listing.ok, true);
    assert.deepEqual(listing.entries.map(e => e.name), ["empty", "sub"]);
    assert.equal(listing.parent, "C:\\");

    // Recursive mkdir
    const created = await envs.mkdir({ name: "winbox", path: "C:\\work\\new-dir\\nested" });
    assert.equal(created.ok, true);
    assert.ok(winRemote.dirs.has("C:\\work\\new-dir\\nested"));
  } finally {
    envs.dispose();
  }
});

test("RemoteConnection reconnects with growing intervals and reports plain-language timeout while retrying", async () => {
  assert.ok(DEFAULT_RECONNECT_DELAYS_MS.length >= 6);
  assert.ok(DEFAULT_RECONNECT_DELAYS_MS[0] < DEFAULT_RECONNECT_DELAYS_MS.at(-1));

  const delays = [5, 10, 20];
  const observed = [];
  const conn = new RemoteConnection({ host: "unreachable-alias", platform: "linux" }, {
    sshCommand: process.execPath,
    reconnectDelaysMs: delays,
    outageTimeoutMs: 45,
    onState: (state, detail) => observed.push({ state, ...detail }),
  });
  conn._selectSsh = async () => {};
  conn._bootstrap = async () => {
    throw Object.assign(new Error("Connection refused"), { transport: true, sshError: "Connection refused" });
  };
  await assert.rejects(conn.waitForReady(), /The host has not reconnected.*Connection refused/s);
  const reconnecting = observed.filter(e => e.state === "reconnecting" && e.retryAfterMs !== undefined);
  assert.ok(reconnecting.length >= 2);
  assert.equal(reconnecting[0].retryAfterMs, 5);
  assert.equal(reconnecting[1].retryAfterMs, 10);
  conn.close();
});
