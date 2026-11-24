/** Durable remote commands, launched through the official Codex exec-server.
 * The managed launcher is short lived. Native detached workers own the command,
 * output log and stdin queue, so expiry of a WebSocket session cannot kill it.
 */
import { randomUUID } from 'node:crypto';
import path from 'node:path';
import { StringDecoder } from 'node:string_decoder';
import { setTimeout as delay } from 'node:timers/promises';

const DEFAULT_OUTPUT = 65536;
const MAX_OUTPUT = 1048576;
const idPattern = /^remote-[a-f0-9-]{36}$/;
const quoteSh = value => `'${String(value).replaceAll("'", "'\\''")}'`;
const quotePs = value => `'${String(value).replaceAll("'", "''")}'`;

function uri(value, windows) {
  if (/^file:/i.test(value)) return value;
  const normalized = value.replaceAll('\\', '/');
  if (windows && normalized.startsWith('//')) return new URL(`file:${normalized}`).href;
  return `file://${normalized.startsWith('/') ? '' : '/'}${normalized.split('/').map((part, index) => index === 0 && /^[A-Za-z]:$/.test(part) ? part : encodeURIComponent(part)).join('/')}`;
}

// Interpret remote file: URIs using the remote platform, not the client OS.
// node:fileURLToPath would turn a Linux URI into a local Windows path here.
function nativePath(value, windows) {
  if (typeof value !== 'string' || !value) throw new Error('Remote environment returned an invalid path');
  if (!/^file:/i.test(value)) return value;
  const url = new URL(value);
  const pathname = decodeURIComponent(url.pathname);
  if (!windows) {
    if (url.hostname && url.hostname !== 'localhost') throw new Error('Remote Linux file URI has an unsupported hostname');
    return pathname;
  }
  if (url.hostname && url.hostname !== 'localhost') return `\\\\${url.hostname}${pathname.replaceAll('/', '\\')}`;
  return pathname.replace(/^\/([A-Za-z]:)/, '$1').replaceAll('/', '\\');
}

