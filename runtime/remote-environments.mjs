import { randomUUID } from "node:crypto";
import { Type } from "typebox";
import { createRemoteCommands } from "./remote-command.mjs";
import { createRemoteFiles } from "./remote-files.mjs";
import {
  joinRemotePath,
  nativePathFromUri,
  normalizeRemotePath,
  remoteDirname,
  remotePathToUri,
  resolveRemoteWorkspacePath,
} from "./remote-paths.mjs";
import { selectSshClient } from "./remote-ssh-client.mjs";
import { listSshConfigHosts } from "./remote-ssh-config.mjs";
import { RemoteConnection, detectRemotePlatform } from "./remote-transport.mjs";

const select = (...values) => Type.Union(values.map(value => Type.Literal(value)));
const name = Type.String({ minLength: 1, maxLength: 64 });
const pathname = Type.String({ minLength: 1, maxLength: 4096 });
const quoteSh = value => `'${String(value).replaceAll("'", "'\\''")}'`;
const quotePs = value => `'${String(value).replaceAll("'", "''")}'`;
const isMissingError = error => /ENOENT|not found|no such file|cannot find|os error 2\b|os error 3\b|系统找不到指定的文件|系统找不到指定的路径/i.test(String(error?.message ?? error));

const commandArgs = Type.Object({
  action: select("run", "read", "write", "kill"),
  environment: name,
  command: Type.Optional(Type.String({ minLength: 1, maxLength: 65536 })),
  cwd: Type.Optional(pathname),
  yieldMs: Type.Optional(Type.Integer({ minimum: 0, maximum: 30000 })),
  maxOutputBytes: Type.Optional(Type.Integer({ minimum: 1, maximum: 256 * 1024 })),
  sessionId: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
  input: Type.Optional(Type.String({ minLength: 1, maxLength: 65536 })),
}, { additionalProperties: false });

const fileArgs = Type.Object({
  action: select("read", "write", "list", "search", "upload", "download"),
  environment: name,
  path: pathname,
  cwd: Type.Optional(pathname),
  localPath: Type.Optional(pathname),
  content: Type.Optional(Type.String({ maxLength: 512 * 1024 })),
  query: Type.Optional(Type.String({ minLength: 1, maxLength: 1024 })),
  offset: Type.Optional(Type.Integer({ minimum: 0 })),
  maxBytes: Type.Optional(Type.Integer({ minimum: 1, maximum: 8 * 1024 * 1024 })),
  maxEntries: Type.Optional(Type.Integer({ minimum: 1, maximum: 10000 })),
  maxMatches: Type.Optional(Type.Integer({ minimum: 1, maximum: 2000 })),
  encoding: Type.Optional(select("utf8", "base64")),
  recursive: Type.Optional(Type.Boolean()),
  caseSensitive: Type.Optional(Type.Boolean()),
}, { additionalProperties: false });

function response(result) {
  return { content: [{ type: "text", text: JSON.stringify(result) }], details: result, isError: result.ok === false };
}

function powershellUtf8Argv(script) {
  const full = "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)\n" +
    "[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)\n" +
    "$OutputEncoding = [Console]::OutputEncoding\n" +
    String(script || "");
  return ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", Buffer.from(full, "utf16le").toString("base64")];
}

