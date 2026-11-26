// CONNECT handling adapted from dsh-remote-explorer 0.8.12,
// src/tunnel/local-http-proxy.ts (Apache-2.0). See licenses/dsh-remote-explorer-APACHE-2.0.txt.
import { Agent, createServer, request } from "node:http";
import { lookup } from "node:dns";
import { BlockList, connect, isIP } from "node:net";
import { once } from "node:events";
import { proxyTunnel, updateCertificates } from "./update-engine.mjs";

const timeout = 10_000;
const hostname = url => url.hostname.replace(/^\[|\]$/g, "");
const responseLine = (socket, status) => socket.end("HTTP/1.1 " + status + "\r\nConnection: close\r\n\r\n");
const localAddresses = new BlockList();
for (const [host, bits] of [["0.0.0.0", 8], ["10.0.0.0", 8], ["127.0.0.0", 8], ["169.254.0.0", 16],
  ["172.16.0.0", 12], ["192.168.0.0", 16], ["224.0.0.0", 4], ["240.0.0.0", 4]]) {
  localAddresses.addSubnet(host, bits, "ipv4");
}
for (const [host, bits] of [["::", 128], ["::1", 128], ["fc00::", 7], ["fe80::", 10], ["ff00::", 8]]) {
  localAddresses.addSubnet(host, bits, "ipv6");
}
const publicAddress = host => !localAddresses.check(host, isIP(host) === 6 ? "ipv6" : "ipv4");

// The direct route is Internet-only. Reuse the resolved addresses here rather
// than resolving the name a second time after checking it.
function lookupPublic(host, options, callback) {
  lookup(host, { ...options, all: true }, (error, values) => {
    if (error) { callback(error); return; }
    const addresses = values.filter(item => publicAddress(item.address));
    if (!addresses.length) { callback(new Error("Direct proxy requires a public address")); return; }
    if (options.all) callback(null, addresses);
    else callback(null, addresses[0].address, addresses[0].family);
  });
}

function directTunnel(target, signal) {
  const host = hostname(target);
  if (isIP(host) && !publicAddress(host)) throw new Error("Direct proxy requires a public address");
  const socket = connect({ host, port: Number(target.port || 443), signal, lookup: lookupPublic });
  const timer = setTimeout(() => socket.destroy(new Error("Connection timed out")), timeout);
  return once(socket, "connect").then(() => socket).finally(() => clearTimeout(timer));
}

function endToEndHeaders(headers) {
  const result = { ...headers };
  const nominated = String(headers.connection || "").toLowerCase().split(",").map(value => value.trim());
  for (const header of [...nominated, "connection", "keep-alive", "proxy-connection", "proxy-authorization",
    "proxy-authenticate", "te", "trailer", "transfer-encoding", "upgrade"]) delete result[header];
  return result;
}

/** A loopback HTTP proxy for plain HTTP downloads and HTTPS CONNECT. */
export async function startRemoteHttpProxy(upstream) {
  const controller = new AbortController();
  const ca = upstream ? updateCertificates() : undefined;
  const sockets = new Set();
  const track = socket => {
    sockets.add(socket);
    socket.once("close", () => sockets.delete(socket));
  };
  const tunnel = async (target, signal) => {
    const socket = await (upstream
      ? proxyTunnel(upstream, target, signal, timeout, ca)
      : directTunnel(target, signal));
    if (signal.aborted) {
      socket.destroy();
      signal.throwIfAborted();
    }
    track(socket);
    return socket;
  };
  const throughProxy = upstream ? new Agent({ keepAlive: false }) : false;
  if (throughProxy) {
    throughProxy.createConnection = (options, callback) => {
      const host = options.host.includes(":") ? "[" + options.host + "]" : options.host;
      tunnel(new URL("tcp://" + host + ":" + options.port), controller.signal)
        .then(socket => callback(null, socket), callback);
    };
  }
  const server = createServer((incoming, outgoing) => {
    let target;
    try { target = new URL(incoming.url); } catch {}
    if (target?.protocol !== "http:" || target.username || target.password) {
      outgoing.writeHead(400).end();
      return;
    }
    const host = hostname(target);
    if (!upstream && isIP(host) && !publicAddress(host)) {
      outgoing.writeHead(403).end();
      return;
    }
    const headers = endToEndHeaders(incoming.headers);
    headers.host = target.host;
    const origin = request(target, { method: incoming.method, headers, agent: throughProxy,
      ...(upstream ? {} : { lookup: lookupPublic }), signal: controller.signal, timeout }, reply => {
      outgoing.writeHead(reply.statusCode, endToEndHeaders(reply.headers));
      reply.on("error", error => outgoing.destroy(error));
      reply.pipe(outgoing);
    });
    origin.on("timeout", () => origin.destroy(new Error("HTTP request timed out")));
    origin.on("error", () => {
      if (outgoing.headersSent) outgoing.destroy();
      else outgoing.writeHead(502).end();
    });
    outgoing.on("close", () => { if (!outgoing.writableFinished) origin.destroy(); });
    incoming.pipe(origin);
  });
  server.on("connection", track);
  server.on("connect", async (message, client, head) => {
    const authority = /^(?:\[[0-9a-f:.]+\]|[a-z0-9._-]+):([0-9]{1,5})$/i.exec(message.url);
    if (!authority || Number(authority[1]) < 1 || Number(authority[1]) > 65535) {
      responseLine(client, "400 Bad Request");
      return;
    }
    let target;
    try { target = new URL("tcp://" + message.url); } catch { responseLine(client, "400 Bad Request"); return; }
    const clientLifetime = new AbortController();
    client.once("close", () => clientLifetime.abort());
    client.on("error", () => client.destroy());
    let destination;
    try {
      destination = await tunnel(target, AbortSignal.any([controller.signal, clientLifetime.signal]));
    } catch {
      if (!client.destroyed) responseLine(client, "502 Bad Gateway");
      return;
    }
    const close = () => { client.destroy(); destination.destroy(); };
    client.once("close", close);
    destination.once("close", close);
    destination.on("error", close);
    client.write("HTTP/1.1 200 Connection Established\r\n\r\n");
    if (head.length) destination.write(head);
    client.pipe(destination);
    destination.pipe(client);
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  return {
    host: "127.0.0.1",
    port: server.address().port,
    close() {
      controller.abort();
      server.close();
      if (throughProxy) throughProxy.destroy();
      for (const socket of sockets) socket.destroy();
    },
  };
}
