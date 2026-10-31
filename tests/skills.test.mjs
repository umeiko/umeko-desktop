import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { tmpdir } from "node:os";
import * as Pi from "../runtime/node_modules/@earendil-works/pi-coding-agent/dist/index.js";
import { prepareNativeSettings } from "../runtime/resources.mjs";
import { manageSkills, sessionSkillOptions } from "../runtime/skills.mjs";

test("native catalog, global defaults and chat overrides preserve resource scopes across reload", async () => {
  const root = mkdtempSync(join(tmpdir(), "umeko-skills-"));
  const previousHome = process.env.HOME;
  process.env.HOME = join(root, "home");
  const skill = (path, name, body = "Use this fixture.") => {
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, `---\nname: ${name}\ndescription: ${name} fixture\n---\n\n${body}\n`);
    return path;
  };
  try {
    // Native ancestor discovery stops at this fixture repository boundary.
    mkdirSync(join(root, ".git"));
    const cwd = join(root, "project"), other = join(root, "other"), agentDir = join(root, "agent"), pkg = join(root, "package");
    mkdirSync(join(cwd, ".pi"), { recursive: true }); mkdirSync(other);
    const on = skill(join(agentDir, "skills/on/SKILL.md"), "on");
    const off = skill(join(agentDir, "skills/off/SKILL.md"), "off", "details\n".repeat(12000));
    writeFileSync(join(dirname(off), "reference.txt"), "reference");
    const extra = skill(join(root, "external/SKILL.md"), "external");
    const project = skill(join(cwd, ".pi/skills/project/SKILL.md"), "project");
    const packaged = skill(join(pkg, "skills/packaged/SKILL.md"), "packaged");
    const sibling = skill(join(pkg, "skills/sibling/SKILL.md"), "sibling");
    writeFileSync(join(pkg, "package.json"), JSON.stringify({ name: "skill-fixture", pi: { skills: ["skills"], extensions: ["index.js"] } }));
    writeFileSync(join(pkg, "index.js"), "throw Error('catalog must not import extensions')");
    const global = { skills: ["-" + dirname(off), "-" + extra], packages: [{ source: pkg, skills: [] }] };
    writeFileSync(join(agentDir, "settings.json"), JSON.stringify(global));
    writeFileSync(join(cwd, ".pi/settings.json"), JSON.stringify({ theme: "project-only" }));
    const input = { cwd, agentDir, agent: {} };
    const catalog = (await manageSkills(Pi, input)).skills;
    const byPath = path => catalog.find(row => row.path === path);
    assert.equal(byPath(off).enabled, false); assert.equal(byPath(on).enabled, true);
    assert.equal(byPath(extra).source, "extra"); assert.equal(byPath(extra).enabled, false);
    assert.equal(byPath(packaged).source, "package"); assert.equal(byPath(packaged).packageSource, pkg);
    assert.equal(byPath(sibling).enabled, false);
    assert.equal(byPath(project).scope, "project"); assert.equal(byPath(project).defaultMutable, false);
    assert.ok(catalog.every(row => /^skill_[A-Za-z0-9_-]+$/.test(row.id) && row.id.length <= 4096));
    await assert.rejects(manageSkills(Pi, { ...input, action: "default", id: byPath(project).id, enabled: true }), /项目/);
    const details = (await manageSkills(Pi, { ...input, action: "details", id: byPath(off).id })).details;
    assert.equal(details.truncated, true); assert.ok(Buffer.byteLength(details.markdown) <= 64 * 1024);
    assert.equal(details.files.find(file => file.path === "reference.txt").size, 9);
    assert.equal(details.size, details.files.reduce((sum, file) => sum + file.size, 0));

    const native = await prepareNativeSettings(Pi, input);
    const options = { cwd, agentDir, settingsManager: native, noExtensions: true, noPromptTemplates: true, noThemes: true, noContextFiles: true };
    const filtered = new Pi.DefaultResourceLoader({ ...options,
      ...await sessionSkillOptions(Pi, { ...input, sessionSkills: { [on]: false, [off]: true, [packaged]: true } }, native) });
    await filtered.reload();
    const first = filtered.getSkills().skills.map(row => row.filePath);
    assert.ok(first.includes(off)); assert.ok(first.includes(packaged)); assert.ok(!first.includes(on));
    const second = new Pi.DefaultResourceLoader(options);
    await second.reload();
    const untouched = second.getSkills().skills.map(row => row.filePath);
    assert.ok(untouched.includes(on)); assert.ok(!untouched.includes(off)); assert.ok(!untouched.includes(packaged));
    const dynamic = skill(join(root, "dynamic/SKILL.md"), "dynamic");
    const dynamicInfo = { source: "fixture-extension", scope: "user", origin: "top-level" };
    const dynamicOptions = await sessionSkillOptions(Pi, { ...input, sessionSkills: { [dynamic]: false } }, native);
    const dynamicLoader = new Pi.DefaultResourceLoader({ ...options, ...dynamicOptions });
    await dynamicLoader.reload();
    dynamicLoader.extendResources({ skillPaths: [{ path: dynamic, metadata: dynamicInfo }] });
    assert.ok(!dynamicLoader.getSkills().skills.some(row => row.filePath === dynamic));
    const dynamicRow = (await manageSkills(Pi, { ...input, loadedSkills: [{ path: dynamic, name: "dynamic", sourceInfo: dynamicInfo }] })).skills.find(row => row.path === dynamic);
    assert.equal(dynamicRow.source, "extension"); assert.equal(dynamicRow.defaultMutable, false);

    // Native defaults change independently; the first chat keeps its explicit choices.
    const changed = (await manageSkills(Pi, { ...input, action: "default", id: byPath(on).id, enabled: false })).skills;
    assert.equal(changed.find(row => row.path === on).enabled, false);
    await filtered.reload();
    const reloaded = filtered.getSkills().skills.map(row => row.filePath);
    assert.ok(reloaded.includes(off)); assert.ok(!reloaded.includes(on));
    assert.equal(JSON.parse(readFileSync(join(cwd, ".pi/settings.json"), "utf8")).theme, "project-only");
    const packageEnabled = (await manageSkills(Pi, { ...input, action: "default", id: byPath(packaged).id, enabled: true })).skills;
    assert.equal(packageEnabled.find(row => row.path === packaged).enabled, true);
    assert.equal(packageEnabled.find(row => row.path === sibling).enabled, false, "enabling one member preserves disabled siblings");
    const enabledOff = (await manageSkills(Pi, { ...input, action: "default", id: byPath(off).id, enabled: true })).skills;
    assert.equal(enabledOff.find(row => row.path === off).enabled, true, "an exact folder exclusion can be re-enabled by the global switch");
    const otherInput = { ...input, cwd: other, sessionSkills: { [project]: true } };
    const otherNative = await prepareNativeSettings(Pi, otherInput);
    const otherOptions = await sessionSkillOptions(Pi, otherInput, otherNative);
    assert.ok(!otherOptions.additionalSkillPaths.includes(project), "a stale project override cannot attach a different project's skill");
    assert.deepEqual(JSON.parse(readFileSync(join(agentDir, "settings.json"), "utf8")).skills, ["-" + extra, "-" + on, "+" + off]);
  } finally {
    if (previousHome === undefined) delete process.env.HOME; else process.env.HOME = previousHome;
    rmSync(root, { recursive: true, force: true });
  }
});

