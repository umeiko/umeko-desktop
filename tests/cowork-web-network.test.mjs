import assert from "node:assert/strict";
import { once } from "node:events";
import { readFile } from "node:fs/promises";
import http from "node:http";
import https from "node:https";
import net from "node:net";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { desktopWebRoute, downloadCoworkPage, probeCoworkWeb } from "../runtime/cowork-tools.mjs";

const fixture = new URL("fixtures/cowork-tls/", import.meta.url);
const caFile = fileURLToPath(new URL("ca.pem", fixture));
const key = await readFile(new URL("server-key.pem", fixture));
const cert = await readFile(new URL("server.pem", fixture));

async function listen(t, server) {
  const sockets = new Set();
  server.on("connection", socket => {
    sockets.add(socket);
    socket.once("close", () => sockets.delete(socket));
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  t.after(() => new Promise(resolve => {
    server.close(resolve);
    for (const socket of sockets) socket.destroy();
  }));
  return server.address().port;
}

test("Cowork fetches intranet sites without an allowlist and verifies the TLS host through a proxy", async t => {
  const headers = [], tunnels = [], routes = [];
  const target = https.createServer({key, cert}, (req, res) => {
    headers.push(req.headers);
    if (req.url === "/start") {
      res.writeHead(302, {Location: "/page"});
      return res.end();
    }
    if (req.url === "/downgrade" || req.url === "/reserved") {
      res.writeHead(302, {Location: req.url === "/reserved" ? "https://169.254.169.254/" : "http://wiki.cowork.test/"});
      return res.end();
    }
    res.writeHead(200, {"Content-Type":"text/plain"});
    res.end("Enterprise notes");
  });
  const targetPort = await listen(t, target);
  let proxyStatus = 200;
  const proxy = http.createServer();
  proxy.on("connect", (req, socket) => {
    tunnels.push([req.url, req.headers["proxy-authorization"]]);
    if (proxyStatus !== 200) return socket.end("HTTP/1.1 407 Proxy Authentication Required\r\n\r\n");
    const upstream = net.connect(targetPort, "127.0.0.1", () => {
      socket.write("HTTP/1.1 200 Connection Established\r\n\r\n");
      socket.pipe(upstream).pipe(socket);
    });
    upstream.on("error", () => socket.destroy());
    socket.on("close", () => upstream.destroy());
  });
  const proxyPort = await listen(t, proxy);
  const origin = `https://127.0.0.1:${targetPort}`;
  const url = new URL(origin + "/start");
  const literalDns = async () => [{address: "198.18.1.2", family: 4}, {address: "192.168.44.7", family: 4}];
  await assert.rejects(downloadCoworkPage(url.href), {code: "ADDRESS_DENIED"});

  url.hostname = "wiki.cowork.test";
  const options = {
    lookupHost:literalDns, steps:[],
    resolveRoute: async requested => {
      routes.push(requested.pathname);
      return {proxy:`http://fixture-user:fixture-password@127.0.0.1:${proxyPort}`, caFile, mode:"custom"};
    },
  };
  const result = await downloadCoworkPage(url.href, options);
  assert.equal(result.body, "Enterprise notes");
  assert.equal(result.url, url.origin + "/page");
  assert.deepEqual(routes, ["/start", "/page"]);
  assert.equal(tunnels[0][0], `192.168.44.7:${targetPort}`);
  assert.equal(tunnels[0][1], "Basic " + Buffer.from("fixture-user:fixture-password").toString("base64"));
  assert.equal(headers[0].host, url.host);
  assert.equal(headers[0]["proxy-authorization"], undefined);
  assert.deepEqual(options.steps.slice(0, 4).map(step => [step.stage, step.status]),
    [["dns","ok"], ["proxy","ok"], ["tls","ok"], ["http","ok"]]);

  const mismatch = new URL(url.href);
  mismatch.hostname = "other.cowork.test";
  await assert.rejects(downloadCoworkPage(mismatch.href, options), {stage:"tls", code:"ERR_TLS_CERT_ALTNAME_INVALID"});
  await assert.rejects(downloadCoworkPage(url.href, {...options,
    resolveRoute:async requested => ({...await options.resolveRoute(requested), caFile:""})}), {stage:"tls"});
  await assert.rejects(downloadCoworkPage(url.origin + "/downgrade", options), {code:"TLS_DOWNGRADE"});
  await assert.rejects(downloadCoworkPage(url.origin + "/reserved", options), {code:"ADDRESS_DENIED"});

  const fakeDns = async () => [{address:"198.18.0.22",family:4},{address:"::ffff:0:c612:16",family:6}];
  const fallback = {...options, lookupHost:fakeDns, steps:[],
    resolveRoute:async requested => ({...await options.resolveRoute(requested), proxyDns:true})};
  assert.equal((await downloadCoworkPage(url.origin + "/page", fallback)).body, "Enterprise notes");
  assert.equal(tunnels.at(-1)[0], url.host);
  assert.equal(fallback.steps[0].viaProxy, true);
  await assert.rejects(downloadCoworkPage(url.href, {...fallback,
    resolveRoute:async () => ({proxy:"", mode:"system", proxyDns:true})}), {code:"PROXY_DNS_ROUTE"});

  proxyStatus = 407;
  const initialTunnels = tunnels.length;
  await assert.rejects(downloadCoworkPage(url.href, options), {stage:"proxy", code:"PROXY_AUTH"});
  assert.equal(tunnels.length, initialTunnels + 1, "must not retry or silently switch to direct access");
});

test("redirects and DNS never widen scope or downgrade TLS", async () => {
  const lookups = [];
  const result = await probeCoworkWeb({url:"https://docs.corp.test", lookupHost: async host => {
    lookups.push(host);
    return [{address:"198.18.0.22",family:4}];
  }});
  assert.equal(result.code, "VPN_SYNTHETIC_DNS");
  assert.deepEqual(lookups, ["docs.corp.test"]);
  await assert.rejects(downloadCoworkPage("https://docs.corp.test:8443", {purpose:"search"}), {code:"SEARCH_ORIGIN"});
  await assert.rejects(downloadCoworkPage("https://www.bing.com/search", {
    purpose:"search", lookupHost:async () => [{address:"198.18.0.22",family:4}],
    resolveRoute:async () => ({proxy:"", mode:"system", proxyDns:true}),
  }), {code:"PROXY_DNS_ROUTE"});
});

test("the authenticated desktop route helper passes settings without returning secrets in probe diagnostics", async t => {
  const calls = [];
  const port = await listen(t, http.createServer(async (req, res) => {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    calls.push({path:req.url, auth:req.headers.authorization, payload:JSON.parse(raw)});
    res.end(JSON.stringify({ok:true, proxy:"http://user:fixture-password@127.0.0.1:1", mode:"system", caFile:""}));
  }));
  const opts = {scope:"scope-fixture", gateway:`http://127.0.0.1:${port}/`, token:"test-token"};
  const target = new URL("https://docs.corp.test");
  await desktopWebRoute(opts)(target, AbortSignal.timeout(2000));
  assert.deepEqual(calls[0], {
    path:"/umeko/cowork-web-route", auth:"Bearer test-token", payload:{scope:"scope-fixture",url:target.href},
  });
  const result = await probeCoworkWeb({...opts, url:target.href, lookupHost: async () => [{address:"1.1.1.1",family:4}]});
  assert.equal(result.stage, "proxy");
  assert.equal(JSON.stringify(result).includes("fixture-password"), false);
});
