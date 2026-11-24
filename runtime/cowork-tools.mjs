import { lookup } from "node:dns/promises";
import { get as getHttp } from "node:http";
import { get as getHttps } from "node:https";
import { BlockList, isIP } from "node:net";
import { parse, parseFragment } from "parse5";
import { Type } from "typebox";
import { registerCoworkLocalTools } from "./cowork-local.mjs";

const synthetic = new BlockList();
synthetic.addSubnet("198.18.0.0", 15, "ipv4");
const reserved = new BlockList();
for (const [address, prefix] of [
  ["0.0.0.0", 8], ["10.0.0.0", 8], ["100.64.0.0", 10], ["127.0.0.0", 8], ["169.254.0.0", 16],
  ["172.16.0.0", 12], ["192.0.0.0", 24], ["192.0.2.0", 24], ["192.168.0.0", 16],
  ["198.18.0.0", 15], ["198.51.100.0", 24], ["203.0.113.0", 24], ["224.0.0.0", 3],
]) reserved.addSubnet(address, prefix, "ipv4");
const globalV6 = new BlockList();
globalV6.addSubnet("2000::", 3, "ipv6");
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

function publicAddress({address, family}) {
  return family === 6 ? globalV6.check(address, "ipv6") && !reserved.check(address, "ipv6") :
    family === 4 && !reserved.check(address);
}

async function request(url, signal, accept = "text/html,text/plain,text/markdown,application/rss+xml,application/xml") {
  const host = url.hostname.replace(/^\[|\]$/g, "");
  const family = isIP(host);
  let addresses = family ? [{address: host, family}] : await lookup(host, {all: true});
  // VPNs that use the benchmarking range can return synthetic DNS answers.
  // Re-resolve that case over HTTPS, then connect to the verified public IP.
  if (!family && addresses.some(row => row.family === 4 && synthetic.check(row.address))) {
    const resolver = new URL("https://1.1.1.1/dns-query");
    resolver.searchParams.set("name", host);
    resolver.searchParams.set("type", "A");
    const {body} = await request(resolver, signal, "application/dns-json");
    addresses = (JSON.parse(body).Answer || []).filter(row => row.type === 1 && isIP(row.data) === 4)
      .map(row => ({address: row.data, family: 4}));
  }
  if (!addresses.length || !addresses.every(publicAddress)) throw new Error("The hostname must resolve to public addresses");
  signal.throwIfAborted();
  const get = url.protocol === "https:" ? getHttps : getHttp;
  return new Promise((resolve, reject) => {
    const req = get(url, {
      signal, agent: false, headers: {"User-Agent": "Umeko-Cowork/1.0", Accept: accept},
      // Reuse the validated DNS response for the connection, keeping the URL's Host and TLS identity.
      lookup: (_host, options, callback) => options.all ? callback(null, addresses) :
        callback(null, addresses[0].address, addresses[0].family),
    }, response => {
      const status = response.statusCode || 0;
      if ([301, 302, 303, 307, 308].includes(status) && response.headers.location) {
        response.destroy();
        resolve({redirect: response.headers.location});
        return;
      }
      if (status < 200 || status >= 300) {
        response.destroy();
        reject(new Error("Web server returned HTTP " + status));
        return;
      }
      const type = response.headers["content-type"] || "text/plain";
      if (!/^(text\/|application\/(?:rss\+xml|xml|xhtml\+xml|dns-json)\b)/i.test(type)) {
        response.destroy();
        reject(new Error("This page is not a supported text document"));
        return;
      }
      const chunks = [];
      let size = 0;
      response.on("error", reject);
      response.on("data", chunk => {
        size += chunk.length;
        if (size > 2 * 1024 * 1024) response.destroy(new Error("Web response exceeds 2 MiB"));
        else chunks.push(chunk);
      });
      response.on("end", () => {
        const charset = type.match(/charset\s*=\s*["']?([-\w]+)/i)?.[1] || "utf-8";
        let decoder;
        try { decoder = new TextDecoder(charset); } catch { decoder = new TextDecoder(); }
        resolve({type, body: decoder.decode(Buffer.concat(chunks))});
      });
    });
    req.on("error", reject);
  });
}

async function download(raw, callerSignal) {
  const deadline = AbortSignal.timeout(15000);
  const signal = callerSignal ? AbortSignal.any([callerSignal, deadline]) : deadline;
  let url = publicWebUrl(raw);
  for (let redirects = 0; redirects <= 4; redirects++) {
    const result = await request(url, signal);
    if (!result.redirect) return {...result, url: url.href};
    url = publicWebUrl(new URL(result.redirect, url).href);
  }
  throw new Error("Too many web redirects");
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

export function coworkTools(pi, allowedTools) {
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
        const {body} = await download(url.href, signal);
        return {provider: "Bing", results: searchResults(body)};
      }],
    ["web_fetch", "网页读取", "Read the text of a public web page. Returns the final URL, title and up to 20,000 characters.",
      Type.Object({url: Type.String({minLength: 1, maxLength: 2048})}), async ({url}, signal) => {
        const result = await download(url, signal);
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
