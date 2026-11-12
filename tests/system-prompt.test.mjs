import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { createSystemPromptController } from '../runtime/system-prompt.mjs';
import {
  createAgentSession, DefaultResourceLoader, SessionManager, SettingsManager,
} from '../runtime/node_modules/@earendil-works/pi-coding-agent/dist/index.js';
import { AssistantMessageEventStream, getCurrentSystemPrompt } from '../runtime/node_modules/@earendil-works/pi-ai/dist/index.js';

const { buildSystemPrompt } = await import(new URL('../runtime/node_modules/@earendil-works/pi-coding-agent/dist/core/system-prompt.js', import.meta.url));
const model = {
  id: 'prompt-fixture', name: 'Prompt fixture', provider: 'fixture', api: 'openai-completions',
  baseUrl: 'http://127.0.0.1/unused', reasoning: false, input: ['text'], contextWindow: 128000,
  maxTokens: 128, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
};
const flatten = (tree) => tree.flatMap((node) => [node, ...flatten(node.children ?? [])]);
const find = (snapshot, predicate) => flatten(snapshot.tree).find(predicate);

async function sandbox(t) {
  const base = process.platform === 'win32' ? 'C:/UmekoTests/p116' : join(tmpdir(), 'umeko-p116');
  await mkdir(base, { recursive: true });
  const root = await mkdtemp(join(base, 'prompt-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  return root;
}

async function fixture(t, root, { name = 'workspace', skills = ['alpha'], content = 'Workspace rules.\n',
  controller: useController = true, enabled = true, extensionFactories = [], appendSources, append, widgetPrompts,
} = {}) {
  const cwd = join(root, name);
  const agentDir = join(root, 'agent');
  await mkdir(cwd, { recursive: true });
  await mkdir(agentDir, { recursive: true });
  for (const name of skills) {
    await mkdir(join(cwd, name), { recursive: true });
    await writeFile(join(cwd, name, 'SKILL.md'), `---\nname: ${name}\ndescription: ${name} examples\n---\nfull skill body\n`);
  }
  const controller = useController ? await createSystemPromptController({
    cwd, agentDir, stateDir: join(root, 'state'), enabled, appendSources, widgetPrompts,
  }) : undefined;
  const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
  const resourceLoader = new DefaultResourceLoader({
    cwd, agentDir, settingsManager, noContextFiles: true, noExtensions: true,
    noSkills: true, noThemes: true, noPromptTemplates: true,
    appendSystemPrompt: append ?? ['Host prompt. ', 'Custom instructions.'],
    extensionFactories,
    agentsFilesOverride: () => ({ agentsFiles: [{ path: join(cwd, 'AGENTS.md'), content }] }),
    skillsOverride: () => ({ skills: skills.map((name) => ({
      name, description: `${name} & examples`, filePath: join(cwd, name, 'SKILL.md'),
      baseDir: join(cwd, name), source: 'project', disableModelInvocation: false,
    })), diagnostics: [] }),
    ...(controller ? { extensionsOverride: controller.extensionsOverride } : {}),
  });
  await resourceLoader.reload();
  const { session } = await createAgentSession({ cwd, agentDir, resourceLoader, settingsManager,
    sessionManager: SessionManager.inMemory(cwd), tools: ['read'], model });
  t.after(() => session.dispose());
  // The stream function below is entirely local; the SDK's ordinary configuration gate
  // must not require or consult a user's provider credential for this fixture.
  session._modelRuntime.hasConfiguredAuth = () => true;
  const captured = [];
  session.agent.streamFunction = (_model, context) => {
    captured.push({ prompt: getCurrentSystemPrompt(context.messages), messages: context.messages });
    const stream = new AssistantMessageEventStream();
    queueMicrotask(() => {
      const message = { role: 'assistant', content: [{ type: 'text', text: 'OK' }],
        api: model.api, provider: model.provider, model: model.id, stopReason: 'stop', timestamp: Date.now(),
        usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } };
      stream.push({ type: 'done', reason: 'stop', message });
      stream.end(message);
    });
    return stream;
  };
  controller?.attach(session, resourceLoader);
  return { cwd, session, controller, captured };
}

test('unmodified and disabled controllers preserve the installed Pi model prompt exactly', async (t) => {
  const root = await sandbox(t);
  const ordinary = await fixture(t, root, { controller: false });
  const original = buildSystemPrompt(ordinary.session._baseSystemPromptOptions);
  await ordinary.session.prompt('Hello');
  assert.equal(ordinary.captured.at(-1).prompt, original);
  const controlled = await fixture(t, root);
  assert.equal(controlled.controller.refresh().originalPrompt, original);
  assert.equal(controlled.controller.refresh().dynamicStatus, 'not-run');
  await controlled.session.prompt('Hello');
  assert.equal(controlled.captured.at(-1).prompt, ordinary.captured.at(-1).prompt);
  const source = find(controlled.controller.refresh(), (node) => node.contributionKind === 'project-context');
  await controlled.controller.mutate({ action: 'save', id: source.id, text: 'Changed file contribution.' });
  controlled.controller.setEnabled(false);
  await controlled.session.prompt('Again');
  assert.equal(controlled.captured.at(-1).prompt, original);
  const disabledSource = find(controlled.controller.refresh(), (node) => node.id === source.id);
  assert.equal(disabledSource.currentText, 'Changed file contribution.');
  assert.equal(disabledSource.effectiveText, source.originalText);
});

test('catalog and project sources change the real stream input and restore exactly', async (t) => {
  const root = await sandbox(t);
  const runtime = await fixture(t, root);
  const initial = runtime.controller.refresh();
  const skill = find(initial, (node) => node.contributionKind === 'skill-catalog');
  assert.match(skill.originalText, /<description>alpha &amp; examples<\/description>/);
  assert.doesNotMatch(skill.originalText, /full skill body/);
  const file = find(initial, (node) => node.contributionKind === 'project-context');
  await runtime.controller.mutate({ action: 'save', id: file.id, text: 'Replacement workspace contribution.' });
  await runtime.controller.mutate({ action: 'toggle', id: skill.id, enabled: false });
  await runtime.session.prompt('Use this prompt');
  assert.match(runtime.captured.at(-1).prompt, /Replacement workspace contribution\./);
  assert.doesNotMatch(runtime.captured.at(-1).prompt, /<name>alpha<\/name>/);
  assert.equal(runtime.captured.at(-1).prompt, runtime.controller.refresh().effectivePrompt);
  await runtime.controller.mutate({ action: 'restore' });
  await runtime.session.prompt('Restore');
  assert.equal(runtime.captured.at(-1).prompt, initial.originalPrompt);
});

test('source identity survives restarts, unrelated insertion and upstream changes', async (t) => {
  const root = await sandbox(t);
  const first = await fixture(t, root);
  const initial = first.controller.refresh();
  const skill = find(initial, (node) => node.contributionKind === 'skill-catalog');
  const file = find(initial, (node) => node.contributionKind === 'project-context');
  const directory = initial.tree.find((node) => node.name === 'Skills');
  await first.controller.mutate({ action: 'toggle', id: directory.id, enabled: false });
  await first.controller.mutate({ action: 'save', id: file.id, text: 'Saved workspace contribution.' });
  const second = await fixture(t, root, { skills: ['beta', 'alpha'], content: 'Upstream changed.\n' });
  const resumed = second.controller.refresh();
  assert.equal(find(resumed, (node) => node.contributionKind === 'skill-catalog' && node.path.includes('alpha')).id, skill.id);
  assert.equal(find(resumed, (node) => node.contributionKind === 'project-context').id, file.id);
  assert.equal(find(resumed, (node) => node.name === 'alpha').enabled, false);
  assert.equal(find(resumed, (node) => node.name === 'beta').enabled, false);
  assert.equal(find(resumed, (node) => node.id === file.id).stale, true);
  assert.equal(find(resumed, (node) => node.id === file.id).effectiveText, 'Saved workspace contribution.');
  const isolated = await fixture(t, root, { name: 'other-workspace' });
  assert.equal(find(isolated.controller.refresh(), (node) => node.name === 'alpha').enabled, true);
  await second.controller.mutate({ action: 'restore', id: directory.id });
  assert.equal(find(second.controller.refresh(), (node) => node.name === 'alpha').enabled, true);
  assert.equal(find(second.controller.refresh(), (node) => node.id === file.id).modified, true);
});

test('host contribution separators and source keys survive selective controls', async (t) => {
  const root = await sandbox(t);
  const appendSources = [
    { id: 'desktop-pi', name: 'Pi 操作说明', text: 'Pi operations. ' },
    { id: 'desktop-control', name: '桌面能力说明', text: 'Desktop operations. ' },
    { id: 'language', name: '回复语言', text: "Reply in the user's language." },
    { id: 'instructions', name: '自定义指令', text: 'My instructions.' },
  ];
  const runtime = await fixture(t, root, { appendSources,
    append: [appendSources.slice(0, 3).map((source) => source.text).join(''), appendSources[3].text] });
  const initial = runtime.controller.refresh();
  assert.equal(initial.originalPrompt, buildSystemPrompt(runtime.session._baseSystemPromptOptions));
  const language = find(initial, (node) => node.name === '回复语言');
  await runtime.controller.mutate({ action: 'toggle', id: language.id, enabled: false });
  await runtime.session.prompt('Hello');
  assert.match(runtime.captured.at(-1).prompt, /Pi operations\. Desktop operations\. \n\nMy instructions\./);
});

test('genuine extension handlers retain order, attribution and replacement fallback', async (t) => {
  const root = await sandbox(t);
  const calls = [];
  const extensionFactories = [
    (pi) => pi.on('before_agent_start', (event) => {
      calls.push('first');
      event.systemPromptOptions.sections.example = 'Structured extension content.';
    }),
    (pi) => pi.on('before_agent_start', (event) => {
      calls.push('second');
      return { systemPrompt: `${event.systemPrompt}\nEXTENSION SUFFIX` };
    }),
  ];
  const runtime = await fixture(t, root, { extensionFactories });
  assert.deepEqual(calls, []);
  await runtime.session.prompt('Hello');
  assert.deepEqual(calls, ['first', 'second']);
  const snapshot = runtime.controller.refresh();
  assert.match(snapshot.originalPrompt, /<example>\nStructured extension content\.\n<\/example>\nEXTENSION SUFFIX$/);
  const sources = snapshot.tree.find((node) => node.name === 'Pi 扩展').children;
  assert.equal(sources.length, 2);
  assert.ok(sources.every((node) => node.children?.length === 1));
  assert.ok(flatten(sources).every((node) => !/<inline|before_agent_start/.test(node.name)));
  const suffix = flatten(sources).find((node) => node.contributionKind === 'extension-append');
  await runtime.controller.mutate({ action: 'toggle', id: suffix.id, enabled: false });
  await runtime.session.prompt('Again');
  assert.doesNotMatch(runtime.captured.at(-1).prompt, /EXTENSION SUFFIX/);
  assert.match(runtime.captured.at(-1).prompt, /Structured extension content\./);
});

test('already-open sessions reload shared workspace controls at command and model boundaries', async (t) => {
  const root = await sandbox(t);
  const first = await fixture(t, root);
  const second = await fixture(t, root);
  const source = find(first.controller.refresh(), (node) => node.contributionKind === 'project-context');
  await first.controller.mutate({ action: 'save', id: source.id, text: 'Shared workspace edit.' });
  const refreshed = second.controller.refresh();
  assert.equal(find(refreshed, (node) => node.id === source.id).currentText, 'Shared workspace edit.');
  await first.controller.mutate({ action: 'save', id: source.id, text: 'Latest shared workspace edit.' });
  await second.session.prompt('Read persisted controls');
  assert.match(second.captured.at(-1).prompt, /Latest shared workspace edit\./);
  const skillDirectory = second.controller.refresh().tree.find((node) => node.name === 'Skills').children[0];
  assert.equal(skillDirectory.name, 'alpha');
  assert.equal(skillDirectory.children[0].name, '技能简介');
  await first.controller.mutate({ action: 'toggle', id: skillDirectory.id, enabled: false });
  assert.equal(find(second.controller.refresh(), (node) => node.id === skillDirectory.children[0].id).enabled, false);
  await second.controller.mutate({ action: 'restore', id: skillDirectory.id });
  assert.equal(find(first.controller.refresh(), (node) => node.id === skillDirectory.children[0].id).enabled, true);
});

test('each append file and host part has independent source controls with exact original separators', async (t) => {
  const root = await sandbox(t);
  const files = [join(root, 'one', 'APPEND_SYSTEM.md'), join(root, 'two', 'APPEND_SYSTEM.md')];
  await mkdir(join(root, 'one'));
  await mkdir(join(root, 'two'));
  await writeFile(files[0], 'First append file.\n');
  await writeFile(files[1], '\uFEFFSecond append file.\n');
  const host = { id: 'language', name: '回复语言', text: 'Host language rule.' };
  const runtime = await fixture(t, root, { append: [files[0], host.text, '', files[1]], appendSources: [host] });
  const initial = runtime.controller.refresh();
  assert.equal(initial.originalPrompt, buildSystemPrompt(runtime.session._baseSystemPromptOptions));
  const sources = flatten(initial.tree).filter((node) => node.contributionKind === 'append-file');
  assert.equal(sources.length, 2);
  assert.notEqual(sources[0].id, sources[1].id);
  assert.equal(sources[1].originalText, 'Second append file.\n');
  await runtime.controller.mutate({ action: 'toggle', id: sources[0].id, enabled: false });
  await runtime.session.prompt('Use distinct sources');
  assert.doesNotMatch(runtime.captured.at(-1).prompt, /First append file/);
  assert.match(runtime.captured.at(-1).prompt, /Host language rule/);
  assert.match(runtime.captured.at(-1).prompt, /Second append file/);
});

test('controller defaults to disabled until explicitly enabled', async (t) => {
  const root = await sandbox(t);
  const controller = await createSystemPromptController({ cwd: root, agentDir: root, stateDir: join(root, 'state') });
  assert.equal(controller.refresh().enabled, false);
});

test('named inline source identity and saved overrides survive unrelated factory insertion', async (t) => {
  const root = await sandbox(t);
  const existing = { name: 'persistent-prompt-source', factory: (pi) => {
    pi.on('before_agent_start', (event) => ({ systemPrompt: `${event.systemPrompt}\nNamed source contribution.` }));
  } };
  const first = await fixture(t, root, { extensionFactories: [existing] });
  await first.session.prompt('First named source');
  const source = find(first.controller.refresh(), (node) => node.contributionKind === 'extension-append');
  const parent = first.controller.refresh().tree.find((node) => node.name === 'Pi 扩展').children[0];
  assert.equal(parent.name, 'persistent prompt source');
  await first.controller.mutate({ action: 'save', id: source.id, text: '\nSaved named source override.' });
  const unrelated = { name: 'unrelated-source', factory: (pi) => {
    pi.on('before_agent_start', (event) => { event.systemPromptOptions.sections.unrelated = 'Unrelated source.'; });
  } };
  const second = await fixture(t, root, { extensionFactories: [unrelated, existing] });
  await second.session.prompt('After insertion');
  const resumed = find(second.controller.refresh(), (node) => node.contributionKind === 'extension-append');
  assert.equal(resumed.id, source.id);
  assert.equal(resumed.currentText, '\nSaved named source override.');
  assert.equal(resumed.stale, false);
  assert.match(second.captured.at(-1).prompt, /Saved named source override\.$/);
});

test('superseded sources expose empty effective text while retaining editable preferences', async (t) => {
  const root = await sandbox(t);
  const replacement = { name: 'replacement-source', factory: (pi) => {
    pi.on('before_agent_start', () => ({ systemPrompt: 'Whole replacement.' }));
  } };
  const suffix = { name: 'suffix-source', factory: (pi) => {
    pi.on('before_agent_start', (event) => ({ systemPrompt: `${event.systemPrompt}\nFinal suffix.` }));
  } };
  const runtime = await fixture(t, root, { extensionFactories: [replacement, suffix] });
  await runtime.session.prompt('Use a complete replacement');
  const snapshot = runtime.controller.refresh();
  const file = find(snapshot, (node) => node.contributionKind === 'project-context');
  assert.equal(file.shadowed, true);
  assert.equal(file.effectiveText, '');
  assert.equal(file.enabled, true);
  assert.equal(file.checkState, 2);
  assert.equal(file.currentText, file.originalText);
  assert.match(file.note, /未注入模型/);
  assert.equal(snapshot.tree.find((node) => node.name === '项目指令文件').shadowed, true);
  await runtime.controller.mutate({ action: 'save', id: file.id, text: 'Edited upstream contribution.' });
  await runtime.session.prompt('Keep replacement precedence');
  assert.equal(runtime.captured.at(-1).prompt, 'Whole replacement.\nFinal suffix.');
  const replacementLeaf = find(runtime.controller.refresh(), (node) => node.contributionKind === 'extension-replacement');
  await runtime.controller.mutate({ action: 'toggle', id: replacementLeaf.id, enabled: false });
  await runtime.session.prompt('Restore prior sources');
  assert.match(runtime.captured.at(-1).prompt, /Edited upstream contribution\./);
  const restored = find(runtime.controller.refresh(), (node) => node.id === file.id);
  assert.equal(restored.shadowed, false);
  assert.equal(restored.effectiveText, 'Edited upstream contribution.');
});

test('tree follows the source layout: Pi core, Skills per Skill, Umeko Desktop and Widgets per Widget', async (t) => {
  const root = await sandbox(t);
  const widget = { name: 'demo-widget', factory: (pi) => {
    pi.on('before_agent_start', (event) => ({ systemPrompt: `${event.systemPrompt}\nWidget contribution.` }));
  } };
  const runtime = await fixture(t, root, { skills: ['alpha', 'beta'], extensionFactories: [widget],
    appendSources: [{ id: 'language', name: '回复语言', text: 'Host prompt. ' }] });
  const initial = runtime.controller.refresh();
  assert.deepEqual(initial.tree.map((node) => node.name), ['Pi 内核', 'Skills', 'Umeko Desktop', 'Widgets', '项目指令文件']);
  assert.deepEqual(initial.tree.map((node) => node.labelKey),
    ['group:core', 'group:skills', 'group:umeko', 'group:widgets', 'group:workspace']);
  const skills = initial.tree.find((node) => node.name === 'Skills').children;
  assert.deepEqual(skills.map((node) => [node.name, node.children.map((child) => child.name)]),
    [['alpha', ['技能简介']], ['beta', ['技能简介']]]);
  assert.deepEqual(initial.tree.find((node) => node.name === 'Widgets').children, []);
  const [extension] = runtime.session.resourceLoader.getExtensions().extensions;
  extension.resolvedPath = join(root, 'umeko-plugins', 'demo-widget', 'extension.mjs');
  await runtime.session.prompt('Hello');
  const snapshot = runtime.controller.refresh();
  const widgets = snapshot.tree.find((node) => node.name === 'Widgets').children;
  assert.equal(widgets.length, 1);
  assert.equal(widgets[0].name, 'demo-widget');
  assert.equal(widgets[0].children[0].contributionKind, 'extension-append');
  assert.equal(snapshot.tree.some((node) => node.name === 'Pi 扩展'), false);
});


test('optional Widget prompts reach Pi without enabling prompt overrides or opening a page', async (t) => {
  const root = await sandbox(t);
  const legacy = await fixture(t, root, { enabled: false });
  const original = legacy.controller.refresh().originalPrompt;
  const runtime = await fixture(t, root, { enabled: false, widgetPrompts: [
    { id: 'example-widget', name: 'Example Widget', text: 'Widget workflow instructions.' },
    { id: 'empty-widget', text: '  \n' },
  ] });
  const snapshot = runtime.controller.refresh();
  const widgets = snapshot.tree.find((node) => node.labelKey === 'group:widgets');
  assert.equal(widgets.children.length, 1);
  assert.equal(widgets.children[0].name, 'Example Widget');
  assert.equal(widgets.children[0].children[0].contributionKind, 'widget-prompt');
  await runtime.session.prompt('Hello');
  assert.equal(runtime.captured.at(-1).prompt, snapshot.originalPrompt);
  assert.match(runtime.captured.at(-1).prompt, /Widget workflow instructions\./);
  runtime.controller.setWidgetPrompts([]);
  assert.equal(runtime.controller.refresh().originalPrompt, original);
  await runtime.session.prompt('Disabled Widget');
  assert.equal(runtime.captured.at(-1).prompt, original);
});

test('cached Pi updates Widget prompts, preserves source controls and reloads without accumulation', async (t) => {
  const root = await sandbox(t);
  const runtime = await fixture(t, root);
  await runtime.session.prompt('Existing conversation');
  const widget = { id: 'example-widget', name: 'Example Widget', text: 'First Widget prompt.' };
  runtime.controller.setWidgetPrompts([widget]);
  const source = find(runtime.controller.refresh(), (node) => node.contributionKind === 'widget-prompt');
  assert.ok(source);
  await runtime.controller.mutate({ action: 'save', id: source.id, text: 'Workspace override.' });
  await runtime.session.prompt('Edited Widget');
  assert.match(runtime.captured.at(-1).prompt, /Workspace override\./);
  assert.doesNotMatch(runtime.captured.at(-1).prompt, /First Widget prompt\./);
  runtime.controller.setWidgetPrompts([{ ...widget, name: 'Renamed Widget', text: 'Second Widget prompt.' }]);
  const changed = find(runtime.controller.refresh(), (node) => node.id === source.id);
  assert.equal(changed.stale, true);
  assert.equal(changed.currentText, 'Workspace override.');
  await runtime.controller.mutate({ action: 'restore', id: source.id });
  await runtime.session.reload();
  await runtime.session.prompt('Reloaded Widget');
  assert.equal(runtime.captured.at(-1).prompt.split('Second Widget prompt.').length, 2);
  const group = runtime.controller.refresh().tree.find((node) => node.labelKey === 'group:widgets');
  await runtime.controller.mutate({ action: 'toggle', id: group.id, enabled: false });
  await runtime.session.prompt('Opted out');
  assert.doesNotMatch(runtime.captured.at(-1).prompt, /Second Widget prompt\./);
  runtime.controller.setEnabled(false);
  await runtime.session.prompt('Manager disabled, declared prompt remains');
  assert.match(runtime.captured.at(-1).prompt, /Second Widget prompt\./);
  runtime.controller.setWidgetPrompts([]);
  assert.equal(runtime.controller.refresh().tree.find((node) => node.labelKey === 'group:widgets').children.length, 0);
  await runtime.session.prompt('Uninstalled Widget');
  assert.doesNotMatch(runtime.captured.at(-1).prompt, /Second Widget prompt\./);
});

test('identical Widget and host text keep independent attribution and stable Widget identities', async (t) => {
  const root = await sandbox(t);
  const shared = 'Identical instructions.';
  const runtime = await fixture(t, root, {
    append: [shared], appendSources: [{ id: 'instructions', name: 'Custom instructions', text: shared }],
    widgetPrompts: [{ id: 'one', name: 'One', text: shared }, { id: 'two', name: 'Two', text: shared }],
  });
  const widgets = runtime.controller.refresh().tree.find((node) => node.labelKey === 'group:widgets');
  assert.equal(widgets.children.length, 2);
  const one = widgets.children[0].children[0];
  const two = widgets.children[1].children[0];
  assert.notEqual(one.id, two.id);
  await runtime.controller.mutate({ action: 'toggle', id: one.id, enabled: false });
  await runtime.session.prompt('Only one Widget disabled');
  assert.equal(runtime.captured.at(-1).prompt.split(shared).length, 3);
  runtime.controller.setWidgetPrompts([{ id: 'two', name: 'Two', text: shared }]);
  assert.equal(find(runtime.controller.refresh(), (node) => node.contributionKind === 'widget-prompt').id, two.id);
});


test('Widget declarations are literal text, not file paths or templates', async (t) => {
  const root = await sandbox(t);
  const path = join(root, 'not-a-prompt.txt');
  await writeFile(path, 'PRIVATE_FILE_CONTENT_MUST_NOT_BE_LOADED');
  const runtime = await fixture(t, root, { enabled: false, widgetPrompts: [
    { id: 'literal', text: path }, { id: 'template', text: '${ENV_VAR} {{config.key}}' },
  ] });
  await runtime.session.prompt('Check literal declarations');
  assert.ok(runtime.captured.at(-1).prompt.includes(path));
  assert.match(runtime.captured.at(-1).prompt, /\$\{ENV_VAR\} \{\{config.key\}\}/);
  assert.doesNotMatch(runtime.captured.at(-1).prompt, /PRIVATE_FILE_CONTENT_MUST_NOT_BE_LOADED/);
});
