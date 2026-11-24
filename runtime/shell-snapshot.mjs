// Session capture and replay adapted from OpenAI Codex (Apache-2.0),
// rust-v0.172.0: codex-rs/core/src/shell_snapshot.rs and
// codex-rs/core/src/unified_exec/shell_snapshot.rs. See licenses/codex-NOTICE.txt.
import { execFile } from "node:child_process";
import { lstatSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { delimiter, win32 } from "node:path";
import { promisify } from "node:util";

const run = promisify(execFile);
const marker = "\0UMEKO_SHELL_ENV\0";
const captureOptions = { timeout: 10_000, maxBuffer: 2 * 1024 * 1024, windowsHide: true };
const powershellEncoding = "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false);";
const windows = process.platform === "win32";
export const blockedShellEnvKey = key =>
  /API_KEY$|ACCESS_TOKEN$|_(AK|SK|SECRET_KEY|SECURITY_TOKEN)$|^NODE_(OPTIONS|PATH)$/i.test(key);
const shellLocalKeys = /^(PWD|OLDPWD|SHLVL|_|BASH_ENV|ENV|UMEKO_(BASH_JOB_HOST|BASH_JOB_SCRIPT))$/i;
const runtimeSessionKeys = /^PI_(SESSION_ID|SESSION_FILE|PROVIDER|MODEL|REASONING_LEVEL)$/;
const windowsApps = entry => /[\\/]Microsoft[\\/]WindowsApps[\\/]?$/i.test(entry);
const pathEntry = entry => entry.trim().replace(/^"(.*)"$/, "$1");
const normalized = entry => win32.normalize(pathEntry(entry)).toLowerCase();
const entries = (path, separator = delimiter) => (path || "").split(separator).map(pathEntry).filter(Boolean);

function executable(path) {
  try { const stat = lstatSync(path); return stat.isFile() || stat.isSymbolicLink(); }
  catch { return false; }
}

function appAlias(path) {
  try { const stat = lstatSync(path); return stat.isSymbolicLink() || stat.size === 0; }
  catch { return false; }
}

export function preferRealExecutables(pathEntries) {
  const ordered = [...pathEntries];
  for (const directory of pathEntries.filter(windowsApps)) {
    let aliases;
    try { aliases = readdirSync(directory).filter(name => /\.exe$/i.test(name) && appAlias(win32.join(directory, name))); }
    catch { continue; }
    const index = ordered.indexOf(directory);
    const lastReal = ordered.reduce((last, candidate, position) => position > index && !windowsApps(candidate) &&
      aliases.some(name => executable(win32.join(candidate, name))) ? position : last, index);
    if (lastReal > index) {
      ordered.splice(index, 1);
      ordered.splice(lastReal, 0, directory);
    }
  }
  return ordered;
}

function setEnv(env, key, value) {
  const name = windows ? Object.keys(env).find(name => name.toLowerCase() === key.toLowerCase()) || key : key;
  env[name] = value;
}

function getEnv(env, key) {
  return env[windows ? Object.keys(env).find(name => name.toLowerCase() === key.toLowerCase()) || key : key];
}

function prefixPath(env, directories) {
  const path = entries(getEnv(env, "PATH"));
  const equal = windows ? normalized : entry => entry;
  const prepend = directories.filter(directory => directory && !path.some(entry => equal(entry) === equal(directory)));
  setEnv(env, "PATH", [...prepend, ...path].join(delimiter));
}

export function parseCapturedEnvironment(stdout) {
  const start = stdout.lastIndexOf(marker);
  if (start < 0 || !stdout.endsWith("\0")) throw new Error("Missing shell environment");
  const environment = Object.create(null);
  for (const item of stdout.slice(start + marker.length).split("\0")) {
    const separator = item.indexOf("=");
    if (separator < 1) continue;
    const key = item.slice(0, separator);
    if (!blockedShellEnvKey(key) && !shellLocalKeys.test(key) && !runtimeSessionKeys.test(key)) {
      setEnv(environment, key, item.slice(separator + 1));
    }
  }
  return environment;
}

const registryScript = powershellEncoding + String.raw`
  $separator = [char]0
  [Console]::Write([string]$separator + "UMEKO_SHELL_ENV" + $separator)
  $machine = [Environment]::GetEnvironmentVariables("Machine")
  $user = [Environment]::GetEnvironmentVariables("User")
  $userPath = $user["Path"]
  $user.Remove("Path")
  foreach ($name in $user.Keys) { $machine[$name] = $user[$name] }
  $machine["Path"] = (@($machine["Path"], $userPath) -ne $null) -join ";"
  foreach ($name in $machine.Keys) {
    [Console]::Write($name + "=" + $machine[$name] + $separator)
  }
`;

const powershellCapture = powershellEncoding + String.raw`
  $separator = [char]0
  [Console]::Write([string]$separator + "UMEKO_SHELL_ENV" + $separator)
  foreach ($item in [Environment]::GetEnvironmentVariables().GetEnumerator()) {
    [Console]::Write($item.Key + "=" + $item.Value + $separator)
  }
`;

async function findRegisteredPython(env, path, cwd) {
  if (!path.some(directory => windowsApps(directory) && appAlias(win32.join(directory, "python.exe"))) ||
      path.some(directory => !windowsApps(directory) && executable(win32.join(directory, "python.exe")))) return;
  const launcher = path.filter(directory => !windowsApps(directory))
    .map(directory => win32.join(directory, "py.exe")).find(executable);
  if (!launcher) return;
  try {
    // Enumeration prints the registered paths without executing an interpreter or a Store alias.
    const { stdout } = await run(launcher, ["-0p"], { ...captureOptions, cwd, env });
    for (const line of stdout.split(/\r?\n/)) {
      const candidate = line.match(/[A-Za-z]:[\\/].+?python\.exe\s*$/i)?.[0].trim();
      if (candidate && !windowsApps(win32.dirname(candidate)) && executable(candidate)) return win32.dirname(candidate);
    }
  } catch { /* A missing Python launcher must not prevent the shell from starting. */ }
}

async function refreshWindowsEnvironment(base, powerShell, cwd, previousPath) {
  if (!powerShell) return { environment: base, registryPath: previousPath };
  try {
    const { stdout } = await run(powerShell.shell, ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", registryScript],
      { ...captureOptions, cwd, env: base });
    const persistent = parseCapturedEnvironment(stdout);
    const registryPath = entries(getEnv(persistent, "PATH"));
    const currentPath = new Set(registryPath.map(normalized));
    const path = entries(getEnv(base, "PATH")).filter(directory =>
      !previousPath.has(normalized(directory)) || currentPath.has(normalized(directory)));
    const known = new Set(path.map(normalized));
    path.push(...registryPath.filter(directory => !known.has(normalized(directory))));
    const environment = { ...base };
    for (const [key, value] of Object.entries(persistent)) setEnv(environment, key, value);
    const python = await findRegisteredPython(environment, path, cwd);
    if (python) path.push(python);
    setEnv(environment, "PATH", preferRealExecutables(path).join(";"));
    return { environment, registryPath: currentPath };
  } catch {
    return { environment: base, registryPath: previousPath };
  }
}

async function capture(shellName, config, env, cwd, prepareCapture) {
  if (!config || config.commandTransport === "stdin") return null;
  let args;
  if (shellName === "powershell") {
    args = ["-NoLogo", "-NonInteractive", "-Command", powershellCapture];
  } else {
    // Git Bash reports PATH in MSYS syntax; convert it before giving it back to Win32.
    const script = String.raw`printf "\0UMEKO_SHELL_ENV\0"; command env -0`;
    const windowsPath = String.raw`; printf "PATH=%s\0" "$(/usr/bin/cygpath -wp "$PATH")"`;
    args = ["--login", "-i", "-c", windows ? script + windowsPath : script];
  }
  try {
    const command = await prepareCapture?.({ file: config.shell, args, env, cwd }) || { file: config.shell, args, env, cwd };
    const { stdout } = await run(command.file, command.args, { ...captureOptions, env: command.env, cwd: command.cwd });
    const result = parseCapturedEnvironment(stdout);
    if (windows) setEnv(result, "PATH", preferRealExecutables(entries(getEnv(result, "PATH"))).join(";"));
    return result;
  } catch {
    return null;
  }
}

export function createShellSnapshots({ getShellConfig, getPowerShellConfig, bundledBin, bundledNodeDir, cwd = homedir(), prepareCapture }) {
  const sessions = new Map();
  let previousPath = new Set();
  const config = get => { try { return get(); } catch { return null; } };
  function refresh(id, shellPath) {
    shellPath ??= sessions.get(id)?.shellPath;
    const pending = (async () => {
      const bash = config(() => getShellConfig(shellPath));
      const powershell = windows ? config(getPowerShellConfig) : null;
      const base = Object.fromEntries(Object.entries(process.env).filter(([key]) => !blockedShellEnvKey(key)));
      if (bundledNodeDir) {
        const equal = windows ? normalized : entry => entry.replace(/\/$/, "");
        const path = entries(getEnv(base, "PATH")).filter(entry => equal(entry) !== equal(bundledNodeDir));
        setEnv(base, "PATH", path.join(delimiter));
      }
      const updated = windows ? await refreshWindowsEnvironment(base, powershell, cwd, previousPath) : { environment: base };
      if (updated.registryPath) previousPath = updated.registryPath;
      const [bashEnv, powerShellEnv] = await Promise.all([
        capture("bash", bash, updated.environment, cwd, prepareCapture),
        capture("powershell", powershell, updated.environment, cwd, prepareCapture),
      ]);
      return { base: updated.environment, bash: bashEnv, powershell: powerShellEnv };
    })();
    sessions.set(id, { shellPath, pending });
    return pending;
  }
  const current = (id, shellPath) => sessions.get(id)?.pending || refresh(id, shellPath);
  return {
    invalidate() { for (const session of sessions.values()) session.pending = undefined; },
    begin(id, shellPath) { void current(id, shellPath); },
    forget(id) { sessions.delete(id); },
    shellPath(id) { return sessions.get(id)?.shellPath; },
    async refresh(id, shellPath) {
      const data = await refresh(id, shellPath);
      return { bash: data.bash ? "captured" : "inherited",
        ...(windows ? { powershell: data.powershell ? "captured" : "inherited" } : {}) };
    },
    async environment(shellName, id, spawnEnv, shellPath) {
      const data = await current(id, shellPath);
      const env = { ...(data[shellName.toLowerCase()] || data.base) };
      for (const [key, value] of Object.entries(spawnEnv || {})) {
        if (runtimeSessionKeys.test(key)) setEnv(env, key, value);
      }
      prefixPath(env, [bundledBin]);
      if (bundledNodeDir) {
        const path = entries(getEnv(env, "PATH"));
        setEnv(env, "PATH", [...path, bundledNodeDir].join(delimiter));
      }
      return env;
    },
  };
}
