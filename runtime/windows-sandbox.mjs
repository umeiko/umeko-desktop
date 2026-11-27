import { closeSync, existsSync, lstatSync, openSync, readFileSync, readSync, realpathSync, rmSync } from 'node:fs';
import { dirname, isAbsolute, join, relative, resolve, win32 } from 'node:path';
import { fileURLToPath } from 'node:url';

const helper = fileURLToPath(new URL('./bin/windows-sandbox/umeko-sandbox.exe', import.meta.url));
const gitFiles = ['bin/bash.exe', 'usr/bin/bash.exe', 'usr/bin/msys-2.0.dll', 'cmd/git.exe', 'ucrt64/bin/git.exe', 'usr/bin/rg.exe'];

function hasGitBash(policy) {
  if (!policy.gitReady || !policy.gitRoot || !policy.archive || !existsSync(policy.archive)) return false;
  try {
    const lengths = readFileSync(join(policy.gitRoot, '.ready'), 'ascii').trim().split('\n');
    const header = Buffer.alloc(2);
    return lengths.length === gitFiles.length && gitFiles.every((file, index) => {
      const path = join(policy.gitRoot, file);
      const stat = lstatSync(path);
      if (!stat.isFile() || stat.size < 2 || stat.size !== Number(lengths[index])) return false;
      const fd = openSync(path, 'r');
      try { return readSync(fd, header, 0, 2, 0) === 2 && header.toString('ascii') === 'MZ'; }
      finally { closeSync(fd); }
    });
  } catch { return false; }
}

export function createSandboxPreparation({ getPolicy, request, language, platform = process.platform,
  required = policy => policy?.enabled }) {
  let pending;
  let reportedAttempt;
  function settle(error) {
    const current = pending;
    pending = undefined;
    if (error) current?.reject(error);
    else current?.resolve();
  }
  function changed() {
    if (!pending) return;
    const policy = getPolicy();
    if (!required(policy) || hasGitBash(policy)) settle();
    else if (!policy.preparing && policy.preparationError && policy.preparationAttempt > pending.attempt) {
      settle(new Error(policy.preparationError));
    }
  }
  async function wait(signal, { report = false } = {}) {
    let policy = getPolicy();
    while (platform === 'win32' && required(policy) && !hasGitBash(policy)) {
      if (signal?.aborted) throw new Error('aborted');
      let flight = pending;
      if (!flight) {
        flight = pending = { ...Promise.withResolvers(), attempt: policy.preparationAttempt ?? 0 };
        request();
      }
      const result = flight.promise;
      let abort;
      try {
        await (signal ? Promise.race([result, new Promise((_, reject) => {
          abort = () => reject(new Error('aborted'));
          signal.addEventListener('abort', abort, { once: true });
          if (signal.aborted) abort();
        })]) : result);
      } finally { signal?.removeEventListener('abort', abort); }
      policy = getPolicy();
    }
    if (signal?.aborted) throw new Error('aborted');
    let notice;
    if (report && platform === 'win32' && policy?.enabled && Number.isFinite(policy.preparationSeconds)
        && policy.preparationAttempt !== reportedAttempt) {
      reportedAttempt = policy.preparationAttempt;
      const seconds = policy.preparationSeconds.toFixed(1);
      if (language?.()?.startsWith('zh')) {
        notice = policy.preparationFirstUse ? `首次使用沙箱，已准备 Git Bash，用时 ${seconds} 秒。`
          : `已恢复沙箱的 Git Bash，用时 ${seconds} 秒。`;
      } else {
        notice = policy.preparationFirstUse ? `Prepared Git Bash for first use of the Windows sandbox in ${seconds} seconds.`
          : `Restored Git Bash for the Windows sandbox in ${seconds} seconds.`;
      }
    }
    return { policy, notice };
  }
  return { wait, changed, close: () => settle(new Error('aborted')) };
}

function includesPath(root, target) {
  const suffix = relative(root, target);
  return suffix !== '..' && !suffix.startsWith('..\\') && !suffix.startsWith('../') && !isAbsolute(suffix);
}

// Follow Codex's shell detection approach: select an actual shell executable
// by type; preserve an explicit user choice. See rust-v0.172.0 shell_detect.rs.
export async function resolveLocalBash({ shellPath, getShellConfig, policy, prepareBundle, signal,
  platform = process.platform }) {
  if (platform !== 'win32' || shellPath || !policy?.bundledGitBash) return getShellConfig(shellPath);
  let discovered;
  try { discovered = getShellConfig(); } catch { /* A packaged copy is available. */ }
  if (discovered && !discovered.commandTransport) {
    const parent = dirname(dirname(discovered.shell));
    if ([parent, dirname(parent)].some(root =>
      existsSync(join(root, 'usr', 'bin', 'msys-2.0.dll')) && existsSync(join(root, 'cmd', 'git.exe')))) {
      return discovered;
    }
  }
  const { policy: prepared } = await prepareBundle(signal);
  return getShellConfig(join(prepared.gitRoot, 'usr', 'bin', 'bash.exe'));
}

