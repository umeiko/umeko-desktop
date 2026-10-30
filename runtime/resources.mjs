// Native resource discovery/settings only: never import or execute extension code.
import { existsSync, mkdirSync, readFileSync, writeFileSync, renameSync, statSync, realpathSync } from "node:fs";
import { dirname, basename, join, relative, resolve, delimiter } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createHash, randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const semver = require("semver");
const runtimeRoot = dirname(fileURLToPath(import.meta.url));
const desktopRepository = "https://github.com/umeiko/umeko-desktop";
export const SUBAGENT_COMPLETION_HINT = "完成任务后，如有需要，请使用 notify_parent 工具向主智能体简要汇报结果。";
const packageName = /^(?:@[a-z0-9._-]+\/)?[a-z0-9][a-z0-9._-]*$/i;
const text = value => typeof value === "string" ? value.slice(0, 4096) : "";
export function webLink(value) {
  try {
    const url = new URL(text(value).replace(/^git\+/, "").replace(/^git:\/\//, "https://").replace(/^git@github.com:/, "https://github.com/"));
    return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href.replace(/\.git(?=$|#)/, "") : "";
  } catch { return ""; }
}
function manifestAt(directory) {
  if (!directory) return {};
  try {
    const file = join(directory, "package.json");
    if (statSync(file).size > 1024 * 1024) return {};
    return JSON.parse(readFileSync(file, "utf8"));
  } catch { return {}; }
}
export function extensionInfo(row) {
  const builtin = row.path.startsWith("builtin:"), name = row.path.slice(8);
  let root = row.metadata?.packageRoot || row.metadata?.baseDir || "";
  let origin = "local", updateKind = "none", manifest = {};
  if (builtin && ["chatbox", "pi-commands", "umeko-control", "background-jobs"].includes(name)) {
    const descriptions = {chatbox:"向聊天和侧栏展示文件、图片、文档与网页。", "pi-commands":"向当前内嵌 Pi 实例发送原生命令和斜杠命令。", "umeko-control":"查询和管理 Umeko 的供应商、主题、扩展与应用设置。", "background-jobs":"运行后台命令、读取独立日志、等待结果或只停止该任务的进程树；阻止按名称批量结束进程。"};
    return {origin:"desktop", bundled:true, description:descriptions[name], homepage:desktopRepository, repository:desktopRepository, version:"", package:"", updateKind:"desktop"};
  }
  if (builtin) {
    const dependency = name === "subagents" ? "@gotgenes/pi-subagents" : "@earendil-works/pi-coding-agent";
    root = join(runtimeRoot, "node_modules", dependency);
    manifest = manifestAt(root);
    origin = name === "subagents" ? "community" : "pi";
    updateKind = manifest.name ? "npm" : "none";
  } else {
    if (!root || !existsSync(join(root, "package.json"))) {
      let current = dirname(row.path);
      for (let i = 0; i < 8; i++) {
        if (existsSync(join(current, "package.json"))) { root = current; break; }
        const parent = dirname(current); if (parent === current) break; current = parent;
      }
    }
    manifest = manifestAt(root);
    if (row.metadata?.origin === "package") origin = "community";
    if (row.metadata?.source?.startsWith("npm:") && packageName.test(manifest.name || "")) updateKind = "npm";
    else if (root && existsSync(join(root, ".git"))) updateKind = "git";
  }
  const repository = webLink(typeof manifest.repository === "string" ? manifest.repository : manifest.repository?.url);
  const descriptions = {codemode:"通过代码组合调用多个工具。", "tool-search":"按名称和说明查找可用工具。", mcp:"连接 MCP 服务器并使用其工具。"};
  return {origin, bundled:builtin, package:text(manifest.name), version:text(manifest.version), description:builtin && descriptions[name] || text(manifest.description),
    homepage:webLink(manifest.homepage), repository, npmUrl:manifest.name && packageName.test(manifest.name) ? "https://www.npmjs.com/package/" + manifest.name : "",
    updateKind, ...(updateKind === "git" ? {packageRoot:root} : {})};
}
function npmVersion(name, cwd) {
  const nodeDir = dirname(process.execPath);
  const candidates = [join(nodeDir,"node_modules/npm/bin/npm-cli.js"), join(nodeDir,"../lib/node_modules/npm/bin/npm-cli.js")];
  for (const directory of (process.env.PATH || "").split(delimiter)) {
    const npm = join(directory,process.platform === "win32" ? "npm.cmd" : "npm");
    try { const file = realpathSync(npm); if (file.endsWith(".js")) candidates.push(file); } catch {}
    candidates.push(join(directory,"node_modules/npm/bin/npm-cli.js"));
  }
  candidates.push("/usr/share/nodejs/npm/bin/npm-cli.js", "/usr/local/lib/node_modules/npm/bin/npm-cli.js");
  const cli = candidates.find(file=>existsSync(file));
  if (!cli) throw new Error("内置 npm 缺失，请重新解压完整安装包");
  try {
    return JSON.parse(execFileSync(process.execPath,[cli,"view",name,"version","--json","--fetch-retries=0","--fetch-timeout=10000"],
      {cwd,encoding:"utf8",timeout:15000,maxBuffer:256*1024,windowsHide:true,stdio:["ignore","pipe","pipe"]}));
  } catch { throw new Error("检查失败，请检查 npm 软件源、网络或包的访问权限"); }
}
export async function checkExtensionUpdate(row, {cwd, lookup = npmVersion} = {}) {
  const info = row.info;
  if (info.updateKind === "npm" && packageName.test(info.package)) {
    const latest = await lookup(info.package,cwd);
    if (!semver.valid(latest)) throw new Error("软件源没有返回有效版本");
    const available = !!semver.valid(info.version) && semver.gt(latest,info.version);
    return {id:row.id,status:available ? "available" : "current", current:info.version, latest,
      message:available ? "发现新版本" : "当前版本已是最新或高于软件源版本"};
  }
  if (info.updateKind === "git") {
    try {
      const options = {cwd:info.packageRoot,encoding:"utf8",timeout:12000,maxBuffer:256*1024,windowsHide:true,stdio:["ignore","pipe","pipe"]};
      const current = execFileSync("git",["rev-parse","HEAD"],options).trim();
      const branch = execFileSync("git",["symbolic-ref","--quiet","--short","HEAD"],options).trim();
      const latest = execFileSync("git",["ls-remote","origin","refs/heads/"+branch],options).trim().split(/\s/)[0];
      if (!/^[a-f0-9]{40,64}$/i.test(latest)) throw new Error();
      return {id:row.id,status:latest === current ? "current" : "available",current:current.slice(0,12),latest:latest.slice(0,12),message:latest === current ? "远端提交未变化" : "远端提交已变更"};
    } catch { throw new Error("无法检查 Git 扩展，请检查远端连接或是否处于分支上"); }
  }
  return {id:row.id,status:"unsupported",message:"本地扩展没有可检查的更新源"};
}

export const builtins = ["codemode", "tool-search", "mcp", "chatbox", "pi-commands", "umeko-control", "background-jobs", "subagents"];
const target = entry => entry.replace(/^[!+-]/, "");
const canonical = (value, base) => value.startsWith("builtin:") ? value : resolve(base, value);
export function extensionName(path, metadata = {}) {
  if (path.startsWith("builtin:")) return path.slice(8);
  // Package entry points commonly live in dist/index.js. The directory is not
  // the package name; use the manifest without importing any extension code.
  if (metadata.origin === "package") {
    try {
      const name = JSON.parse(readFileSync(join(metadata.packageRoot || metadata.baseDir, "package.json"), "utf8")).name;
      if (typeof name === "string" && name.trim()) return name;
    } catch {}
    if (metadata.source?.startsWith("npm:")) return metadata.source.slice(4).replace(/@[^/@]+$/, "");
    if (metadata.packageRoot) return basename(metadata.packageRoot);
  }
  return /^index\.[cm]?[jt]s$/.test(basename(path)) ? basename(dirname(path)) : basename(path);
}
function checkErrors(settings) {
  const errors = settings.drainErrors();
  if (errors.length) throw new Error(errors.map(e => e.error?.message || e.message || "Pi 设置无法读写").join("; "));
}
export async function prepareNativeSettings(Pi, input) {
  const { cwd, agentDir, agent = {} } = input;
  mkdirSync(agentDir, { recursive: true });
  if (agent.safeMode) return Pi.SettingsManager.inMemory({}, { projectTrusted: false });
  const settings = Pi.SettingsManager.create(cwd, agentDir, { projectTrusted: true });
  checkErrors(settings);
  // Import the desktop's extra paths once. Native pi config then owns their
  // +/- filters, so reopening a session never re-enables a disabled resource.
  const marker = join(agentDir, "umeko-paths.json");
  const previous = existsSync(marker) ? JSON.parse(readFileSync(marker, "utf8")) : {};
  const current = { extensions: agent.extensionPaths || [], skills: agent.skillPaths || [] };
  if (!existsSync(marker) && Object.values(current).every(paths => paths.length === 0)) return settings;
  for (const [kind, paths] of Object.entries(current)) {
    const oldPaths = previous[kind] || [];
    if (JSON.stringify(oldPaths) === JSON.stringify(paths)) continue;
    const removed = oldPaths.filter(p => !paths.includes(p));
    const entries = (settings.getGlobalSettings()[kind] || []).filter(p => !removed.includes(canonical(target(p), agentDir)));
    for (const path of paths) {
      if (!oldPaths.includes(path) && !entries.some(p => canonical(target(p), agentDir) === path)) entries.push(path);
    }
    if (kind === "extensions") settings.setExtensionPaths(entries); else settings.setSkillPaths(entries);
  }
  await settings.flush(); checkErrors(settings);
  if (JSON.stringify(previous) !== JSON.stringify(current)) {
    const temp = marker + "." + randomUUID() + ".tmp";
    writeFileSync(temp, JSON.stringify(current)); renameSync(temp, marker);
  }
  return settings;
}

async function discover(Pi, input, settings) {
  const manager = new Pi.DefaultPackageManager({ cwd: input.cwd, agentDir: input.agentDir, settingsManager: settings, builtinExtensions: builtins });
  const resolved = await manager.resolve(async () => "skip");
  // pi config can replace an external file declaration with only '-file'.
  // Keep that existing, explicitly disabled file available for re-enabling.
  for (const [scope, data, base] of [["user", settings.getGlobalSettings(), input.agentDir], ["project", settings.getProjectSettings(), join(input.cwd, ".pi")]]) {
    for (const value of data.extensions || []) {
      if (!value.startsWith("-") || value.startsWith("-builtin:") || /[*?]/.test(value)) continue;
      const path = canonical(target(value), base);
      if (!resolved.extensions.some(row => row.path === path) && /\.[jt]s$/.test(path) && existsSync(path) && statSync(path).isFile()) {
        resolved.extensions.push({ path, enabled: false, metadata: { scope, origin: "top-level", source: "local" } });
      }
    }
  }
  return resolved.extensions.filter(row => !input.agent?.safeMode || row.path.startsWith("builtin:")).map(row => ({ ...row,
    id: createHash("sha256").update(JSON.stringify([row.path, row.metadata.scope, row.metadata.source])).digest("hex").slice(0, 24),
    name: extensionName(row.path, row.metadata),
    scope: row.metadata.scope === "project" ? "project" : "global",
  }));
}

export async function manageResources(Pi, input) {
  const settings = await prepareNativeSettings(Pi, input);
  let rows = await discover(Pi, input, settings);
  if (input.action === "toggle") {
    if (input.agent?.safeMode) throw new Error("请先关闭恢复模式，再修改扩展配置");
    const row = rows.find(r => r.id === input.id);
    if (!row) throw new Error("扩展已变更，请刷新列表后重试");
    const project = row.metadata.scope === "project";
    const data = project ? settings.getProjectSettings() : settings.getGlobalSettings();
    const base = project ? join(input.cwd, ".pi") : input.agentDir;
    const pattern = row.path.startsWith("builtin:") ? row.path : row.metadata.origin === "package" ? relative(row.metadata.packageRoot || row.metadata.baseDir, row.path).replaceAll("\\", "/") : row.path;
    const matches = p => row.metadata.origin === "package" ? target(p) === pattern : canonical(target(p), base) === canonical(pattern, base);
    const entry = (input.enabled ? "+" : "-") + pattern;
    if (row.metadata.origin === "package") {
      const packages = structuredClone(data.packages || []);
      const index = packages.findIndex(p => (typeof p === "string" ? p : p.source) === row.metadata.source);
      if (index < 0) throw new Error("扩展包配置已变更，请刷新后重试");
      const pkg = typeof packages[index] === "string" ? { source: packages[index] } : packages[index];
      pkg.extensions = [...(pkg.extensions || []).filter(p => !matches(p)), entry]; packages[index] = pkg;
      if (project) settings.setProjectPackages(packages); else settings.setPackages(packages);
    } else {
      const paths = (data.extensions || []).filter(p => !/^[!+-]/.test(p) || !matches(p));
      if (row.metadata.source === "local" && !paths.some(p => !/^[!+-]/.test(p) && matches(p))) paths.push(pattern);
      paths.push(entry);
      if (project) settings.setProjectExtensionPaths(paths); else settings.setExtensionPaths(paths);
    }
    await settings.flush(); checkErrors(settings);
    rows = await discover(Pi, input, settings);
  }
  const extensions = rows.map(({ metadata, ...row }) => ({ ...row, source: metadata.source, info:extensionInfo({...row,metadata}) }));
  if (input.action === "check-update") {
    const row = extensions.find(row=>row.id === input.id);
    if (!row) throw new Error("扩展已变更，请刷新列表后重试");
    return {extensions,update:await checkExtensionUpdate(row,{cwd:input.cwd})};
  }
  return { extensions, safeMode: !!input.agent?.safeMode };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    // Discovery must not fetch models or install missing packages.
    process.env.PI_OFFLINE = "1";
    const { installProviderPolicy } = await import("./provider-policy.mjs"); installProviderPolicy({ offline: true });
    const Pi = await import(pathToFileURL(join(dirname(fileURLToPath(import.meta.url)), "node_modules/@earendil-works/pi-coding-agent/dist/index.js")));
    let raw = ""; for await (const chunk of process.stdin) raw += chunk;
    process.stdout.write(JSON.stringify({ ok: true, ...await manageResources(Pi, JSON.parse(raw)) }) + "\n");
  } catch (error) { process.stdout.write(JSON.stringify({ ok: false, error: error.message }) + "\n"); process.exitCode = 1; }
}