export async function runRemoteProcess(connection, platform, {
  argv,
  cwd,
  env = {},
  timeoutMs,
  maxOutputBytes = 4 * 1024 * 1024,
  onData,
  signal,
} = {}) {
  signal?.throwIfAborted();
  const info = typeof connection.waitForReady === "function"
    ? await connection.waitForReady(signal)
    : await connection.ready();
  const effectivePlatform = platform || (String(info.platformOs || "").toLowerCase() === "windows" ? "windows" : "linux");
  const home = nativePathFromUri(info.userHomeDir || info.cwd, effectivePlatform);
  const resolvedCwd = resolveRemoteWorkspacePath(nativePathFromUri(info.cwd || info.userHomeDir, effectivePlatform), cwd || ".", {
    platform: effectivePlatform,
    homeDir: home,
  });
  const processId = `umeko-proc-${randomUUID()}`;
  const cleanEnv = {};
  for (const [k, v] of Object.entries(env || {})) {
    if (typeof v === "string") cleanEnv[k] = v;
  }
  await connection.rpc("process/start", {
    processId,
    argv,
    cwd: remotePathToUri(resolvedCwd, effectivePlatform),
    envPolicy: { inherit: "all", ignoreDefaultExcludes: false, exclude: [], set: cleanEnv, includeOnly: [] },
    env: cleanEnv,
    tty: false,
    pipeStdin: false,
    arg0: null,
  }, { signal, retry: false });

  const stdoutChunks = [];
  const stderrChunks = [];
  const combinedChunks = [];
  let totalBytes = 0;
  let truncated = false;
  let afterSeq = null;
  let exited = false;
  let exitCode = null;
  let failure = null;
  let timedOut = false;
  let aborted = false;
  const deadline = timeoutMs && timeoutMs > 0 ? Date.now() + timeoutMs : null;

  const terminate = () => connection.rpc("process/terminate", { processId }, { retry: false }).catch(() => {});
  const onAbort = () => { aborted = true; void terminate(); };
  signal?.addEventListener("abort", onAbort, { once: true });

  try {
    while (!exited) {
      if (signal?.aborted) {
        aborted = true;
        await terminate();
        break;
      }
      const remaining = deadline !== null ? deadline - Date.now() : 500;
      if (deadline !== null && remaining <= 0) {
        timedOut = true;
        await terminate();
        break;
      }
      const waitMs = Math.max(20, Math.min(500, remaining));
      const page = await connection.rpc("process/read", {
        processId,
        afterSeq,
        maxBytes: 65536,
        waitMs,
      }, { signal });
      afterSeq = page.nextSeq ?? afterSeq;
      for (const item of page.chunks || []) {
        const buf = Buffer.from(item.chunk, "base64");
        if (!buf.length) continue;
        onData?.(buf, item.stream);
        if (totalBytes < maxOutputBytes) {
          const slice = buf.length + totalBytes > maxOutputBytes ? buf.subarray(0, maxOutputBytes - totalBytes) : buf;
          totalBytes += slice.length;
          if (slice.length < buf.length) truncated = true;
          if (item.stream === "stderr") stderrChunks.push(slice);
          else stdoutChunks.push(slice);
          combinedChunks.push(slice);
        } else {
          truncated = true;
        }
      }
      if (page.failure) failure = page.failure;
      if (page.exited || page.closed) {
        exited = true;
        exitCode = page.exitCode ?? (failure ? 1 : 0);
      }
    }
  } finally {
    signal?.removeEventListener("abort", onAbort);
  }

  return {
    stdout: Buffer.concat(stdoutChunks).toString("utf8"),
    stderr: Buffer.concat(stderrChunks).toString("utf8"),
    combined: Buffer.concat(combinedChunks).toString("utf8"),
    stdoutBytes: Buffer.concat(stdoutChunks),
    stderrBytes: Buffer.concat(stderrChunks),
    exitCode,
    failure,
    timedOut,
    aborted,
    truncated,
  };
}

/**
 * List available drive roots on a Windows remote (e.g. C:\, D:\).
 * Adapted from dsh-remote 1.4.1 (lib/remote-fs.js & lib/routes-fs.js), MIT.
 */
