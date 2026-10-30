import { spawn } from "node:child_process";
import { closeSync, mkdirSync, openSync } from "node:fs";
import { mkdtemp, open } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
import { createJiti } from "jiti";
import { getShellConfig } from "./node_modules/@earendil-works/pi-coding-agent/dist/utils/shell.js";
import { assertProcessCommandAllowed, blockedProcessCommand } from "./process-guard.mjs";

// Fixed pi-bg primitives only: importing its extension entry would replace bash
// and introduce UI/injection behavior. Each manager owns a fresh registry.
async function loadPrimitives() {
  const cache = join(process.env.PI_CODING_AGENT_DIR || join(homedir(), ".pi", "agent"), "cache", "umeko-background-jobs");
  const jiti = createJiti(import.meta.url, { moduleCache: false, tryNative: false, fsCache: cache });
  const root = new URL("./", import.meta.resolve("@alexlikevibe/pi-bg/package.json"));
  const [{ BackgroundRegistry }, { spawnWithFileOutput }] = await Promise.all([
    jiti.import(fileURLToPath(new URL("src/state.ts", root))),
    jiti.import(fileURLToPath(new URL("src/spawn.ts", root))),
  ]);
  return { BackgroundRegistry, spawnWithFileOutput };
}

// Adapted from @alexlikevibe/pi-bg 2.3.0 src/spawn.ts (MIT).
// Windows needs windowsHide, which its public primitive does not expose.
// stdout/stderr go directly to disk; no growing in-memory output buffer.
function spawnHiddenWithFileOutput({ file, fileArgs, cwd, logPath, errPath }) {
  mkdirSync(join(logPath, ".."), { recursive: true });
  const outFd = openSync(logPath, "w");
  let errFd;
  try {
    errFd = openSync(errPath, "w");
    const child = spawn(file, fileArgs, { cwd, stdio: ["ignore", outFd, errFd],
      detached: true, windowsHide: true, env: { ...process.env } });
    const exit = new Promise(resolve => {
      child.once("exit", (code, signal) => resolve({ code, signal }));
      child.once("error", error => resolve({ code: 1, signal: null, error: error.message }));
    });
    if (!child.pid) throw new Error("Failed to spawn background process");
    child.unref();
    return { pid: child.pid, exit };
  } finally {
    closeSync(outFd);
    if (errFd !== undefined) closeSync(errFd);
  }
}

const snapshot = job => ({ id: job.id, command: job.command, cwd: job.cwd, pid: job.pid,
  status: job.status, exitCode: job.exitCode, signal: job.signal,
  startedAt: job.startedAt, completedAt: job.completedAt,
  stdoutPath: job.logPath, stderrPath: job.errPath, ...(job.error ? { error: job.error } : {}) });

export async function createJobManager({ shellPath, cwd = process.cwd() } = {}) {
  const { BackgroundRegistry, spawnWithFileOutput } = await loadPrimitives();
  const registry = new BackgroundRegistry();
  const directory = await mkdtemp(join(tmpdir(), "umeko-background-jobs-"));
  let disposed = false, disposal;
  function owned(id) {
    const job = registry.jobs.get(id);
    if (!job) throw new Error("Unknown background job in this session");
    return job;
  }
  async function start({ command, cwd: workingDirectory = cwd } = {}) {
    if (disposed) throw new Error("Background job manager is closed");
    if (typeof command !== "string" || !command.trim()) throw new Error("A command is required");
    assertProcessCommandAllowed(command);
    const { shell, args, commandTransport } = getShellConfig(shellPath);
    if (commandTransport === "stdin") throw new Error("Background jobs require Git Bash or a shell accepting -c");
    const id = randomUUID(), logPath = join(directory, `${id}.stdout.log`), errPath = join(directory, `${id}.stderr.log`);
    const launch = process.platform === "win32" ? spawnHiddenWithFileOutput : spawnWithFileOutput;
    const child = launch({ file: shell, fileArgs: [...args, command], cwd: workingDirectory, logPath, errPath });
    const job = { id, command, cwd: workingDirectory, pid: child.pid, logPath, errPath,
      status: "running", exitCode: null, signal: null, startedAt: Date.now() };
    registry.jobs.set(id, job);
    registry.totalStarted++;
    job.donePromise = child.exit.then(result => {
      job.exitCode = result.code; job.signal = result.signal; job.error = result.error;
      job.status = job.killRequested ? "killed" : result.code === 0 ? "completed" : "failed";
      job.completedAt = Date.now();
      return snapshot(job);
    });
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
  async function wait(id, { timeoutMs = 10000 } = {}) {
    const job = owned(id);
    if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 0 || timeoutMs > 60000) throw new Error("timeoutMs must be between 0 and 60000");
    if (job.status !== "running") return { ...snapshot(job), timedOut: false };
    let timer;
    try {
      const result = await Promise.race([job.donePromise, new Promise(resolve => {
        timer = setTimeout(() => resolve(null), timeoutMs);
      })]);
      return { ...(result || snapshot(job)), timedOut: result === null };
    } finally { clearTimeout(timer); }
  }
  async function kill(id) {
    const job = owned(id);
    if (job.status !== "running") return snapshot(job);
    if (!Number.isSafeInteger(job.pid) || job.pid <= 0 || job.pid === process.pid) throw new Error("Invalid owned process PID");
    if (job.killPromise) return job.killPromise;
    job.killPromise = (async () => {
      job.killRequested = true;
      try {
        if (process.platform === "win32") {
          await new Promise((resolve, reject) => {
            // The only Windows killer targets the PID recorded at spawn.
            const child = spawn(join(process.env.SystemRoot || "C:\\Windows", "System32", "taskkill.exe"),
              ["/PID", String(job.pid), "/T", "/F"], { stdio: "ignore", windowsHide: true });
            child.once("error", reject);
            child.once("exit", code => code === 0 || job.status !== "running" ? resolve() : reject(new Error(`Could not stop background job (taskkill exit ${code})`)));
          });
        } else {
          try { process.kill(-job.pid, "SIGKILL"); }
          catch (error) { if (error.code !== "ESRCH") throw error; }
        }
        const result = await wait(id, { timeoutMs: 10000 });
        if (result.timedOut) throw new Error("Background process did not exit after stop");
        return snapshot(job);
      } catch (error) { if (job.status === "running") job.killRequested = false; throw error; }
    })();
    try { return await job.killPromise; } finally { job.killPromise = undefined; }
  }
  function dispose() {
    if (disposal) return disposal;
    disposed = true;
    disposal = (async () => {
      const results = await Promise.allSettled([...registry.jobs.values()].filter(job => job.status === "running").map(job => kill(job.id)));
      const failures = results.filter(result => result.status === "rejected");
      if (failures.length) throw new AggregateError(failures.map(result => result.reason), "Could not stop all background jobs");
    })();
    return disposal;
  }
  return { start, status, read, wait, kill, list: () => [...registry.jobs.values()].map(snapshot), dispose, directory };
}

