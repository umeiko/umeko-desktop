// Command sessions, bounded collection and yield adapted from OpenAI Codex,
// rust-v0.172.0: codex-rs/core/src/unified_exec/. See licenses/codex-NOTICE.txt.
import { mkdtemp, open } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
import { createJiti } from "jiti";
import { getPowerShellConfig, getShellConfig } from "./node_modules/@earendil-works/pi-coding-agent/dist/utils/shell.js";
import { assertProcessCommandAllowed, blockedProcessCommand } from "./process-guard.mjs";
import { launchCommand } from "./command-process.mjs";
import { sandboxCommand, sandboxFailure } from "./windows-sandbox.mjs";

const modelBytesPerStream = 20_000;
export const DEFAULT_YIELD_MS = 10_000;

// Fixed pi-bg primitives only: importing its extension entry would replace bash
// and introduce UI/injection behavior. Each manager owns a fresh registry.
async function loadPrimitives() {
  const cache = join(process.env.PI_CODING_AGENT_DIR || join(homedir(), ".pi", "agent"), "cache", "umeko-background-jobs");
  const jiti = createJiti(import.meta.url, { moduleCache: false, tryNative: false, fsCache: cache });
  const root = new URL("./", import.meta.resolve("@alexlikevibe/pi-bg/package.json"));
  const { BackgroundRegistry } = await jiti.import(fileURLToPath(new URL("src/state.ts", root)));
  return { BackgroundRegistry };
}

const snapshot = job => ({ id: job.id, command: job.command, cwd: job.cwd, pid: job.pid,
  status: job.status, exitCode: job.exitCode, signal: job.signal, shell: job.shellName,
  startedAt: job.startedAt, completedAt: job.completedAt,
  stdoutPath: job.logPath, stderrPath: job.errPath, ...(job.error ? { error: job.error } : {}),
  ...(job.reason ? { reason: job.reason } : {}),
  ...(job.sandboxNotice ? { sandboxNotice: job.sandboxNotice } : {}),
  ...(job.sandboxFailure ? { sandboxFailure: job.sandboxFailure } : {}) });

