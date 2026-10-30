/**
 * Adapted from pi-marketplace@0.1.3 (MIT), Copyright (c) 2026 507.
 * Upstream: https://registry.npmjs.org/pi-marketplace/-/pi-marketplace-0.1.3.tgz
 * See marketplace-LICENSE.txt for the retained MIT notice.
 * Desktop delta: configured registry/CA transport, exact-name fallback, pinned
 * versions, direct tarball source scan, structured output.
 */
import {execFile} from 'node:child_process';
import {readFile,mkdtemp,rm,readdir} from 'node:fs/promises';
import {Readable,Transform} from 'node:stream';
import {pipeline} from 'node:stream/promises';
import {createGunzip} from 'node:zlib';
import {setImmediate as yieldScan} from 'node:timers/promises';
import {existsSync} from 'node:fs';
import {join,relative,dirname,resolve,posix,win32} from 'node:path';
import {tmpdir} from 'node:os';
import {EnvHttpProxyAgent,fetch as undiciFetch} from 'undici';
import * as tar from 'tar';

// Per archive: compressed input, decoded tar bytes (including headers/padding),
// and physical entries (including metadata). No archive is buffered whole.
// Limits apply before writing.
// 2026-10-30: all 20 results on npm's first keywords:pi-package search page
// completed source scans within these limits (largest download 15,221,332 bytes;
// largest declared unpacked size 52,058,316 bytes; largest file count 1,241).
export const ARCHIVE_LIMITS = Object.freeze({compressedBytes:32*1024*1024,entries:20000,expandedBytes:128*1024*1024});
// Per cache, not per item: settled JSON UTF-8 bytes plus key/entry overhead;
// pending promises reserve overhead and still count toward the entry limit.
export const CACHE_LIMITS = Object.freeze({maxEntries:64,maxBytes:8*1024*1024,ttlMs:5*60*1000});
export function createBoundedCache({maxEntries=CACHE_LIMITS.maxEntries,maxBytes=CACHE_LIMITS.maxBytes,ttlMs=CACHE_LIMITS.ttlMs,now=Date.now}={}) {
 const items=new Map();let bytes=0;
 function remove(key){const item=items.get(key);if(item){bytes-=item.bytes;items.delete(key);}}
 function prune(){for(const [key,item] of items)if(now()>=item.expires)remove(key);}
 function trim(){while(items.size>maxEntries||bytes>maxBytes)remove(items.keys().next().value);}
 function get(key){prune();const item=items.get(key);if(item){items.delete(key);items.set(key,item);}return item?.value;}
 function set(key,value){
  prune();remove(key);const overhead=Buffer.byteLength(String(key),'utf8')+64;
  const item={value,bytes:overhead,expires:now()+ttlMs};
  if(!(value instanceof Promise))item.bytes+=Buffer.byteLength(JSON.stringify(value)??'null','utf8');
  items.set(key,item);bytes+=item.bytes;trim();
  if(value instanceof Promise)value.then(resolved=>{
   if(items.get(key)!==item)return;
   bytes-=item.bytes;item.bytes=overhead+Buffer.byteLength(JSON.stringify(resolved)??'null','utf8');bytes+=item.bytes;trim();
  },()=>{if(items.get(key)===item)remove(key);});
  return value;
 }
 return {get,set,delete:remove,clear(){items.clear();bytes=0;},
  getOrCreate(key,loader){const cached=get(key);return cached===undefined?set(key,Promise.resolve().then(loader)):cached;},
  stats(){prune();return {entries:items.size,bytes};}};
}
function checkCancelled(signal){signal?.throwIfAborted();}
function capError(kind,value){return new Error(`Archive ${kind} limit exceeded: ${value}${kind==='entry count'?' entries':' bytes'}`);}
function byteLimiter(kind,limit){let bytes=0;return new Transform({transform(chunk,_encoding,done){bytes+=chunk.length;done(bytes>limit?capError(kind,limit):null,bytes>limit?undefined:chunk);}});}
// Count physical tar headers too (PAX/long-name/ignored entries), before tar
// allocates metadata or creates files. Only a single 512-byte header is retained.
function entryLimiter(limit){let count=0,skip=0,used=0;const header=Buffer.alloc(512);
 return new Transform({transform(chunk,_encoding,done){try{
  let offset=0;while(offset<chunk.length){
   if(skip){const n=Math.min(skip,chunk.length-offset);skip-=n;offset+=n;continue;}
   const n=Math.min(512-used,chunk.length-offset);chunk.copy(header,used,offset,offset+n);used+=n;offset+=n;
   if(used===512){used=0;if(header.some(byte=>byte!==0)){
    if(++count>limit)throw capError('entry count',limit);
    const size=new tar.Header(header).size;
    if(!Number.isSafeInteger(size)||size<0)throw new Error('Archive contains an invalid entry size');
    skip=Math.ceil(size/512)*512;
   }}
  }done(null,chunk);
 }catch(error){done(error);}}});
}

