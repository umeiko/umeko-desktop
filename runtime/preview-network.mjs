// Private child-process network settings shared with the verified updater routes.
// No machine settings, package-manager config files, or trust stores are changed.
import fs from 'node:fs/promises';
import {spawn} from 'node:child_process';
import {X509Certificate} from 'node:crypto';
import {withUpdateRoutes, updateCertificates} from './update-engine.mjs';

const UPSTREAM='https://github.com/umeiko/umeko-desktop.git';
const CERTIFICATE_CODES=['SELF_SIGNED_CERT_IN_CHAIN','DEPTH_ZERO_SELF_SIGNED_CERT','UNABLE_TO_GET_ISSUER_CERT_LOCALLY','UNABLE_TO_VERIFY_LEAF_SIGNATURE','CERT_HAS_EXPIRED','CERT_NOT_YET_VALID','ERR_TLS_CERT_ALTNAME_INVALID','CERT_REVOKED'];
const CONNECTION_CODES=['ECONNRESET','ECONNREFUSED','EHOSTUNREACH','ENETUNREACH','ERR_SSL_WRONG_VERSION_NUMBER','ERR_SSL_PACKET_LENGTH_TOO_LONG'];
const SAFE_CODES=new Set([...CERTIFICATE_CODES,...CONNECTION_CODES,'ENOTFOUND','EAI_AGAIN','ETIMEDOUT','PROXY','PREVIEW_PROXY_UNSUPPORTED','PREVIEW_CA_INVALID','PREVIEW_HELPER_UNAVAILABLE','PREVIEW_EMPTY_RESULT','PREVIEW_CANCELLED','PREVIEW_NETWORK']);