export async function createJobManager({ shellPath, cwd = process.cwd(), host, hostScript, onCleanup, getSandbox } = {}) {
  const { BackgroundRegistry } = await loadPrimitives();
  const registry = new BackgroundRegistry();
  const directory = await mkdtemp(join(tmpdir(), "umeko-background-jobs-"));
  let disposed = false, disposal;
  function owned(id) {
    const job = registry.jobs.get(id);
    if (!job) throw new Error("Unknown background job in this session");
    return job;
  }
  async function start({ command, cwd: workingDirectory = cwd, workspace = cwd, env, shellPath: sessionShellPath = shellPath,
    shellName = "bash", shellConfig, timeoutMs, signal, toolCallId, owner } = {}) {
    if (disposed) throw new Error("Background job manager is closed");
    if (signal?.aborted) throw new Error("aborted");
    if (typeof command !== "string" || !command.trim()) throw new Error("A command is required");
    assertProcessCommandAllowed(command, shellName);
    const { shell, args, commandTransport } = shellConfig ||
      (shellName === "powershell" ? getPowerShellConfig() : getShellConfig(sessionShellPath));
    if (commandTransport === "stdin") throw new Error("Command sessions require a shell that accepts the command as an argument");
    const id = randomUUID(), logPath = join(directory, `${id}.stdout.log`), errPath = join(directory, `${id}.stderr.log`);
    const launch = sandboxCommand({ file: shell, args: [...args, command], cwd: workingDirectory, env, workspace, policy: getSandbox?.() });
    const child = launchCommand({ host, hostScript, file: launch.file, fileArgs: launch.args,
      cwd: workingDirectory, logPath, errPath, env: launch.env });
    const job = { id, command, cwd: workingDirectory, child, shellName, logPath, errPath, toolCallId, owner,
      status: "running", exitCode: null, signal: null, startedAt: Date.now(), sandboxNotice: launch.notice };
    registry.jobs.set(id, job);
    registry.totalStarted++;
    let killTimer;
    const abort = () => void kill(id, "aborted").catch(() => {});
    if (timeoutMs !== undefined) killTimer = setTimeout(() => void kill(id, "timeout").catch(() => {}), timeoutMs);
    job.donePromise = child.exit.then(async result => {
      clearTimeout(killTimer);
      job.exitCode = result.code; job.signal = result.signal ?? null; job.error = result.error;
      job.cleanup = { cleanup: result.cleanup, remaining: result.remaining };
      if (launch.level !== "off" && result.code && !job.reason && !result.error) {
        let stderr = "";
        try {
          const handle = await open(errPath, "r");
          try {
            const size = (await handle.stat()).size;
            const offset = Math.max(0, size - 8192);
            const tail = Buffer.alloc(size - offset);
            const { bytesRead } = await handle.read(tail, 0, tail.length, offset);
            stderr = tail.subarray(0, bytesRead).toString("utf8");
          } finally { await handle.close(); }
        } catch { /* The exit result is still available if the log is gone. */ }
        job.sandboxFailure = sandboxFailure(launch.level, launch.allowNetwork, stderr);
      }
      job.status = result.cleanup !== "done" ? "failed" : job.reason ? "killed" : result.code === 0 ? "completed" : "failed";
      job.completedAt = Date.now();
      onCleanup?.(job);
      return snapshot(job);
    });
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
    const ready = await child.ready.finally(() => signal?.removeEventListener("abort", abort));
    if (ready) Object.assign(job, ready);
    if (signal?.aborted) throw new Error("aborted");
    if (!job.pid) throw new Error(job.error || "Failed to spawn command");
    return snapshot(job);
  }
  function status(id) { return snapshot(owned(id)); }
  async function read(id, { stdoutOffset = 0, stderrOffset = 0, maxBytes = 65536 } = {}) {
    const job = owned(id);
    const finished = job.status !== "running";
    if (![stdoutOffset, stderrOffset].every(value => Number.isSafeInteger(value) && value >= 0)) throw new Error("Output offsets must be non-negative byte offsets");
    if (!Number.isSafeInteger(maxBytes) || maxBytes < 1 || maxBytes > 1048576) throw new Error("maxBytes must be between 1 and 1048576");
    async function chunk(path, offset) {
      const handle = await open(path, "r");
      try {
        const size = (await handle.stat()).size;
        if (offset > size) throw new Error("Output offset is beyond this job's log");
        // Up to three look-ahead bytes let even maxBytes:1 advance over a
        // complete UTF-8 character without losing or duplicating its bytes.
        const buffer = Buffer.alloc(Math.min(maxBytes + 3, size - offset));
        const { bytesRead } = await handle.read(buffer, 0, buffer.length, offset);
        // Do not split a UTF-8 codepoint: leave its partial bytes for next read.
        let count = Math.min(bytesRead, maxBytes);
        if (count) {
          let lead = count - 1;
          while (lead >= 0 && (buffer[lead] & 0xc0) === 0x80) lead--;
          if (lead >= 0) {
            const byte = buffer[lead], width = byte >= 0xf0 ? 4 : byte >= 0xe0 ? 3 : byte >= 0xc0 ? 2 : 1;
            if (count - lead < width) {
              if (lead === 0 && bytesRead >= width) count = width;
              // After exit there will be no more bytes to complete this suffix.
              // Buffer's UTF-8 decoder replaces it, and its byte cursor advances.
              else if (finished && bytesRead < lead + width) count = bytesRead;
              else count = lead;
            }
          }
        }
        return { text: buffer.subarray(0, count).toString("utf8"), offset: offset + count, hasMore: offset + count < size };
      } finally { await handle.close(); }
    }
    const [stdout, stderr] = await Promise.all([chunk(job.logPath, stdoutOffset), chunk(job.errPath, stderrOffset)]);
    return { ...snapshot(job), stdout: stdout.text, stderr: stderr.text,
      stdoutOffset: stdout.offset, stderrOffset: stderr.offset, hasMore: stdout.hasMore || stderr.hasMore };
  }
  async function wait(id, { timeoutMs = 10000, signal } = {}) {
    const job = owned(id);
    if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 0 || timeoutMs > 60000) throw new Error("timeoutMs must be between 0 and 60000");
    if (job.status !== "running") return { ...snapshot(job), timedOut: false };
    let timer, abort;
    try {
      const result = await Promise.race([job.donePromise, new Promise((resolve, reject) => {
        timer = setTimeout(() => resolve(null), timeoutMs);
        abort = () => reject(new Error("aborted"));
        signal?.addEventListener("abort", abort, { once: true });
        if (signal?.aborted) abort();
      })]);
      return { ...(result || snapshot(job)), timedOut: result === null };
    } finally { clearTimeout(timer); signal?.removeEventListener("abort", abort); }
  }
  async function kill(id, reason = "stopped") {
    const job = owned(id);
    if (job.status !== "running") return snapshot(job);
    if (job.killPromise) return job.killPromise;
    job.killPromise = (async () => {
      job.reason = reason;
      try {
        await job.child.terminate();
        const result = await wait(id, { timeoutMs: 10000 });
        if (result.timedOut) throw new Error("Background process did not exit after stop");
        if (job.cleanup.cleanup !== "done") throw new Error(`Command tree cleanup ${job.cleanup.cleanup}`);
        return snapshot(job);
      } catch (error) { if (job.status === "running") job.reason = undefined; throw error; }
    })();
    try { return await job.killPromise; } finally { job.killPromise = undefined; }
  }
  async function write(id, input) {
    const job = owned(id);
    if (job.status !== "running") throw new Error("Command input closed");
    if (typeof input !== "string" || !input || Buffer.byteLength(input) > 16_384) {
      throw new Error("Input must be between 1 and 16384 UTF-8 bytes");
    }
    assertProcessCommandAllowed(input, job.shellName);
    await job.child.write(input);
    return snapshot(job);
  }
  async function stopRunning(reason) {
    const running = [...registry.jobs.values()].filter(job => job.status === "running");
    return Promise.all(running.map(async job => {
      try { await kill(job.id, reason); } catch { /* stop reports the outcome below */ }
      return job.cleanup || { cleanup: "failed", remaining: job.pid ? [job.pid] : null };
    }));
  }
  function dispose() {
    if (disposal) return disposal;
    disposed = true;
    disposal = (async () => {
      const results = await stopRunning("session closed");
      if (results.some(result => result.cleanup !== "done")) throw new Error("Could not stop all background jobs");
    })();
    return disposal;
  }
  return { start, status, read, wait, kill, write, stopRunning,
    list: () => [...registry.jobs.values()].map(snapshot), dispose, directory };
}