test("package uninstall eligibility and explicit same-name chat selection", async () => {
  const root = mkdtempSync(join(tmpdir(), "umeko-skill-selection-"));
  const previousHome = process.env.HOME;
  process.env.HOME = join(root, "home");
  const skill = path => {
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, "---\nname: shared-name\ndescription: Same-name selection fixture\n---\nUse this skill.\n");
    return path;
  };
  try {
    mkdirSync(join(root, ".git"));
    const cwd = join(root, "project"), agentDir = join(root, "agent"), pkg = join(root, "package");
    mkdirSync(cwd);
    const local = skill(join(agentDir, "skills/local/SKILL.md"));
    const packaged = skill(join(pkg, "skills/packaged/SKILL.md"));
    writeFileSync(join(pkg, "package.json"), JSON.stringify({ name: "selection-fixture", pi: { skills: ["skills"] } }));
    writeFileSync(join(agentDir, "settings.json"), JSON.stringify({ packages: [{ source: pkg, skills: [] }] }));
    const input = { cwd, agentDir, agent: {} };
    const rows = (await manageSkills(Pi, input)).skills;
    assert.equal(rows.find(row => row.path === local).removable, false);
    assert.equal(rows.find(row => row.path === packaged).removable, true);
    const native = await prepareNativeSettings(Pi, input);
    const options = { cwd, agentDir, settingsManager: native, noExtensions: true, noPromptTemplates: true, noThemes: true, noContextFiles: true };
    const selected = new Pi.DefaultResourceLoader({ ...options,
      ...await sessionSkillOptions(Pi, { ...input, sessionSkills: { [local]: false, [packaged]: true } }, native) });
    await selected.reload();
    const actual = selected.getSkills().skills.filter(row => row.name === "shared-name");
    assert.equal(actual.length, 1); assert.equal(actual[0].filePath, packaged);
    const dynamic = (await manageSkills(Pi, { ...input, loadedSkills: [{ path: join(root, "dynamic/SKILL.md"), name: "dynamic", sourceInfo: { origin: "package", source: "npm:not-registered", scope: "user" } }] })).skills.find(row => row.name === "dynamic");
    assert.equal(dynamic.removable, false, "a dynamic claim is not a native package registration");
  } finally {
    if (previousHome === undefined) delete process.env.HOME; else process.env.HOME = previousHome;
    rmSync(root, { recursive: true, force: true });
  }
});

