// Official Codex exec-server v0.172.0 JSON-RPC over a private OpenSSH tunnel.
// Sources at tag rust-v0.172.0: codex-rs/exec-server/README.md,
// codex-rs/exec-server-protocol/src/{protocol,rpc}.rs,
// codex-rs/exec-server/src/client_recovery.rs, codex-rs/websocket-auth/src/lib.rs.
// SSH owns authentication and host identity; Umeko never handles private keys.
import { spawn } from "node:child_process";
import { createReadStream } from "node:fs";
import { access, mkdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { createHash, randomBytes } from "node:crypto";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "node:net";
import { pipeline } from "node:stream/promises";
import WebSocket from "ws";
import { updateRequest } from "./update-engine.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const manifest = JSON.parse(await readFile(join(here, "remote-exec-assets.json"), "utf8"));
const retryable = new Set(["environment/info", "fs/readFile", "fs/readDirectory", "fs/getMetadata", "fs/getMetadataBatch", "fs/canonicalize", "fs/walk", "fs/readBlock", "process/read"]);
const sessionBound = new Set(["fs/readBlock", "fs/writeBlock", "process/read"]);
const quoteSh = value => `'${String(value).replaceAll("'", "'\\''")}'`;
const quotePs = value => `'${String(value).replaceAll("'", "''")}'`;
const exists = async path => access(path).then(() => true, () => false);
const abortError = () => Object.assign(new Error("Remote request cancelled"), { name: "AbortError" });
const connectionError = () => Object.assign(new Error("Remote connection interrupted"), { transport: true });
const fatalSsh = /permission denied|authentication failed|host key verification failed|remote host identification has changed|no matching host key|too many authentication failures|bad configuration|could not resolve hostname|unprotected private key|bad permissions|sign_and_send_pubkey: signing failed/i;
const sleep = (ms, signal) => new Promise((resolve, reject) => {
  if (signal?.aborted) return reject(abortError());
  const abort = () => { clearTimeout(timer); reject(abortError()); };
  const timer = setTimeout(() => { signal?.removeEventListener("abort", abort); resolve(); }, ms);
  signal?.addEventListener("abort", abort, { once: true });
});
function abortable(promise, signal) {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(abortError());
  return new Promise((resolve, reject) => {
    const abort = () => { cleanup(); reject(abortError()); };
    const cleanup = () => signal.removeEventListener("abort", abort);
    signal.addEventListener("abort", abort, { once: true });
    promise.then(value => { cleanup(); resolve(value); }, error => { cleanup(); reject(error); });
  });
}

export function sshArguments(host) {
  if (typeof host !== "string" || !/^[a-zA-Z0-9_][a-zA-Z0-9_.@:\-]*$/.test(host)) throw new Error("Enter an OpenSSH host alias or hostname");
  return ["-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2"];
}

function remoteCommand(platform, script) {
  return platform === "windows"
    ? `powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand ${Buffer.from(script, "utf16le").toString("base64")}`
    : `sh -c ${quoteSh(script)}`;
}

function streamedCommand(platform) {
  // Keep the Windows OpenSSH/cmd command line below its 8191-character limit.
  // The script is executable source on stdin, not a giant encoded argv value.
  return platform === "windows"
    ? remoteCommand(platform, "$source=[Console]::In.ReadToEnd(); & ([ScriptBlock]::Create($source))")
    : "sh -s";
}

export function discoveryScript(platform) {
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
@{arch=$arch;root=$root;binary=$binary;present=(Test-Path -LiteralPath $binary -PathType Leaf)} | ConvertTo-Json -Compress
`;
  return `set -eu
case "$(uname -m)" in x86_64|amd64) arch=x64;; aarch64|arm64) arch=arm64;; *) echo 'Unsupported remote architecture' >&2; exit 1;; esac
root="$HOME/.local/share/umeko/remote-exec/${manifest.version}/$arch"
umask 077; mkdir -p "$root"; chmod 700 "$root"
present=false; [ ! -f "$root/codex-exec-server" ] || present=true
printf '%s\\n' "$arch" "$root" "$root/codex-exec-server" "$present"
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

export class RemoteConnection {
  constructor(config, options = {}) {
    if (!config || !["windows", "linux"].includes(config.platform)) throw new Error("Remote platform must be windows or linux");
    sshArguments(config.host);
    this.config = { ...config }; this.options = options;
    let command = options.sshCommand;
    if (!command && process.env.UMEKO_REMOTE_TEST_MODE === "1" && process.env.UMEKO_SSH_COMMAND_JSON) command = JSON.parse(process.env.UMEKO_SSH_COMMAND_JSON);
    this.sshCommand = typeof command === "string" ? [command] : command || ["ssh"];
    if (!Array.isArray(this.sshCommand) || !this.sshCommand.length || this.sshCommand.some(value => typeof value !== "string" || !value)) throw new Error("Invalid SSH command");
    this.state = "disconnected"; this.sessionId = null; this.sessionGeneration = 0;
    this.closed = false; this.nextId = 1; this.pending = new Map(); this.children = new Set(); this.controller = new AbortController();
  }