// Only stable categories and codes leave the helper. Git/npm/pip diagnostics can
// contain proxy credentials and host names, so raw text never becomes UI data.
export function classifyPreviewFailure(raw) {
  const text=typeof raw==='string'?raw:[raw?.message,raw?.stderr,raw?.stdout].filter(Boolean).join('\n');
  const code=typeof raw?.code==='string'?raw.code:'';
  if(CERTIFICATE_CODES.includes(code))return {category:'certificate',code};
  const certificateCode=CERTIFICATE_CODES.find(value=>text.includes(value));
  if(certificateCode)return {category:'certificate',code:certificateCode};
  if(code==='PREVIEW_CA_INVALID')return {category:'certificate',code};
  if(/certificate.*(?:expired|not yet valid)|CERT_HAS_EXPIRED|CERT_NOT_YET_VALID/i.test(text))return {category:'certificate',code:'CERT_HAS_EXPIRED'};
  if(/certificate.*(?:host.?name|does not match|mismatch)|no alternative certificate subject name/i.test(text))return {category:'certificate',code:'ERR_TLS_CERT_ALTNAME_INVALID'};
  if(/CERTIFICATE_VERIFY_FAILED|certificate verify failed|unable to (?:get|verify).*(?:issuer|certificate)|self[- ]signed certificate|server certificate verification failed|SSL (?:peer )?certificate.*(?:cannot|problem|invalid)|CERT_TRUST_|SEC_E_UNTRUSTED_ROOT|schannel.*(?:certificate|trust)/i.test(text))return {category:'certificate',code:'UNABLE_TO_GET_ISSUER_CERT_LOCALLY'};
  if(code==='PREVIEW_PROXY_UNSUPPORTED')return {category:'proxy',code};
  const status=Number(raw?.proxyStatus) || Number(text.match(/(?:proxy[^\n]*?|CONNECT[^\n]*?|tunnel[^\n]*?)(407|502|503|504)\b/i)?.[1]) || Number(text.match(/HTTP code (407|502|503|504)[^\n]*(?:proxy|CONNECT)/i)?.[1]);
  if(status && [407,502,503,504].includes(status))return {category:'proxy',code:'PROXY',proxyStatus:status};
  if(['ENOTFOUND','EAI_AGAIN'].includes(code)||/ENOTFOUND|EAI_AGAIN|could not resolve (?:host|proxy)|name or service not known|temporary failure in name resolution|nodename nor servname|NameResolutionError|(?:getaddrinfo|hostname).*failed/i.test(text))return {category:'dns',code:code==='EAI_AGAIN'?'EAI_AGAIN':'ENOTFOUND'};
  if(code==='ETIMEDOUT'||/ETIMEDOUT|timed?\s*out|timeout|ReadTimeout|ConnectTimeout/i.test(text))return {category:'timeout',code:'ETIMEDOUT'};
  if(CONNECTION_CODES.includes(code))return {category:'other',code};
  if(/ECONNRESET|connection (?:was )?reset/i.test(text))return {category:'other',code:'ECONNRESET'};
  if(/ECONNREFUSED|connection refused|could(?:n't| not) connect to server|failed to connect to/i.test(text))return {category:/proxy/i.test(text)?'proxy':'other',code:'ECONNREFUSED'};
  if(code==='PROXY'||/ProxyError|proxy authentication|proxy connect|unsupported proxy|tunnel connection failed/i.test(text))return {category:'proxy',code:'PROXY'};
  return {category:'other',code:SAFE_CODES.has(code)?code:'PREVIEW_NETWORK'};
}

const removedNames=['http_proxy','https_proxy','all_proxy','no_proxy','npm_proxy','pip_proxy','pip_trusted_host','npm_config_proxy','npm_config_https_proxy','npm_config_noproxy','npm_config_cafile','npm_config_strict_ssl','ssl_cert_file','requests_ca_bundle','curl_ca_bundle','pip_cert','node_extra_ca_certs','node_tls_reject_unauthorized','git_ssl_no_verify','git_ssl_cainfo','git_proxy_ssl_cainfo'];
function environmentSettings(base,proxy,caFile) {
  const environment={...base}, overrides={};
  for(const key of Object.keys(environment))if(removedNames.includes(key.toLowerCase()))delete environment[key];
  const put=(key,value)=>{environment[key]=overrides[key]=value;};
  for(const name of ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']){put(name,proxy);put(name.toLowerCase(),proxy);}
  put('UMEKO_UPDATE_PROXY',proxy);
  put('NO_PROXY',proxy?'':'*');put('no_proxy',proxy?'':'*');
  // npm ignores empty env values too. Its typed null clears .npmrc proxies.
  for(const name of ['npm_config_proxy','npm_config_https_proxy'])put(name,proxy || 'null');
  put('PIP_PROXY',proxy);
  put('UMEKO_PREVIEW_DIRECT',proxy?'0':'1');
  // pip skips empty environment values; whitespace explicitly empties its
  // append-style trusted-host list instead of inheriting a verification bypass.
  put('PIP_TRUSTED_HOST',' ');
  put('npm_config_noproxy',proxy?'':'*');put('npm_config_strict_ssl','true');
  for(const name of ['SSL_CERT_FILE','REQUESTS_CA_BUNDLE','CURL_CA_BUNDLE','PIP_CERT','npm_config_cafile','NODE_EXTRA_CA_CERTS','GIT_SSL_CAINFO','GIT_PROXY_SSL_CAINFO'])put(name,caFile);
  // Command-scope Git settings override inherited generic file settings without
  // writing ~/.gitconfig. Keep unrelated existing command-scope settings.
  const countKey=Object.keys(environment).find(key=>key.toUpperCase()==='GIT_CONFIG_COUNT');
  const count=Number(countKey?environment[countKey]:0);
  if(!Number.isSafeInteger(count)||count<0||count>10000)throw Object.assign(Error('Invalid Git environment'),{code:'PREVIEW_HELPER_UNAVAILABLE'});
  if(countKey && countKey!=='GIT_CONFIG_COUNT')delete environment[countKey];
  const settings=[['http.proxy',proxy],['http.sslVerify','true'],['http.proxySSLVerify','true'],['http.sslCAInfo',caFile],['http.proxySSLCAInfo',caFile],['http.schannelUseSSLCAInfo','true'],[`http.${UPSTREAM}.proxy`,proxy],[`http.${UPSTREAM}.sslVerify`,'true']];
  settings.forEach(([key,value],index)=>{put(`GIT_CONFIG_KEY_${count+index}`,key);put(`GIT_CONFIG_VALUE_${count+index}`,value);});
  put('GIT_CONFIG_COUNT',String(count+settings.length));
  return {environment,overrides,removeEnvironment:[...removedNames,'git_config_count']};
}
export function previewEnvironment(base,proxy,caFile) {
  return environmentSettings(base,proxy,caFile).environment;
}

async function commandTransport({command,args,env,signal}) {
  return new Promise((resolve,reject)=>{
    const child=spawn(command,args,{env,windowsHide:true,stdio:['ignore','pipe','pipe'],signal});
    let stdout='',stderr='';
    const bounded=(current,chunk)=>(current+chunk.toString()).slice(-65536);
    child.stdout.on('data',chunk=>{stdout=bounded(stdout,chunk);});
    child.stderr.on('data',chunk=>{stderr=bounded(stderr,chunk);});
    let timedOut=false;
    const timer=setTimeout(()=>{timedOut=true;child.kill();},60000);
    child.on('error',error=>{clearTimeout(timer);reject(error);});
    child.on('close',code=>{
      clearTimeout(timer);
      if(timedOut)reject(Object.assign(Error('Preview request timed out'),{code:'ETIMEDOUT'}));
      else if(code===0)resolve({stdout});
      else reject(Object.assign(Error('Preview request failed'),{stdout,stderr}));
    });
  });
}

export async function probePreviewNetwork(options={},transport=options.transport || commandTransport) {
  const base=options.environment || process.env, attempts=[], network=options.network || {};
  const cancelled=()=>options.signal?.aborted || options.cancelled?.();
  try {
    if(cancelled())throw Object.assign(Error('Cancelled'),{code:'PREVIEW_CANCELLED'});
    const certificates=updateCertificates(options.certificateReader);
    if(!certificates.length)throw Error('Empty CA bundle');
    for(const certificate of certificates)new X509Certificate(certificate);
    if(!options.caFile)throw Error('Missing CA file');
    await fs.writeFile(options.caFile,certificates.join('\n')+'\n',{mode:0o600});
    await fs.chmod(options.caFile,0o600);
  } catch(error) {
    return {ok:false,category:error.code==='PREVIEW_CANCELLED'?'other':'certificate',code:error.code==='PREVIEW_CANCELLED'?'PREVIEW_CANCELLED':'PREVIEW_CA_INVALID',attempts};
  }
  try {
    const selected=await withUpdateRoutes(async proxy=>{
      const route=proxy?'系统代理':'直连';
      try {
        if(cancelled())throw Object.assign(Error('Cancelled'),{code:'PREVIEW_CANCELLED'});
        // urllib cannot share SOCKS or TLS-to-proxy transports. A successful Git
        // probe on those routes would incorrectly promise Python download access.
        if(proxy){let protocol;try{protocol=new URL(proxy).protocol;}catch{}
          if(protocol!=='http:')throw Object.assign(Error('Unsupported preview proxy'),{code:'PREVIEW_PROXY_UNSUPPORTED',routeUnavailable:true});}
        const settings=environmentSettings(base,proxy,options.caFile);
        const result=await transport({command:options.git || 'git',args:['ls-remote','--exit-code',UPSTREAM,'refs/heads/main'],env:settings.environment,signal:options.signal});
        if(cancelled())throw Object.assign(Error('Cancelled'),{code:'PREVIEW_CANCELLED'});
        const output=typeof result==='string'?result:result?.stdout;
        if(!output?.trim())throw Object.assign(Error('Empty Git result'),{code:'PREVIEW_EMPTY_RESULT'});
        attempts.push({route,code:'OK'});
        return {ok:true,route,environment:settings.overrides,removeEnvironment:settings.removeEnvironment,attempts};
      } catch(error) {
        if(error.code==='ENOENT')error=Object.assign(Error('Git unavailable'),{code:'PREVIEW_HELPER_UNAVAILABLE'});
        const failure=classifyPreviewFailure(error);
        attempts.push({route,...failure});
        throw Object.assign(Error('Preview network failed'),failure,{routeUnavailable:!!error.routeUnavailable});
      }
    },{environment:base,network,signal:options.signal,...(options.proxy!==undefined?{proxy:options.proxy}:{})});
    return selected;
  } catch(error) {return {ok:false,...classifyPreviewFailure(error),attempts};}
}

if(import.meta.main) {
  let result;
  try {
    const [mode,file]=process.argv.slice(2);
    if(mode==='probe')result=await probePreviewNetwork({caFile:file});
    else if(mode==='classify'){
      let raw='';
      if(file)raw=await fs.readFile(file,'utf8');
      else for await(const chunk of process.stdin){raw+=chunk;if(raw.length>65536)break;}
      result=classifyPreviewFailure(raw);
    } else result={ok:false,category:'other',code:'PREVIEW_HELPER_UNAVAILABLE',attempts:[]};
  } catch {result={ok:false,category:'other',code:'PREVIEW_HELPER_UNAVAILABLE',attempts:[]};}
  process.stdout.write(JSON.stringify(result)+'\n');
}
