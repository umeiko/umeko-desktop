// Private child-process network settings shared with the verified updater routes.
// No machine settings, package-manager config files, or trust stores are changed.
import fs from 'node:fs/promises';
import path from 'node:path';
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

const removedNames=['http_proxy','https_proxy','all_proxy','npm_proxy','pip_proxy','npm_config_proxy','npm_config_https_proxy'];
const caNames=['ssl_cert_file','requests_ca_bundle','curl_ca_bundle','pip_cert','node_extra_ca_certs','git_ssl_cainfo','git_proxy_ssl_cainfo','npm_config_cafile'];
function environmentSettings(base,proxy,caFile,toolTrust={}) {
  const environment={...base}, overrides={};
  for(const key of Object.keys(environment))if(removedNames.includes(key.toLowerCase()))delete environment[key];
  const put=(key,value)=>{
    for(const existing of Object.keys(environment))if(existing.toLowerCase()===key.toLowerCase())environment[existing]=overrides[existing]=value;
    environment[key]=overrides[key]=value;
  };
  for(const name of ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']){put(name,proxy);put(name.toLowerCase(),proxy);}
  put('UMEKO_UPDATE_PROXY',proxy);
  if(!proxy){
    // urllib and other inherited clients need '*' to ignore stale native proxy
    // settings on the selected direct route. Keep every existing bypass entry.
    for(const name of ['NO_PROXY','no_proxy','npm_config_noproxy']){
      const existing=Object.keys(base).filter(key=>key.toLowerCase()===name.toLowerCase()).map(key=>base[key]).filter(Boolean).join(',');
      const value=existing.split(/[\s,]+/).includes('*')?existing:[existing,'*'].filter(Boolean).join(',');
      put(name,value);
    }
  }
  // npm ignores empty env values too. Its typed null clears .npmrc proxies.
  for(const name of ['npm_config_proxy','npm_config_https_proxy'])put(name,proxy || 'null');
  put('PIP_PROXY',proxy);
  put('UMEKO_PREVIEW_DIRECT',proxy?'0':'1');
  // Only add trust; verification flags and native indexes/registries stay intact.
  for(const name of ['SSL_CERT_FILE','REQUESTS_CA_BUNDLE','CURL_CA_BUNDLE','NODE_EXTRA_CA_CERTS'])put(name,caFile);
  if(toolTrust.pip)put('PIP_CERT',caFile);
  if(toolTrust.npm)put('npm_config_cafile',caFile);
  if(toolTrust.git)for(const name of ['GIT_SSL_CAINFO','GIT_PROXY_SSL_CAINFO'])put(name,caFile);
  // Command-scope Git settings override inherited generic file settings without
  // writing ~/.gitconfig. Keep unrelated existing command-scope settings.
  const countKey=Object.keys(environment).find(key=>key.toUpperCase()==='GIT_CONFIG_COUNT');
  const count=Number(countKey?environment[countKey]:0);
  if(!Number.isSafeInteger(count)||count<0||count>10000)throw Object.assign(Error('Invalid Git environment'),{code:'PREVIEW_HELPER_UNAVAILABLE'});
  if(countKey && countKey!=='GIT_CONFIG_COUNT')delete environment[countKey];
  const settings=[['http.proxy',proxy],[`http.${UPSTREAM}.proxy`,proxy]];
  settings.forEach(([key,value],index)=>{put(`GIT_CONFIG_KEY_${count+index}`,key);put(`GIT_CONFIG_VALUE_${count+index}`,value);});
  put('GIT_CONFIG_COUNT',String(count+settings.length));
  return {environment,overrides,removeEnvironment:[...removedNames,'git_config_count']};
}
export function previewEnvironment(base,proxy,caFile,toolTrust={}) {
  return environmentSettings(base,proxy,caFile,toolTrust).environment;
}

async function commandTransport({command,args,env,signal,cwd,timeout=60000}) {
  return new Promise((resolve,reject)=>{
    const child=spawn(command,args,{env,cwd,windowsHide:true,stdio:['ignore','pipe','pipe'],signal});
    let stdout='',stderr='',truncated=false;
    const bounded=(current,chunk)=>{const value=current+chunk.toString();if(value.length>65536)truncated=true;return value.slice(-65536);};
    child.stdout.on('data',chunk=>{stdout=bounded(stdout,chunk);});
    child.stderr.on('data',chunk=>{stderr=bounded(stderr,chunk);});
    let timedOut=false;
    const timer=setTimeout(()=>{timedOut=true;child.kill();},timeout);
    child.on('error',error=>{clearTimeout(timer);reject(error);});
    child.on('close',code=>{
      clearTimeout(timer);
      if(timedOut)reject(Object.assign(Error('Preview request timed out'),{code:'ETIMEDOUT'}));
      else if(code===0)resolve({stdout,truncated});
      else reject(Object.assign(Error('Preview request failed'),{stdout,stderr,exitCode:code}));
    });
  });
}

// pip prints Python repr values, including escaped Windows paths. Let Python
// decode them with literal_eval rather than guessing or evaluating tool output.
const pipCaQuery=String.raw`import ast,json,os,subprocess,sys
r=subprocess.run([sys.executable,'-m','pip','config','list'],capture_output=True,text=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
if r.returncode: sys.exit(1)
paths=[]
for line in r.stdout.splitlines():
    key,sep,value=line.partition('=')
    if sep and key.endswith('.cert'):
        value=ast.literal_eval(value)
        if not isinstance(value,str): sys.exit(1)
        paths.append(value)
print(json.dumps(paths))`;

async function nativeTrust(options,base) {
  const query=options.queryTransport || commandTransport;
  const run=async(command,args,absent=false)=>{
    try{const result=await query({command,args,env:base,cwd:options.cwd,signal:options.signal,timeout:15000});
      if(result.truncated)throw Error('Incomplete tool config');return result.stdout;}
    catch(error){if(absent && error.exitCode===1 && !error.stdout && !error.stderr)return '';throw error;}
  };
  const npm=args=>process.platform==='win32'
    ?run(base.ComSpec || base.COMSPEC || 'cmd.exe',['/d','/c',`npm.cmd --prefix runtime config get ${args}`])
    :run('npm',['--prefix','runtime','config','get',...args.split(' ')]);
  const [pip,npmTrust,git]=await Promise.allSettled([
    (async()=>{const paths=JSON.parse(await run(options.python || (process.platform==='win32'?'python':'python3'),['-c',pipCaQuery]));
      if(!Array.isArray(paths)||!paths.every(value=>typeof value==='string'))throw Error('Invalid pip config');return {paths};})(),
    (async()=>{const [file,raw]=await Promise.all([npm('cafile'),npm('ca --json')]);
      const value=JSON.parse(raw), certificates=value===null?[]:Array.isArray(value)?value:[value];
      if(!certificates.every(value=>typeof value==='string'))throw Error('Invalid npm config');
      const configured=file.replace(/\r?\n$/,'');
      return {paths:configured==='null'?[]:[configured],certificates};})(),
    (async()=>({paths:await Promise.all([
      run(options.git || 'git',['config','--get','http.sslCAInfo'],true),
      run(options.git || 'git',['config','--get-urlmatch','http.sslCAInfo',UPSTREAM],true),
      run(options.git || 'git',['config','--get','http.proxySSLCAInfo'],true),
    ]).then(values=>values.map(value=>value.replace(/\r?\n$/,'')))}))(),
  ]);
  const paths=Object.entries(base).filter(([key])=>caNames.includes(key.toLowerCase())).map(([,value])=>value);
  const certificates=[], toolTrust={};
  for(const [name,result] of [['pip',pip],['npm',npmTrust],['git',git]]){
    toolTrust[name]=result.status==='fulfilled';
    if(toolTrust[name]){paths.push(...result.value.paths);certificates.push(...result.value.certificates || []);}
  }
  for(const file of new Set(paths.filter(Boolean))){
    // Missing/unreadable configured files are deliberately silent. A failed
    // tool query, however, leaves that tool's CA override completely untouched.
    try{certificates.push(await fs.readFile(path.resolve(options.cwd || '.',file),'utf8'));}catch{}
  }
  return {certificates,toolTrust};
}

export async function probePreviewNetwork(options={},transport=options.transport || commandTransport) {
  const base=options.environment || process.env, attempts=[], network=options.network || {};
  const cancelled=()=>options.signal?.aborted || options.cancelled?.();
  let toolTrust;
  try {
    if(cancelled())throw Object.assign(Error('Cancelled'),{code:'PREVIEW_CANCELLED'});
    const certificates=updateCertificates(options.certificateReader);
    if(!certificates.length)throw Error('Empty CA bundle');
    for(const certificate of certificates)new X509Certificate(certificate);
    if(!options.caFile)throw Error('Missing CA file');
    const native=await nativeTrust(options,base);
    toolTrust=native.toolTrust;
    await fs.writeFile(options.caFile,[...certificates,...native.certificates].join('\n')+'\n',{mode:0o600});
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
        const settings=environmentSettings(base,proxy,options.caFile,toolTrust);
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
    const [mode,file,configuration]=process.argv.slice(2);
    if(mode==='probe')result=await probePreviewNetwork({...(configuration?JSON.parse(await fs.readFile(configuration,'utf8')):{}),caFile:file});
    else if(mode==='classify'){
      let raw='';
      if(file)raw=await fs.readFile(file,'utf8');
      else for await(const chunk of process.stdin){raw+=chunk;if(raw.length>65536)break;}
      result=classifyPreviewFailure(raw);
    } else result={ok:false,category:'other',code:'PREVIEW_HELPER_UNAVAILABLE',attempts:[]};
  } catch {result={ok:false,category:'other',code:'PREVIEW_HELPER_UNAVAILABLE',attempts:[]};}
  process.stdout.write(JSON.stringify(result)+'\n');
}
