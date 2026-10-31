// Pi owns skill discovery, parsing and settings. This adapter never imports extensions.
import { closeSync, existsSync, lstatSync, opendirSync, openSync, readSync, statSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { prepareNativeSettings } from "./resources.mjs";

const key = path => process.platform === "win32" ? resolve(path).toLowerCase() : resolve(path);
const strip = entry => entry.replace(/^[!+-]/, "");
const sameSkill = (candidate, path) => key(candidate) === key(path) || (path.endsWith(sep + "SKILL.md") && key(candidate) === key(dirname(path)));
const override = (input, path) => typeof input.sessionSkills?.[path] === "boolean" ? input.sessionSkills[path] : undefined;
const idFor = (path, metadata) => "skill_" + Buffer.from(JSON.stringify([path, metadata.scope, metadata.source])).toString("base64url");
const checkErrors = settings => {
  const errors = settings.drainErrors();
  if (errors.length) throw new Error(errors.map(e => e.error?.message || e.message || "Pi 设置无法读写").join("; "));
};

export async function discoverSkills(Pi, input, settings) {
  const manager = new Pi.DefaultPackageManager({ cwd: input.cwd, agentDir: input.agentDir, settingsManager: settings });
  const resolved = await manager.resolve(async () => "skip");
  const resources = [...resolved.skills];
  // Native config can retain only a negative external path after disabling it.
  // Recover that declared path without scanning unrelated directories.
  for (const [scope, data, base] of [["user", settings.getGlobalSettings(), input.agentDir], ["project", settings.getProjectSettings(), join(input.cwd, ".pi")]]) {
    for (const value of data.skills || []) {
      if (typeof value !== "string" || !value.startsWith("-") || /[*?]/.test(value)) continue;
      const path = resolve(base, strip(value));
      if (existsSync(path) && !resources.some(row => key(row.path) === key(path))) resources.push({ path, enabled: false, metadata: { scope, origin: "top-level", source: "local" } });
    }
  }
  const rows = [], seen = new Set();
  for (const resource of resources) {
    const parsed = Pi.loadSkills({ cwd: input.cwd, agentDir: input.agentDir, skillPaths: [resource.path], includeDefaults: false });
    for (const skill of parsed.skills) {
      const path = skill.filePath, metadata = resource.metadata;
      if (seen.has(key(path))) continue;
      seen.add(key(path));
      const scope = metadata.scope === "project" ? "project" : "global";
      const source = metadata.origin === "package" ? "package" : metadata.source === "auto" ? scope : "extra";
      const defaultMutable = scope === "global" && metadata.scope !== "temporary";
      const id = idFor(path, metadata);
      if (id.length > 4096) continue;
      rows.push({ id, name: skill.name, path, description: skill.description, source, scope,
        enabled: !!resource.enabled, attached: false,
        packageSource: metadata.origin === "package" ? metadata.source : "",
        removable: metadata.origin === "package" && !!metadata.source, defaultMutable,
        defaultReason: defaultMutable ? "" : "项目技能仅在所属项目生效；请使用当前聊天开关。",
        metadata, sourceInfo: { ...skill.sourceInfo, ...metadata, path } });
    }
  }
  // Extensions may contribute skills during resources_discover. The bridge
  // passes the already-loaded native records; scanning never executes modules.
  for (const skill of input.loadedSkills || []) {
    const path = skill.path || skill.filePath;
    if (typeof path !== "string" || !isAbsolute(path) || seen.has(key(path))) continue;
    const metadata = skill.sourceInfo || {};
    const id = idFor(path, metadata);
    if (id.length > 4096) continue;
    seen.add(key(path));
    rows.push({ id, path, name: String(skill.name || ""), description: String(skill.description || ""), source: "extension",
      scope: metadata.scope === "project" ? "project" : "global", enabled: true,
      attached: false, packageSource: metadata.origin === "package" ? metadata.source || "" : "",
      removable: false, defaultMutable: false, defaultReason: "由扩展在运行时提供；默认开关由该扩展管理。", metadata, sourceInfo: metadata });
  }
  // Availability follows the same precedence as sessionSkillOptions and Pi's
  // name deduplication. Keep displaced entries visible without claiming that
  // the model can invoke both same-name skills.
  if (!input.agent?.safeMode && !input.globalCoordinator) {
    const names = new Set();
    const selected = rows.filter(row => override(input, row.path) === true);
    const defaults = rows.filter(row => row.enabled && override(input, row.path) === undefined);
    for (const row of [...selected, ...defaults]) {
      if (!names.has(row.name)) { row.attached = true; names.add(row.name); }
    }
  }
  return rows;
}

function setGlobalDefault(settings, input, row, enabled) {
  if (!row.defaultMutable) throw new Error(row.defaultReason);
  const data = settings.getGlobalSettings(), metadata = row.metadata;
  if (metadata.origin === "package") {
    const packages = structuredClone(data.packages || []);
    const index = packages.findIndex(pkg => (typeof pkg === "string" ? pkg : pkg.source) === metadata.source);
    if (index < 0) throw new Error("技能包配置已变化，请刷新后重试");
    const pkg = typeof packages[index] === "string" ? { source: packages[index] } : packages[index];
    const pattern = relative(metadata.packageRoot || metadata.baseDir, row.path).split(sep).join("/");
    // An empty native package filter means disable all. Keep that baseline
    // explicit when enabling one member, so siblings are not enabled as well.
    const filters = Array.isArray(pkg.skills) && pkg.skills.length === 0 ? ["!**/*"] : pkg.skills || [];
    pkg.skills = [...filters.filter(value => !sameSkill(resolve(metadata.packageRoot || metadata.baseDir, strip(value)), row.path)), (enabled ? "+" : "-") + pattern];
    packages[index] = pkg; settings.setPackages(packages);
  } else {
    const same = value => sameSkill(resolve(input.agentDir, strip(value)), row.path);
    const paths = (data.skills || []).filter(value => !/^[!+-]/.test(value) || !same(value));
    if (metadata.source === "local" && !paths.some(value => !/^[!+-]/.test(value) && same(value))) paths.push(row.path);
    paths.push((enabled ? "+" : "-") + row.path);
    settings.setSkillPaths(paths);
  }
}

export function skillDetails(row) {
  const path = row.path, directory = dirname(path), files = [];
  const limits = { bytes: 64 * 1024, files: 300, entries: 1500, depth: 12 };
  let truncated = false, size = 0, entries = 0, fd;
  let markdown = "";
  try {
    const info = statSync(path);
    fd = openSync(path, "r");
    const buffer = Buffer.alloc(Math.min(info.size, limits.bytes));
    const count = readSync(fd, buffer, 0, buffer.length, 0);
    markdown = buffer.subarray(0, count).toString("utf8");
    truncated = info.size > count;
  } finally { if (fd !== undefined) closeSync(fd); }
  // A standalone markdown skill does not own its parent directory.
  const walk = (dir, depth) => {
    if (depth > limits.depth) { truncated = true; return; }
    let handle;
    try {
      handle = opendirSync(dir);
      for (let entry; (entry = handle.readSync());) {
        if (++entries > limits.entries || files.length >= limits.files) { truncated = true; break; }
        const full = join(dir, entry.name);
        if (entry.isSymbolicLink()) { truncated = true; continue; }
        if (entry.isDirectory()) walk(full, depth + 1);
        else if (entry.isFile()) {
          const bytes = lstatSync(full).size;
          files.push({ path: relative(directory, full).split(sep).join("/"), size: bytes }); size += bytes;
        }
        if (entries > limits.entries || files.length >= limits.files) { truncated = true; break; }
      }
    } finally { handle?.closeSync(); }
  };
  if (path.endsWith(sep + "SKILL.md")) walk(directory, 0);
  else { size = statSync(path).size; files.push({ path: relative(directory, path), size }); }
  files.sort((a, b) => a.path.localeCompare(b.path));
  return { id: row.id, path, directory, markdown, files, size, truncated };
}

export async function manageSkills(Pi, input) {
  if (input.action === "validateText") return validateSkillDocuments(input.documents);
  const settings = await prepareNativeSettings(Pi, input);
  let rows = await discoverSkills(Pi, input, settings);
  const action = input.action || "list";
  if (!["list", "details", "default"].includes(action)) throw new Error("未知技能操作");
  if (action !== "list") {
    const row = rows.find(row => row.id === input.id);
    if (!row) throw new Error("技能已变化，请刷新列表后重试");
    if (action === "details") return { ok: true, details: skillDetails(row) };
    if (input.agent?.safeMode) throw new Error("请先关闭恢复模式，再修改技能默认设置");
    if (typeof input.enabled !== "boolean") throw new Error("技能开关必须为布尔值");
    setGlobalDefault(settings, input, row, input.enabled);
    await settings.flush(); checkErrors(settings);
    rows = await discoverSkills(Pi, input, settings);
  }
  return { ok: true, skills: rows };
}

export async function validateSkillDocuments(documents) {
  if (!Array.isArray(documents) || documents.length > 2048) throw new Error("技能文档清单无效或过大");
  const entry = import.meta.resolve("@earendil-works/pi-coding-agent");
  const { parseFrontmatter } = await import(new URL("./utils/frontmatter.js", entry));
  let bytes = 0;
  const rows = documents.map(document => {
    if (typeof document.markdown !== "string" || typeof document.key !== "string") throw new Error("技能文档内容无效");
    bytes += Buffer.byteLength(document.markdown);
    if (bytes > 128 * 1024 * 1024) throw new Error("技能文档超过 128 MiB 限制");
    const diagnostics = [];
    let name = String(document.directoryName || "").slice(0, 256), description = "";
    try {
      // Use Pi's YAML/BOM/newline parser directly, without creating temporary
      // files. These metadata rules match its native loadSkillFromFile rules.
      const { frontmatter } = parseFrontmatter(document.markdown);
      name = typeof frontmatter.name === "string" && frontmatter.name ? frontmatter.name : name;
      description = typeof frontmatter.description === "string" ? frontmatter.description : "";
      if (!description.trim()) diagnostics.push("description is required");
      else if (description.length > 1024) diagnostics.push("description exceeds 1024 characters");
      if (name.length > 64) diagnostics.push("name exceeds 64 characters");
      if (!/^[a-z0-9-]+$/.test(name)) diagnostics.push("name must use lowercase letters, digits and hyphens");
      if (name.startsWith("-") || name.endsWith("-") || name.includes("--")) diagnostics.push("name has invalid hyphen placement");
    } catch (error) { diagnostics.push(String(error.message || error).slice(0, 500)); }
    return { key: document.key.slice(0, 256), name: name.slice(0, 256), description: description.slice(0, 1024), valid: diagnostics.length === 0, diagnostics };
  });
  return { ok: true, documents: rows };
}

export async function sessionSkillOptions(Pi, input, nativeSettings) {
  if (input.agent?.safeMode || input.globalCoordinator) return {};
  const overrides = input.sessionSkills;
  if (!overrides || typeof overrides !== "object" || Array.isArray(overrides)) return {};
  const rows = await discoverSkills(Pi, input, nativeSettings);
  const selected = rows.filter(row => overrides[row.path] === true);
  // Explicit additions make default-disabled skills visible to Pi's own parser.
  // The callback also runs for resources added later by native extension hooks.
  return {
    additionalSkillPaths: selected.map(row => row.path),
    skillsOverride: result => {
      const forced = [], names = new Set(), diagnostics = [...result.diagnostics];
      for (const row of selected) {
        let skill = result.skills.find(skill => key(skill.filePath) === key(row.path));
        // Pi deduplicates names before this callback. Recover an explicitly
        // attached path if a default-enabled namesake displaced it.
        if (!skill) {
          const loaded = Pi.loadSkills({ cwd: input.cwd, agentDir: input.agentDir, skillPaths: [row.path], includeDefaults: false });
          skill = loaded.skills.find(skill => key(skill.filePath) === key(row.path));
          diagnostics.push(...loaded.diagnostics);
        }
        if (skill && !names.has(skill.name)) {
          forced.push({ ...skill, sourceInfo: row.sourceInfo }); names.add(skill.name);
        }
      }
      return { ...result, diagnostics, skills: [...forced, ...result.skills.filter(skill => overrides[skill.filePath] !== false && !names.has(skill.name))] };
    },
  };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    process.env.PI_OFFLINE = "1";
    const { installProviderPolicy } = await import("./provider-policy.mjs"); installProviderPolicy({ offline: true });
    const Pi = await import(pathToFileURL(join(dirname(fileURLToPath(import.meta.url)), "node_modules/@earendil-works/pi-coding-agent/dist/index.js")));
    let raw = ""; for await (const chunk of process.stdin) raw += chunk;
    process.stdout.write(JSON.stringify(await manageSkills(Pi, JSON.parse(raw))) + "\n");
  } catch (error) { process.stdout.write(JSON.stringify({ ok: false, error: error.message }) + "\n"); process.exitCode = 1; }
}
