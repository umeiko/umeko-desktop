// Pi owns skill discovery, parsing and settings. This adapter never imports extensions.
import { closeSync, existsSync, lstatSync, opendirSync, openSync, readSync, statSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { prepareNativeSettings } from "./resources.mjs";
import { setImmediate as yieldDirectoryScan } from "node:timers/promises";

const key = path => process.platform === "win32" ? resolve(path).toLowerCase() : resolve(path);
const strip = entry => entry.replace(/^[!+-]/, "");
const sameSkill = (candidate, path) => key(candidate) === key(path) || (path.endsWith(sep + "SKILL.md") && key(candidate) === key(dirname(path)));
const override = (input, path) => typeof input.sessionSkills?.[path] === "boolean" ? input.sessionSkills[path] : undefined;
const idFor = (path, metadata) => "skill_" + Buffer.from(JSON.stringify([path, metadata.scope, metadata.source])).toString("base64url");
const checkErrors = settings => {
  const errors = settings.drainErrors();
  if (errors.length) throw new Error(errors.map(e => e.error?.message || e.message || "Pi 设置无法读写").join("; "));
};

// Apply chat overrides before deduplicating names, both in the catalog and in
// the native loader. Pi's default-enabled resources keep their native order.
function effectiveSkills(rows, input) {
  const names = new Set();
  return [...rows.filter(row => override(input, row.path) === true),
    ...rows.filter(row => row.enabled && override(input, row.path) === undefined)]
    .filter(row => { if (names.has(row.name)) return false; names.add(row.name); return true; });
}

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
  if (input.skillsEnabled !== false && !input.agent?.safeMode && !input.globalCoordinator) {
    for (const row of effectiveSkills(rows, input)) row.attached = true;
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
  if (input.action === "browse") {
    const value = await browseSkillFolders(input);
    try {
      if (!Pi) {
        // Keep browsing independent of the full SDK while using Pi's own
        // package filters to report and enforce the same availability.
        const entry = import.meta.resolve("@earendil-works/pi-coding-agent");
        const [settingsModule, packagesModule] = await Promise.all([
          import(new URL("./core/settings-manager.js", entry)),
          import(new URL("./core/package-manager.js", entry)),
        ]);
        Pi = { SettingsManager: settingsModule.SettingsManager, DefaultPackageManager: packagesModule.DefaultPackageManager };
      }
      const settings = await prepareNativeSettings(Pi, input);
      const manager = new Pi.DefaultPackageManager({cwd:input.cwd,agentDir:input.agentDir,settingsManager:settings});
      const resolved = await manager.resolve(async()=>"skip");
      const defaults = new Map(resolved.skills.map(row=>[key(row.path),!!row.enabled]));
      for(const row of value.skills) {
        const known=defaults.has(key(row.path)), nativeEnabled=defaults.get(key(row.path)) || false;
        row.defaultEnabled=nativeEnabled;
        row.enabled=override(input,row.path) ?? nativeEnabled;
        row.canToggle=known && row.valid && !input.agent?.safeMode && !input.globalCoordinator && input.skillsEnabled!==false;
      }
    } catch(error) {
      value.stateError=String(error.message || error).slice(0,500);
      for(const row of value.skills)Object.assign(row,{enabled:override(input,row.path) ?? false,canToggle:false});
    }
    return value;
  }
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

// A Skill is managed as one directory, with an independent chat selection. Only the
// current global/workspace roots belong in the folder manager. Discovery stays
// bounded and inert, including when a user drops a huge or malformed document.
export async function browseSkillFolders(input) {
  const roots = { global: resolve(input.agentDir, "skills"),
    project: input.includeProject ? resolve(input.cwd, ".pi/skills") : "" };
  const skills = [], documents = [];
  let entries = 0, bytes = 0, truncated = false;
  for (const scope of ["project", "global"]) {
    const root = roots[scope];
    if (!root || !existsSync(root)) continue;
    const walk = async (directory, depth) => {
      if (depth > 24 || entries >= 20000 || skills.length >= 5000 || bytes >= 128 * 1024 * 1024) { truncated = true; return; }
      if (lstatSync(directory).isSymbolicLink()) return;
      const path = join(directory, "SKILL.md");
      if (directory !== root && existsSync(path) && lstatSync(path).isFile() && !lstatSync(path).isSymbolicLink()) {
        let fd;
        try {
          fd = openSync(path, "r");
          const buffer = Buffer.alloc(64 * 1024);
          const count = readSync(fd, buffer, 0, buffer.length, 0);
          bytes += count;
          const folderName = directory.slice(directory.lastIndexOf(sep) + 1);
          const id = idFor(path, { scope, source: "directory" });
          if (id.length <= 4096) {
            documents.push({ key: String(skills.length), markdown: buffer.subarray(0, count).toString("utf8"), directoryName: folderName });
            skills.push({ id, name: folderName, folderName, path, directory, scope, kind: "folder" });
          }
        } finally { if (fd !== undefined) closeSync(fd); }
        return; // Assets inside a Skill are never separate rows or a file tree.
      }
      let handle;
      try {
        handle = opendirSync(directory);
        for (let entry; (entry = handle.readSync());) {
          if (++entries > 20000 || skills.length >= 5000 || bytes >= 128 * 1024 * 1024) { truncated = true; break; }
          if (!entry.name.startsWith(".") && entry.isDirectory() && !entry.isSymbolicLink()) await walk(join(directory, entry.name), depth + 1);
          if (entries % 64 === 0) await yieldDirectoryScan();
        }
      } finally { handle?.closeSync(); }
    };
    await walk(root, 0);
  }
  const parsed = { documents: [] };
  for (let offset = 0; offset < documents.length; offset += 2048)
    parsed.documents.push(...(await validateSkillDocuments(documents.slice(offset, offset + 2048))).documents);
  for (let index = 0; index < skills.length; index++) {
    const document = parsed.documents[index];
    Object.assign(skills[index], { skillName: document.name, description: document.description, valid: document.valid });
  }
  return { ok: true, roots, skills, truncated };
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
  // Keep native files and +/- settings intact. The override also filters skills
  // contributed by extension hooks after startup, including on /reload.
  if (input.skillsEnabled === false) return {
    noSkills: true,
    skillsOverride: result => ({ ...result, skills: [] }),
  };
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
      const diagnostics = [...result.diagnostics];
      const candidates = result.skills.map(skill => ({ path: skill.filePath, name: skill.name, enabled: true, skill }));
      // Pi has already discarded duplicate names. Its current collision
      // diagnostics retain the enabled alternatives, including resources added
      // by extensions. Recover those instead of reusing a stale startup catalog
      // (which could undo a subsequent native default change on /reload).
      const recover = [...selected];
      for (const diagnostic of result.diagnostics) {
        const collision = diagnostic.collision;
        if (collision?.resourceType === "skill" && overrides[collision.winnerPath] === false)
          recover.push({ path: collision.loserPath });
      }
      for (const row of recover) {
        if (candidates.some(candidate => key(candidate.path) === key(row.path))) continue;
        const loaded = Pi.loadSkills({ cwd: input.cwd, agentDir: input.agentDir, skillPaths: [row.path], includeDefaults: false });
        const skill = loaded.skills.find(skill => key(skill.filePath) === key(row.path));
        diagnostics.push(...loaded.diagnostics);
        if (skill) candidates.push({ path: row.path, name: skill.name, enabled: true,
          skill: row.sourceInfo ? { ...skill, sourceInfo: row.sourceInfo } : skill });
      }
      const forced = selected.map(row => candidates.find(candidate => key(candidate.path) === key(row.path))).filter(Boolean);
      return { ...result, diagnostics, skills: effectiveSkills([...forced, ...candidates], input).map(row => row.skill) };
    },
  };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    process.env.PI_OFFLINE = "1";
    let raw = ""; for await (const chunk of process.stdin) raw += chunk;
    const input = JSON.parse(raw);
    let Pi;
    // Folder browsing needs only native resource settings and frontmatter, not the full SDK,
    // tool registry, provider clients and extension transpilation machinery.
    if (!["browse", "validateText"].includes(input.action)) {
      const { installProviderPolicy } = await import("./provider-policy.mjs"); installProviderPolicy({ offline: true });
      Pi = await import(pathToFileURL(join(dirname(fileURLToPath(import.meta.url)), "node_modules/@earendil-works/pi-coding-agent/dist/index.js")));
    }
    process.stdout.write(JSON.stringify(await manageSkills(Pi, input)) + "\n");
  } catch (error) { process.stdout.write(JSON.stringify({ ok: false, error: error.message }) + "\n"); process.exitCode = 1; }
}