const bashHints = 'Use the bash tool for Unix commands and pipelines on Windows, including grep, tail, head, sed, cat, wc and find. Prefer the grep tool or rg to search file contents.';
const powershellHints = 'Use PowerShell syntax in the powershell tool. For Unix commands and pipelines use the bash tool. Use Select-String for matching text, Get-Content -Tail for the last lines, and Get-ChildItem for file lists. Read UTF-8 files with Get-Content -Encoding UTF8.';
export function windowsShellHints(name, { platform = process.platform } = {}) {
  if (platform !== 'win32') return '';
  return name === 'bash' ? bashHints : name === 'powershell' ? powershellHints : '';
}

// Prepare a native argv launch. The existing caller continues to own stdio,
// cancellation, and the Windows Job Object or background job record.
export function sandboxCommand({ file, args, cwd, env = process.env, workspace, policy, stdinOpen = false }, {platform = process.platform} = {}) {
  const legacyWslBash = /^.*[\\/]Windows[\\/]System32[\\/]bash\.exe$/i.test(file);
  if (platform === 'win32' && policy?.gitRoot && /(?:^|[\\/])bash(?:\.exe)?$/i.test(file)) {
    const packagedBash = join(policy.gitRoot, 'usr', 'bin', 'bash.exe');
    if ((policy.enabled && !legacyWslBash) ||
        win32.normalize(file).toLowerCase() === win32.normalize(packagedBash).toLowerCase()) {
      // Launch the actual MSYS executable with its own utilities on PATH.
      const pathKey = Object.keys(env).find(key => key.toUpperCase() === 'PATH') || 'PATH';
      env = { ...env, [pathKey]: [join(policy.gitRoot, 'usr', 'bin'), join(policy.gitRoot, 'ucrt64', 'bin'), env[pathKey]]
        .filter(Boolean).join(win32.delimiter) };
      file = packagedBash;
    }
  }
  if (platform !== 'win32' || !policy?.enabled) return { file, args, env, level: 'off' };
  const launcher = policy.launcher || helper;
  if (!existsSync(launcher)) throw new Error('Windows sandbox could not start: the packaged launcher is missing. Use a complete Windows package.');
  if (!policy.home || !policy.temp || !workspace) throw new Error('Windows sandbox could not start: workspace or sandbox storage is missing.');
  const root = realpathSync.native(workspace);
  const directory = realpathSync.native(resolve(root, cwd || root));
  if (!includesPath(root, directory)) {
    throw new Error('Windows sandbox blocked the working directory: start the command inside the current workspace.');
  }
  if ([policy.home, policy.temp, launcher].some(path => includesPath(root, path))) {
    throw new Error('Windows sandbox blocked this workspace because it contains the launcher or sandbox settings. Choose a project folder inside it.');
  }
  const level = policy.elevated ? 'elevated' : 'non-elevated';
  const allowNetwork = policy.allowNetwork || level === 'non-elevated';
  const notice = allowNetwork && !policy.allowNetwork
    ? 'Windows sandbox is running with file-system restrictions. Network blocking is not active until you complete administrator setup in Agent settings.'
    : undefined;
  if (/(?:^|[\\/])wsl(?:\.exe)?$/i.test(file) || legacyWslBash) {
    throw new Error('Windows sandbox blocked the WSL launcher: use Git Bash or Windows PowerShell for this command.');
  }
  return {
    file: launcher,
    args: ['run', policy.home, policy.temp, root, directory, level, allowNetwork ? 'allow' : 'block',
      ...(stdinOpen ? ['--stdin-open'] : []), file, ...args],
    env,
    level,
    allowNetwork,
    notice,
  };
}

export function sandboxFailure(level, allowNetwork, output = '') {
  if (level === 'off') return undefined;
  const startup = output.split(/\r?\n/).find(line => line.startsWith('Windows sandbox could not start:'));
  if (startup) return startup;
  if (/couldn.t create signal pipe, Win32 error 5/i.test(output)) {
    return 'Git Bash could not initialize its signal pipe inside the Windows sandbox. Use the PowerShell tool, or set shell to powershell in background_job.';
  }
  if (!allowNetwork && /\b(?:10013|WSAEACCES|ENETUNREACH)\b|could not connect|failed to connect|network is unreachable|connection refused|proxy error|无法连接/i.test(output)) {
    return 'The command could not connect. This Windows sandbox was configured to block network access.';
  }
  if (/permission denied|access (?:is )?denied|unauthorizedaccessexception|\bEACCES\b|拒绝访问|沒有存取權限/i.test(output)) {
    return 'Windows denied access while the sandbox was active. Write files only in the current workspace or the sandbox temp directory. Check the command output for the path.';
  }
  return `Windows sandbox was active (${level}). Writes are limited to the current workspace and sandbox temp directory. Network access was ${allowNetwork ? 'allowed' : 'blocked'}.`;
}
