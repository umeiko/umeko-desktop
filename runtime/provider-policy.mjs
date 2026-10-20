// Process-level routing guard. This is not a sandbox for shell child processes.
// Install before importing Pi or user extensions. All model HTTP goes to our
// authenticated loopback gateway; the gateway owns explicit supplier URLs/keys.
import net from "node:net";
import tls from "node:tls";
import http from "node:http";
import https from "node:https";
import http2 from "node:http2";
import dgram from "node:dgram";
import { syncBuiltinESMExports } from "node:module";

let allowed;
let mcpEndpoints = [];
const denied = () => { throw new Error("网络请求已阻止：模型连接须使用 Umeko 中配置的供应商"); };
function check(host, port, protocol = "http:") {
  if (allowed && protocol === "http:" && host === "127.0.0.1" && Number(port) === Number(allowed.port)) return;
  if (mcpEndpoints.some(url => url.protocol === protocol && url.hostname === host && Number(url.port || (protocol === "https:" ? 443 : 80)) === Number(port))) return;
  denied();
}
export function setMcpNetwork(entries) {
  mcpEndpoints = entries.filter(entry => entry.config.enabled !== false).flatMap(entry => [entry.config.url, entry.config.oauth?.authServerMetadataUrl])
    .filter(Boolean).map(value => new URL(value)).filter(url => ["http:", "https:"].includes(url.protocol) && !url.username && !url.password);
}
export function setGateway(value) {
  const url = new URL(value);
  if (url.protocol !== "http:" || url.hostname !== "127.0.0.1" || !url.port || url.username || url.password || url.pathname !== "/") denied();
  allowed = url;
}
export function installProviderPolicy() {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = function(input, init) {
    const url = new URL(typeof input === "string" || input instanceof URL ? input : input.url);
    check(url.hostname, url.port || (url.protocol === "https:" ? 443 : 80), url.protocol);
    return originalFetch(input, { ...init, redirect: "error" });
  };
  const connect = net.Socket.prototype.connect;
  net.Socket.prototype.connect = function(...args) {
    const first = Array.isArray(args[0]) ? args[0][0] : args[0];
    if (typeof first === "object") {
      if (first.path || first.socket) denied();
      const host = first.servername || first.host || "localhost";
      if (mcpEndpoints.some(url => url.hostname === host && Number(url.port || (url.protocol === "https:" ? 443 : 80)) === Number(first.port))) {
        return connect.apply(this, args);
      }
      check(host, first.port);
    } else check(typeof args[1] === "string" ? args[1] : "localhost", first);
    return connect.apply(this, args);
  };
  const tlsConnect = tls.connect;
  tls.connect = function(...args) {
    const first = typeof args[0] === "object" ? args[0] : { port: args[0], host: typeof args[1] === "string" ? args[1] : "localhost" };
    check(first.servername || first.host || "localhost", first.port || 443, "https:");
    return tlsConnect.apply(this, args);
  };
  http2.connect = denied;
  dgram.createSocket = denied;
  const request = http.request;
  http.request = function(input, options, callback) {
    const data = typeof input === "string" || input instanceof URL ? new URL(input) : input;
    check(data.hostname || data.host || "localhost", data.port || 80, data.protocol || "http:");
    return request.call(this, input, options, callback);
  };
  http.get = function(...args) { const req = http.request(...args); req.end(); return req; };
  const secureRequest = https.request;
  https.request = function(input, options, callback) {
    const data = typeof input === "string" || input instanceof URL ? new URL(input) : input;
    check(data.hostname || data.host || "localhost", data.port || 443, "https:");
    return secureRequest.call(this, input, options, callback);
  };
  https.get = function(...args) { const req = https.request(...args); req.end(); return req; };
  syncBuiltinESMExports();
}