const parameters = { type: "object", properties: {
  action: { type: "string", enum: ["start", "status", "read", "wait", "kill", "list"] },
  command: { type: "string", description: "Shell command for start" },
  cwd: { type: "string", description: "Working directory for start" },
  id: { type: "string", description: "Job ID returned by start; only jobs in this session are accessible" },
  stdoutOffset: { type: "integer", minimum: 0, description: "Byte cursor returned by the previous read" },
  stderrOffset: { type: "integer", minimum: 0, description: "Byte cursor returned by the previous read" },
  maxBytes: { type: "integer", minimum: 1, maximum: 1048576 },
  timeoutMs: { type: "integer", minimum: 0, maximum: 60000 },
}, required: ["action"] };

export function createBackgroundJobsExtension(options = {}) {
  let manager;
  const getManager = () => manager ||= createJobManager(options);
  async function dispose() {
    const current = manager;
    if (!current) return;
    await (await current).dispose();
    if (manager === current) manager = undefined;
  }
  function extension(pi) {
    pi.on("tool_call", event => {
      // Pi's native command tools share input.command, including calls made
      // through codemode. Other built-ins are file tools, not shell executors.
      if (!["bash", "powershell"].includes(event.toolName) && !(event.toolName === "background_job" && event.input?.action === "start")) return;
      const reason = blockedProcessCommand(event.input?.command, event.toolName === "powershell" ? "powershell" : "bash");
      if (reason) return { block: true, reason };
    });
    pi.on("session_before_switch", dispose);
    pi.on("session_shutdown", dispose);
    pi.registerTool({ name: "background_job", label: "Background job",
      description: "Run a shell command in the background and keep working. Start returns a job ID and separate output log paths. Use read with returned byte cursors for new output, wait with a bounded timeout for exit status, and kill by job ID to stop only this session's job tree. Jobs stop when the session closes or switches.",
      parameters,
      async execute(_toolCallId, input, _signal, _onUpdate, ctx) {
        try {
          const jobs = await getManager();
          let result;
          if (input.action === "start") result = await jobs.start({ command: input.command, cwd: input.cwd || ctx?.cwd || options.cwd });
          else if (input.action === "list") result = jobs.list();
          else if (input.action === "status") result = jobs.status(input.id);
          else if (input.action === "read") result = await jobs.read(input.id, input);
          else if (input.action === "wait") result = await jobs.wait(input.id, input);
          else if (input.action === "kill") result = await jobs.kill(input.id);
          else throw new Error("Unknown background job action");
          return { content: [{ type: "text", text: JSON.stringify(result) }], details: result };
        } catch (error) {
          return { content: [{ type: "text", text: error.message }], isError: true };
        }
      },
    });
  }
  return { extension, dispose, getManager };
}

export function backgroundJobsExtension(pi) { return createBackgroundJobsExtension().extension(pi); }
export default backgroundJobsExtension;