  _state(state, detail = {}) { this.state = state; this.options.onState?.(state, detail); }

  _spawn(args) {
    const child = spawn(this.sshCommand[0], [...this.sshCommand.slice(1), ...sshArguments(this.config.host), ...args], { windowsHide: true, stdio: ["pipe", "pipe", "pipe"] });
    this.children.add(child); child.once("exit", () => this.children.delete(child));
    return child;
  }

  async _ssh(script, { inputFile, timeout = 30_000 } = {}) {
    if (this.closed) throw abortError();
    const child = this._spawn([this.config.host, inputFile ? remoteCommand(this.config.platform, script) : streamedCommand(this.config.platform)]);
    let output = "", diagnostics = "";
    const result = new Promise((resolve, reject) => {
      const timer = setTimeout(() => { child.kill(); reject(Object.assign(new Error("SSH command timed out"), { transport: true })); }, timeout);
      const abort = () => { child.kill(); reject(abortError()); };
      this.controller.signal.addEventListener("abort", abort, { once: true });
      child.stdout.on("data", data => { output += data.toString(); if (output.length > 1024 * 1024) child.kill(); });
      child.stderr.on("data", data => { diagnostics = (diagnostics + data.toString()).slice(-8192); });
      child.on("error", error => { clearTimeout(timer); this.controller.signal.removeEventListener("abort", abort); reject(Object.assign(new Error(`Unable to start OpenSSH: ${error.code || "unknown error"}`), { fatal: true })); });
      child.on("exit", code => {
        clearTimeout(timer); this.controller.signal.removeEventListener("abort", abort);
        if (code === 0) resolve(output.trim());
        else {
          // Never report stdout (bootstrap contains a bearer), argv, or remote
          // PowerShell source. SSH authentication failures get actionable text.
          const lines = diagnostics.split(/\r?\n/);
          const fatal = lines.find(value => fatalSsh.test(value));
          const network = lines.find(value => /^(?:ssh: |kex_exchange_identification: |banner exchange: |Connection (?:closed|reset|timed out))/i.test(value));
          const line = fatal || network;
          reject(Object.assign(new Error(line ? `OpenSSH: ${line.trim().slice(0, 512)}` : `Remote executor bootstrap failed (SSH exit ${code ?? "signal"})`), { fatal: !!fatal || code !== 255, transport: code === 255 }));
        }
      });
    });
    // The upload and child can fail independently; attach a handler immediately
    // while streaming so a remote exit cannot become an unhandled rejection.
    result.catch(() => {});
    if (inputFile) {
      try { await pipeline(createReadStream(inputFile), child.stdin); }
      catch { child.kill(); const error = await result.then(() => null, failure => failure); throw error || new Error("Unable to upload the official remote executor"); }
    } else child.stdin.end(script + "\n");
    return result;
  }

  async _bootstrap() {
    const infoText = await this._ssh(discoveryScript(this.config.platform));
    let info;
    if (this.config.platform === "windows") info = JSON.parse(infoText);
    else { const [arch, root, binary, present] = infoText.split(/\r?\n/); info = { arch, root, binary, present: present === "true" }; }
    if (!info.present) {
      const asset = await assetFile(this.config.platform, info.arch, this.options);
      const temporary = `${info.root}/upload-${randomBytes(6).toString("hex")}`;
      const receive = this.config.platform === "windows"
        ? `$ErrorActionPreference='Stop';$f=[IO.File]::Open(${quotePs(temporary)},'CreateNew');try{[Console]::OpenStandardInput().CopyTo($f)}finally{$f.Dispose()}`
        : `umask 077; cat > ${quoteSh(temporary)}`;
      // First deployment can take minutes over a jump host. This is a single
      // scoped transfer, not a background retry or a server-wide operation.
      await this._ssh(receive, { inputFile: asset, timeout: 30 * 60_000 });
      const install = this.config.platform === "windows"
        ? `$ErrorActionPreference='Stop';Move-Item -LiteralPath ${quotePs(temporary)} -Destination ${quotePs(info.binary)} -Force`
        : `set -eu; tar -xzf ${quoteSh(temporary)} -C ${quoteSh(info.root)}; found=$(find ${quoteSh(info.root)} -maxdepth 2 -type f -name 'codex-exec-server*' ! -name '*tar*' | head -n 1); [ -n "$found" ]; [ "$found" = ${quoteSh(info.binary)} ] || mv "$found" ${quoteSh(info.binary)}; chmod 700 ${quoteSh(info.binary)}; rm -f ${quoteSh(temporary)}`;
      await this._ssh(install);
    }
    const listener = await this._ssh(listenerScript(this.config.platform, info.root, info.binary), { timeout: 60_000 });
    let result;
    if (this.config.platform === "windows") result = JSON.parse(listener);
    else { const [port, token] = listener.split(/\r?\n/); result = { port: Number(port), token }; }
    if (!Number.isInteger(result.port) || result.port < 1 || result.port > 65535 || !/^[A-Za-z0-9+/=_-]{32,128}$/.test(result.token)) throw Object.assign(new Error("Invalid private executor listener"), { fatal: true });
    return result;
  }

