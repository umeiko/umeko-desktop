// Resolve before spawning: Windows' executable search can prefer System32 to
// PATH. OpenSSH itself evaluates Host/Include/Match; no private key is read here.
import childProcess from "node:child_process";
import fs from "node:fs/promises";
import { constants } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import shellQuote from "shell-quote";

const envValue = (env, name) => env[Object.keys(env).find(key => key.toLowerCase() === name.toLowerCase())] || "";
const validHost = host => typeof host === "string" && /^[a-zA-Z0-9_][a-zA-Z0-9_.@:\-]*$/.test(host);
const posixPath = value => /(?:^|[\s="'`(])\/(?!\/)/.test(value);
const msysSsh = executable => /[\\/]usr[\\/]bin[\\/]ssh(?:\.exe)?$/i.test(executable);

export function sshDiagnostic(stderr) {
  return String(stderr || "").split(/\r?\n/)
    .map(line => line.replace(/[\x00-\x1f\x7f-\x9f]/g, "").trim())
    .filter(line => line && !/^debug[123]:/i.test(line))
    .slice(-8).map(line => line.slice(0, 512)).join("\n");
}

async function executableFile(file, windows) {
  try {
    if (!(await fs.stat(file)).isFile()) return false;
    if (!windows) await fs.access(file, constants.X_OK);
    return true;
  } catch { return false; }
}

async function gitSshCandidates(env, userHome, directories) {
  const p = path.win32;
  const roots = [
    ...[envValue(env, "ProgramFiles"), envValue(env, "ProgramFiles(x86)"), envValue(env, "ProgramW6432")].filter(Boolean).map(root => p.join(root, "Git")),
    p.join(envValue(env, "LOCALAPPDATA") || p.join(userHome, "AppData", "Local"), "Programs", "Git"),
    p.join(userHome, "scoop", "apps", "git", "current"),
  ];
  for (const directory of directories) {
    if (await executableFile(p.join(directory, "git.exe"), true)) {
      roots.push(p.resolve(directory, ".."));
      if (/[/\\]mingw(?:32|64)[/\\]bin$/i.test(directory)) roots.push(p.resolve(directory, "..", ".."));
    }
  }
  return [...new Set(roots.map(root => p.resolve(root, "usr", "bin", "ssh.exe")))];
}

function effectiveConfig(executable, args, env) {
  return new Promise((resolve, reject) => {
    // -G does not connect or launch ProxyCommand. It DOES preserve the user's
    // Match exec semantics, which can run commands from their own SSH config.
    childProcess.execFile(executable, ["-G", ...args], { env, windowsHide: true, timeout: 10_000, maxBuffer: 1024 * 1024 }, (error, stdout, stderr) => {
      if (error) {
        const sshError = sshDiagnostic(stderr);
        const message = "Unable to evaluate OpenSSH configuration (ssh -G)";
        return reject(Object.assign(new Error(sshError ? `${message}\n${sshError}` : message),
          { sshClient: executable, ...(sshError ? { sshError } : {}) }));
      }
      resolve(String(stdout));
    });
  });
}

// Only recognize a direct OpenSSH ProxyCommand. This is argv inspection, never
// shell execution. Arbitrary shell scripts/wrappers cannot be evaluated safely.
function proxySshArguments(command) {
  let words;
  try { words = shellQuote.parse(command, name => `$${name}`); } catch { return null; }
  if (words.some(word => typeof word !== "string")) return null;
  if (!/(?:^|[\\/])ssh(?:\.exe)?$/i.test(words[0] || "")) return null;
  const args = words.slice(1);
  const probeArgs = [];
  const takesValue = new Set(["B", "b", "c", "D", "E", "e", "F", "I", "i", "J", "L", "l", "m", "O", "o", "P", "p", "Q", "R", "S", "W", "w"]);
  for (let index = 0; index < args.length; index++) {
    const value = args[index];
    if (!value.startsWith("-")) return validHost(value) ? [...probeArgs, value] : null;
    if (value === "--") return validHost(args[index + 1]) ? [...probeArgs, "--", args[index + 1]] : null;
    // The outer client expands %h:%p before running a proxy. Passing that raw
    // forwarding specification to -G would fail validation, despite no connect.
    // Forwarding options do not change IdentityFile/ProxyCommand selection.
    if (/^-[DLRWw]/.test(value)) {
      if (value.length === 2) index++;
      continue;
    }
    probeArgs.push(value);
    for (let letter = 1; letter < value.length; letter++) {
      if (!takesValue.has(value[letter])) continue;
      if (letter === value.length - 1 && index + 1 < args.length) probeArgs.push(args[++index]);
      break;
    }
  }
  return null;
}

function jumpArguments(value) {
  return value.split(",").filter(jump => jump && jump !== "none").map(jump => {
    const match = /^(?:([^@]+)@)?([^:]+)(?::(\d+))?$/.exec(jump);
    if (!match || !validHost(match[2])) return null;
    return [...(match[1] ? ["-l", match[1]] : []), ...(match[3] ? ["-p", match[3]] : []), match[2]];
  }).filter(Boolean);
}

async function requiresMsys(executable, host, env) {
  const pending = [[host]], visited = new Set();
  while (pending.length) {
    const args = pending.shift();
    const identity = JSON.stringify(args);
    if (visited.has(identity)) continue;
    if (visited.size >= 32) throw new Error("OpenSSH proxy configuration has too many nested hosts. Simplify the proxy chain before reconnecting.");
    visited.add(identity);
    const config = await effectiveConfig(executable, args, env);
    for (const line of config.split(/\r?\n/)) {
      const match = /^(identityfile|proxycommand|proxyjump)\s+(.+)$/i.exec(line);
      if (!match) continue;
      const [, key, value] = match;
      if (key.toLowerCase() !== "proxyjump" && posixPath(value)) return true;
      if (key.toLowerCase() === "proxycommand" && value !== "none") {
        const nested = proxySshArguments(value);
        if (nested) pending.push(nested);
      }
      if (key.toLowerCase() === "proxyjump") pending.push(...jumpArguments(value));
    }
  }
  return false;
}

/** Select an absolute OpenSSH executable using the caller's shell environment. */
export async function selectSshClient(host, { env = process.env, platform = process.platform, userHome = homedir() } = {}) {
  if (!validHost(host)) throw new Error("Enter an OpenSSH host alias or hostname");
  const windows = platform === "win32", p = windows ? path.win32 : path.posix;
  const directories = envValue(env, "PATH").split(windows ? ";" : ":").map(entry => entry.replace(/^"(.*)"$/, "$1")).map(entry => p.resolve(entry || "."));
  let preferred;
  for (const directory of directories) {
    const candidate = p.join(directory, windows ? "ssh.exe" : "ssh");
    if (await executableFile(candidate, windows)) { preferred = candidate; break; }
  }
  if (!windows) {
    if (preferred) return preferred;
    throw new Error("OpenSSH was not found on PATH. Install OpenSSH or add its executable directory to your shell PATH, then restart Umeko.");
  }
  if (preferred && msysSsh(preferred)) return preferred;
  if (preferred && !await requiresMsys(preferred, host, env)) return preferred;
  for (const candidate of await gitSshCandidates(env, userHome, directories)) {
    if (await executableFile(candidate, true)) return candidate;
  }
  if (preferred) throw new Error("This host uses POSIX paths in OpenSSH configuration. Install Git for Windows with OpenSSH, or use Windows paths in IdentityFile and ProxyCommand, then reconnect.");
  throw new Error("OpenSSH was not found on PATH or in a standard Git for Windows installation. Install OpenSSH or Git for Windows, then restart Umeko.");
}
