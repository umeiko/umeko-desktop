/**
 * Adapted from pi-marketplace@0.1.3 (MIT), Copyright (c) 2026 507.
 * Upstream: https://registry.npmjs.org/pi-marketplace/-/pi-marketplace-0.1.3.tgz
 * See marketplace-LICENSE.txt for the retained MIT notice.
 * Desktop delta: configured registry/CA transport, exact-name fallback, pinned
 * versions, direct tarball source scan, structured output.
 */
import {execFile} from 'node:child_process';
import {readFile,writeFile,mkdtemp,rm,readdir} from 'node:fs/promises';
import {existsSync} from 'node:fs';
import {join,relative,dirname,resolve} from 'node:path';
import {tmpdir} from 'node:os';
import {EnvHttpProxyAgent,fetch as undiciFetch} from 'undici';
import * as tar from 'tar';

function registryError(message,status=0,unsupported=false){return Object.assign(new Error(message),{status,unsupported});}
function runNode(args,cwd,env){return new Promise((resolve,reject)=>{
 execFile(process.execPath,args,{cwd,env,windowsHide:true,timeout:15000,maxBuffer:4*1024*1024},(error,stdout)=>{
  if(error)reject(new Error('Could not resolve npm configuration: '+error.message));else resolve(stdout);
 });
});}
function npmCliPath(){
 const candidates=[process.env.npm_execpath,join(dirname(process.execPath),'node_modules/npm/bin/npm-cli.js'),join(process.env.APPDATA||'', 'npm/node_modules/npm/bin/npm-cli.js')].filter(Boolean);
 const found=candidates.find(x=>existsSync(x));if(!found)throw new Error('npm-cli.js not found for effective registry configuration');return found;
}