  async _forward(remotePort) {
    const localPort = await new Promise((resolve, reject) => {
      const probe = createServer(); probe.once("error", reject); probe.listen(0, "127.0.0.1", () => { const port = probe.address().port; probe.close(() => resolve(port)); });
    });
    const child = this._spawn(["-v", "-N", "-o", "ExitOnForwardFailure=yes", "-L", `127.0.0.1:${localPort}:127.0.0.1:${remotePort}`, this.config.host]);
    child.stdin.end(); this.tunnel = child;
    let failure, diagnostics = "", listening = false;
    child.stderr.on("data", data => {
      diagnostics = (diagnostics + data.toString()).slice(-8192);
      const line = diagnostics.split(/\r?\n/).find(value => fatalSsh.test(value));
      if (line) failure = Object.assign(new Error(`OpenSSH: ${line.trim().slice(0, 512)}`), { fatal: true });
      // Do not send the bearer to a port merely because it accepts TCP. The
      // SSH child itself must report that it owns this loopback bind first.
      if (diagnostics.includes(`Local forwarding listening on 127.0.0.1 port ${localPort}.`)) listening = true;
    });
    child.once("error", error => { failure = Object.assign(new Error(`Unable to start OpenSSH: ${error.code || "unknown error"}`), { fatal: true }); });
    child.once("exit", () => { if (this.tunnel === child) { this.tunnel = null; this._lost(); } });
    for (let i = 0; i < 100; i++) {
      if (failure) throw failure;
      if (child.exitCode !== null) throw connectionError();
      if (this.closed) throw abortError();
      if (listening) return localPort;
      await sleep(100, this.controller.signal);
    }
    throw Object.assign(new Error("SSH tunnel timed out"), { transport: true });
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
    this._state("reconnecting");
    // One bounded recovery loop; close cancels sleeps and scoped SSH children.
    this.ready().catch(() => {});
  }

  async _connect() {
    this._state(this.sessionId ? "reconnecting" : "connecting");
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        this._drop();
        const listener = await this._bootstrap();
        const port = await this._forward(listener.port);
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
        this._state("connected", { sessionId: this.sessionId, sessionGeneration: this.sessionGeneration, resumed: !!previous && previous === this.sessionId });
        return this.environmentInfo;
      } catch (error) {
        this._drop();
        if (this.closed || error.name === "AbortError") throw abortError();
        // Detection skew can leave the old WS attachment alive briefly. Keep
        // the same resume ID and bounded recovery budget; never fork a session
        // while the retained attachment still owns its process/file handles.
        if (error instanceof RemoteRpcError && /session .*already attached/i.test(error.message)) error.transport = true;
        if (error.fatal || !error.transport || attempt === 2) { this._state("error", { message: error.message }); throw error; }
        this._state("reconnecting", { attempt: attempt + 1, message: error.message, retryAfterMs: 60_000 });
        await sleep(60_000, this.controller.signal);
      }
    }
  }

  ready() {
    if (this.closed) return Promise.reject(new Error("Remote connection is closed"));
    if (this.socket?.readyState === WebSocket.OPEN && this.state === "connected") return Promise.resolve(this.environmentInfo);
    if (!this.connecting) this.connecting = this._connect().finally(() => { this.connecting = null; });
    return this.connecting;
  }

  async rpc(method, params, { signal, retry } = {}) {
    // Serialize before awaiting so caller mutation cannot change a replay.
    const serialized = params === undefined ? undefined : JSON.stringify(params);
    if (signal?.aborted) throw abortError();
    await abortable(this.ready(), signal); const generation = this.sessionGeneration;
    try { return await this._request(method, serialized, signal); }
    catch (error) {
      const optedInWrite = retry === true && (method === "fs/writeFile" || method === "fs/writeBlock" || method === "fs/createDirectory" && serialized !== undefined && JSON.parse(serialized)?.recursive === true);
      if (retry === false || !(retryable.has(method) || optedInWrite) || !error.transport || signal?.aborted || this.closed) throw error;
      await abortable(this.ready(), signal);
      if (sessionBound.has(method) && generation !== this.sessionGeneration) throw Object.assign(new Error("Remote session expired; reopen the process or file handle"), { code: "REMOTE_SESSION_CHANGED" });
      return this._request(method, serialized, signal);
    }
  }

  _drop() {
    const socket = this.socket; this.socket = null; socket?.terminate();
    const tunnel = this.tunnel; this.tunnel = null; tunnel?.kill();
    for (const pending of this.pending.values()) { pending.cleanup(); pending.reject(connectionError()); }
    this.pending.clear();
  }

  close() {
    if (this.closed) return;
    this.closed = true; this.controller.abort(); this._drop();
    for (const child of this.children) child.kill();
    this._state("disconnected");
  }
}
