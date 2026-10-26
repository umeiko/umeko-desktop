// Synthetic certificates and loopback traffic only. The OS trust store is never modified.
import {test, mock} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import https from 'node:https';
import http from 'node:http';
import net from 'node:net';
import tls from 'node:tls';
import dns from 'node:dns';
import {once} from 'node:events';
import {updateCertificates, updateRequest} from '../runtime/update-engine.mjs';

const fixture=new URL('./fixtures/update-tls/',import.meta.url);
const ca=await fs.readFile(new URL('ca.pem',fixture),'utf8');
const read=tls.getCACertificates;
mock.method(tls,'getCACertificates',type=>type==='system'?[...read(type),ca]:read(type));
dns.setDefaultResultOrder('ipv4first');

async function listen(t,server) {
  const sockets=new Set();
  server.on('connection',socket=>{sockets.add(socket);socket.on('close',()=>sockets.delete(socket));});
  server.listen(0,'127.0.0.1');await once(server,'listening');
  t.after(()=>new Promise(resolve=>{server.close(resolve);for(const socket of sockets)socket.destroy();}));
  return server.address().port;
}
async function endpoint(t,untrusted=false) {
  const key=await fs.readFile(new URL(untrusted?'untrusted-key.pem':'server-key.pem',fixture));
  const cert=await fs.readFile(new URL(untrusted?'untrusted.pem':'server.pem',fixture));
  const requests=[];
  const server=https.createServer({key,cert},(req,res)=>{requests.push(req.headers);res.end('verified fixture');});
  return {server,key,cert,requests,url:`https://127.0.0.1:${await listen(t,server)}/fixture`};
}
async function body(response) {let text='';for await(const chunk of response)text+=chunk;return text;}
function automatic(t,proxy) {
  const previous=process.env.UMEKO_UPDATE_PROXY;
  process.env.UMEKO_UPDATE_PROXY=proxy;
  t.after(()=>{if(previous===undefined)delete process.env.UMEKO_UPDATE_PROXY;else process.env.UMEKO_UPDATE_PROXY=previous;});
}

test('system trust extends default and extra roots without replacing them',()=>{
  assert.deepEqual(updateCertificates(type=>type==='default'?['mozilla','extra','same']:['enterprise','same']),['mozilla','extra','same','enterprise']);
  assert.deepEqual(updateCertificates(type=>{if(type==='system')throw Error('unreadable store');return ['mozilla'];}),['mozilla']);
});
test('a root exposed by the system store validates a real HTTPS connection',async t=>{
  const target=await endpoint(t);
  assert.equal(await body(await updateRequest(target.url,{proxy:''})),'verified fixture');
});
test('both HTTPS proxy and target validate with the system root; credentials stay at the proxy',async t=>{
  const target=await endpoint(t), tunnels=[];
  const proxy=https.createServer({key:target.key,cert:target.cert});
  proxy.on('connect',(req,socket)=>{
    tunnels.push(req.headers);
    const upstream=net.connect(new URL(target.url).port,'127.0.0.1',()=>{
      socket.write('HTTP/1.1 200 Connection Established\r\n\r\n');socket.pipe(upstream).pipe(socket);
    });
    upstream.on('error',()=>socket.destroy());socket.on('close',()=>upstream.destroy());
  });
  const port=await listen(t,proxy);
  assert.equal(await body(await updateRequest(target.url,{proxy:`https://user:fixture-secret@127.0.0.1:${port}`,headers:{Range:'bytes=1-4'}})),'verified fixture');
  assert.ok(tunnels[0]['proxy-authorization']);
  assert.equal(target.requests[0].range,'bytes=1-4');
  assert.equal(target.requests[0]['proxy-authorization'],undefined);
});
test('automatic system-proxy failure tries verified direct access and remembers the successful route',async t=>{
  const target=await endpoint(t), routes=[], network={};let connects=0;
  const proxy=http.createServer();proxy.on('connect',(_req,socket)=>{connects++;socket.destroy();});
  automatic(t,`http://127.0.0.1:${await listen(t,proxy)}`);
  for(let i=0;i<2;i++)assert.equal(await body(await updateRequest(target.url,{network,onRoute:route=>routes.push(route)})),'verified fixture');
  assert.equal(connects,1);
  assert.deepEqual(routes,['系统代理','直连','直连']);
});
test('untrusted chains and host-name mismatches stay rejected with actionable errors',async t=>{
  const target=await endpoint(t,true);
  await assert.rejects(updateRequest(target.url,{proxy:''}),e=>e.code==='DEPTH_ZERO_SELF_SIGNED_CERT'&&e.retryable===false&&e.message.includes('系统信任证书'));
  const trusted=await endpoint(t);
  await assert.rejects(updateRequest(trusted.url.replace('127.0.0.1','localhost'),{proxy:''}),e=>e.code==='ERR_TLS_CERT_ALTNAME_INVALID'&&e.message.includes('域名不匹配'));
});
test('proxy gateway errors try direct, while authentication rejection stays explicit',async t=>{
  const target=await endpoint(t);let status=502, connects=0;
  const proxy=http.createServer();
  proxy.on('connect',(_req,socket)=>{connects++;socket.end(`HTTP/1.1 ${status} Fixture\r\nContent-Length: 0\r\n\r\n`);});
  automatic(t,`http://127.0.0.1:${await listen(t,proxy)}`);
  assert.equal(await body(await updateRequest(target.url)),'verified fixture');
  status=407;
  await assert.rejects(updateRequest(target.url),e=>e.code==='PROXY'&&e.proxyStatus===407);
  assert.equal(connects,2);assert.equal(target.requests.length,1);
});
test('proxy/direct failures report route codes without exposing credentials; cancellation never changes routes',async t=>{
  const target=await endpoint(t,true), proxy=http.createServer();
  proxy.on('connect',(_req,socket)=>socket.destroy());
  automatic(t,`http://user:fixture-secret@127.0.0.1:${await listen(t,proxy)}`);
  await assert.rejects(updateRequest(target.url),e=>e.routes.length===2&&e.message.includes('系统代理')&&e.message.includes('直连')&&!e.message.includes('fixture-secret'));
  const signal=new AbortController();signal.abort();const routes=[];
  await assert.rejects(updateRequest(target.url,{signal:signal.signal,onRoute:r=>routes.push(r)}),e=>e.code==='ABORT_ERR');
  assert.deepEqual(routes,[]);
});
