import { existsSync, realpathSync } from 'node:fs';
import { isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const helper = fileURLToPath(new URL('./bin/windows-sandbox/umeko-sandbox.exe', import.meta.url));

function includesPath(root, target) {
  const suffix = relative(root, target);
  return suffix !== '..' && !suffix.startsWith('..\\') && !suffix.startsWith('../') && !isAbsolute(suffix);
}

// Prepare a native argv launch. The existing caller continues to own stdio,
// cancellation, and the Windows Job Object or background job record.
export function sandboxCommand({ file, args, cwd, env = process.env, workspace, policy }, {platform = process.platform} = {}) {
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
  if (/(?:^|[\\/])wsl(?:\.exe)?$/i.test(file) || /^.*[\\/]Windows[\\/]System32[\\/]bash\.exe$/i.test(file)) {
    throw new Error('Windows sandbox blocked the WSL launcher: use Git Bash or Windows PowerShell for this command.');
  }
  return {
    file: launcher,
    args: ['run', policy.home, policy.temp, root, directory, level, allowNetwork ? 'allow' : 'block', file, ...args],
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
  if (!allowNetwork && /\b(?:10013|WSAEACCES|ENETUNREACH)\b|could not connect|failed to connect|network is unreachable|connection refused|proxy error|无法连接/i.test(output)) {
    return 'The command could not connect. This Windows sandbox was configured to block network access.';
  }
  if (/permission denied|access (?:is )?denied|unauthorizedaccessexception|\bEACCES\b|拒绝访问|沒有存取權限/i.test(output)) {
    return 'Windows denied access while the sandbox was active. Write files only in the current workspace or the sandbox temp directory. Check the command output for the path.';
  }
  return `Windows sandbox was active (${level}). Writes are limited to the current workspace and sandbox temp directory. Network access was ${allowNetwork ? 'allowed' : 'blocked'}.`;
}

// Pi reconnects a closed transport with the latest settings. A stale client
// cannot start a subprocess or send it work once its transport is closed.
export function trackLocalMcpTransport(transport, active) {
  for (const method of ['start', 'send']) {
    const invoke = transport[method].bind(transport);
    transport[method] = async (...args) => {
      if (!active.has(transport)) throw new Error('The local MCP connection closed. Reconnect it to use the current Windows sandbox policy.');
      return invoke(...args);
    };
  }
  const close = transport.close.bind(transport);
  transport.close = async (...args) => {
    active.delete(transport);
    return close(...args);
  };
  active.add(transport);
  return transport;
}