function commandCwd(value, defaultCwd, home, windows) {
  const p = windows ? path.win32 : path.posix;
  let requested = nativePath(value ?? defaultCwd, windows);
  const base = nativePath(defaultCwd, windows);
  if (!p.isAbsolute(base)) throw new Error('Remote environment returned a nonabsolute cwd');
  if (windows && /^[A-Za-z]:(?:$|[^\\/])/.test(requested)) throw new Error('Drive-relative remote cwd is unsupported; use an absolute path');
  if (requested === '~') requested = home;
  else if ((windows ? /^~[\\/]/ : /^~\//).test(requested)) requested = p.join(home, requested.slice(2));
  return p.resolve(base, requested);
}

function isMissing(error) {
  return /ENOENT|not found|no such file|cannot find|os error 2\b|系统找不到指定的文件/i.test(String(error?.message ?? error));
}

function linuxWorker(root, cwd, shell) {
  return `#!/bin/sh
umask 077
cd ${quoteSh(root)} || exit 1
# mkdir is the launch receipt: replaying process/start never starts twice.
mkdir claimed 2>/dev/null || exit 0
: > output
mkfifo stdin || { echo 'Cannot create stdin FIFO' >> output; echo 1 > exit; exit 1; }
exec 3<>stdin
cd ${quoteSh(cwd)} || { echo 'Cannot enter command cwd' >> ${quoteSh(`${root}/output`)}; echo 1 > ${quoteSh(`${root}/exit`)}; exit 1; }
setsid ${quoteSh(shell)} ${quoteSh(`${root}/command.sh`)} < ${quoteSh(`${root}/stdin`)} >> ${quoteSh(`${root}/output`)} 2>&1 3>&- &
child=$!
printf '%s' "$child" > ${quoteSh(`${root}/pid`)}
(
  n=1
  while kill -0 "$child" 2>/dev/null; do
    if [ -f ${quoteSh(root)}/input-$n.ready ]; then
      cat ${quoteSh(root)}/input-$n.data >&3 || exit
      n=$((n + 1))
    elif [ -f ${quoteSh(`${root}/kill`)} ]; then
      kill -TERM -- "-$child" 2>/dev/null || kill -TERM "$child" 2>/dev/null
      sleep 1
      kill -KILL -- "-$child" 2>/dev/null || true
      exit
    else
      sleep 0.05
    fi
  done
) &
feeder=$!
wait "$child"
code=$?
kill "$feeder" 2>/dev/null || true
exec 3>&-
printf '%s' "$code" > ${quoteSh(`${root}/exit.tmp`)}
mv ${quoteSh(`${root}/exit.tmp`)} ${quoteSh(`${root}/exit`)}
`;
}

// PowerShell/.NET are supplied by Windows; the launcher explicitly escapes a
// parent's Job Object, with a separate hidden console (Windows PowerShell can
// silently skip execution with DETACHED_PROCESS and invalid console handles).
function windowsWorker(root, cwd, shell, commandFile) {
  const source = String.raw`
using System;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Diagnostics;
using System.Runtime.InteropServices;
public static class UmekoDurableCommand {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
  struct STARTUPINFO { public int cb; public string reserved, desktop, title; public int x,y,xSize,ySize,xChars,yChars,fill,flags; public short show,reserved2; public IntPtr reservedPtr,input,output,error; }
  [StructLayout(LayoutKind.Sequential)]
  struct PROCESS_INFORMATION { public IntPtr process,thread; public int pid,tid; }
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
  static extern bool CreateProcess(string app, StringBuilder command, IntPtr pa, IntPtr ta, bool inherit, uint flags, IntPtr env, string cwd, ref STARTUPINFO startup, out PROCESS_INFORMATION info);
  [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
  static string Q(string s) { return "\"" + s.Replace("\"", "\\\"") + "\""; }
  public static void Launch(string powershell, string script, string root) {
    STARTUPINFO si = new STARTUPINFO(); si.cb = Marshal.SizeOf(si); si.flags = 1; si.show = 0;
    PROCESS_INFORMATION pi;
    string args = Q(powershell) + " -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File " + Q(script);
    if (!CreateProcess(powershell, new StringBuilder(args), IntPtr.Zero, IntPtr.Zero, false,
        0x01000210, IntPtr.Zero, root, ref si, out pi))
      throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
    CloseHandle(pi.thread); CloseHandle(pi.process);
  }
  static Task Pump(Stream input, FileStream output, object gate) {
    return Task.Run(() => { byte[] buffer = new byte[8192]; int count;
      while ((count = input.Read(buffer, 0, buffer.Length)) > 0) {
        lock (gate) { output.Write(buffer, 0, count); output.Flush(); }
      }
    });
  }
  public static void Run(string shell, string arguments, string cwd, string root) {
    try { using (File.Open(Path.Combine(root,"claimed"), FileMode.CreateNew, FileAccess.Write, FileShare.Read)) {} }
    catch (IOException) { if (File.Exists(Path.Combine(root,"claimed"))) return; throw; }
    int code = 1;
    try {
      using (FileStream output = new FileStream(Path.Combine(root,"output"), FileMode.Create, FileAccess.Write, FileShare.ReadWrite)) {
        ProcessStartInfo info = new ProcessStartInfo(shell, arguments);
        info.WorkingDirectory = cwd; info.UseShellExecute = false; info.CreateNoWindow = true;
        info.RedirectStandardInput = true; info.RedirectStandardOutput = true; info.RedirectStandardError = true;
        using (Process child = Process.Start(info)) {
          File.WriteAllText(Path.Combine(root,"pid"), child.Id.ToString());
          object gate = new object();
          Task stdout = Pump(child.StandardOutput.BaseStream, output, gate);
          Task stderr = Pump(child.StandardError.BaseStream, output, gate);
          int n = 1;
          bool stdinClosed = false;
          while (!child.WaitForExit(50)) {
            if (File.Exists(Path.Combine(root,"kill"))) {
              using (Process killer = Process.Start(new ProcessStartInfo("taskkill.exe", "/PID " + child.Id + " /T /F") { UseShellExecute=false, CreateNoWindow=true })) { killer.WaitForExit(); }
              break;
            }
            string file = Path.Combine(root,"input-" + n);
            if (File.Exists(file + ".ready")) {
              if (!stdinClosed) {
                try { byte[] bytes = File.ReadAllBytes(file + ".data"); child.StandardInput.BaseStream.Write(bytes,0,bytes.Length); child.StandardInput.BaseStream.Flush(); }
                catch (IOException) { stdinClosed = true; }
              }
              n++;
            }
          }
          child.WaitForExit(); Task.WaitAll(stdout, stderr); code = child.ExitCode;
        }
      }
    } catch (Exception error) { File.AppendAllText(Path.Combine(root,"output"), error.ToString(), new UTF8Encoding(false)); }
    File.WriteAllText(Path.Combine(root,"exit.tmp"), code.ToString());
    File.Move(Path.Combine(root,"exit.tmp"), Path.Combine(root,"exit"));
  }
}
`;
  const isCmd = /(?:^|[\\/])cmd(?:\.exe)?$/i.test(shell);
  const argumentsText = isCmd ? `/d /s /c ""${commandFile}""` : `-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "${commandFile}"`;
  return `param([switch]$Launch)
$ErrorActionPreference = 'Stop'
$root = ${quotePs(root)}
try { Add-Type -TypeDefinition @'
${source}
'@
} catch { [IO.File]::WriteAllText((Join-Path $root 'launch-error'), $_.Exception.ToString()); exit 1 }
if ($Launch) {
  try { [UmekoDurableCommand]::Launch((Join-Path $PSHOME 'powershell.exe'), $PSCommandPath, $root) }
  catch { [IO.File]::WriteAllText((Join-Path $root 'launch-error'), $_.Exception.ToString()); exit 1 }
} else {
  [UmekoDurableCommand]::Run(${quotePs(shell)}, ${quotePs(argumentsText)}, ${quotePs(cwd)}, $root)
}
`;
}

export function createRemoteCommands(connection) {
  const jobs = new Map();
  let queue = Promise.resolve();

  async function execute(args, { signal } = {}) {
    // One ordered cursor and one stdin sequence per command client. In particular,
    // simultaneous read calls must never consume the same bytes twice.
    const prior = queue;
    let release;
    queue = new Promise(resolve => { release = resolve; });
    await prior;
    let job;
    try {
      signal?.throwIfAborted();
      const metadata = await connection.ready();
      const windows = String(metadata.platformOs ?? connection.platform ?? connection.config?.platform).toLowerCase() === 'windows';
      const p = windows ? path.win32 : path.posix;
      const home = nativePath(metadata.userHomeDir, windows);
      const base = windows ? p.join(home, 'AppData', 'Local', 'Temp', 'umeko-remote-commands') : p.join(home, '.cache', 'umeko-remote-commands');
      const rpc = (method, params, retry = true) => connection.rpc(method, params, { signal, retry });
      const write = (file, value) => rpc('fs/writeFile', { path: uri(file, windows), dataBase64: Buffer.from(value).toString('base64') });
      const readText = async file => {
        try { return Buffer.from((await rpc('fs/readFile', { path: uri(file, windows) })).dataBase64, 'base64').toString('utf8'); }
        catch (error) { if (isMissing(error)) return null; throw error; }
      };
      const publishInput = async () => {
        if (!job.pendingInput) return;
        const pending = job.pendingInput;
        if (!pending.dataWritten) {
          await write(p.join(job.root, `input-${pending.number}.data`), pending.input);
          pending.dataWritten = true;
        }
        await write(p.join(job.root, `input-${pending.number}.ready`), '');
        job.inputSeq = pending.number;
        job.pendingInput = null;
      };
      const observeLauncher = async () => {
        if (!job.launcher?.pending) return;
        const launcher = job.launcher;
        try {
          const state = await rpc('process/read', { processId: launcher.processId, afterSeq: launcher.afterSeq, maxBytes: 16384, waitMs: 100 });
          launcher.afterSeq = state.nextSeq ?? launcher.afterSeq;
          launcher.output = (launcher.output + (state.chunks ?? []).map(chunk => Buffer.from(chunk.chunk, 'base64').toString('utf8')).join('')).slice(-16384);
          if (state.failure || state.exited && state.exitCode !== 0) throw new Error(`Remote command launcher failed: ${state.failure || launcher.output || `exit ${state.exitCode}`}`);
          if (state.exited) launcher.pending = false;
        } catch (error) {
          // The durable worker can already be running after its managed launcher
          // expired. Only the missing managed handle is harmless here.
          if (error.code !== 'REMOTE_SESSION_CHANGED' && !/unknown process|process.*not found/i.test(String(error?.message ?? error))) throw error;
          launcher.pending = false;
        }
      };
      const action = args.action ?? 'run';
      if (action === 'run') {
        if (typeof args.command !== 'string' || !args.command.trim()) throw new Error('remote_command run requires a nonempty command');
        const sessionId = `remote-${randomUUID()}`;
        job = { sessionId, root: p.join(base, sessionId), cursor: 0, inputSeq: 0, decoder: new StringDecoder('utf8') };
        jobs.set(sessionId, job);
        const cwd = commandCwd(args.cwd, metadata.cwd, home, windows);
        // Windows remote_command has PowerShell semantics even when the executor
        // reports cmd.exe as its detected login shell. File helpers rely on it.
        const shellPath = typeof metadata.shell === 'string' ? metadata.shell : metadata.shell?.path;
        const shell = windows ? 'powershell.exe' : shellPath ? nativePath(shellPath, false) : '/bin/sh';
        const isCmd = windows && /(?:^|[\\/])cmd(?:\.exe)?$/i.test(shell);
        const commandFile = p.join(job.root, windows ? (isCmd ? 'command.cmd' : 'command.ps1') : 'command.sh');
        const workerFile = p.join(job.root, windows ? 'worker.ps1' : 'worker.sh');
        await rpc('fs/createDirectory', { path: uri(job.root, windows), recursive: true });
        await write(commandFile, windows ? (isCmd ? `@chcp 65001 >nul\r\n${args.command}\r\n` : `\uFEFF[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)\n[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)\n$OutputEncoding = [Console]::OutputEncoding\n${args.command}\n`) : `${args.command}\n`);
        await write(workerFile, windows ? `\uFEFF${windowsWorker(job.root, cwd, shell, commandFile)}` : linuxWorker(job.root, cwd, shell));
        const argv = windows ? ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', workerFile, '-Launch'] : ['/bin/sh', '-c', `command -v setsid >/dev/null || { echo 'setsid is required' > ${quoteSh(p.join(job.root, 'launch-error'))}; exit 1; }; setsid /bin/sh ${quoteSh(workerFile)} </dev/null >${quoteSh(p.join(job.root, 'launcher.log'))} 2>&1 &`];
        const launchParams = { processId: `${sessionId}-launcher`, argv, cwd: uri(cwd, windows), envPolicy: { inherit: 'all', ignoreDefaultExcludes: false, exclude: [], set: {}, includeOnly: [] }, env: {}, tty: false, pipeStdin: false, arg0: null };
        job.launcher = { processId: launchParams.processId, afterSeq: null, output: '', pending: true };
        for (let attempt = 0; attempt < 2; attempt++) {
          try { await rpc('process/start', launchParams, false); break; }
          catch (error) {
            // The transport correctly refuses generic process/start replay.
            // This particular launcher is safe to replay: its native worker's
            // atomic claim prevents duplicate commands even in a new session.
            if (/already exists|duplicate|already.*process/i.test(String(error?.message ?? error))) break;
            if (attempt === 0 && error.transport && !signal?.aborted) { await connection.ready(); continue; }
            throw error;
          }
        }
        await observeLauncher();
      } else {
        if (!idPattern.test(args.sessionId ?? '')) throw new Error('A valid remote command sessionId is required');
        job = jobs.get(args.sessionId);
        if (!job) throw new Error(`Unknown remote command session: ${args.sessionId}`);
        // An identical write while its predecessor still has an unresolved
        // publication acknowledgement is a retry of that pending chunk.
        const retryPendingInput = action === 'write' && job.pendingInput?.input === args.input;
        await publishInput();
        if (action === 'write') {
          if (typeof args.input !== 'string') throw new Error('remote_command write requires input text');
          if (!retryPendingInput) job.pendingInput = { number: job.inputSeq + 1, input: args.input, dataWritten: false };
          // Keep the pending stage if the transport fails. A later call finishes
          // publishing the same chunk, without rewriting already-published data.
          await publishInput();
        } else if (action === 'kill') {
          await write(p.join(job.root, 'kill'), '');
        } else if (action !== 'read') throw new Error(`Unknown remote_command action: ${action}`);
      }

      const yieldMs = Math.max(0, Math.min(Number(args.yieldMs ?? (action === 'run' ? 1000 : 0)) || 0, 30000));
      const maxBytes = Math.max(1, Math.min(Math.trunc(Number(args.maxOutputBytes ?? DEFAULT_OUTPUT)) || DEFAULT_OUTPUT, MAX_OUTPUT));
      const deadline = Date.now() + yieldMs;
      let exitText;
      let bytes = Buffer.alloc(0);
      do {
        await observeLauncher();
        const launchError = await readText(p.join(job.root, 'launch-error'));
        if (launchError !== null) throw new Error(`Remote command launch failed: ${launchError}`);
        exitText = await readText(p.join(job.root, 'exit'));
        if (exitText !== null && job.launcher) job.launcher.pending = false;
        for (let attempt = 0; attempt < 2; attempt++) {
          const handleId = randomUUID().replaceAll('-', '');
          let opened = false;
          try {
            await rpc('fs/open', { handleId, path: uri(p.join(job.root, 'output'), windows), mode: 'read' });
            opened = true;
            if (job.launcher) job.launcher.pending = false;
            const block = await rpc('fs/readBlock', { handleId, offset: job.cursor, len: maxBytes });
            bytes = Buffer.from(block.chunk, 'base64');
            break;
          } catch (error) {
            if (attempt === 0 && (error.transport || error.code === 'REMOTE_SESSION_CHANGED' || /unknown.*handle|handle.*not found/i.test(String(error?.message ?? error)))) { await connection.ready(); continue; }
            if (!isMissing(error)) throw error;
            break;
          } finally { if (opened) await rpc('fs/close', { handleId }).catch(() => {}); }
        }
        if (bytes.length || exitText !== null || Date.now() >= deadline) break;
        await delay(Math.min(100, Math.max(1, deadline - Date.now())), undefined, { signal });
      } while (true);
      job.cursor += bytes.length;
      let output = job.decoder.write(bytes);
      // Terminal status is also the caller's stop-reading signal. A full block
      // requires another read even after process exit, including an exact-size
      // final block; otherwise callers could silently discard retained output.
      const outputPending = bytes.length >= maxBytes;
      const exitCode = exitText === null || outputPending ? null : Number(exitText.trim());
      if (exitCode !== null && bytes.length < maxBytes) output += job.decoder.end();
      return { sessionId: job.sessionId, status: exitCode === null ? 'running' : exitCode === 0 ? 'completed' : 'failed', output, exitCode, cursor: job.cursor };
    } catch (error) {
      if (job) error.sessionId = job.sessionId;
      throw error;
    } finally { release(); }
  }
  return { execute };
}
