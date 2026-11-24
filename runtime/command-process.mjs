import { spawn } from "node:child_process";
import { closeSync, openSync } from "node:fs";
import { join } from "node:path";
import { createInterface } from "node:readline";

const windows = process.platform === "win32";
const cleanupDeadlineMs = 1_500;
const clean = { cleanup: "done", remaining: [] };

function launchWindowsHost({ host, hostScript, file, fileArgs, cwd, logPath, errPath, env }) {
  const child = spawn(host, [...(hostScript ? [hostScript] : []), "--umeko-bash-job"], {
    cwd, env: { ...env, PYINSTALLER_RESET_ENVIRONMENT: "1" },
    windowsHide: true, stdio: ["pipe", "pipe", "ignore"],
  });
  const lines = createInterface({ input: child.stdout });
  const ready = Promise.withResolvers();
  const done = Promise.withResolvers();
  const writes = new Map();
  let sequence = 0, cleanupTimer, settled = false, stopping = false;

  function finish(result) {
    if (settled) return;
    settled = true;
    clearTimeout(cleanupTimer);
    child.stdin.end();
    lines.close();
    ready.resolve();
    for (const write of writes.values()) write.reject(new Error("Command input closed"));
    writes.clear();
    done.resolve(result);
  }

  child.stdin.on("error", () => {});
  child.once("error", error => finish({ code: 1, error: error.message, cleanup: "failed", remaining: null }));
  child.once("close", () => finish({ code: 1, error: "Windows command host exited", cleanup: "failed", remaining: null }));
  lines.on("line", line => {
    let result;
    try { result = JSON.parse(line); } catch { return; }
    if (Number.isInteger(result.pid)) ready.resolve({ pid: result.pid, ppid: result.ppid });
    if (result.writeId !== undefined) {
      const write = writes.get(result.writeId);
      if (!write) return;
      writes.delete(result.writeId);
      if (result.error) write.reject(new Error(result.error));
      else write.resolve();
    }
    if (result.cleanup) finish({ ...result, code: result.exitCode,
      ...(Object.hasOwn(result, "error") ? { error: `Unable to start Windows command (${result.error ?? "unknown error"})` } : {}) });
  });
  child.stdin.write(JSON.stringify({ args: [file, ...fileArgs], cwd, stdoutPath: logPath, stderrPath: errPath }) + "\n");

  function terminate() {
    if (settled || stopping) return;
    stopping = true;
    child.stdin.end("stop\n");
    cleanupTimer = setTimeout(() => {
      // The host's last job handle closes even if its reply cannot reach Node.
      child.kill();
      finish({ code: 1, cleanup: "timed_out", remaining: null });
    }, cleanupDeadlineMs);
  }

  async function write(input) {
    if (settled || stopping) throw new Error("Command input closed");
    if (writes.size >= 8) throw new Error("Command input queue is full");
    const pending = Promise.withResolvers();
    const writeId = ++sequence;
    writes.set(writeId, pending);
    child.stdin.write(JSON.stringify({ writeId, input }) + "\n", error => {
      if (!error || !writes.delete(writeId)) return;
      pending.reject(error);
    });
    let timer;
    try {
      await Promise.race([pending.promise, new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("Command did not accept input before the deadline")), cleanupDeadlineMs);
      })]);
    } finally {
      clearTimeout(timer);
    }
  }
  return { ready: ready.promise, exit: done.promise, terminate, write };
}

function terminateGroup(pid) {
  try { process.kill(-pid, "SIGKILL"); }
  catch (error) { if (error.code !== "ESRCH") throw error; }
}

// Adapted from @alexlikevibe/pi-bg 2.3.0 src/spawn.ts (MIT).
// Windows desktop sessions use the Job Object host above. Node-only callers
// without the native host retain the standalone PID-tree implementation.
function launchDirect({ file, fileArgs, cwd, logPath, errPath, env }) {
  const outFd = openSync(logPath, "w");
  let errFd, child;
  try {
    errFd = openSync(errPath, "w");
    child = spawn(file, fileArgs, { cwd, stdio: ["pipe", outFd, errFd], detached: !windows, windowsHide: true, env });
  } finally {
    closeSync(outFd);
    if (errFd !== undefined) closeSync(errFd);
  }
  child.stdin.on("error", () => {});
  const exit = new Promise(resolve => {
    child.once("error", error => resolve({ code: 1, error: error.message, ...clean }));
    child.once("exit", (code, signal) => {
      child.stdin.end();
      if (!windows) {
        try { terminateGroup(child.pid); }
        catch (error) { resolve({ code, signal, error: error.message, cleanup: "failed", remaining: null }); return; }
      }
      resolve({ code, signal, ...clean });
    });
  });
  function terminate() {
    if (!child.pid || child.exitCode !== null || child.signalCode !== null) return;
    if (!windows) { terminateGroup(child.pid); return; }
    return new Promise((resolve, reject) => {
      const killer = spawn(join(process.env.SystemRoot || "C:\\Windows", "System32", "taskkill.exe"),
        ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore", windowsHide: true });
      killer.once("error", reject);
      killer.once("exit", code => code === 0 || child.exitCode !== null || child.signalCode !== null
        ? resolve() : reject(new Error(`Could not stop command tree (taskkill exit ${code})`)));
    });
  }
  return {
    ready: child.pid ? Promise.resolve({ pid: child.pid }) : exit.then(() => undefined), exit, terminate,
    write: input => new Promise((resolve, reject) => {
      if (child.stdin.destroyed) { reject(new Error("Command input closed")); return; }
      child.stdin.write(input, error => error ? reject(error) : resolve());
    }),
  };
}

export function launchCommand(options) {
  return windows && options.host ? launchWindowsHost(options) : launchDirect(options);
}