async function listRemoteWindowsDrives(connection, signal) {
  const result = await runRemoteProcess(connection, "windows", {
    argv: powershellUtf8Argv("[IO.DriveInfo]::GetDrives() | Where-Object { $_.IsReady } | ForEach-Object { $_.Name }"),
    timeoutMs: 15_000,
    signal,
  });
  let drives = result.stdout
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(line => /^[A-Za-z]:\\?$/.test(line))
    .map(line => `${line[0].toUpperCase()}:\\`);
  if (!drives.length) {
    const fallback = await runRemoteProcess(connection, "windows", {
      argv: ["cmd.exe", "/d", "/c", "fsutil fsinfo drives"],
      timeoutMs: 10_000,
      signal,
    }).catch(() => ({ stdout: "" }));
    drives = (fallback.stdout.match(/[A-Za-z]:\\/g) || []).map(d => `${d[0].toUpperCase()}:\\`);
  }
  const unique = [...new Set(drives)].sort();
  return unique.map(drive => ({ name: drive, path: drive, isDirectory: true, isFile: false, isDrive: true }));
}

function connectionProgress(name, status) {
  if (status.state !== "reconnecting" && !(status.state === "connected" && status.recovered)) return;
  const result = { ok: true, operation: "remote-environments.reconnect", environment: name, state: status.state,
    message: status.state === "reconnecting" ? "正在重新连接" : "连接已恢复" };
  for (const key of ["attempt", "retryAfterMs", "nextRetryAt", "outageStartedAt", "recovered", "resumed"]) {
    if (status[key] !== undefined) result[key] = status[key];
  }
  return response(result);
}

function connectionErrorDetails(error) {
  return Object.fromEntries(["code", "sshClient", "sshError", "state", "attempt", "retryAfterMs", "nextRetryAt", "outageStartedAt"]
    .filter(key => error[key] !== undefined).map(key => [key, error[key]]));
}

