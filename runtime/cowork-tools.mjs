import { lookup } from "node:dns/promises";
import http from "node:http";
import https from "node:https";
import tls from "node:tls";
import { X509Certificate } from "node:crypto";
import { open } from "node:fs/promises";
import { proxyTunnel, updateCertificates } from "./update-engine.mjs";
import { BlockList, isIP } from "node:net";
import { parse, parseFragment } from "parse5";
import { Type } from "typebox";
import { registerCoworkLocalTools } from "./cowork-local.mjs";

const vpnSynthetic = new BlockList();
vpnSynthetic.addSubnet("198.18.0.0", 15);
vpnSynthetic.addSubnet("::ffff:c612:0", 111, "ipv6");
vpnSynthetic.addSubnet("::ffff:0:c612:0", 111, "ipv6");

const byteLimit = 2 * 1024 * 1024;
const caLimit = 4 * 1024 * 1024;
const searchOrigin = "https://www.bing.com";
const reserved = new BlockList();
for (const [address, prefix] of [
  ["0.0.0.0", 8], ["100.100.100.200", 32], ["127.0.0.0", 8], ["169.254.0.0", 16],
  ["192.0.0.0", 24], ["192.0.2.0", 24],
  ["198.18.0.0", 15], ["198.51.100.0", 24], ["203.0.113.0", 24], ["224.0.0.0", 3],
]) reserved.addSubnet(address, prefix, "ipv4");
const routableV6 = new BlockList();
routableV6.addSubnet("2000::", 3, "ipv6");
routableV6.addSubnet("fc00::", 7, "ipv6");
reserved.addAddress("fd00:ec2::254", "ipv6");
for (const [address, prefix] of [["2001::", 23], ["2001:db8::", 32], ["2002::", 16], ["3fff::", 20]]) {
  reserved.addSubnet(address, prefix, "ipv6");
}

export function publicWebUrl(raw) {
  const url = new URL(raw);
  if (!["https:", "http:"].includes(url.protocol) || url.port || url.username || url.password) {
    throw new Error("Use a public HTTP or HTTPS URL without credentials or a custom port");
  }
  const host = url.hostname.replace(/^\[|\]$/g, "");
  if (!isIP(host) && (!host.includes(".") || /\.(?:localhost|local|internal|lan|home|onion)\.?$/i.test(host))) {
    throw new Error("Only public web hosts are supported");
  }
  url.hash = "";
  return url;
}

function routableAddress({address, family}) {
  return family === 6 ? routableV6.check(address, "ipv6") && !reserved.check(address, "ipv6") :
    family === 4 && !reserved.check(address);
}

function networkError(stage, code, message) {
  return Object.assign(new Error(message), { stage, code });
}

const certificateError = code => /CERT|SELF_SIGNED|UNABLE_TO_(?:VERIFY|GET_ISSUER)|ERR_SSL/.test(code);

function targetUrl(raw, purpose) {
  let url;
  try { url = new URL(raw); } catch {
    throw networkError("policy", "INVALID_URL", "Enter a valid HTTP or HTTPS URL");
  }
  if (!["https:", "http:"].includes(url.protocol) || url.username || url.password)
    throw networkError("policy", "INVALID_URL", "Only HTTP and HTTPS URLs without credentials are supported");
  url.hash = "";
  if (purpose === "search" && url.origin !== searchOrigin)
    throw networkError("policy", "SEARCH_ORIGIN", "Public search can only reach the configured search provider");
  return url;
}

function abortable(promise, signal) {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const onAbort = () => reject(signal.reason);
    signal.addEventListener("abort", onAbort, {once: true});
    promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", onAbort));
  });
}

