// Official Codex exec-server v0.172.0 JSON-RPC over a private OpenSSH tunnel.
// Sources at tag rust-v0.172.0: codex-rs/exec-server/README.md,
// codex-rs/exec-server-protocol/src/{protocol,rpc}.rs,
// codex-rs/exec-server/src/client_recovery.rs, codex-rs/websocket-auth/src/lib.rs.
// SSH owns authentication and host identity; Umeko never handles private keys.
import { spawn } from "node:child_process";
import { createReadStream } from "node:fs";
import { access, mkdir, mkdtemp, readFile, rename, rmdir, unlink, writeFile } from "node:fs/promises";
import { createHash, randomBytes } from "node:crypto";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "node:net";
import { pipeline } from "node:stream/promises";
import { deflateRawSync } from "node:zlib";
import WebSocket from "ws";
import { updateRequest } from "./update-engine.mjs";
import { selectSshClient, sshDiagnostic } from "./remote-ssh-client.mjs";
import { withBootstrapLock } from "./remote-bootstrap-lock.mjs";
import { networkProbeUrl, networkTestScript, outboundLabels, remoteForwardStatus, remoteOutbound, serverNetwork } from "./remote-network.mjs";
import { prepareRemoteShellProcess } from "./remote-network-command.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const manifest = JSON.parse(await readFile(join(here, "remote-exec-assets.json"), "utf8"));
const retryable = new Set(["environment/info", "fs/readFile", "fs/readDirectory", "fs/getMetadata", "fs/getMetadataBatch", "fs/canonicalize", "fs/walk", "fs/readBlock", "process/read"]);
const sessionBound = new Set(["fs/readBlock", "fs/writeBlock", "process/read"]);
const quoteSh = value => `'${String(value).replaceAll("'", "'\\''")}'`;
const quotePs = value => `'${String(value).replaceAll("'", "''")}'`;
const exists = async path => access(path).then(() => true, () => false);
const abortError = () => Object.assign(new Error("Remote request cancelled"), { name: "AbortError" });
const connectionError = () => Object.assign(new Error("Remote connection interrupted"), { transport: true });
const fatalSsh = /permission denied|authentication failed|host key verification failed|remote host identification has changed|no matching host key|too many authentication failures|bad configuration|could not resolve hostname|unprotected private key|bad permissions|sign_and_send_pubkey: signing failed|posix_spawnp: no such file/i;
const disconnectedSsh = /connection (?:reset|timed out|closed)|connection to .+ closed by remote host|broken pipe|send\(\) failed,\s*10054|lost connection/i;
const rejectedSsh = /host key verification failed|remote host identification has changed|permission denied \(|no matching host key type found/i;
const retryDelays = [2_000, 4_000, 8_000, 16_000, 32_000, 60_000];
const outageTimeoutMs = 10 * 60_000;
const sessionChanged = () => Object.assign(new Error("Remote session expired; reopen the process or file handle"), { code: "REMOTE_SESSION_CHANGED" });
function sshFailure(message, stderr, transport, fatal = false) {
  const sshError = sshDiagnostic(stderr);
  return Object.assign(new Error(sshError ? `${message}\n${sshError}` : message), {
    transport, fatal: fatal || fatalSsh.test(sshError), ...(sshError ? { sshError } : {}),
  });
}
const sleep = (ms, signal) => new Promise((resolve, reject) => {
  if (signal?.aborted) return reject(abortError());
  const abort = () => { clearTimeout(timer); reject(abortError()); };
  const timer = setTimeout(() => { signal?.removeEventListener("abort", abort); resolve(); }, ms);
  signal?.addEventListener("abort", abort, { once: true });
});
export function sshArguments(host) {
  if (typeof host !== "string" || !/^[a-zA-Z0-9_][a-zA-Z0-9_.@:\-]*$/.test(host)) throw new Error("Enter an OpenSSH host alias or hostname");
  return ["-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2"];
}

function remoteCommand(platform, script) {
  if (platform !== "windows") return `sh -c ${quoteSh(script)}`;
  // An inline startup command avoids depending on stdin EOF through Windows
  // OpenSSH. Compress the longer listener script to fit cmd.exe's argv limit.
  const payload = deflateRawSync(script).toString("base64");
  const source = `$m=[IO.MemoryStream]::new([Convert]::FromBase64String('${payload}'));` +
    `$d=[IO.Compression.DeflateStream]::new($m,[IO.Compression.CompressionMode]::Decompress);` +
    `$r=[IO.StreamReader]::new($d);try{&([ScriptBlock]::Create($r.ReadToEnd()))}finally{$r.Dispose()}`;
  const command = `powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand ${Buffer.from(source, "utf16le").toString("base64")}`;
  if (command.length > 8191) throw new Error("Remote Windows startup command exceeds the cmd.exe command length limit");
  return command;
}

function sftpPath(value, windows, remote = false) {
  if (/[\r\n]/.test(value)) throw new Error("An SFTP path contains a newline");
  const normalized = windows ? value.replaceAll("\\", "/") : value;
  const absolute = remote && windows && /^[a-z]:\//i.test(normalized) ? `/${normalized}` : normalized;
  return `"${absolute.replaceAll("\\", "\\\\").replaceAll('"', '\\"')}"`;
}

export function discoveryScript(platform, uploadId) {
  if (platform === "windows") return `
$ErrorActionPreference='Stop'
$arch=[System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLowerInvariant()
if($arch -eq 'amd64'){$arch='x64'}
if($arch -notin @('x64','arm64')){throw 'Unsupported remote architecture'}
$root=Join-Path $HOME '.local/share/umeko/remote-exec/${manifest.version}'
$root=Join-Path $root $arch
$binary=Join-Path $root 'codex-exec-server.exe'
New-Item -ItemType Directory -Force -Path $root | Out-Null
$acl=New-Object System.Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true,$false)
$sid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User
$rule=New-Object System.Security.AccessControl.FileSystemAccessRule($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
$acl.AddAccessRule($rule);Set-Acl -LiteralPath $root -AclObject $acl
$staged=${uploadId ? `(Test-Path -LiteralPath (Join-Path $root ${quotePs(`upload-${uploadId}`)}) -PathType Leaf)` : "$false"}
@{arch=$arch;root=$root;binary=$binary;present=(Test-Path -LiteralPath $binary -PathType Leaf);staged=$staged} | ConvertTo-Json -Compress
`;
  return `set -eu
case "$(uname -m)" in x86_64|amd64) arch=x64;; aarch64|arm64) arch=arm64;; *) echo 'Unsupported remote architecture' >&2; exit 1;; esac
root="$HOME/.local/share/umeko/remote-exec/${manifest.version}/$arch"
umask 077; mkdir -p "$root"; chmod 700 "$root"
present=false; [ ! -f "$root/codex-exec-server" ] || present=true
staged=false${uploadId ? `; [ ! -f "$root/"${quoteSh(`upload-${uploadId}`)} ] || staged=true` : ""}
printf '%s\\n' "$arch" "$root" "$root/codex-exec-server" "$present" "$staged"
`;
}

// State is in a private home directory. Reuse requires the recorded executable
// to own the actual loopback listener, rather than trusting a saved port alone.
export function listenerScript(platform, root, binary) {
  if (platform === "windows") return `
$ErrorActionPreference='Stop'
$root=${quotePs(root)};$binary=${quotePs(binary)}
$statePath=Join-Path $root 'listener.json';$tokenPath=Join-Path $root 'listener.token'
function Owns-Listener([int]$processId,[int]$port){
 $pattern='(?m)^\\s*TCP\\s+127\\.0\\.0\\.1:'+$port+'\\s+0\\.0\\.0\\.0:0\\s+\\S+\\s+'+$processId+'\\s*$'
 return ((& netstat.exe -ano -p tcp | Out-String) -match $pattern)
}
$state=$null
if(Test-Path -LiteralPath $statePath){try{
 $saved=Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
 $proc=Get-Process -Id ([int]$saved.pid) -ErrorAction SilentlyContinue
 if($proc -and $proc.Path -eq $binary -and (Owns-Listener ([int]$saved.pid) ([int]$saved.port)) -and (Test-Path -LiteralPath $tokenPath)){$state=$saved}
}catch{}}
if(!$state){
 # Reuse the native breakaway/hidden-console launch method exercised by
 # remote-command.mjs. CIM/WMI is unavailable to ordinary SSH tokens.
 Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class UmekoRemoteExecutor {
 [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
 struct STARTUPINFO { public int cb; public string reserved, desktop, title; public int x,y,xSize,ySize,xChars,yChars,fill,flags; public short show,reserved2; public IntPtr reservedPtr,input,output,error; }
 [StructLayout(LayoutKind.Sequential)]
 struct PROCESS_INFORMATION { public IntPtr process,thread; public int pid,tid; }
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
 static extern bool CreateProcess(string app, StringBuilder command, IntPtr pa, IntPtr ta, bool inherit, uint flags, IntPtr env, string cwd, ref STARTUPINFO startup, out PROCESS_INFORMATION info);
 [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
 public static int Launch(string app, string command, string cwd) {
  STARTUPINFO si = new STARTUPINFO(); si.cb = Marshal.SizeOf(si); si.flags = 1; si.show = 0;
  PROCESS_INFORMATION pi;
  if (!CreateProcess(app, new StringBuilder(command), IntPtr.Zero, IntPtr.Zero, false,
      0x01000210, IntPtr.Zero, cwd, ref si, out pi))
   throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
  CloseHandle(pi.thread); CloseHandle(pi.process); return pi.pid;
 }
}
'@
 $probe=New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback,0);$probe.Start();$port=$probe.LocalEndpoint.Port;$probe.Stop()
 $bytes=New-Object byte[] 32;$rng=[System.Security.Cryptography.RandomNumberGenerator]::Create();$rng.GetBytes($bytes);$rng.Dispose()
 [IO.File]::WriteAllText($tokenPath,[Convert]::ToBase64String($bytes))
 $line='"'+$binary+'" --listen ws://127.0.0.1:'+$port+' --concurrent-requests 16 --ws-auth capability-token --ws-token-file "'+$tokenPath+'"'
 $processId=[UmekoRemoteExecutor]::Launch($binary,$line,$HOME)
 $state=@{pid=$processId;port=$port}
 $ready=$false
 for($i=0;$i -lt 80;$i++){
  if(Owns-Listener $processId $port){$ready=$true;break};Start-Sleep -Milliseconds 100
 }
 if(!$ready){throw 'Remote executor did not open its private listener'}
 [IO.File]::WriteAllText($statePath,($state|ConvertTo-Json -Compress))
}
@{port=$state.port;token=([IO.File]::ReadAllText($tokenPath)).Trim()}|ConvertTo-Json -Compress
`;
  return `set -eu
root=${quoteSh(root)}; binary=${quoteSh(binary)}
umask 077
valid=false
if [ -f "$root/listener.state" ]; then
 read -r pid port < "$root/listener.state"
 case "$pid:$port" in *[!0-9:]*|:*) ;; *)
  if [ "$(readlink "/proc/$pid/exe" 2>/dev/null || true)" = "$binary" ]; then
   # Match the TCP socket inode to this process, including the loopback bind.
   hex=$(printf '%04X' "$port")
   for inode in $(awk -v addr="0100007F:$hex" '$2==addr && $4=="0A" {print $10}' /proc/net/tcp); do
    for fd in "/proc/$pid/fd/"*; do [ "$(readlink "$fd" 2>/dev/null || true)" != "socket:[$inode]" ] || valid=true; done
   done
  fi;; esac
fi
if [ "$valid" != true ] || [ ! -s "$root/listener.token" ]; then
 # Kernel assigns a free port. Read the executor's own startup record, never
 # substitute a different service found by scanning a preferred port.
 od -An -N32 -tx1 /dev/urandom | tr -d ' \\n' > "$root/listener.token"
 : > "$root/listener.log"
 (cd "$HOME"; nohup "$binary" --listen ws://127.0.0.1:0 --concurrent-requests 16 --ws-auth capability-token --ws-token-file "$root/listener.token" > "$root/listener.log" 2>&1 < /dev/null & echo $! > "$root/listener.pid")
 pid=$(cat "$root/listener.pid"); port=''
 i=0; while [ "$i" -lt 80 ]; do
  for fd in "/proc/$pid/fd/"*; do
   inode=$(readlink "$fd" 2>/dev/null | sed -n 's/socket:\\[\\([0-9]*\\)\\]/\\1/p' || true)
   [ -n "$inode" ] || continue
   hex=$(awk -v inode="$inode" '$10==inode && $4=="0A" && $2 ~ /^0100007F:/ {split($2,a,":");print a[2]}' /proc/net/tcp)
   [ -z "$hex" ] || { port=$(printf '%d' "0x$hex"); break; }
  done
  [ -z "$port" ] || break
  kill -0 "$pid" 2>/dev/null || { echo 'Remote executor exited during startup' >&2; exit 1; }
  sleep 0.1; i=$((i+1))
 done
 [ -n "$port" ] || { echo 'Remote executor did not open its private listener' >&2; exit 1; }
 printf '%s %s\\n' "$pid" "$port" > "$root/listener.state"
fi
printf '%s\\n' "$port" "$(cat "$root/listener.token")"
`;
}

async function download(url, target) {
  // Reuse Umeko's maintained proxy/TLS routing; never touch proxy services.
  const response = await updateRequest(url);
  if (response.statusCode !== 200) { response.resume(); throw new Error(`Release download failed (${response.statusCode})`); }
  const digest = createHash("sha256"), chunks = [];
  for await (const chunk of response) { digest.update(chunk); chunks.push(chunk); }
  // Authorized product hash; only download admission checks bytes once.
  if (digest.digest("hex") !== target.sha256) throw Object.assign(new Error("Official exec-server release digest mismatch"), { fatal: true });
  await writeFile(target.temporary, Buffer.concat(chunks), { mode: 0o600 });
}

const assetDownloads = new Map();
async function assetFile(platform, arch, options) {
  const asset = manifest.assets[`${platform}-${arch}`];
  if (!asset) throw new Error("Unsupported remote architecture");
  const packaged = join(options.assetsDir || join(here, "remote-exec-assets"), asset.name);
  if (await exists(packaged)) return packaged;
  const cache = options.cacheDir || join(process.env.LOCALAPPDATA || process.env.XDG_CACHE_HOME || join(homedir(), ".cache"), "Umeko", "remote-exec", manifest.version);
  const target = join(cache, asset.name);
  if (await exists(target)) return target;
  if (!assetDownloads.has(target)) assetDownloads.set(target, (async () => {
    await mkdir(cache, { recursive: true });
    const temporary = `${target}.${randomBytes(6).toString("hex")}.download`;
    try {
      try { await download(`https://github.com/openai/codex/releases/download/${manifest.version}/${asset.name}`, { ...asset, temporary }); }
      catch (error) { if (!error.fatal) error.transport = true; throw error; }
      await rename(temporary, target); return target;
    } finally { await unlink(temporary).catch(() => {}); }
  })().finally(() => assetDownloads.delete(target)));
  return assetDownloads.get(target);
}

export class RemoteRpcError extends Error {
  constructor(error) { super(error.message || "Remote RPC failed"); this.name = "RemoteRpcError"; this.code = error.code; this.data = error.data; }
}

function checkedSshCommand(command) {
  const args = typeof command === "string" ? [command] : command;
  if (!Array.isArray(args) || !args.length || args.some(value => typeof value !== "string" || !value)) throw new Error("Invalid SSH command");
  return args;
}

export class RemoteConnection {
  constructor(config, options = {}) {
    if (!config || !["windows", "linux"].includes(config.platform)) throw new Error("Remote platform must be windows or linux");
    sshArguments(config.host);
    this.config = { ...config }; this.options = options;
    const command = options.sshCommand;
    this.sshCommand = command === undefined ? null : checkedSshCommand(command);
    this.sshClient = this.sshCommand?.[0];
    this.state = "disconnected"; this.sessionId = null; this.sessionGeneration = 0;
    this.closed = false; this.nextId = 1; this.pending = new Map(); this.children = new Set(); this.controller = new AbortController();
    this.waiters = new Set();
    this.networkMode = "auto";
    this.networkRevision = 0;
  }

  _state(state, detail = {}) {
    this.state = state;
    this.options.onState?.(state, { ...detail, ...(this.sshClient ? { sshClient: this.sshClient } : {}),
      ...(state === "connected" && this.networkStatus ? { networkStatus: this.networkStatus } : {}) });
  }

  commandProxyPort() {
    return this.networkStatus?.port;
  }

  refreshNetwork() {
    this.networkRevision++;
    if (this.state === "connected" && !this.connecting && !this.closed) {
      this._drop();
      this._lost();
    }
  }

  async setNetworkMode(mode, signal) {
    if (this.networkMode !== mode) {
      this.networkMode = mode;
      this.refreshNetwork();
    }
    await this.waitForReady(signal);
    return this.networkStatus ?? serverNetwork();
  }

  async testNetwork(url, signal) {
    await this.waitForReady(signal);
    const script = networkTestScript(this.config.platform, url, this.commandProxyPort());
    return await this._ssh(script, { timeout: 15_000 }) === "reachable";
  }

  async _networkRoute() {
    const config = this.options.getNetworkConfig?.();
    if (!config) return;
    if (config.enabled === false || this.networkMode === "off") {
      this.networkStatus = serverNetwork("本机网络共享已关闭");
      return;
    }
    if (this.networkMode === "auto") {
      const probe = networkTestScript(this.config.platform, networkProbeUrl, undefined, true);
      if (await this._ssh(probe, { timeout: 15_000 }) === "reachable") {
        this.networkStatus = serverNetwork();
        return;
      }
    }
    try { return await remoteOutbound(config, this.sshEnv, this.controller.signal); }
    catch {
      if (this.closed) throw abortError();
      this.networkStatus = serverNetwork("本机代理无法启动或代理地址无效");
    }
  }

  async _selectSsh() {
    if (this.options.sshCommand !== undefined) return;
    // The fault injector forwards the selected real client and never chooses it.
    const wrapper = this.options.sshWrapper === undefined ? null : checkedSshCommand(this.options.sshWrapper);
    const env = await this.options.getSshEnvironment?.() ?? process.env;
    this.sshClient = await selectSshClient(this.config.host, { env });
    if (this.closed) throw abortError();
    this.sshCommand = wrapper || [this.sshClient];
    this.sshEnv = wrapper ? { ...env, UMEKO_REAL_SSH: this.sshClient,
      UMEKO_SSH_TEST_CONTROL: process.env.UMEKO_SSH_TEST_CONTROL } : env;
    this._state(this.state, this.outageStartedAt === undefined ? {} : this._outageDetails());
  }

  _spawn(args) {
    return this._spawnClient(this.sshCommand[0], [...this.sshCommand.slice(1), ...sshArguments(this.config.host), ...args], this.sshEnv);
  }

  _spawnClient(executable, args, env) {
    const child = spawn(executable, args, { env, windowsHide: true, stdio: ["pipe", "pipe", "pipe"] });
    child.stdin.on("error", () => {}); // Exit diagnostics are collected from stderr.
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    this.children.add(child); child.once("exit", () => this.children.delete(child));
    return child;
  }

  async _ssh(script, { inputFile, timeout = 30_000 } = {}) {
    if (this.closed) throw abortError();
    const streamScript = !inputFile && process.platform !== "win32" && this.config.platform === "linux";
    const child = this._spawn([...(inputFile || streamScript ? [] : ["-n"]), this.config.host,
      streamScript ? "sh -s" : remoteCommand(this.config.platform, script)]);
    return this._readChild(child, { inputFile, inputText: streamScript ? `${script}\n` : undefined, timeout, label: "SSH command" });
  }

  async _readChild(child, { inputFile, inputText, timeout, label, sftp = false }) {
    let output = "", diagnostics = "";
    const result = new Promise((resolve, reject) => {
      const cleanup = () => { clearTimeout(timer); this.controller.signal.removeEventListener("abort", abort); };
      const timer = setTimeout(() => {
        cleanup();
        child.kill();
        const fatal = rejectedSsh.test(sshDiagnostic(diagnostics));
        reject(sshFailure(`${label} timed out`, diagnostics, !fatal, fatal));
      }, timeout);
      const abort = () => { cleanup(); child.kill(); reject(abortError()); };
      this.controller.signal.addEventListener("abort", abort, { once: true });
      child.stdout.on("data", data => { output += data; if (output.length > 1024 * 1024) child.kill(); });
      child.stderr.on("data", data => { diagnostics = (diagnostics + data).slice(-8192); });
      child.once("error", error => { cleanup(); reject(sshFailure(`Unable to start ${label}`, error.message, false, true)); });
      child.once("close", code => {
        cleanup();
        if (code === 0) resolve(output.trim());
        else {
          // SFTP builds do not all report the SSH child's exit as numeric 255.
          const sshError = sshDiagnostic(diagnostics);
          const disconnected = !rejectedSsh.test(sshError) && (code === 255 || sftp && disconnectedSsh.test(sshError));
          // Stdout can contain the listener bearer. Publish only bounded stderr.
          reject(sshFailure(`${label} failed (exit ${code ?? "signal"})`, diagnostics, disconnected, !disconnected));
        }
      });
    });
    // The upload and child can fail independently; attach a handler immediately
    // while streaming so a remote exit cannot become an unhandled rejection.
    result.catch(() => {});
    if (inputFile) {
      try { await pipeline(createReadStream(inputFile), child.stdin); }
      catch { child.kill(); const error = await result.then(() => null, failure => failure); throw error || new Error("Unable to upload the official remote executor"); }
    } else child.stdin.end(inputText);
    return result;
  }

  async _sftpUpload(inputFile, destination, { timeout, resume }) {
    const windowsClient = process.platform === "win32";
    const executable = join(dirname(this.sshClient), windowsClient ? "sftp.exe" : "sftp");
    if (!await exists(executable)) throw new Error(`OpenSSH SFTP is missing next to ${this.sshClient}`);
    const folder = await mkdtemp(join(tmpdir(), "umeko-sftp-"));
    const batch = join(folder, "upload.sftp");
    try {
      const put = resume ? "put -a" : "put";
      await writeFile(batch, `${put} ${sftpPath(inputFile, windowsClient)} ${sftpPath(destination, this.config.platform === "windows", true)}\n`, { mode: 0o600 });
      const child = this._spawnClient(executable, ["-b", batch, "-S", this.sshClient, ...sshArguments(this.config.host).slice(1), this.config.host], this.sshEnv);
      await this._readChild(child, { timeout, label: "OpenSSH SFTP upload", sftp: true });
    } finally {
      await unlink(batch).catch(() => {});
      await rmdir(folder).catch(() => {});
    }
  }

  async _bootstrap() {
    const sftp = process.platform === "win32" || this.config.platform === "windows";
    // A connection owns its staging name across retries. Other sessions use
    // different names, so their partial uploads cannot be mistaken for ours.
    const uploadId = sftp ? (this.sftpUploadId ||= randomBytes(6).toString("hex")) : undefined;
    const infoText = await this._ssh(discoveryScript(this.config.platform, uploadId));
    let info;
    if (this.config.platform === "windows") info = JSON.parse(infoText);
    else {
      const [arch, root, binary, present, staged] = infoText.split(/\r?\n/);
      info = { arch, root, binary, present: present === "true", staged: staged === "true" };
    }
    if (!info.present) {
      const asset = await assetFile(this.config.platform, info.arch, this.options);
      const temporary = `${info.root}/upload-${uploadId || randomBytes(6).toString("hex")}`;
      // First deployment can take minutes over a jump host. This is a single
      // scoped transfer, not a background retry or a server-wide operation.
      const timeout = 30 * 60_000;
      if (sftp) await this._sftpUpload(asset, temporary, { timeout, resume: info.staged === true });
      else await this._ssh(`umask 077; cat > ${quoteSh(temporary)}`, { inputFile: asset, timeout });
      const install = this.config.platform === "windows"
        ? `$ErrorActionPreference='Stop';if (Test-Path -LiteralPath ${quotePs(info.binary)} -PathType Leaf) { Remove-Item -LiteralPath ${quotePs(temporary)} -Force } else { Move-Item -LiteralPath ${quotePs(temporary)} -Destination ${quotePs(info.binary)} }`
        : `set -eu
if [ ! -x ${quoteSh(info.binary)} ]; then
  unpack=${quoteSh(temporary + ".unpack")}
  mkdir -p "$unpack"
  trap 'rm -rf -- "$unpack"' EXIT
  tar -xzf ${quoteSh(temporary)} -C "$unpack"
  found=$(find "$unpack" -maxdepth 2 -type f -name 'codex-exec-server*' ! -name '*tar*' | head -n 1)
  [ -n "$found" ]
  chmod 700 "$found"
  mv "$found" ${quoteSh(info.binary)}
fi
rm -f ${quoteSh(temporary)}`;
      await this._ssh(withBootstrapLock(this.config.platform, info.root, install), { timeout: 90_000 });
    }
    this.sftpUploadId = undefined;
    const listener = await this._ssh(withBootstrapLock(this.config.platform, info.root,
      listenerScript(this.config.platform, info.root, info.binary)), { timeout: 120_000 });
    let result;
    if (this.config.platform === "windows") result = JSON.parse(listener);
    else { const [port, token] = listener.split(/\r?\n/); result = { port: Number(port), token }; }
    if (!Number.isInteger(result.port) || result.port < 1 || result.port > 65535 || !/^[A-Za-z0-9+/=_-]{32,128}$/.test(result.token)) throw Object.assign(new Error("Invalid private executor listener"), { fatal: true });
    return result;
  }

  async _forward(remotePort, route) {
    const localPort = await new Promise((resolve, reject) => {
      const probe = createServer(); probe.once("error", reject); probe.listen(0, "127.0.0.1", () => { const port = probe.address().port; probe.close(() => resolve(port)); });
    });
    const child = this._spawn(["-v", "-n", "-N", "-o", "ClearAllForwardings=no", "-o", "ExitOnForwardFailure=yes",
      "-L", `127.0.0.1:${localPort}:127.0.0.1:${remotePort}`,
      ...(route ? ["-R", `127.0.0.1:0:${route.host}:${route.port}`] : []), this.config.host]);
    child.stdin.end(); this.tunnel = child;
    let failure, diagnostics = "", ended = false, listening = false, forwarded;
    this.tunnelDiagnostics = "";
    child.stderr.on("data", data => {
      diagnostics = (diagnostics + data).slice(-8192);
      if (this.tunnel === child) this.tunnelDiagnostics = diagnostics;
      // Do not send the bearer to a port merely because it accepts TCP. The
      // SSH child itself must report that it owns this loopback bind first.
      if (diagnostics.includes(`Local forwarding listening on 127.0.0.1 port ${localPort}.`)) listening = true;
      if (route && forwarded === undefined) forwarded = remoteForwardStatus(diagnostics, route);
    });
    child.once("error", error => { failure = sshFailure("Unable to start OpenSSH", error.message, false, true); });
    child.once("close", () => { ended = true; });
    child.once("exit", () => { if (this.tunnel === child) { this.tunnel = null; this._lost(); } });
    for (let i = 0; i < 100; i++) {
      if (failure) throw failure;
      if (forwarded === false) {
        this.tunnel = null;
        child.kill();
        return false;
      }
      if (ended) {
        const fatal = rejectedSsh.test(sshDiagnostic(diagnostics));
        throw sshFailure(`SSH tunnel exited (${child.exitCode ?? child.signalCode ?? "unknown"})`, diagnostics, !fatal, fatal);
      }
      if (this.closed) throw abortError();
      if (listening && (!route || forwarded) && child.exitCode === null && child.signalCode === null) {
        if (route) this.networkStatus = { network: "local", port: forwarded, outbound: route.outbound,
          outboundLabel: outboundLabels[route.outbound], message: "服务器正在使用本机网络" };
        return localPort;
      }
      await sleep(100, this.controller.signal);
    }
    const fatal = rejectedSsh.test(sshDiagnostic(diagnostics));
    throw sshFailure("SSH tunnel timed out", diagnostics, !fatal, fatal);
  }

  async _openSocket(port, token) {
    const ws = new WebSocket(`ws://127.0.0.1:${port}`, { headers: { Authorization: `Bearer ${token}` }, handshakeTimeout: 10_000, maxPayload: 32 * 1024 * 1024 });
    this.socket = ws;
    ws.on("message", bytes => {
      let message; try { message = JSON.parse(bytes.toString()); } catch { return; }
      if (message.id !== undefined) {
        const pending = this.pending.get(message.id);
        if (pending) { this.pending.delete(message.id); pending.cleanup(); message.error ? pending.reject(new RemoteRpcError(message.error)) : pending.resolve(message.result); }
      } else if (typeof message.method === "string") this.options.onNotification?.(message.method, message.params);
    });
    ws.on("close", () => { if (this.socket === ws) { this.socket = null; this._lost(); } });
    ws.on("error", () => {}); // Handshake failure is sanitized below.
    await new Promise((resolve, reject) => {
      ws.once("open", resolve);
      ws.once("unexpected-response", (_request, response) => {
        response.resume(); ws.terminate();
        reject(Object.assign(new Error([401, 403].includes(response.statusCode) ? "Remote executor bearer authentication failed" : `Remote executor handshake failed (${response.statusCode})`), { fatal: true }));
      });
      ws.once("error", () => reject(connectionError())); ws.once("close", () => reject(connectionError()));
    });
  }

  _request(method, serialized, signal) {
    if (signal?.aborted) return Promise.reject(abortError());
    const ws = this.socket;
    if (!ws || ws.readyState !== WebSocket.OPEN) return Promise.reject(connectionError());
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const abort = () => { this.pending.delete(id); cleanup(); reject(abortError()); };
      const cleanup = () => { signal?.removeEventListener("abort", abort); clearTimeout(timer); };
      const timer = setTimeout(() => { this.pending.delete(id); cleanup(); reject(Object.assign(new Error(`Remote ${method} timed out; completion may be unknown`), { transport: true })); this._drop(); this._lost(); }, this.options.rpcTimeoutMs || 120_000);
      this.pending.set(id, { resolve, reject, cleanup });
      signal?.addEventListener("abort", abort, { once: true });
      ws.send(JSON.stringify({ id, method, ...(serialized === undefined ? {} : { params: JSON.parse(serialized) }) }), error => {
        if (error && this.pending.delete(id)) { cleanup(); reject(connectionError()); }
      });
    });
  }

  _lost() {
    for (const pending of this.pending.values()) { pending.cleanup(); pending.reject(connectionError()); }
    this.pending.clear();
    if (this.closed || this.connecting) return;
    this._beginOutage();
    const reason = sshDiagnostic(this.tunnelDiagnostics);
    if (reason) this.reconnectSshError = reason;
    // Keep a single connection attempt alive across concurrent tools. The
    // per-tool wait can expire without cancelling this environment's recovery.
    this.ready().catch(() => {});
  }

  _beginOutage() {
    if (this.outageStartedAt !== undefined) return;
    this.outageStartedAt = Date.now();
    for (const waiter of this.waiters) waiter.startDeadline();
  }

  _outageDetails() {
    return {
      outageStartedAt: this.outageStartedAt, attempt: this.reconnectAttempt,
      nextRetryAt: this.nextRetryAt, sshError: this.reconnectSshError,
    };
  }

  _clearOutage() {
    this.outageStartedAt = this.nextRetryAt = this.reconnectSshError = undefined;
  }

  async _connect() {
    if (this.sessionId) this._beginOutage();
    for (let attempt = 1; !this.closed; attempt++) {
      this.reconnectAttempt = attempt;
      this.nextRetryAt = undefined;
      if (this.outageStartedAt === undefined) this._state("connecting");
      else this._state("reconnecting", this._outageDetails());
      try {
        this._drop();
        this.tunnelDiagnostics = "";
        await this._selectSsh();
        const listener = await this._bootstrap();
        const revision = this.networkRevision;
        const route = this.networkUpstream = await this._networkRoute();
        let port = await this._forward(listener.port, route);
        if (port === false) {
          route.close?.();
          this.networkUpstream = undefined;
          this.networkStatus = serverNetwork("服务器拒绝 SSH 反向转发，无法使用本机网络");
          port = await this._forward(listener.port);
        }
        await this._openSocket(port, listener.token);
        const previous = this.sessionId;
        let result;
        try { result = await this._request("initialize", JSON.stringify({ clientName: "umeko-remote", ...(previous ? { resumeSessionId: previous } : {}) }), this.controller.signal); }
        catch (error) {
          if (!(error instanceof RemoteRpcError) || !/unknown session id/i.test(error.message)) throw error;
          // Retention expired. A fresh session has no process/file handles.
          result = await this._request("initialize", JSON.stringify({ clientName: "umeko-remote" }), this.controller.signal);
        }
        this.sessionId = result.sessionId;
        if (previous !== this.sessionId) this.sessionGeneration++;
        this.socket.send(JSON.stringify({ method: "initialized", params: {} }));
        this.environmentInfo = result.environmentInfo || await this._request("environment/info", "{}", this.controller.signal);
        if (revision !== this.networkRevision) continue;
        const recovered = this.outageStartedAt !== undefined;
        const recovery = recovered ? { outageStartedAt: this.outageStartedAt, attempt, recovered } : {};
        this._clearOutage();
        this._state("connected", { sessionId: this.sessionId, sessionGeneration: this.sessionGeneration, resumed: !!previous && previous === this.sessionId, ...recovery });
        return this.environmentInfo;
      } catch (error) {
        this._drop();
        if (this.closed || error.name === "AbortError") throw abortError();
        // Detection skew can leave the old WS attachment alive briefly. Keep
        // the same resume ID; never fork a session
        // while the retained attachment still owns its process/file handles.
        if (error instanceof RemoteRpcError && /session .*already attached/i.test(error.message)) error.transport = true;
        if (error.transport && !error.sshError && sshDiagnostic(this.tunnelDiagnostics)) error = sshFailure(error.message, this.tunnelDiagnostics, true, error.fatal);
        this.sshClient ||= error.sshClient;
        error.sshClient = this.sshClient;
        if (error.fatal || !error.transport) {
          this._clearOutage();
          this._state("error", { message: error.message, sshError: error.sshError });
          throw error;
        }
        if (error.sshError) this.reconnectSshError = error.sshError;
        this._beginOutage();
        const retryAfterMs = retryDelays[Math.min(attempt - 1, retryDelays.length - 1)];
        this.reconnectAttempt = attempt + 1;
        this.nextRetryAt = Date.now() + retryAfterMs;
        this._state("reconnecting", { ...this._outageDetails(), retryAfterMs });
        await (this.options.reconnectSleep ?? sleep)(retryAfterMs, this.controller.signal);
      }
    }
    throw abortError();
  }

  _finishWaiters(error, info) {
    for (const waiter of this.waiters) waiter.finish(error, info);
  }

  ready() {
    if (this.closed) return Promise.reject(new Error("Remote connection is closed"));
    if (this.socket?.readyState === WebSocket.OPEN && this.state === "connected") return Promise.resolve(this.environmentInfo);
    if (!this.connecting) this.connecting = this._connect().then(info => {
      this.connecting = null;
      this._finishWaiters(null, info);
      return info;
    }, error => {
      this.connecting = null;
      this._finishWaiters(error);
      throw error;
    });
    return this.connecting;
  }

  waitForReady(signal) {
    if (signal?.aborted || this.closed) return Promise.reject(abortError());
    if (this.socket?.readyState === WebSocket.OPEN && this.state === "connected") return Promise.resolve(this.environmentInfo);
    return new Promise((resolve, reject) => {
      let timer;
      const abort = () => waiter.finish(abortError());
      const waiter = {
        finish: (error, info) => {
          clearTimeout(timer);
          signal?.removeEventListener("abort", abort);
          this.waiters.delete(waiter);
          if (error) reject(error);
          else resolve(info);
        },
        startDeadline: () => {
          if (this.outageStartedAt === undefined || timer) return;
          const budget = this.options.outageTimeoutMs ?? outageTimeoutMs;
          const remaining = Math.max(0, budget - (Date.now() - this.outageStartedAt));
          timer = setTimeout(() => {
            const error = sshFailure("The host has not reconnected. Umeko is still retrying in the background.", this.reconnectSshError);
            const retryAfterMs = this.nextRetryAt === undefined ? undefined : Math.max(0, this.nextRetryAt - Date.now());
            waiter.finish(Object.assign(error, this._outageDetails(), { code: "REMOTE_RECONNECT_TIMEOUT", state: "reconnecting", retryAfterMs, sshClient: this.sshClient }));
          }, remaining);
        },
      };
      this.waiters.add(waiter);
      signal?.addEventListener("abort", abort, { once: true });
      this.ready().catch(() => {});
      waiter.startDeadline();
    });
  }

  async rpc(method, params, { signal, retry, sessionGeneration, wait = true } = {}) {
    // Serialize before awaiting so caller mutation cannot change a replay.
    const serialized = params === undefined ? undefined : JSON.stringify(params);
    if (signal?.aborted) throw abortError();
    const optedInWrite = retry === true && (method === "fs/writeFile" || method === "fs/writeBlock" || method === "fs/createDirectory" && params?.recursive === true);
    const canReplay = wait && retry !== false && (retryable.has(method) || optedInWrite);
    for (;;) {
      if (wait) await this.waitForReady(signal);
      else if (this.state !== "connected" || this.socket?.readyState !== WebSocket.OPEN) throw connectionError();
      if (sessionBound.has(method) && sessionGeneration === undefined) sessionGeneration = this.sessionGeneration;
      if (sessionGeneration !== undefined && sessionGeneration !== this.sessionGeneration) throw sessionChanged();
      const socket = this.socket;
      const remotePort = method === "process/start" && this.commandProxyPort();
      // Workspace shells start a streaming exec-server process directly.
      // Apply the same proxy setup used by durable remote_command launches.
      const requestParams = remotePort && serialized
        ? JSON.stringify(prepareRemoteShellProcess(JSON.parse(serialized), remotePort, this.config.platform === "windows"))
        : serialized;
      try { return await this._request(method, requestParams, signal); }
      catch (error) {
        if (!error.transport || signal?.aborted || this.closed) throw error;
        if (this.socket === socket) {
          this._drop();
          this._lost();
        }
        if (!canReplay) throw error;
      }
    }
  }

  _drop() {
    const socket = this.socket; this.socket = null; socket?.terminate();
    const tunnel = this.tunnel; this.tunnel = null; tunnel?.kill();
    this.networkUpstream?.close?.();
    this.networkUpstream = this.networkStatus = undefined;
    for (const pending of this.pending.values()) { pending.cleanup(); pending.reject(connectionError()); }
    this.pending.clear();
  }

  close() {
    if (this.closed) return;
    this.closed = true; this.controller.abort(); this._drop();
    this._finishWaiters(abortError());
    for (const child of this.children) child.kill();
    this._state("disconnected");
  }
}