export function createRegistryClient({agent={},cwd=process.cwd(),fetch:injectedFetch}={}) {
 let configured,dispatcher;const docCache=new Map(),detailCache=new Map(),auditCache=new Map();
 async function configure(){return configured??=(async()=>{
  const env={...process.env};
  if(agent.npmRegistry)env.npm_config_registry=agent.npmRegistry;
  if(agent.npmUserconfig)env.npm_config_userconfig=agent.npmUserconfig;
  if(agent.npmCafile)env.npm_config_cafile=agent.npmCafile;
  const args=[npmCliPath(),'config','list','--json'];
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
 })();}
 async function request(url,options={}){
  await configure();
  return injectedFetch?injectedFetch(url,options):undiciFetch(url,{...options,dispatcher,signal:options.signal||AbortSignal.timeout(30000)});
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
async function upstreamGetPackageDetail(name, version) {
    const data = await fetchRegistryDoc(name);
    const latestName = version ?? getLatestVersionName(data);
    const latestVersion = latestName ? data.versions?.[latestName] : undefined;
    if (!latestVersion || !latestName) {
        throw new Error(`npm registry detail for ${name} did not contain a latest version`);
    }
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
async function upstreamFetchRegistryDoc(name) {
    const res = await request(`${NPM_REGISTRY.replace(/\/$/, "")}/${encodeURIComponent(name)}`, {
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
async function sourceScan(detail) {
  const findings = [];
  const tmpDir = await mkdtemp(join(tmpdir(), 'umeko-marketplace-audit-'));
  try {
    const res = await request(detail.dist.tarball);
    if (!res.ok) throw registryError('Source download failed: HTTP ' + res.status, res.status);
    const archive = join(tmpDir, 'source.tgz');
    await writeFile(archive, Buffer.from(await res.arrayBuffer()));
    await tar.x({file: archive, cwd: tmpDir, preservePaths: false, strict: true,
      filter: (entryPath, entry) => !entryPath.replaceAll('\\', '/').split('/').includes('..')
        && !/^(?:[a-z]:|[\\/])/i.test(entryPath)
        && ['File', 'Directory', 'OldFile', 'ContiguousFile'].includes(entry.type)});
    await walkAndScan(join(tmpDir, 'package'), join(tmpDir, 'package'), findings);
    return findings;
  } finally { await rm(tmpDir, {recursive: true, force: true}); }
}

async function walkAndScan(dir, rootDir, findings) {
    let entries;
    try {
        entries = await readdir(dir, {
            withFileTypes: true
        });
    } catch  {
        return;
    }
    for (const entry of entries){
        const fullPath = join(dir, entry.name);
        if (IGNORED_DIRECTORIES.includes(entry.name)) continue;
        if (entry.isDirectory()) {
            await walkAndScan(fullPath, rootDir, findings);
            continue;
        }
        const ext = entry.name.includes(".") ? `.${entry.name.split(".").pop()}` : "";
        if (SOURCE_EXTENSIONS.includes(ext)) {
            await scanFile(fullPath, rootDir, findings);
        }
    }
}
async function scanFile(filePath, rootDir, findings) {
    let content;
    try {
        content = await readFile(filePath, "utf-8");
    } catch  {
        return;
    }
    const relPath = relative(rootDir, filePath) || filePath;
    const lines = content.split("\n");
    for (const danger of DANGER_PATTERNS){
        const regex = new RegExp(danger.pattern.source, danger.pattern.flags);
        let match;
        while((match = regex.exec(content)) !== null){
            let lineNum = 1;
            let charCount = 0;
            for(let i = 0; i < lines.length; i++){
                charCount += lines[i].length + 1;
                if (charCount > match.index) {
                    lineNum = i + 1;
                    break;
                }
            }
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
async function performAudit(name, deepScan = true, version) {
  const detail = await getPackageDetail(name, version);
  const meta = metadataCheck(detail);
  let findings = [], deepScanned = false, scanError;
  if (deepScan) {
    try { findings = await sourceScan(detail); deepScanned = true; }
    catch(error) { scanError = error instanceof Error ? error.message : String(error);
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
        parts.push("Metadata-only audit (no source scan). Run with deepScan=true for full analysis.");
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
        lines.push("No dangerous patterns found in source code.", "");
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


 async function fetchRegistryDoc(name){
  if(!docCache.has(name))docCache.set(name,upstreamFetchRegistryDoc(name).catch(error=>{docCache.delete(name);throw error;}));
  return docCache.get(name);
 }
 async function getPackageDetail(name,version){
  await configure();const key=name+'@'+(version||'latest');
  if(!detailCache.has(key))detailCache.set(key,upstreamGetPackageDetail(name,version).catch(error=>{detailCache.delete(key);throw error;}));
  return detailCache.get(key);
 }
 async function fullAudit(name,deepScan=true,version){
  const detail=await getPackageDetail(name,version);const key=name+'@'+detail.version+':'+Boolean(deepScan);
  if(!auditCache.has(key))auditCache.set(key,performAudit(name,deepScan,detail.version).catch(error=>{auditCache.delete(key);throw error;}));
  return auditCache.get(key);
 }
 async function searchPackages(query,{limit=20,type}={}){
  await configure();let packages,method='search',searchError;
  try {packages=await upstreamSearchPackages(query,{limit});}
  catch(error){
   if(!([404,405,501].includes(error.status)||error.unsupported))throw error;
   const exact=query.trim();
   if(!/^(?:@[a-z0-9._-]+\/)?[a-z0-9._-]+$/i.test(exact))throw error;
   searchError=error.message;const detail=await getPackageDetail(exact);
   if(!detail.keywords.includes('pi-package'))throw new Error('Exact-name result is not tagged pi-package');
   packages=[detail];method='exact-name';
  }
  if(type){const filtered=[];for(const p of packages){const detail=await getPackageDetail(p.name,p.version);if(inferPackageTypes(detail.piManifest).includes(type))filtered.push({...p,types:inferPackageTypes(detail.piManifest)});}packages=filtered;}
  return {method,registry:NPM_REGISTRY,packages,...(searchError?{searchError}:{})};
 }
 return {searchPackages,getPackageDetail,fullAudit,formatSearchResults,formatPackageDetail,formatAuditReport,metadataCheck,
   getConfiguration:configure,close:async()=>{await dispatcher?.close();}};
}