function registryError(message,status=0,unsupported=false){return Object.assign(new Error(message),{status,unsupported});}
function runNode(args,cwd,env){return new Promise((resolve,reject)=>{
 execFile(process.execPath,args,{cwd,env,windowsHide:true,timeout:15000,maxBuffer:4*1024*1024},(error,stdout)=>{
  if(error)reject(new Error('Could not resolve npm configuration: '+error.message));else resolve(stdout);
 });
});}
export function resolveNpmCliPath({execPath=process.execPath,env=process.env,platform=process.platform,exists=existsSync}={}){
 const paths=platform==='win32'?win32:posix;
 const nodeDir=paths.dirname(execPath);
 const candidates=[env.npm_execpath,
  paths.join(nodeDir,'node_modules/npm/bin/npm-cli.js'),
  paths.join(nodeDir,'../lib/node_modules/npm/bin/npm-cli.js'),
  env.APPDATA&&paths.join(env.APPDATA,'npm/node_modules/npm/bin/npm-cli.js')].filter(Boolean);
 const found=candidates.find(candidate=>exists(candidate));if(!found)throw new Error('npm-cli.js not found for effective registry configuration');return found;
}

export function createRegistryClient({agent={},cwd=process.cwd(),fetch:injectedFetch,limits={},cacheOptions={}}={}) {
 const bounds={...ARCHIVE_LIMITS,...limits};
 let configured,dispatcher;const docCache=createBoundedCache(cacheOptions),detailCache=createBoundedCache(cacheOptions),auditCache=createBoundedCache(cacheOptions);
 async function configure(){return configured??=(async()=>{
  const env={...process.env};
  if(agent.npmRegistry)env.npm_config_registry=agent.npmRegistry;
  if(agent.npmUserconfig)env.npm_config_userconfig=agent.npmUserconfig;
  if(agent.npmCafile)env.npm_config_cafile=agent.npmCafile;
  const args=[resolveNpmCliPath(),'config','list','--json'];
  const config=JSON.parse(await runNode(args,cwd,env));
  NPM_REGISTRY=String(agent.npmRegistry||env.npm_config_registry||env.NPM_CONFIG_REGISTRY||config.registry||'https://registry.npmjs.org').replace(/\/$/,'');
  const cafile=agent.npmCafile||env.npm_config_cafile||env.NPM_CONFIG_CAFILE||config.cafile;
  const ca=cafile?await readFile(resolve(cwd,cafile),'utf8'):undefined;
  const rejectUnauthorized=config['strict-ssl']!==false;
  const tls={...(ca?{ca}:{}),rejectUnauthorized};
  const httpProxy=config.proxy||env.HTTP_PROXY||env.http_proxy||'';
  const httpsProxy=config['https-proxy']||config.proxy||env.HTTPS_PROXY||env.https_proxy||httpProxy;
  const noProxy=Array.isArray(config.noproxy)?config.noproxy.join(','):config.noproxy||env.NO_PROXY||env.no_proxy||'';
  dispatcher=new EnvHttpProxyAgent({httpProxy,httpsProxy,noProxy,connect:tls,requestTls:tls,proxyTls:tls});
  return {registry:NPM_REGISTRY,cafile:cafile||null};
 })().catch(error=>{configured=undefined;throw error;});}
 async function request(url,options={}){
  checkCancelled(options.signal);
  await configure();
  const signal=AbortSignal.any([AbortSignal.timeout(30000),...(options.signal?[options.signal]:[])]);
  checkCancelled(signal);
  return injectedFetch?injectedFetch(url,{...options,signal}):undiciFetch(url,{...options,dispatcher,signal});
 }
let NPM_REGISTRY = "https://registry.npmjs.org";

const DEFAULT_LIMIT = 20;
async function upstreamSearchPackages(query, options) {
    const limit = options?.limit ?? DEFAULT_LIMIT;
    const url = new URL(`${NPM_REGISTRY.replace(/\/$/, "")}/-/v1/search`);
    const searchText = [
        "keywords:pi-package",
        query.trim()
    ].filter(Boolean).join(" ");
    url.searchParams.set("text", searchText);
    url.searchParams.set("size", String(Math.min(limit, 250)));
    const res = await request(url.toString(), {
        signal:options?.signal,
        headers: {
            Accept: "application/json"
        }
    });
    if (!res.ok) throw registryError(`npm registry search failed: HTTP ${res.status}`, res.status);
    let data; try { data = await res.json(); } catch { throw registryError("Registry returned invalid search JSON", 0, true); }
    if (!data || !Array.isArray(data.objects) || data.objects.some(obj => !obj?.package || typeof obj.package.name !== "string")) throw registryError("Registry returned a non-search response", 0, true);
  return data.objects.map((obj)=>({
            name: String(obj.package.name ?? ""),
            version: String(obj.package.version ?? "0.0.0"),
            description: String(obj.package.description ?? ""),
            keywords: Array.isArray(obj.package.keywords) ? obj.package.keywords : [],
            links: normalizeLinks(String(obj.package.name ?? ""), obj.package),
            publisher: normalizePublisher(obj.package.publisher),
            date: String(obj.package.date ?? ""),
            downloads: {
                monthly: Number(obj.downloads?.monthly ?? 0),
                weekly: Number(obj.downloads?.weekly ?? 0)
            },
            score: {
                final: Number(obj.score?.final ?? 0)
            }
        }));
}
async function upstreamGetPackageDetail(name, version, signal) {
    const data = await fetchRegistryDoc(name,signal);
    const latestName = version ?? getLatestVersionName(data);
    const latestVersion = latestName ? data.versions?.[latestName] : undefined;
    if (!latestVersion || !latestName) {
        throw new Error(`npm registry detail for ${name} did not contain a latest version`);
    }
    if (latestVersion.version !== latestName) throw new Error('Registry version metadata does not match the requested exact version');
    const maintainerSource = latestVersion.maintainers ?? data.maintainers;
    const date = data.time?.[latestName] ?? "";
    return {
        name: String(latestVersion.name ?? name),
        version: String(latestVersion.version ?? latestName),
        description: String(latestVersion.description ?? ""),
        keywords: Array.isArray(latestVersion.keywords) ? latestVersion.keywords : [],
        links: normalizeLinks(name, latestVersion, data),
        publisher: normalizePublisher(latestVersion._npmUser ?? data._npmUser ?? firstMaintainer(maintainerSource)),
        date,
        downloads: {
            monthly: 0,
            weekly: 0
        },
        score: {
            final: 0
        },
        license: latestVersion.license ?? "UNKNOWN",
        author: latestVersion.author,
        maintainers: normalizeMaintainers(maintainerSource),
        dependencies: latestVersion.dependencies,
        peerDependencies: latestVersion.peerDependencies,
        devDependencies: latestVersion.devDependencies,
        piManifest: latestVersion.pi ?? {},
        dist: {
            tarball: getString(latestVersion.dist?.tarball) ?? "",
            shasum: getString(latestVersion.dist?.shasum) ?? "",
            integrity: getString(latestVersion.dist?.integrity) ?? "",
            fileCount: Number(latestVersion.dist?.fileCount ?? 0),
            unpackedSize: Number(latestVersion.dist?.unpackedSize ?? 0)
        },
        flags: data.flags ?? latestVersion.flags
    };
}
async function getPkgPiManifest(name) {
    try {
        const data = await fetchRegistryDoc(name);
        const latestName = getLatestVersionName(data);
        if (!latestName) return {};
        return data.versions?.[latestName]?.pi ?? {};
    } catch  {
        return {};
    }
}
function inferPackageTypes(manifest) {
    const types = [];
    if (manifest.extensions?.length) types.push("extension");
    if (manifest.skills?.length) types.push("skill");
    if (manifest.prompts?.length) types.push("prompt");
    if (manifest.themes?.length) types.push("theme");
    return types;
}
async function upstreamFetchRegistryDoc(name,signal) {
    const res = await request(`${NPM_REGISTRY.replace(/\/$/, "")}/${encodeURIComponent(name)}`, {
        signal,
        headers: {
            Accept: "application/json"
        }
    });
    if (!res.ok) throw registryError(`npm registry detail failed for ${name}: HTTP ${res.status}`, res.status);
    return await res.json();
}
function getLatestVersionName(data) {
    const latest = data["dist-tags"]?.latest;
    if (latest && data.versions?.[latest]) return latest;
    const versionKeys = Object.keys(data.versions ?? {});
    return versionKeys.at(-1) ?? null;
}
function normalizeLinks(packageName, primary, fallback) {
    const primaryLinks = getLinksRecord(primary);
    const fallbackLinks = getLinksRecord(fallback);
    const homepage = getLinkValue(primaryLinks?.homepage) ?? getLinkValue(primary.homepage) ?? getLinkValue(fallbackLinks?.homepage) ?? getLinkValue(fallback?.homepage);
    const repository = getLinkValue(primaryLinks?.repository) ?? getLinkValue(primary.repository) ?? getLinkValue(fallbackLinks?.repository) ?? getLinkValue(fallback?.repository);
    const npm = getLinkValue(primaryLinks?.npm) ?? getLinkValue(fallbackLinks?.npm) ?? `https://www.npmjs.com/package/${encodeURIComponent(packageName)}`;
    return {
        npm,
        ...homepage ? {
            homepage
        } : {},
        ...repository ? {
            repository
        } : {}
    };
}
function normalizePublisher(value) {
    if (value && typeof value === "object") {
        const record = value;
        return {
            username: getString(record.username) ?? getString(record.name) ?? "unknown",
            ...getString(record.email) ? {
                email: getString(record.email)
            } : {}
        };
    }
    return {
        username: "unknown"
    };
}
function normalizeMaintainers(value) {
    if (!Array.isArray(value)) return [];
    return value.map((item)=>normalizePublisher(item)).filter((item)=>item.username !== "unknown");
}
function firstMaintainer(value) {
    return Array.isArray(value) ? value[0] : undefined;
}
function getLinksRecord(value) {
    const links = value?.links;
    return links && typeof links === "object" ? links : undefined;
}
function getLinkValue(value) {
    if (typeof value === "string") return value;
    if (value && typeof value === "object") {
        return getString(value.url);
    }
    return undefined;
}
function getString(value) {
    return typeof value === "string" ? value : undefined;
}

const DANGER_PATTERNS = [
    {
        pattern: /\brm\s+(-rf|--recursive)\s+/g,
        severity: "critical",
        description: "Recursive file deletion"
    },
    {
        pattern: /rimraf\s*\(/g,
        severity: "critical",
        description: "rimraf (recursive delete)"
    },
    {
        pattern: /fs\.unlink/g,
        severity: "critical",
        description: "File unlink/delete"
    },
    {
        pattern: /fs\.rmdir/g,
        severity: "critical",
        description: "Directory removal"
    },
    {
        pattern: /fs\.rm/g,
        severity: "critical",
        description: "fs.rm recursive delete"
    },
    {
        pattern: /eval\s*\(/g,
        severity: "high",
        description: "eval() dynamic code execution"
    },
    {
        pattern: /new\s+Function\s*\(/g,
        severity: "high",
        description: "Function() constructor"
    },
    {
        pattern: /execSync\s*\(/g,
        severity: "high",
        description: "Synchronous command execution"
    },
    {
        pattern: /exec\(\s*`/g,
        severity: "high",
        description: "Template literal in exec()"
    },
    {
        pattern: /spawn\s*\(/g,
        severity: "high",
        description: "Child process spawn"
    },
    {
        pattern: /process\.env/g,
        severity: "medium",
        description: "Environment variable access"
    },
    {
        pattern: /child_process/g,
        severity: "medium",
        description: "Child process module"
    },
    {
        pattern: /fetch\s*\(\s*http/gi,
        severity: "medium",
        description: "External HTTP request"
    },
    {
        pattern: /https?(?:Request|Agent)/gi,
        severity: "medium",
        description: "HTTP client usage"
    },
    {
        pattern: /chmod\s*\(/g,
        severity: "low",
        description: "File permission change"
    },
    {
        pattern: /chown\s*\(/g,
        severity: "low",
        description: "File ownership change"
    }
];
const IGNORED_DIRECTORIES = [
    "node_modules",
    ".git",
    ".cache",
    "coverage"
];
const SOURCE_EXTENSIONS = [
    ".ts",
    ".js",
    ".mjs",
    ".cjs"
];
function metadataCheck(detail) {
    const deps = detail.dependencies ?? {};
    const peerDeps = detail.peerDependencies ?? {};
    const types = [];
    if (detail.piManifest.extensions?.length) types.push("extension");
    if (detail.piManifest.skills?.length) types.push("skill");
    if (detail.piManifest.prompts?.length) types.push("prompt");
    if (detail.piManifest.themes?.length) types.push("theme");
    return {
        types,
        dependencyCount: Object.keys(deps).length,
        peerDependencyCount: Object.keys(peerDeps).length,
        fileCount: detail.dist.fileCount,
        unpackedSize: detail.dist.unpackedSize,
        isInsecure: (detail.flags?.insecure ?? 0) > 0,
        publishedAt: detail.date
    };
}
async function quickAudit(name) {
    const detail = await getPackageDetail(name);
    return buildReport(name, detail.version, metadataCheck(detail), [], false);
}
async function sourceScan(detail,signal) {
  checkCancelled(signal);
  const findings = [];
  const tmpDir = await mkdtemp(join(tmpdir(), 'umeko-marketplace-audit-'));
  try {
    const res = await request(detail.dist.tarball,{signal});
    if (!res.ok) throw registryError('Source download failed: HTTP ' + res.status, res.status);
    const extractor=tar.x({cwd: tmpDir, preservePaths: false, strict: true,
      filter: (entryPath, entry) => !entryPath.replaceAll('\\', '/').split('/').includes('..')
        && !/^(?:[a-z]:|[\\/])/i.test(entryPath)
        && ['File', 'Directory', 'OldFile', 'ContiguousFile'].includes(entry.type)});
    await pipeline(Readable.fromWeb(res.body),byteLimiter('compressed download',bounds.compressedBytes),
      createGunzip(),byteLimiter('expanded archive',bounds.expandedBytes),entryLimiter(bounds.entries),extractor,{signal});
    await walkAndScan(join(tmpDir, 'package'), join(tmpDir, 'package'), findings,signal);
    return findings;
  } finally { await rm(tmpDir, {recursive: true, force: true}); }
}

async function walkAndScan(dir, rootDir, findings,signal) {
    await yieldScan(undefined,{signal});checkCancelled(signal);
    let entries;
    try {
        entries = await readdir(dir, {
            withFileTypes: true
        });
    } catch  {
        return;
    }
    for (const entry of entries){
        checkCancelled(signal);
        const fullPath = join(dir, entry.name);
        if (IGNORED_DIRECTORIES.includes(entry.name)) continue;
        if (entry.isDirectory()) {
            await walkAndScan(fullPath, rootDir, findings,signal);
            continue;
        }
        const ext = entry.name.includes(".") ? `.${entry.name.split(".").pop()}` : "";
        if (SOURCE_EXTENSIONS.includes(ext)) {
            await scanFile(fullPath, rootDir, findings,signal);
        }
    }
}
async function scanFile(filePath, rootDir, findings,signal) {
    let content;
    try {
        content = await readFile(filePath, {encoding:"utf-8",signal});
    } catch  {
        checkCancelled(signal);
        return;
    }
    const relPath = relative(rootDir, filePath) || filePath;
    const lines = content.split("\n");
    for (const danger of DANGER_PATTERNS){
        await yieldScan(undefined,{signal});
        const regex = new RegExp(danger.pattern.source, danger.pattern.flags);
        let match,lineNum=1,charCount=lines[0]?.length+1,matched=0;
        while((match = regex.exec(content)) !== null){
            if(++matched%256===0)await yieldScan(undefined,{signal});
            while(charCount<=match.index&&lineNum<lines.length)charCount+=lines[lineNum++].length+1;
            findings.push({
                severity: danger.severity,
                pattern: danger.description,
                file: relPath,
                line: lineNum,
                context: truncate(lines[lineNum - 1]?.trim() ?? "", 100)
            });
        }
    }
}
function truncate(s, n) {
    return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}
async function performAudit(name, deepScan = true, version, signal) {
  const detail = await getPackageDetail(name, version,{signal});
  const meta = metadataCheck(detail);
  let findings = [], deepScanned = false, scanError;
  if (deepScan) {
    try { findings = await sourceScan(detail,signal); deepScanned = true; }
    catch(error) { checkCancelled(signal);scanError = error instanceof Error ? error.message : String(error);
      findings = [{severity:'info',pattern:'Source scan unavailable',file:'',context:scanError}]; }
  }
  return {...buildReport(name, detail.version, meta, findings, deepScanned), requestedDeepScan: deepScan, ...(scanError?{scanError}:{})};
}
function buildReport(name, version, meta, findings, deepScanned) {
    const crit = findings.filter((f)=>f.severity === "critical").length;
    const high = findings.filter((f)=>f.severity === "high").length;
    const med = findings.filter((f)=>f.severity === "medium").length;
    const overallRisk = crit > 0 ? "critical" : high > 0 ? "high" : med > 2 ? "medium" : med > 0 ? "low" : "info";
    const hasExtensions = meta.types.includes("extension");
    const parts = [];
    if (hasExtensions && crit > 0) {
        parts.push(`⚠️ This extension contains ${crit} critical-risk patterns (file deletion, code execution). Review source before installing.`);
    } else if (hasExtensions && high > 0) {
        parts.push(`This extension contains ${high} high-risk patterns. Review recommended.`);
    } else if (findings.length === 0 && deepScanned) {
        parts.push("No configured danger patterns were found in published source. This keyword scan is not a safety guarantee.");
    } else if (!deepScanned) {
        parts.push("Metadata-only notes (no source scan). A keyword scan is not a safety guarantee.");
    } else {
        parts.push(`${findings.length} finding(s) found (${crit} critical, ${high} high, ${med} medium, ${findings.filter((f)=>f.severity === "low").length} low, ${findings.filter((f)=>f.severity === "info").length} info).`);
    }
    return {
        packageName: name,
        version,
        overallRisk,
        metadata: meta,
        findings,
        summary: parts.join(" "),
        deepScanned
    };
}

function formatSearchResults(packages) {
    if (packages.length === 0) return "No pi packages found. Try different keywords.";
    const lines = [];
    lines.push(`Found ${packages.length} pi package(s):\n`);
    for (const pkg of packages){
        const types = pkg.types?.length ? `[${pkg.types.join(", ")}]` : "";
        const desc = truncate(pkg.description || "(no description)", 70);
        const downloads = pkg.piDevDownloads || withMonthlySuffix(formatDownloads(pkg.downloads.monthly));
        const meta = [
            downloads ? `⬇️ ${downloads}` : "",
            pkg.piDevAuthor ? `👤 ${pkg.piDevAuthor}` : "",
            pkg.piDevTimeAgo ? `🕒 ${pkg.piDevTimeAgo}` : ""
        ].filter(Boolean).join("  ");
        lines.push(`📦 **${pkg.name}** ${types}`.trim());
        lines.push(`   v${pkg.version}  ${desc}`);
        if (meta) lines.push(`   ${meta}`);
        lines.push(`   Install: \`pi install npm:${pkg.name}\``);
        if (pkg.piDevUrl) lines.push(`   Gallery: ${pkg.piDevUrl}`);
        else lines.push(`   Gallery: https://pi.dev/packages/${encodeURIComponent(pkg.name)}`);
        lines.push("");
    }
    return lines.join("\n");
}
function formatPackageDetail(detail) {
    const types = inferTypesString(detail.piManifest);
    const depCount = Object.keys(detail.dependencies ?? {}).length;
    const peerDepCount = Object.keys(detail.peerDependencies ?? {}).length;
    const lines = [
        `## 📦 ${detail.name}`,
        "",
        `**Version**: ${detail.version}`,
        `**Type**: ${types || "unknown"}`,
        `**License**: ${formatLicense(detail.license)}`,
        `**Author**: ${formatAuthor(detail.author)}`,
        `**Publisher**: ${detail.publisher.username}${detail.publisher.email ? ` (${detail.publisher.email.split("@")[1] ?? ""})` : ""}`,
        `**Published**: ${formatDate(detail.date)}`,
        "",
        `### Description`,
        detail.description || "(no description)",
        "",
        `### Pi Manifest`,
        formatPiManifest(detail.piManifest),
        "",
        `### Dependencies`,
        `${depCount} dependencies${peerDepCount ? `, ${peerDepCount} peer dependencies` : ""}`,
        formatDeps(detail.dependencies),
        "",
        `### Size`,
        `${detail.dist.fileCount} files, ${formatSize(detail.dist.unpackedSize)}`,
        "",
        `### Links`,
        `- npm: ${detail.links.npm ?? `https://www.npmjs.com/package/${detail.name}`}`,
        `- Gallery: https://pi.dev/packages/${encodeURIComponent(detail.name)}`,
        ...detail.links.repository ? [
            `- Repository: ${detail.links.repository}`
        ] : [],
        ...detail.links.homepage ? [
            `- Homepage: ${detail.links.homepage}`
        ] : [],
        ""
    ];
    return lines.join("\n");
}
function formatAuditReport(report) {
    const riskEmoji = report.overallRisk === "critical" ? "🔴" : report.overallRisk === "high" ? "🟠" : report.overallRisk === "medium" ? "🟡" : report.overallRisk === "low" ? "🟢" : "⚪";
    const lines = [
        `## 🔍 Security Audit: ${report.packageName}`,
        "",
        `**Overall Risk**: ${riskEmoji} ${report.overallRisk.toUpperCase()}`,
        `**Version**: ${report.version}`,
        `**Scanned At**: ${new Date().toISOString()}`,
        ""
    ];
    lines.push("### 📋 Metadata Check", "");
    lines.push(`| Item | Value |`);
    lines.push(`|------|-------|`);
    lines.push(`| Resource Types | ${report.metadata.types.join(", ") || "none"} |`);
    lines.push(`| Dependencies | ${report.metadata.dependencyCount} |`);
    lines.push(`| Peer Dependencies | ${report.metadata.peerDependencyCount} |`);
    lines.push(`| Files | ${report.metadata.fileCount} |`);
    lines.push(`| Unpacked Size | ${formatSize(report.metadata.unpackedSize)} |`);
    lines.push(`| npm Insecure Flag | ${report.metadata.isInsecure ? "⚠️ YES" : "✅ No"} |`);
    lines.push(`| Published | ${formatDate(report.metadata.publishedAt)} |`);
    lines.push("");
    if (report.findings.length > 0) {
        lines.push("### 🚨 Findings", "");
        for (const f of report.findings){
            const emoji = f.severity === "critical" ? "🔴" : f.severity === "high" ? "🟠" : f.severity === "medium" ? "🟡" : "🟢";
            lines.push(`${emoji} **[${f.severity.toUpperCase()}]** \`${f.pattern}\` in \`${f.file}\`:${f.line ?? "?"}`);
            if (f.context) lines.push(`   Context: \`${truncate(f.context, 80)}\``);
            lines.push("");
        }
        lines.push(`**Total**: ${report.findings.length} finding(s) (${report.findings.filter((f)=>f.severity === "critical" || f.severity === "high").length} high/critical)`);
        lines.push("");
    } else {
        lines.push("### ✅ Source Scan", "");
        lines.push("No configured patterns found. This keyword scan is not a safety guarantee.", "");
    }
    lines.push("### 📝 Summary", "");
    lines.push(report.summary);
    lines.push("", "---");
    lines.push("*⚠️ This is a static keyword-based scan. It cannot detect obfuscated or dynamically constructed code. Always review extension source code before installing.*");
    return lines.join("\n");
}
function truncate(value, maxLen) {
    return value.length > maxLen ? value.slice(0, maxLen - 1) + "…" : value;
}
function formatDownloads(monthly) {
    if (monthly >= 1000_000) return `${(monthly / 1000_000).toFixed(1)}M`;
    if (monthly >= 1000) return `${(monthly / 1000).toFixed(1)}K`;
    return monthly > 0 ? String(monthly) : "";
}
function withMonthlySuffix(value) {
    return value ? `${value}/mo` : "";
}
function formatSize(bytes) {
    if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${bytes} B`;
}
function formatDate(dateStr) {
    if (!dateStr) return "unknown";
    try {
        const d = new Date(dateStr);
        if (Number.isNaN(d.getTime())) return dateStr;
        const now = new Date();
        const diffMs = now.getTime() - d.getTime();
        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
        if (diffDays < 1) return "today";
        if (diffDays < 7) return `${diffDays}d ago`;
        if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
        return d.toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
            year: "numeric"
        });
    } catch  {
        return dateStr;
    }
}
function formatLicense(license) {
    if (typeof license === "string") return license || "unspecified";
    const fields = [
        "type",
        "name",
        "url"
    ].map((key)=>license[key]).filter((value)=>typeof value === "string" && value.trim().length > 0);
    return fields.length ? fields.join(" · ") : "unspecified";
}
function formatAuthor(author) {
    if (!author) return "unknown";
    if (typeof author === "string") return author;
    const fields = [
        "name",
        "email",
        "url"
    ].map((key)=>author[key]).filter((value)=>typeof value === "string" && value.trim().length > 0);
    return fields.length ? fields.join(" · ") : "unknown";
}
function inferTypesString(manifest) {
    const types = [];
    if (manifest.extensions?.length) types.push("extension");
    if (manifest.skills?.length) types.push("skill");
    if (manifest.prompts?.length) types.push("prompt");
    if (manifest.themes?.length) types.push("theme");
    return types.join(", ") || "(not declared)";
}
function formatPiManifest(manifest) {
    const parts = [];
    if (manifest.extensions?.length) parts.push(`extensions: [${manifest.extensions.join(", ")}]`);
    if (manifest.skills?.length) parts.push(`skills: [${manifest.skills.join(", ")}]`);
    if (manifest.prompts?.length) parts.push(`prompts: [${manifest.prompts.join(", ")}]`);
    if (manifest.themes?.length) parts.push(`themes: [${manifest.themes.join(", ")}]`);
    return parts.length > 0 ? parts.join("\n") : "(none declared)";
}
function formatDeps(deps) {
    if (!deps || Object.keys(deps).length === 0) return "(none)";
    const entries = Object.entries(deps).slice(0, 10);
    const lines = entries.map(([name, ver])=>`- ${name}: ${ver}`);
    if (Object.keys(deps).length > 10) lines.push(`... and ${Object.keys(deps).length - 10} more`);
    return "\n" + lines.join("\n");
}


 async function fetchRegistryDoc(name,signal){
  checkCancelled(signal);const value=await docCache.getOrCreate(name,()=>upstreamFetchRegistryDoc(name,signal));checkCancelled(signal);return value;
 }
 async function getPackageDetail(name,version,{signal}={}){
  checkCancelled(signal);
  await configure();const key=name+'@'+(version||'latest');
  const value=await detailCache.getOrCreate(key,()=>upstreamGetPackageDetail(name,version,signal));checkCancelled(signal);return value;
 }
 async function fullAudit(name,deepScan=true,version,{signal}={}){
  const detail=await getPackageDetail(name,version,{signal});const key=name+'@'+detail.version+':'+Boolean(deepScan);
  const cached=auditCache.get(key);if(cached){const value=await cached;checkCancelled(signal);return value;}
  const pending=performAudit(name,deepScan,detail.version,signal);
  auditCache.set(key,pending);
  const value=await pending;
  // A scan transport/limit failure remains visible, but must be retried next time.
  if(value.scanError)auditCache.delete(key);
  checkCancelled(signal);return value;
 }
 async function searchPackages(query,{limit=20,type,signal}={}){
  checkCancelled(signal);
  await configure();let packages,method='search',searchError;
  try {packages=await upstreamSearchPackages(query,{limit,signal});}
  catch(error){
   if(!([404,405,501].includes(error.status)||error.unsupported))throw error;
   const exact=query.trim();
   if(!/^(?:@[a-z0-9._-]+\/)?[a-z0-9._-]+$/i.test(exact))throw error;
   searchError=error.message;const detail=await getPackageDetail(exact,undefined,{signal});
   if(!detail.keywords.includes('pi-package'))throw new Error('Exact-name result is not tagged pi-package');
   packages=[detail];method='exact-name';
  }
  if(type){const filtered=[];for(const p of packages){const detail=await getPackageDetail(p.name,p.version,{signal});if(inferPackageTypes(detail.piManifest).includes(type))filtered.push({...p,types:inferPackageTypes(detail.piManifest)});}packages=filtered;}
  checkCancelled(signal);
  return {method,registry:NPM_REGISTRY,packages,...(searchError?{searchError}:{})};
 }
 return {searchPackages,getPackageDetail,fullAudit,formatSearchResults,formatPackageDetail,formatAuditReport,metadataCheck,
   cacheStats:()=>({docs:docCache.stats(),details:detailCache.stats(),audits:auditCache.stats()}),
   getConfiguration:configure,close:async()=>{await dispatcher?.close();}};
}
