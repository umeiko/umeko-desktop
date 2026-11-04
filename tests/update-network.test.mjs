// Synthetic certificates and loopback traffic only. The OS trust store is never modified.
import {test, mock} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import https from 'node:https';
import http from 'node:http';
import net from 'node:net';
import tls from 'node:tls';
import dns from 'node:dns';
import os from 'node:os';
import path from 'node:path';
import {once} from 'node:events';
import {updateCertificates, updateRequest, withUpdateRoutes} from '../runtime/update-engine.mjs';
import {classifyPreviewFailure, previewEnvironment, probePreviewNetwork} from '../runtime/preview-network.mjs';

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

async function previewOptions(t,environment={}) {
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'umeko-preview-network-'));
  t.after(()=>fs.rm(directory,{recursive:true,force:true}));
  return {environment,caFile:path.join(directory,'ca.pem'),certificateReader:()=>[ca]};
}
test('shared routes keep explicit selection and remember the automatic winner',async()=>{
  const environment={UMEKO_UPDATE_PROXY:'http://user:fixture-secret@proxy.invalid:8080'}, network={}, seen=[];
  const operation=async proxy=>{seen.push(proxy);if(proxy)throw Object.assign(Error('fixture'),{code:'ECONNREFUSED'});return 'ok';};
  assert.equal(await withUpdateRoutes(operation,{environment,network}),'ok');
  assert.equal(await withUpdateRoutes(operation,{environment,network}),'ok');
  assert.deepEqual(seen,[environment.UMEKO_UPDATE_PROXY,'','']);
  const explicit=[];
  await assert.rejects(withUpdateRoutes(async proxy=>{explicit.push(proxy);throw Object.assign(Error('fixture'),{code:'ECONNREFUSED'});},{environment,proxy:environment.UMEKO_UPDATE_PROXY}),{code:'ECONNREFUSED'});
  assert.deepEqual(explicit,[environment.UMEKO_UPDATE_PROXY]);
});
test('preview Git probe falls back to direct, exports selected overrides, and reuses that route',async t=>{
  const proxy='http://user:fixture-secret@proxy.invalid:8080';
  const options=await previewOptions(t,{UMEKO_UPDATE_PROXY:proxy,PATH:'keep-python-path',npm_config_registry:'https://registry.example.test',UNRELATED:'keep'});
  options.network={};const seen=[];
  const transport=async call=>{
    seen.push(call);
    if(call.env.HTTPS_PROXY)throw Object.assign(Error('connect proxy.invalid fixture-secret'),{code:'ECONNREFUSED'});
    return {stdout:'fixture-object\trefs/heads/main\n'};
  };
  const result=await probePreviewNetwork(options,transport);
  assert.equal(result.ok,true);assert.equal(result.route,'直连');
  assert.deepEqual(seen.map(call=>call.env.HTTPS_PROXY),[proxy,'']);
  assert.deepEqual(seen[1].args,['ls-remote','--exit-code','https://github.com/umeiko/umeko-desktop.git','refs/heads/main']);
  assert.equal(seen[1].env.PATH,'keep-python-path');assert.equal(seen[1].env.npm_config_registry,'https://registry.example.test');
  assert.equal(result.environment.PATH,undefined);assert.equal(result.environment.npm_config_registry,undefined);
  assert.equal(result.environment.HTTPS_PROXY,'');assert.equal(result.environment.NO_PROXY,'*');
  assert.ok(result.removeEnvironment.includes('node_tls_reject_unauthorized'));
  assert.ok(!JSON.stringify({route:result.route,attempts:result.attempts}).includes('proxy.invalid'));
  assert.ok(!JSON.stringify(result).includes('fixture-secret'));
  assert.equal((await probePreviewNetwork(options,transport)).ok,true);
  assert.deepEqual(seen.map(call=>call.env.HTTPS_PROXY),[proxy,'','']);
});
test('preview trust file merges default, extra and system roots through updater certificate reader',async t=>{
  const options=await previewOptions(t), calls=[];
  const extra=await fs.readFile(new URL('untrusted.pem',fixture),'utf8');
  options.certificateReader=type=>{calls.push(type);return type==='default'?[ca,extra]:[extra,ca];};
  const result=await probePreviewNetwork(options,async()=>({stdout:'fixture refs/heads/main'}));
  assert.equal(result.ok,true);assert.deepEqual(calls,['default','system']);
  assert.equal(await fs.readFile(options.caFile,'utf8'),ca+'\n'+extra+'\n');
  assert.equal(result.environment.GIT_SSL_CAINFO,options.caFile);
  assert.equal(result.environment.NODE_EXTRA_CA_CERTS,options.caFile);
});
test('preview environments replace conflicting proxy and TLS settings while preserving unrelated configuration',()=>{
  const base={PATH:'python-dir',npm_config_registry:'https://npm.example.test',ALL_PROXY:'socks5://old.invalid',all_proxy:'old',NO_PROXY:'old',npm_proxy:'old',PIP_PROXY:'old',GIT_SSL_NO_VERIFY:'1',NODE_TLS_REJECT_UNAUTHORIZED:'0',GIT_CONFIG_COUNT:'1',GIT_CONFIG_KEY_0:'core.autocrlf',GIT_CONFIG_VALUE_0:'true'};
  const env=previewEnvironment(base,'http://proxy.invalid:8080','fixture-ca.pem');
  for(const name of ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy','PIP_PROXY','npm_config_proxy','npm_config_https_proxy'])assert.equal(env[name],'http://proxy.invalid:8080');
  assert.equal(env.NO_PROXY,'');assert.equal(env.no_proxy,'');assert.equal(env.npm_config_noproxy,'');
  assert.equal(env.npm_proxy,undefined);assert.equal(env.GIT_SSL_NO_VERIFY,undefined);assert.equal(env.NODE_TLS_REJECT_UNAUTHORIZED,undefined);
  assert.equal(env.npm_config_strict_ssl,'true');assert.equal(env.GIT_CONFIG_COUNT,'9');
  assert.equal(env.PIP_TRUSTED_HOST,' ');assert.equal(env.UMEKO_PREVIEW_DIRECT,'0');
  assert.equal(env.GIT_CONFIG_KEY_0,'core.autocrlf');assert.equal(env.GIT_CONFIG_VALUE_0,'true');
  assert.equal(env.GIT_CONFIG_KEY_1,'http.proxy');assert.equal(env.GIT_CONFIG_VALUE_1,'http://proxy.invalid:8080');
  assert.equal(env.GIT_CONFIG_KEY_2,'http.sslVerify');assert.equal(env.GIT_CONFIG_VALUE_2,'true');
  assert.equal(env.GIT_CONFIG_KEY_3,'http.proxySSLVerify');assert.equal(env.GIT_CONFIG_VALUE_3,'true');
  assert.equal(env.GIT_CONFIG_KEY_6,'http.schannelUseSSLCAInfo');assert.equal(env.GIT_CONFIG_VALUE_6,'true');
  assert.equal(env.GIT_CONFIG_KEY_7,'http.https://github.com/umeiko/umeko-desktop.git.proxy');
  assert.equal(env.GIT_CONFIG_KEY_8,'http.https://github.com/umeiko/umeko-desktop.git.sslVerify');assert.equal(env.GIT_CONFIG_VALUE_8,'true');
  for(const name of ['SSL_CERT_FILE','REQUESTS_CA_BUNDLE','CURL_CA_BUNDLE','PIP_CERT','npm_config_cafile','NODE_EXTRA_CA_CERTS','GIT_SSL_CAINFO','GIT_PROXY_SSL_CAINFO'])assert.equal(env[name],'fixture-ca.pem');
  assert.equal(env.PATH,base.PATH);assert.equal(env.npm_config_registry,base.npm_config_registry);
  const direct=previewEnvironment(base,'','fixture-ca.pem');
  assert.equal(direct.HTTPS_PROXY,'');assert.equal(direct.ALL_PROXY,'');assert.equal(direct.PIP_PROXY,'');assert.equal(direct.NO_PROXY,'*');assert.equal(direct.npm_config_noproxy,'*');
  assert.equal(direct.UMEKO_PREVIEW_DIRECT,'1');
  assert.equal(direct.npm_config_proxy,'null');assert.equal(direct.npm_config_https_proxy,'null');
  assert.equal(direct.UMEKO_UPDATE_PROXY,'');assert.equal(env.UMEKO_UPDATE_PROXY,'http://proxy.invalid:8080');
});
test('preview direct route clears a configured npm proxy without changing its file',async t=>{
  const {execFile}=await import('node:child_process');
  const {promisify}=await import('node:util');
  const options=await previewOptions(t);
  const userconfig=path.join(path.dirname(options.caFile),'npmrc');
  const globalconfig=path.join(path.dirname(options.caFile),'global-npmrc');
  const original='https-proxy=http://stale.invalid:8080\nproxy=http://stale.invalid:8080\n';
  await fs.writeFile(userconfig,original);await fs.writeFile(globalconfig,'');
  const env=previewEnvironment({...process.env,NPM_CONFIG_USERCONFIG:userconfig,NPM_CONFIG_GLOBALCONFIG:globalconfig},'',options.caFile);
  // This only reads npm's parsed configuration, without a registry request.
  const command=process.platform==='win32'?[process.env.ComSpec || 'cmd.exe',['/d','/c','npm.cmd config get https-proxy']]:['npm',['config','get','https-proxy']];
  const result=await promisify(execFile)(...command,{env,cwd:path.dirname(options.caFile),windowsHide:true});
  assert.equal(result.stdout.trim(),'null');
  assert.equal(await fs.readFile(userconfig,'utf8'),original);
});
test('preview failures classify certificate, proxy, DNS, timeout and other without raw diagnostics',()=>{
  const cases=[
    ['fatal: unable to access https://secret.invalid: SSL certificate problem: unable to get local issuer certificate','certificate','UNABLE_TO_GET_ISSUER_CERT_LOCALLY'],
    ['pip SSLError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed','certificate','UNABLE_TO_GET_ISSUER_CERT_LOCALLY'],
    ['npm ERR! code SELF_SIGNED_CERT_IN_CHAIN: self signed certificate in certificate chain','certificate','SELF_SIGNED_CERT_IN_CHAIN'],
    ['urllib.error.URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed>','certificate','UNABLE_TO_GET_ISSUER_CERT_LOCALLY'],
    ['fatal: Received HTTP code 407 from proxy after CONNECT user:secret@private.invalid','proxy','PROXY'],
    ['fatal: Could not resolve host: private.invalid','dns','ENOTFOUND'],
    ['npm ERR! network request to https://private.invalid failed, reason: connect ETIMEDOUT','timeout','ETIMEDOUT'],
    ['fatal: not a git repository private.invalid secret','other','PREVIEW_NETWORK'],
  ];
  for(const [raw,category,code] of cases){const result=classifyPreviewFailure(raw);assert.equal(result.category,category);assert.equal(result.code,code);assert.ok(!JSON.stringify(result).includes('private.invalid'));assert.ok(!JSON.stringify(result).includes('secret'));}
});
test('preview skips unsupported SOCKS and HTTPS proxies before selecting direct',async t=>{
  for(const proxy of ['socks5://user:fixture-secret@private.invalid:1080','https://user:fixture-secret@private.invalid:8443']){
    const options=await previewOptions(t,{UMEKO_UPDATE_PROXY:proxy}), seen=[];
    const result=await probePreviewNetwork(options,async call=>{seen.push(call.env.HTTPS_PROXY);return 'fixture refs/heads/main';});
    assert.equal(result.ok,true);assert.deepEqual(seen,['']);
    assert.deepEqual(result.attempts[0],{route:'系统代理',category:'proxy',code:'PREVIEW_PROXY_UNSUPPORTED'});
    assert.ok(!JSON.stringify(result).includes('private.invalid'));assert.ok(!JSON.stringify(result).includes('fixture-secret'));
  }
});
test('preview retains certificate precedence, refuses proxy authentication fallback, and rejects unusable helpers',async t=>{
  const options=await previewOptions(t,{UMEKO_UPDATE_PROXY:'http://private.invalid:8080'});let calls=0;
  const certificate=await probePreviewNetwork(options,async()=>{if(++calls===1)throw Error('SSL certificate problem: unable to get local issuer certificate private.invalid');throw Object.assign(Error('direct failed'),{code:'ENOTFOUND'});});
  assert.equal(certificate.ok,false);assert.equal(certificate.category,'certificate');assert.equal(certificate.attempts.length,2);
  calls=0;
  const auth=await probePreviewNetwork(options,async()=>{calls++;throw Error('CONNECT tunnel failed, response 407');});
  assert.equal(auth.category,'proxy');assert.equal(auth.proxyStatus,407);assert.equal(calls,1);
  const noGit=await probePreviewNetwork({...options,proxy:''},async()=>{throw Object.assign(Error('missing'),{code:'ENOENT'});});
  assert.equal(noGit.code,'PREVIEW_HELPER_UNAVAILABLE');
  const empty=await probePreviewNetwork({...options,proxy:''},async()=>({stdout:''}));
  assert.equal(empty.code,'PREVIEW_EMPTY_RESULT');
  const invalid=await probePreviewNetwork({...options,certificateReader:()=>['invalid CA']},async()=>{throw Error('must not run');});
  assert.equal(invalid.category,'certificate');assert.equal(invalid.code,'PREVIEW_CA_INVALID');assert.deepEqual(invalid.attempts,[]);
});
