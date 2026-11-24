import { systemProxy } from "./package-install.mjs";
import { startRemoteHttpProxy } from "./remote-http-proxy.mjs";

export const networkDescription = "When a server cannot reach the internet, Umeko automatically shares this computer's network, so remote commands need no proxy arguments.";
export const networkProbeUrl = "https://github.com/robots.txt";
const noProxy = "localhost,127.0.0.1,::1";
export const remoteProxyUrl = port => "http://127.0.0.1:" + port;
export const serverNetwork = (message = "服务器使用自己的网络") => ({ network: "remote", message });
export const outboundLabels = {
  configured: "Umeko 设置的代理",
  system: "本机系统代理",
  builtin: "本机直连（内置 HTTP 代理）",
};

const quoteShell = value => "'" + String(value).replaceAll("'", "'\\''") + "'";
const quotePowerShell = value => "'" + String(value).replaceAll("'", "''") + "'";

export async function remoteOutbound(config, env, signal) {
  const configured = typeof config.proxy === "string" ? config.proxy.trim() : "";
  const address = configured || await systemProxy(networkProbeUrl, undefined, env, signal);
  if (!address) return { ...await startRemoteHttpProxy(), outbound: "builtin" };
  let proxy;
  try { proxy = new URL(address); } catch { throw new Error("本机代理地址无效"); }
  const outbound = configured ? "configured" : "system";
  if (!["http:", "https:", "socks5:", "socks5h:"].includes(proxy.protocol) ||
      !proxy.hostname || proxy.pathname !== "/" && proxy.pathname !== "" || proxy.search || proxy.hash ||
      proxy.port === "0") throw new Error("本机代理地址或协议无效");
  if (proxy.protocol === "http:" && !proxy.username && !proxy.password) {
    return { host: proxy.hostname, port: Number(proxy.port || 80), outbound };
  }
  // Relay HTTPS, authenticated HTTP and SOCKS upstreams as an HTTP proxy.
  // Authentication stays on this computer and the relay never falls back to direct.
  return { ...await startRemoteHttpProxy(proxy), outbound };
}

export function networkTestScript(platform, input, port, probe = false) {
  let target;
  try { target = new URL(input); } catch {}
  if (!target || !["https:", "http:"].includes(target.protocol) || target.username || target.password) {
    throw new Error("请提供不含用户名或密码的 HTTP 或 HTTPS 网址");
  }
  const bypass = port ? noProxy : "*";
  const proxy = port ? remoteProxyUrl(port) : "";
  // A probe must read the downloaded bytes. A HEAD response, including a
  // gateway error page, can succeed while GET requests from this host stall.
  const transfer = probe ? ["--output", platform === "windows" ? "NUL" : "/dev/null"] : ["--head"];
  const flags = ["--disable", "--silent", "--show-error", ...transfer, "--connect-timeout", "4",
    "--max-time", "6", "--fail", "--proxy", proxy, "--noproxy", bypass, "--", target.href];
  if (platform === "windows") {
    // Windows PowerShell drops an empty native argument. All hosts here use
    // --noproxy to explicitly select the route, including the direct probe.
    const windowsFlags = flags.filter((_, i) => port || ![flags.indexOf("--proxy"), flags.indexOf("--proxy") + 1].includes(i));
    return `if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
  & curl.exe ${windowsFlags.map(quotePowerShell).join(" ")} 2>$null | Out-Null
  if ($LASTEXITCODE -eq 0) { 'reachable' } else { 'unreachable' }
} else {
  try {
    $request = [Net.WebRequest]::Create(${quotePowerShell(target.href)})
    $request.Method = '${probe ? "GET" : "HEAD"}'; $request.Timeout = 6000; $request.ReadWriteTimeout = 6000; $request.AllowAutoRedirect = $false
    ${port ? `$request.Proxy = New-Object Net.WebProxy(${quotePowerShell(proxy)}, $true)` : "$request.Proxy = $null"}
    $reply = $request.GetResponse()
    try { ${probe ? "$reply.GetResponseStream().CopyTo([IO.Stream]::Null); " : ""}'reachable' } finally { $reply.Dispose() }
  } catch {
    if ($_.Exception.Response) { $_.Exception.Response.Dispose() }
    'unreachable'
  }
}`;
  }
  return `ok=false
if command -v curl >/dev/null 2>&1; then
  curl ${flags.map(quoteShell).join(" ")} >/dev/null 2>&1 && ok=true
elif command -v wget >/dev/null 2>&1; then
  WGETRC=/dev/null wget --quiet ${probe ? "-O /dev/null" : "--spider"} --timeout=5 --tries=1 ${port
    ? `-e ${quoteShell("http_proxy=" + proxy)} -e ${quoteShell("https_proxy=" + proxy)} -e ${quoteShell("no_proxy=" + noProxy)}`
    : "--no-proxy"} -- ${quoteShell(target.href)} && ok=true
fi
if [ "$ok" = true ]; then printf '%s\\n' reachable; else printf '%s\\n' unreachable; fi`;
}

export function remoteForwardStatus(diagnostics, route) {
  // OpenSSH reports zero until the server atomically chooses a free port.
  const allocated = /(?:^|\n)Allocated port ([0-9]+) for remote forward to ([^\r\n]+)\r?(?:\n|$)/g;
  for (const match of diagnostics.matchAll(allocated)) {
    if (match[2].replace(/^\[([^\]]+)\]:/, "$1:") === route.host.replace(/^\[|\]$/g, "") + ":" + route.port &&
        Number(match[1]) > 0 && Number(match[1]) <= 65535) {
      return Number(match[1]);
    }
  }
  if (/(?:^|\n)(?:Error: |Warning: )?remote port forwarding failed for listen port 0\b/i.test(diagnostics)) return false;
}