export function desktopWebRoute(config) {
  if (!config?.scope) return async () => ({proxy: "", mode: "direct"});
  return async (url, signal) => {
    // Always connect directly to the authenticated desktop loopback channel.
    const endpoint = new URL("/umeko/cowork-web-route", config.gateway);
    if (endpoint.protocol !== "http:" || endpoint.hostname !== "127.0.0.1")
      throw networkError("proxy", "ROUTE_SERVICE", "The desktop network service is unavailable");
    const data = JSON.stringify({scope: config.scope, url: url.href});
    const response = await new Promise((resolve, reject) => {
      const req = http.request(endpoint, {
        method: "POST", agent: false, signal,
        headers: {Authorization: "Bearer " + config.token, "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(data)},
      }, async res => {
        try {
          let raw = "";
          for await (const block of res.setEncoding("utf8")) {
            raw += block;
            if (raw.length > 16384) throw Error("Invalid route response");
          }
          resolve(JSON.parse(raw));
        } catch (error) { reject(error); }
      });
      req.on("error", reject);
      req.end(data);
    });
    if (!response.ok) throw networkError(response.stage || "proxy", response.code || "ROUTE_SERVICE",
      response.message || "The desktop network service could not resolve a route");
    return response;
  };
}

async function webCertificates(file) {
  const defaults = updateCertificates();
  if (!file) return defaults;
  try {
    const descriptor = await open(file, "r");
    try {
      const info = await descriptor.stat();
      if (!info.isFile() || info.size > caLimit) throw Error("Invalid CA file");
      const buffer = Buffer.alloc(info.size);
      const {bytesRead} = await descriptor.read(buffer, 0, info.size, 0);
      const pem = buffer.subarray(0, bytesRead).toString();
      const blocks = pem.match(/-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----/g) || [];
      if (!blocks.length || blocks.some(block => !new X509Certificate(block).ca)) throw Error("Expected CA certificates");
      return [...defaults, ...blocks];
    } finally { await descriptor.close(); }
  } catch {
    throw networkError("tls", "INVALID_CA", "The configured PEM certificate bundle is unavailable or invalid");
  }
}

async function request(url, {signal, accept, resolveRoute, lookupHost, steps}) {
  const hostname = url.hostname.replace(/^\[|\]$/g, "");
  steps.push({stage: "dns", status: "running"});
  const dnsStep = steps.at(-1);
  const family = isIP(hostname);
  let addresses = [], dnsFailure;
  try {
    addresses = family ? [{address: hostname, family}]
      : await abortable(lookupHost(hostname, {all: true}), signal);
  } catch (error) {
    dnsFailure = networkError("dns", error.code || "DNS_FAILED", "The system DNS could not resolve the target");
  }
  // Some VPNs return a synthetic IPv4 address alongside a real IPv6 address.
  // Use the usable native answer without sending the hostname to a public DNS provider.
  const fakeAddress = row => vpnSynthetic.check(row.address, row.family === 6 ? "ipv6" : "ipv4");
  if (!family && addresses.some(fakeAddress)) {
    addresses = addresses.filter(row => !fakeAddress(row));
    if (!addresses.length)
      dnsFailure = networkError("dns", "VPN_SYNTHETIC_DNS", "The VPN returned only a synthetic address. Enable real DNS answers or proxy DNS in Cowork network settings");
  }
  const eligibleForProxyDns = !family && url.protocol === "https:" &&
    !/(?:^|\.)(?:localhost|localdomain)\.?$/i.test(hostname) && !/^metadata\.google\.internal\.?$/i.test(hostname);
  const unresolved = !addresses.length;
  const noAddress = dnsFailure || networkError("dns", "DNS_FAILED", "The system DNS returned no addresses");
  if (unresolved && !eligibleForProxyDns) throw noAddress;
  if (!addresses.every(routableAddress))
    throw networkError("policy", "ADDRESS_DENIED", "The target resolves to a reserved local or non-routable address");

  if (!unresolved) dnsStep.status = "ok";
  steps.push({stage: "proxy", status: "running"});
  const proxyStep = steps.at(-1);
  let route;
  try { route = await resolveRoute(url, signal); }
  catch (error) { throw error.stage ? error : networkError("proxy", "ROUTE_SERVICE", "Could not resolve the system proxy"); }
  proxyStep.route = route.proxy ? route.mode : "direct";
  const proxyDns = unresolved && route.proxyDns === true;
  if (unresolved && !proxyDns) {
    steps.pop();
    throw noAddress;
  }
  if (proxyDns && !route.proxy)
    throw networkError("proxy", "PROXY_DNS_ROUTE", "Proxy DNS requires a proxy, but the selected route is direct");
  if (proxyDns) {
    dnsStep.viaProxy = true;
    dnsStep.status = "ok";
  }

  const secure = url.protocol === "https:";
  let ca;
  if (secure || route.proxy?.startsWith("https:")) {
    try { ca = await webCertificates(route.caFile); }
    catch (error) { proxyStep.status = "ok"; throw error; }
  }
  let agent = false;
  if (route.proxy) {
    // Tunnel only to an address checked above, retaining the HTTP Host and TLS
    // peer name for the original URL. A proxy may reject numeric CONNECT.
    const target = new URL(url.href);
    if (!proxyDns) {
      const address = (addresses.find(row => row.family === 4) || addresses[0]).address;
      target.hostname = isIP(address) === 6 ? "[" + address + "]" : address;
    }
    let socket;
    try {
      socket = await proxyTunnel(new URL(route.proxy), target, signal, 7000, ca);
      signal.throwIfAborted();
    } catch (error) {
      socket?.destroy();
      if (certificateError(error.code))
        throw networkError("proxy", "PROXY_TLS", "TLS verification failed for the HTTPS proxy. Check its certificate and hostname");
      throw networkError("proxy", error.proxyStatus === 407 ? "PROXY_AUTH" : error.code || "PROXY_CONNECT",
        error.proxyStatus === 407 ? "Proxy authentication is required or was rejected"
          : "The proxy could not establish a connection to the target" + (error.proxyStatus ? " (HTTP " + error.proxyStatus + ")" : ""));
    }
    agent = secure ? new https.Agent() : new http.Agent();
    agent.createConnection = options => secure
      ? tls.connect({...options, socket, ca, rejectUnauthorized: true, servername: family ? "" : hostname,
        checkServerIdentity: (_host, cert) => tls.checkServerIdentity(hostname, cert)})
      : socket;
  }
  proxyStep.status = "ok";
  const stage = secure ? "tls" : "http";
  steps.push({stage, status: "running"});
  try {
    return await new Promise((resolve, reject) => {
      const req = (secure ? https : http).get(url, {
        signal, agent, ca, rejectUnauthorized: true,
        headers: {"User-Agent":"Umeko-Cowork/1.0", Accept:accept, "Accept-Encoding":"identity"},
        lookup: (_host, options, callback) => options.all ? callback(null, addresses)
          : callback(null, addresses[0].address, addresses[0].family),
      }, async res => {
        try {
          steps.at(-1).status = "ok";
          if (secure) steps.push({stage: "http", status: "running"});
          const status = res.statusCode || 0;
          steps.at(-1).httpStatus = status;
          if ([301, 302, 303, 307, 308].includes(status) && res.headers.location) {
            res.destroy();
            steps.at(-1).status = "ok";
            resolve({redirect: res.headers.location});
            return;
          }
          if (status < 200 || status >= 300)
            throw networkError("http", "HTTP_" + status, "Target returned HTTP " + status);
          const type = res.headers["content-type"] || "text/plain";
          if (!/^(text\/|application\/(?:rss\+xml|xml|xhtml\+xml)\b)/i.test(type))
            throw networkError("http", "NOT_TEXT", "The response is not a supported text document");
          const chunks = [];
          let size = 0;
          for await (const chunk of res) {
            size += chunk.length;
            if (size > byteLimit) throw networkError("http", "BODY_LIMIT", "The response exceeds 2 MiB");
            chunks.push(chunk);
          }
          const charset = type.match(/charset\s*=\s*["']?([-\w]+)/i)?.[1] || "utf-8";
          let decoder;
          try { decoder = new TextDecoder(charset); } catch { decoder = new TextDecoder(); }
          steps.at(-1).status = "ok";
          resolve({type, body: decoder.decode(Buffer.concat(chunks))});
        } catch (error) { res.destroy(); reject(error); }
      });
      req.on("socket", socket => {
        if (!secure) return;
        socket.once("secureConnect", () => { steps.at(-1).status = "ok"; });
      });
      req.on("error", reject);
    });
  } catch (error) {
    if (error.stage) throw error;
    const code = error.code || signal.reason?.name || "CONNECTION";
    const tlsError = certificateError(code);
    throw networkError(tlsError ? "tls" : "http", code,
      code === "ERR_TLS_CERT_ALTNAME_INVALID" ? "The certificate does not match the target hostname"
      : /CERT_HAS_EXPIRED|CERT_NOT_YET_VALID/.test(code) ? "The certificate is expired or not yet valid"
      : tlsError ? "TLS verification failed. Check the system trust store and the configured CA"
      : "The connection timed out or was interrupted");
  } finally { if (agent) agent.destroy(); }
}

export async function downloadCoworkPage(raw, {signal: callerSignal, resolveRoute = desktopWebRoute(),
  purpose = "fetch", lookupHost = lookup, steps = []} = {}) {
  const deadline = AbortSignal.timeout(15000);
  const signal = callerSignal ? AbortSignal.any([callerSignal, deadline]) : deadline;
  let url = targetUrl(raw, purpose);
  for (let redirects = 0; redirects <= 4; redirects++) {
    const accept = "text/html,text/plain,text/markdown,application/rss+xml,application/xml";
    const result = await request(url, {signal, accept, resolveRoute, lookupHost, steps});
    if (!result.redirect) return {...result, url: url.href};
    const next = targetUrl(new URL(result.redirect, url).href, purpose);
    if (url.protocol === "https:" && next.protocol !== "https:")
      throw networkError("policy", "TLS_DOWNGRADE", "An HTTPS redirect tried to switch to an insecure connection");
    url = next;
  }
  throw networkError("http", "REDIRECT_LIMIT", "Too many web redirects");
}

export async function probeCoworkWeb(config) {
  const steps = [];
  try {
    await downloadCoworkPage(config.url, {...config, resolveRoute: desktopWebRoute(config), steps});
    return {ok:true, steps};
  } catch (error) {
    if (steps.at(-1)?.status === "running") steps.at(-1).status = "error";
    return {ok:false, steps, stage:error.stage || "http", code:error.code || "FAILED",
      message:error.stage ? error.message : "The request could not be completed"};
  }
}

const hidden = new Set(["script", "style", "template", "noscript", "svg", "nav", "footer", "aside", "form"]);
const paragraph = new Set(["article", "section", "div", "p", "li", "br", "tr", "pre", "h1", "h2", "h3", "h4"]);
function plainText(root) {
  const chunks = [];
  const stack = [root];
  while (stack.length) {
    const node = stack.pop();
    if (typeof node === "string") chunks.push(node);
    else if (node.nodeName === "#text") chunks.push(node.value);
    else if (!hidden.has(node.tagName)) {
      const children = node.childNodes || [];
      if (paragraph.has(node.tagName)) { chunks.push("\n"); stack.push("\n"); }
      for (let index = children.length - 1; index >= 0; index--) stack.push(children[index]);
    }
  }
  return chunks.join("").replace(/[^\S\n]+/g, " ").replace(/\s*\n\s*/g, "\n").trim();
}

function first(root, predicate) {
  const queue = [root];
  for (let index = 0; index < queue.length; index++) {
    if (predicate(queue[index])) return queue[index];
    for (const child of queue[index].childNodes || []) queue.push(child);
  }
}

export function pageText(html) {
  const tree = parse(html);
  const main = first(tree, node => node.tagName === "main" || node.attrs?.some(attr => attr.name === "role" && attr.value === "main"));
  const body = first(tree, node => node.tagName === "body");
  const title = first(tree, node => node.tagName === "title");
  return {title: title ? plainText(title) : "", text: (main && plainText(main)) || plainText(body || tree)};
}

function rssField(item, name) {
  const value = item.match(new RegExp("<" + name + "\\b[^>]*>([\\s\\S]*?)<\\/" + name + ">", "i"))?.[1] || "";
  const inner = value.replace(/^\s*<!\[CDATA\[([\s\S]*?)\]\]>\s*$/, "$1");
  return plainText(parseFragment(inner));
}

export function searchResults(rss) {
  const results = [];
  for (const match of rss.matchAll(/<item\b[^>]*>([\s\S]*?)<\/item>/gi)) {
    try {
      const link = publicWebUrl(rssField(match[1], "link")).href;
      const title = rssField(match[1], "title").slice(0, 240);
      if (!title || results.some(row => row.url === link)) continue;
      results.push({title, url: link, snippet: rssField(match[1], "description").slice(0, 500)});
      if (results.length === 6) break;
    } catch { /* Skip invalid or missing result links. */ }
  }
  return results;
}

export function coworkTools(pi, allowedTools, network = {}) {
  const resolveRoute = desktopWebRoute(network);
  const download = (url, signal, purpose) => downloadCoworkPage(url, {signal, resolveRoute, purpose});
  const allowed = new Set(allowedTools);
  registerCoworkLocalTools(pi, allowed);
  pi.on("tool_call", event => {
    if (!allowed.has(event.toolName)) return {block: true, reason: "This tool is outside the Cowork role's capabilities."};
  });
  const tools = [
    ["web_search", "网页搜索", "Find public web sources via Bing RSS. Returns titles, URLs and snippets. Read sources with web_fetch before citing details.",
      Type.Object({query: Type.String({minLength: 1, maxLength: 400})}), async ({query}, signal) => {
        const url = new URL("https://www.bing.com/search");
        url.searchParams.set("format", "rss");
        url.searchParams.set("q", query.trim());
        const {body} = await download(url.href, signal, "search");
        return {provider: "Bing", results: searchResults(body)};
      }],
    ["web_fetch", "网页读取", "Read text from a public or internal web page. Returns the final URL, title and up to 20,000 characters.",
      Type.Object({url: Type.String({minLength: 1, maxLength: 2048})}), async ({url}, signal) => {
        const result = await download(url, signal, "fetch");
        const {title, text} = /html/i.test(result.type) ? pageText(result.body) : {title: "", text: result.body.trim()};
        return {url: result.url, title, text: text.slice(0, 20000), truncated: text.length > 20000};
      }],
  ];
  for (const [name, label, description, parameters, execute] of tools) {
    if (!allowed.has(name)) continue;
    pi.registerTool({name, label, description, parameters, exposure: "direct", annotations: {readOnlyHint: true},
      async execute(_id, args, signal) {
        const result = await execute(args, signal);
        return {content: [{type: "text", text: JSON.stringify(result)}]};
      },
    });
  }
}