const parameters = { type: "object", properties: {
  action: { type: "string", enum: ["start", "status", "read", "write", "wait", "kill", "list"] },
  command: { type: "string", description: "Shell command for start" },
  shell: { type: "string", enum: ["bash", "powershell"], description: "Shell for start (default: bash)" },
  input: { type: "string", description: "Text to send to standard input; include a newline to submit a line" },
  cwd: { type: "string", description: "Working directory for start" },
  id: { type: "string", description: "Job ID returned by start; only jobs in this session are accessible" },
  stdoutOffset: { type: "integer", minimum: 0, description: "Byte cursor returned by the previous read" },
  stderrOffset: { type: "integer", minimum: 0, description: "Byte cursor returned by the previous read" },
  maxBytes: { type: "integer", minimum: 1, maximum: 1048576 },
  timeoutMs: { type: "integer", minimum: 0, maximum: 60000 },
}, required: ["action"] };

export function createBackgroundJobsExtension(options = {}) {
  const managers = new Map();
  const sessionId = ctx => ctx?.sessionManager?.getSessionId();
  const getManager = id => {
    if (!managers.has(id)) managers.set(id, createJobManager({ ...options, onCleanup: job => options.onCleanup?.(id, job) }));
    return managers.get(id);
  };
  async function dispose(id) {
    const current = managers.get(id);
    if (!current) return;
    try { await (await current).dispose(); }
    finally { if (managers.get(id) === current) managers.delete(id); }
  }
  async function stop(id) {
    const current = managers.get(id);
    return current ? (await current).stopRunning("aborted") : [];
  }
  async function disposeAll() {
    return Promise.allSettled([...managers.keys()].map(id => dispose(id)));
  }
  async function foreground({ signal, timeout, onData, owner, sessionId: id, ...request }) {
    const jobs = await getManager(id);
    const job = await jobs.start({ ...request, signal, owner });
    let cancelled;
    const abort = () => { cancelled ||= jobs.kill(job.id, "aborted").catch(() => {}); };
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
    try {
      await jobs.wait(job.id, { timeoutMs: DEFAULT_YIELD_MS, signal });
      const chunk = await jobs.read(job.id, { maxBytes: modelBytesPerStream });
      if (chunk.stdout) onData(Buffer.from(chunk.stdout));
      if (chunk.stderr) onData(Buffer.from(`${chunk.stdout ? "\n" : ""}${chunk.stderr}`));
      const details = [chunk.sandboxNotice, chunk.sandboxFailure].filter(Boolean);
      if (details.length) onData(Buffer.from(`\n${details.join("\n")}\n`));
      if (signal?.aborted || chunk.reason === "aborted") throw new Error("aborted");
      if (chunk.status !== "running" && chunk.reason === "timeout") throw new Error(`timeout:${timeout}`);
      if (chunk.error) throw new Error(chunk.error);
      if (chunk.status === "running" || chunk.hasMore) {
        return { exitCode: chunk.status === "running" ? null : chunk.exitCode, commandSession: {
          id: job.id, status: chunk.status, stdoutOffset: chunk.stdoutOffset, stderrOffset: chunk.stderrOffset,
          stdoutPath: job.stdoutPath, stderrPath: job.stderrPath, hasMore: chunk.hasMore,
        } };
      }
      return { exitCode: chunk.exitCode ?? 1 };
    } finally {
      signal?.removeEventListener("abort", abort);
      if (cancelled) await cancelled;
    }
  }
  function extension(pi) {
    pi.on("tool_call", event => {
      // Pi's native command tools share input.command, including calls made
      // through codemode. Other built-ins are file tools, not shell executors.
      if (!["bash", "powershell"].includes(event.toolName) && !(event.toolName === "background_job" && event.input?.action === "start")) return;
      const name = event.toolName === "powershell" || event.input?.shell === "powershell" ? "powershell" : "bash";
      const reason = blockedProcessCommand(event.input?.command, name);
      if (reason) return { block: true, reason };
    });
    pi.on("session_before_switch", (_event, ctx) => dispose(sessionId(ctx)));
    pi.on("session_shutdown", (_event, ctx) => dispose(sessionId(ctx)));
    pi.registerTool({ name: "background_job", label: "Background job",
      description: "Manage shell commands in this conversation. Use an ID returned by bash, PowerShell, or start. Read new output with the returned byte cursors, write text to stdin, wait for exit, or kill the command tree. Log files contain full stdout and stderr.",
      parameters,
      async execute(toolCallId, input, signal, _onUpdate, ctx) {
        try {
          if (input.action === "start" && options.canStart && !(await options.canStart())) throw new Error("Checkpoint restoration is active in this workspace");
          const jobs = await getManager(sessionId(ctx));
          let result;
          if (input.action === "start") {
            const shellPath = options.getShellPath?.(ctx) || options.shellPath;
            const shellName = input.shell === "powershell" ? "powershell" : "bash";
            const env = await options.getEnvironment?.(ctx, shellPath, shellName);
            const workspace = ctx?.cwd || options.cwd || process.cwd();
            result = await jobs.start({ command: input.command, env, shellPath, shellName, signal, toolCallId,
              workspace, cwd: resolve(workspace, input.cwd || ".") });
          }
          else if (input.action === "list") result = jobs.list();
          else if (input.action === "status") result = jobs.status(input.id);
          else if (input.action === "read") result = await jobs.read(input.id, { ...input, maxBytes: Math.min(input.maxBytes ?? modelBytesPerStream, modelBytesPerStream) });
          else if (input.action === "write") result = await jobs.write(input.id, input.input);
          else if (input.action === "wait") result = await jobs.wait(input.id, { ...input, signal });
          else if (input.action === "kill") result = await jobs.kill(input.id);
          else throw new Error("Unknown background job action");
          return { content: [{ type: "text", text: JSON.stringify(result) }], details: result };
        } catch (error) {
          return { content: [{ type: "text", text: error.message }], isError: true };
        }
      },
    });
  }
  return {
    extension, dispose, foreground, stop, disposeAll,
    getManager(id) {
      // Callers inspecting a standalone extension can omit the ID when it has
      // one manager. Tool execution itself always uses its own context.
      return arguments.length === 0 && managers.size === 1 ? managers.values().next().value : getManager(id);
    },
  };
}

export function backgroundJobsExtension(pi) { return createBackgroundJobsExtension().extension(pi); }
export default backgroundJobsExtension;
