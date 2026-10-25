// Native resource discovery/settings only: never import or execute extension code.
import { existsSync, mkdirSync, readFileSync, writeFileSync, renameSync, statSync } from "node:fs";
import { dirname, basename, join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createHash, randomUUID } from "node:crypto";

export const builtins = ["codemode", "tool-search", "mcp", "chatbox", "pi-commands"];
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
  return { extensions: rows.map(({ metadata, ...row }) => ({ ...row, source: metadata.source })), safeMode: !!input.agent?.safeMode };
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