test("catalog attached reports only the effective same-name winner", async () => {
  const root = mkdtempSync(join(tmpdir(), "umeko-catalog-collision-"));
  const previousHome = process.env.HOME;
  process.env.HOME = join(root, "home");
  try {
    mkdirSync(join(root, ".git"));
    const cwd = join(root, "project"), agentDir = join(root, "agent"), pkg = join(root, "package");
    mkdirSync(cwd);
    const local = join(agentDir, "skills/local/SKILL.md"), packaged = join(pkg, "skills/packaged/SKILL.md");
    for (const path of [local, packaged]) {
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, "---\nname: catalog-collision\ndescription: Native same-name catalog fixture\n---\nUse this skill.\n");
    }
    writeFileSync(join(pkg, "package.json"), JSON.stringify({ name: "catalog-fixture", pi: { skills: ["skills"] } }));
    writeFileSync(join(agentDir, "settings.json"), JSON.stringify({ packages: [pkg] }));
    const input = { cwd, agentDir, agent: {} };
    const defaults = (await manageSkills(Pi, input)).skills;
    assert.ok(defaults.every(row => row.enabled), "both resources remain natively enabled and discoverable");
    assert.deepEqual(defaults.filter(row => row.attached).map(row => row.path), [local]);
    const selected = (await manageSkills(Pi, { ...input, sessionSkills: { [packaged]: true } })).skills;
    assert.deepEqual(selected.filter(row => row.attached).map(row => row.path), [packaged]);
    const excluded = (await manageSkills(Pi, { ...input, sessionSkills: { [local]: false, [packaged]: false } })).skills;
    assert.equal(excluded.some(row => row.attached), false);
  } finally {
    if (previousHome === undefined) delete process.env.HOME; else process.env.HOME = previousHome;
    rmSync(root, { recursive: true, force: true });
  }
});