export function createRemoteEnvironments({ request, emit, getConfig = () => ({}), getSshEnvironment }) {
  const live = new Map();

  async function withProgress(name, entry, onUpdate, operation) {
    let reconnection;
    const update = status => {
      const progress = connectionProgress(name, status);
      if (!progress) return;
      if (status.recovered) reconnection = progress.details;
      onUpdate?.(progress);
    };
    entry.listeners.add(update);
    try {
      if (entry.status.state === "reconnecting" ||
          entry.status.recovered && entry.lastReportedRecovery !== entry.status.outageStartedAt) update(entry.status);
      const result = await operation();
      if (!reconnection) return result;
      entry.lastReportedRecovery = reconnection.outageStartedAt;
      return { ...result, reconnection };
    }
    finally { entry.listeners.delete(update); }
  }

  async function toolResult(name, entry, onUpdate, operation) {
    try { return response(await withProgress(name, entry, onUpdate, operation)); }
    catch (error) {
      if (error.code !== "REMOTE_RECONNECT_TIMEOUT") throw error;
      return response({ ok: false, error: error.message, ...connectionErrorDetails(error) });
    }
  }

  function close(name) {
    const entry = live.get(name);
    if (!entry) return;
    live.delete(name);
    entry.connection.close();
  }

  async function environment(name, signal) {
    const result = await request("remote-environments.list", {}, signal);
    if (!result.ok) throw new Error(result.error || "Unable to load remote environments.");
    const settings = result.environments.find(row => row.name === name);
    if (!settings) {
      close(name);
      throw new Error(`Unknown remote environment "${name}". Add it with umeko_desktop first.`);
    }
    const current = live.get(name);
    if (current && current.host === settings.host && current.platform === settings.platform) return current;
    close(name);
    const { host, platform } = settings;
    const status = {}, listeners = new Set();
    const connection = new RemoteConnection({ host, platform }, {
      sshWrapper: getConfig()?.remoteTestSshCommand,
      getSshEnvironment,
      onState(state, detail = {}) {
        for (const key of Object.keys(status)) if (key !== "sshClient") delete status[key];
        status.state = state;
        for (const key of ["sshClient", "message", "sshError", "attempt", "retryAfterMs", "nextRetryAt", "outageStartedAt", "recovered", "resumed"]) {
          if (detail[key] !== undefined) status[key] = detail[key];
        }
        emit({ type: "remote_environment_state", name, host, platform, state, ...status });
        for (const listener of listeners) listener(status);
      },
    });
    const entry = {
      name, host, platform, connection, status, listeners,
      commands: createRemoteCommands(connection),
      files: createRemoteFiles(connection),
      windowsBashPath: undefined,
    };
    live.set(name, entry);
    return entry;
  }

  async function resolveHome(entry, signal) {
    const info = typeof entry.connection.waitForReady === "function"
      ? await entry.connection.waitForReady(signal)
      : await entry.connection.ready();
    const home = nativePathFromUri(info.userHomeDir || info.cwd, entry.platform);
    const cwd = nativePathFromUri(info.cwd || info.userHomeDir, entry.platform);
    const tempDir = info.tempDir ? nativePathFromUri(info.tempDir, entry.platform) : "";
    return { info, home, cwd, tempDir };
  }

  async function home(args, signal) {
    if (!args || typeof args !== "object" || typeof args.name !== "string" || !args.name) {
      return { ok: false, error: "Provide the name of a configured remote environment." };
    }
    try {
      const entry = await environment(args.name, signal);
      const { home: homePath, cwd, tempDir } = await resolveHome(entry);
      return {
        ok: true,
        operation: "remote-environments.home",
        name: args.name,
        host: entry.host,
        platform: entry.platform,
        home: homePath,
        cwd,
        tempDir,
      };
    } catch (error) {
      return { ok: false, error: error.message };
    }
  }

  async function browse(args, signal) {
    if (!args || typeof args !== "object" || typeof args.name !== "string" || !args.name) {
      return { ok: false, error: "Provide the name of a configured remote environment." };
    }
    let entry;
    try {
      entry = await environment(args.name, signal);
      const { home: homePath } = await resolveHome(entry);
      const raw = typeof args.path === "string" ? args.path.trim() : "";
      const includeFiles = args.includeFiles === true;
      if (entry.platform === "windows" && (raw === "" || raw === "/")) {
        const drives = await listRemoteWindowsDrives(entry.connection, signal);
        return {
          ok: true,
          operation: "remote-environments.browse",
          name: args.name,
          host: entry.host,
          platform: entry.platform,
          path: "",
          parent: "",
          isDriveList: true,
          directories: drives,
          entries: drives,
        };
      }
      const requested = raw ? resolveRemoteWorkspacePath(homePath, raw, { platform: entry.platform, homeDir: homePath }) : homePath;
      let canonical = requested;
      try {
        const canon = await entry.connection.rpc("fs/canonicalize", { path: remotePathToUri(requested, entry.platform) }, { signal });
        if (canon?.path) canonical = normalizeRemotePath(nativePathFromUri(canon.path, entry.platform), entry.platform);
      } catch {
        // Canonicalize can fail on virtual roots or before readDirectory reports ENOENT.
      }
      const listing = await entry.connection.rpc("fs/readDirectory", { path: remotePathToUri(canonical, entry.platform) }, { signal });
      const items = (listing.entries || [])
        .filter(item => item?.fileName && item.fileName !== "." && item.fileName !== ".." && !/[\\/\0]/.test(item.fileName))
        .map(item => ({
          name: item.fileName,
          path: joinRemotePath(canonical, item.fileName, entry.platform),
          isDirectory: item.isDirectory === true,
          isFile: item.isFile === true,
        }))
        .sort((a, b) => {
          if (includeFiles && a.isDirectory !== b.isDirectory) return a.isDirectory ? -1 : 1;
          return a.name.toLowerCase().localeCompare(b.name.toLowerCase());
        });
      const directories = items.filter(item => item.isDirectory);
      return {
        ok: true,
        operation: "remote-environments.browse",
        name: args.name,
        host: entry.host,
        platform: entry.platform,
        path: canonical,
        parent: remoteDirname(canonical, entry.platform),
        isDriveList: false,
        directories,
        entries: includeFiles ? items : directories,
      };
    } catch (error) {
      return {
        ok: false,
        error: error.message,
        missing: isMissingError(error),
        name: args.name,
        host: entry?.host || "",
      };
    }
  }

  async function mkdir(args, signal) {
    if (!args || typeof args !== "object" || typeof args.name !== "string" || !args.name || typeof args.path !== "string" || !args.path.trim()) {
      return { ok: false, error: "Provide name and path to create a remote directory." };
    }
    try {
      const entry = await environment(args.name, signal);
      const { home: homePath } = await resolveHome(entry);
      const target = resolveRemoteWorkspacePath(homePath, args.path, { platform: entry.platform, homeDir: homePath });
      await entry.connection.rpc("fs/createDirectory", {
        path: remotePathToUri(target, entry.platform),
        recursive: true,
        followSymlinks: false,
      }, { signal, retry: true });
      return {
        ok: true,
        operation: "remote-environments.mkdir",
        name: args.name,
        host: entry.host,
        platform: entry.platform,
        path: target,
      };
    } catch (error) {
      return { ok: false, error: error.message };
    }
  }

  async function workspaceOp(args, signal) {
    if (!args || typeof args !== "object" || typeof args.name !== "string" || !args.name || typeof args.op !== "string") {
      return { ok: false, error: "Provide name and op for workspace operation." };
    }
    try {
      const entry = await environment(args.name, signal);
      if (args.op === "sshTarget") {
        const env = await getSshEnvironment?.() ?? process.env;
        const sshClient = entry.connection.sshClient || await selectSshClient(entry.host, { env });
        return { ok: true, name: args.name, host: entry.host, platform: entry.platform, sshClient };
      }
      const { home: homePath, cwd, tempDir } = await resolveHome(entry);
      const baseCwd = args.cwd ? resolveRemoteWorkspacePath(homePath, args.cwd, { platform: entry.platform, homeDir: homePath }) : cwd;
      const resolveTarget = raw => resolveRemoteWorkspacePath(baseCwd, raw ?? ".", { platform: entry.platform, homeDir: homePath });
      const uriOf = value => remotePathToUri(value, entry.platform);

      if (args.op === "home") {
        return { ok: true, name: args.name, host: entry.host, platform: entry.platform, home: homePath, cwd, tempDir };
      }
      if (args.op === "exec") {
        let argv = Array.isArray(args.argv) && args.argv.length ? args.argv.map(String) : null;
        if (!argv) {
          if (typeof args.command !== "string" || !args.command.trim()) {
            return { ok: false, error: "workspace exec requires argv or command." };
          }
          argv = entry.platform === "windows" ? powershellUtf8Argv(args.command) : ["/bin/sh", "-c", args.command];
        }
        const result = await runRemoteProcess(entry.connection, entry.platform, {
          argv,
          cwd: baseCwd,
          env: args.env || {},
          timeoutMs: Number(args.timeoutMs) || 120_000,
          maxOutputBytes: Number(args.maxOutputBytes) || 4 * 1024 * 1024,
          signal,
        });
        return {
          ok: true,
          stdout: result.stdout,
          stderr: result.stderr,
          exitCode: result.exitCode,
          timedOut: result.timedOut,
          truncated: result.truncated,
        };
      }
      if (args.op === "readDir") {
        const target = resolveTarget(args.path ?? ".");
        const listing = await entry.connection.rpc("fs/readDirectory", { path: uriOf(target) }, { signal });
        const entries = (listing.entries || [])
          .filter(item => item?.fileName && item.fileName !== "." && item.fileName !== ".." && !/[\\/\0]/.test(item.fileName))
          .map(item => ({
            name: item.fileName,
            path: joinRemotePath(target, item.fileName, entry.platform),
            isDirectory: item.isDirectory === true,
            isFile: item.isFile === true,
          }));
        if (args.withMetadata && entries.length) {
          try {
            const batch = await entry.connection.rpc("fs/getMetadataBatch", {
              paths: entries.map(item => uriOf(item.path)),
              followSymlinks: false,
            }, { signal });
            if (Array.isArray(batch?.results)) {
              for (let i = 0; i < entries.length && i < batch.results.length; i++) {
                const row = batch.results[i];
                const meta = row?.Ok || row;
                if (meta && typeof meta.size === "number") {
                  entries[i].size = meta.size;
                  entries[i].modifiedAtMs = meta.modifiedAtMs;
                  entries[i].isSymlink = meta.isSymlink === true;
                }
              }
            }
          } catch {
            // Optional metadata enrichment.
          }
        }
        return { ok: true, path: target, entries };
      }
      if (args.op === "stat") {
        const target = resolveTarget(args.path);
        try {
          const meta = await entry.connection.rpc("fs/getMetadata", {
            path: uriOf(target),
            followSymlinks: args.followSymlinks !== false,
          }, { signal });
          return { ok: true, exists: true, path: target, ...meta };
        } catch (error) {
          if (isMissingError(error)) return { ok: true, exists: false, path: target };
          throw error;
        }
      }
      if (args.op === "readFile") {
        const target = resolveTarget(args.path);
        const maxBytes = Math.max(1, Math.min(Number(args.maxBytes) || 4 * 1024 * 1024, 16 * 1024 * 1024));
        const meta = await entry.connection.rpc("fs/getMetadata", { path: uriOf(target), followSymlinks: true }, { signal });
        if (!meta.isFile) return { ok: false, error: "Remote path is not a regular file." };
        if (meta.size <= maxBytes && meta.size <= 4 * 1024 * 1024) {
          const data = await entry.connection.rpc("fs/readFile", { path: uriOf(target), followSymlinks: true }, { signal });
          return { ok: true, path: target, dataBase64: data.dataBase64, size: meta.size, truncated: false };
        }
        const handleId = randomUUID().replaceAll("-", "");
        await entry.connection.rpc("fs/open", { handleId, path: uriOf(target), mode: "read" }, { signal, retry: false });
        try {
          const pieces = [];
          let total = 0;
          while (total < maxBytes) {
            const block = await entry.connection.rpc("fs/readBlock", { handleId, offset: total, len: Math.min(256 * 1024, maxBytes - total) }, { signal });
            const buf = Buffer.from(block.chunk, "base64");
            if (!buf.length) break;
            pieces.push(buf);
            total += buf.length;
            if (block.eof) break;
          }
          return { ok: true, path: target, dataBase64: Buffer.concat(pieces).toString("base64"), size: meta.size, truncated: total < meta.size };
        } finally {
          await entry.connection.rpc("fs/close", { handleId }, { retry: false }).catch(() => {});
        }
      }
      if (args.op === "writeFile") {
        const target = resolveTarget(args.path);
        const parent = remoteDirname(target, entry.platform);
        if (parent) {
          await entry.connection.rpc("fs/createDirectory", { path: uriOf(parent), recursive: true, followSymlinks: false }, { signal, retry: true });
        }
        const dataBase64 = typeof args.dataBase64 === "string" ? args.dataBase64 : Buffer.from(String(args.content ?? ""), "utf8").toString("base64");
        await entry.connection.rpc("fs/writeFile", { path: uriOf(target), dataBase64, followSymlinks: false }, { signal, retry: true });
        return { ok: true, path: target };
      }
      if (args.op === "mkdir") {
        const target = resolveTarget(args.path);
        await entry.connection.rpc("fs/createDirectory", { path: uriOf(target), recursive: true, followSymlinks: false }, { signal, retry: true });
        return { ok: true, path: target };
      }
      if (args.op === "remove") {
        const target = resolveTarget(args.path);
        await entry.connection.rpc("fs/remove", {
          path: uriOf(target),
          recursive: args.recursive !== false,
          force: args.force !== false,
          followSymlinks: false,
        }, { signal, retry: false });
        return { ok: true, path: target };
      }
      if (args.op === "rename") {
        const source = resolveTarget(args.path);
        const dest = resolveTarget(args.destination);
        const argv = entry.platform === "windows"
          ? powershellUtf8Argv(`$ErrorActionPreference='Stop'; Move-Item -LiteralPath ${quotePs(source)} -Destination ${quotePs(dest)}`)
          : ["/bin/sh", "-c", `mv -- ${quoteSh(source)} ${quoteSh(dest)}`];
        const result = await runRemoteProcess(entry.connection, entry.platform, { argv, cwd: baseCwd, timeoutMs: 30_000, signal });
        if (result.exitCode !== 0) {
          return { ok: false, error: (result.stderr || result.stdout || `Rename failed (exit ${result.exitCode})`).trim() };
        }
        return { ok: true, path: source, destination: dest };
      }
      return { ok: false, error: `Unknown workspace op: ${args.op}` };
    } catch (error) {
      return { ok: false, error: error.message, missing: isMissingError(error) };
    }
  }

  return {
    getEntry: environment,
    home,
    browse,
    mkdir,
    workspaceOp,
    sshHosts(opts) {
      return { ok: true, hosts: listSshConfigHosts(opts) };
    },
    async detectPlatform(host, signal) {
      try {
        const result = await detectRemotePlatform(host, {
          getSshEnvironment,
          sshWrapper: getConfig()?.remoteTestSshCommand,
          signal,
        });
        return { ok: true, host, ...result };
      } catch (error) {
        return { ok: false, error: error.message, sshClient: error.sshClient, sshError: error.sshError };
      }
    },
    async test(args, signal, onUpdate) {
      if (!args || typeof args !== "object" || Object.keys(args).length !== 1 || typeof args.name !== "string" || !args.name) {
        return { ok: false, error: "Provide the name of a configured remote environment." };
      }
      let entry;
      const diagnostics = () => Object.fromEntries(["sshClient", "sshError"]
        .filter(key => entry?.status[key]).map(key => [key, entry.status[key]]));
      try {
        entry = await environment(args.name, signal);
        const info = await withProgress(args.name, entry, onUpdate, () => entry.connection.waitForReady(signal));
        return { ok: true, operation: "remote-environments.test", name: args.name, state: "connected", platform: entry.platform,
          cwd: info.cwd, ...(info.reconnection ? { reconnection: info.reconnection } : {}), ...diagnostics() };
      } catch (error) {
        return { ok: false, error: error.message, ...diagnostics(), ...connectionErrorDetails(error) };
      }
    },
    close,
    dispose() {
      for (const name of live.keys()) close(name);
    },
    extension(pi) {
      pi.registerTool({
        name: "remote_command", label: "Remote command", parameters: commandArgs,
        description: "Run shell commands in a named SSH environment. Run returns output and a sessionId; if running, read it to get new output, write input including its newline, or kill that session. Use umeko_desktop remote-environments.list to find configured environments. The session can survive a network interruption.",
        annotations: { readOnlyHint: false, destructiveHint: true },
        async execute(_id, args, signal, onUpdate, ctx) {
          const entry = await environment(args.environment, signal);
          return toolResult(args.environment, entry, onUpdate,
            () => entry.commands.execute(args, { signal, cwd: ctx.cwd }));
        },
      });
      pi.registerTool({
        name: "remote_files", label: "Remote files", parameters: fileArgs,
        description: "Read or write a file, list a directory, search file contents, or upload/download a file or directory in a named SSH environment. path and cwd are remote. localPath is a local workspace path for transfers. Reconnecting resumes in-progress file transfers.",
        annotations: { readOnlyHint: false, destructiveHint: true },
        async execute(_id, args, signal, onUpdate, ctx) {
          const entry = await environment(args.environment, signal);
          return toolResult(args.environment, entry, onUpdate, () => entry.files.execute(args, {
            signal, cwd: ctx.cwd,
            onUpdate: value => onUpdate?.(response(value)),
          }));
        },
      });
    },
  };
}
