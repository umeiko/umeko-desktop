import { spawn } from 'node:child_process';
import { posix } from 'node:path';

const quote = value => "'" + value.replaceAll("'", "'\"'\"'") + "'";
const names = ['bash', 'read', 'edit', 'write'];
const fileLimit = 16 * 1024 * 1024;

function runSsh(workspace, script, { input, signal, timeout = 30, onData } = {}) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new Error('aborted'));
    const child = spawn(workspace.executable, [...workspace.args, script], {
      stdio: [input === undefined ? 'ignore' : 'pipe', 'pipe', 'pipe'], windowsHide: true,
    });
    const stdout = [], stderr = [];
    let size = 0, error, settled = false, recentError = '';
    const stop = message => { error ??= new Error(message); child.kill(); };
    const abort = () => stop('aborted');
    const timer = setTimeout(() => stop(`timeout:${timeout}`), timeout * 1000);
    const finish = (code, startupError) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
      if (error || startupError) return reject(error || startupError);
      if (onData && code !== null && code !== 255) return resolve({exitCode: code});
      if (code === 0) return resolve(Buffer.concat(stdout));
      reject(new Error((onData ? recentError : Buffer.concat(stderr).toString()).trim() || `SSH exited with status ${code}.`));
    };
    for (const [stream, chunks] of [[child.stdout, stdout], [child.stderr, stderr]]) {
      stream.on('data', chunk => {
        if (error) return;
        if (onData) {
          if (stream === child.stderr) recentError = (recentError + chunk).slice(-1024);
          return onData(chunk);
        }
        size += chunk.length;
        if (size > fileLimit) return stop('Remote file exceeds the 16 MiB tool limit.');
        chunks.push(chunk);
      });
    }
    if (child.stdin) {
      child.stdin.on('error', err => { if (err.code !== 'EPIPE') stop(err.message); });
      child.stdin.end(input);
    }
    signal?.addEventListener('abort', abort, {once: true});
    child.once('error', error => finish(null, error));
    child.once('close', finish);
  });
}

export function sshWorkspaceTools(Pi, cwd, workspace) {
  const exec = (command, options) => runSsh(workspace, command, options);
  const bashWithCwd = command => `sh -c ${quote(`CDPATH=; cd ${quote(workspace.path)} || exit\nexec bash -c ${quote(command)}`)}`;
  const bash = Pi.createBashToolDefinition(cwd, {
    exposeSessionEnvironment: false,
    operations: { exec: (command, _cwd, { onData, signal, timeout }) =>
      exec(bashWithCwd(command), { onData, signal, timeout: timeout ?? 120 }) },
  });
  const makeFileTool = (factory, name) => {
    // Pi owns schemas, rendering and exact edit matching. Bind IO to the raw
    // POSIX path instead of Pi's local normalization or working directory.
    const template = factory(cwd);
    return { ...template, execute: (id, params, signal, update, ctx) => {
      const raw = params.path.replace(/^@/, '');
      const target = raw === '~' || raw.startsWith('~/')
        ? '"$HOME"' + (raw.length > 1 ? '/' + quote(raw.slice(2)) : '')
        : quote(posix.resolve(workspace.path, raw));
      const inShell = script => `sh -c ${quote(`file=${target}\n${script}`)}`;
      const operations = {
        access: async () => {},
        readFile: () => exec(inShell(`test -f "$file" || { printf 'Not a regular file: %s\\n' "$file" >&2; exit 1; }; cat "$file"`), { signal }),
        mkdir: async () => {},
        writeFile: (_path, input) => exec(inShell(`
dir=$(dirname "$file") || exit
${name === 'write' ? 'mkdir -p "$dir" || exit' : ''}
if [ -L "$file" ] || { [ -e "$file" ] && [ ! -f "$file" ]; }; then
  printf '%s\\n' 'The target must be a regular file.' >&2; exit 1
fi
tmp=$(mktemp "$dir/.umeko-write.XXXXXXXX") || exit
trap 'rm -f "$tmp"' EXIT
trap 'exit 1' HUP INT TERM
if [ -f "$file" ]; then cp -p "$file" "$tmp" || exit; fi
cat >"$tmp" || exit
bytes=$(wc -c <"$tmp") || exit
[ "$bytes" -eq ${Buffer.byteLength(input)} ] || exit 1
mv -f "$tmp" "$file"`), { input, signal }),
      };
      return factory(cwd, { operations }).execute(id, params, signal, update, ctx);
    } };
  };
  return [bash, makeFileTool(Pi.createReadToolDefinition, 'read'),
    makeFileTool(Pi.createEditToolDefinition, 'edit'), makeFileTool(Pi.createWriteToolDefinition, 'write')];
}

export const sshWorkspaceToolNames = names;
