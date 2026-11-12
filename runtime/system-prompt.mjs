/** Source controls for Pi 1.3's real prompt, without changing Pi or running preview hooks. */
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, realpathSync, renameSync, writeFileSync } from 'node:fs';
import { basename, join, resolve } from 'node:path';
import { formatSkillsForPrompt } from '@earendil-works/pi-coding-agent';
import { getCurrentSystemMessage, getCurrentSystemPrompt } from '@earendil-works/pi-ai';

// The installed, pinned Pi implementation is the renderer, including its whitespace rules.
const { buildSystemPrompt, buildSystemPromptSections, normalizeBuildSystemPromptOptions } =
  await import(new URL('./core/system-prompt.js', import.meta.resolve('@earendil-works/pi-coding-agent')));

function canonical(path) {
  let result = resolve(path);
  try { result = realpathSync.native(result); } catch {}
  result = result.replaceAll('\\', '/');
  return process.platform === 'win32' ? result.toLowerCase() : result;
}

// Product identity only: these digests never validate files or experimental artifacts.
function identity(key) { return createHash('sha256').update(key).digest('hex').slice(0, 24); }
const copyOptions = (options) => normalizeBuildSystemPromptOptions(options);
const joinParts = (parts, separator = '') => ({ type: 'join', parts, separator });
const wrap = (part, prefix, suffix = '') => ({ type: 'wrap', part, prefix, suffix });
// Display order follows the maintainer's spec. Optional groups are hidden while empty.
const groupNames = {
  core: 'Pi 内核', skills: 'Skills', umeko: 'Umeko Desktop', widgets: 'Widgets',
  workspace: '项目指令文件', extensions: 'Pi 扩展',
};
const optionalGroups = new Set(['workspace', 'extensions']);
const sectionNames = {
  preamble: '角色说明', tools: '工具说明', rules: '工作规则', docs: 'Pi 文档指引',
  cwd: '当前工作目录', addendum: '附加说明', project_context: '工作区指令', skills: '技能目录',
};

/**
 * Pass extensionsOverride to DefaultResourceLoader, then attach the resulting real session.
 * appendSources describes literal contributions already supplied by the host; it injects nothing.
 */
export async function createSystemPromptController(options) {
  const controller = new SystemPromptController(options);
  return controller;
}

function normalizeWidgetPrompts(sources) {
  if (!Array.isArray(sources) || sources.length > 64) throw new Error('Invalid Widget prompt sources');
  const seen = new Set();
  return sources.flatMap((source) => {
    if (!source || !/^[a-z0-9][a-z0-9-]{0,63}$/.test(source.id) || seen.has(source.id)
      || typeof source.text !== 'string' || Buffer.byteLength(source.text, 'utf8') > 8192) {
      throw new Error('Invalid Widget prompt source');
    }
    seen.add(source.id);
    return source.text.trim() ? [{ id: source.id, name: String(source.name || source.id).slice(0, 8000), text: source.text }] : [];
  });
}

class SystemPromptController {
  constructor({ cwd, agentDir, stateDir, enabled = false, onChange, appendSources = [], widgetPrompts = [] }) {
    this.cwd = canonical(cwd);
    this.agentDir = agentDir;
    this.stateDir = stateDir;
    this.enabled = Boolean(enabled);
    this.onChange = onChange;
    this.appendSources = appendSources;
    this.widgetPrompts = normalizeWidgetPrompts(widgetPrompts);
    this.state = { version: 1, workspace: this.cwd, edits: {}, toggles: {} };
    this.records = [];
    this.dynamic = false;
    this.nodes = new Map();
    this.definitions = new Map();
    this.wrappedHandlers = new WeakMap();
    this.appendSourcesCache = new WeakMap();
    this.extensionsOverride = (base) => {
      for (const extension of base.extensions) this.wrapExtension(extension);
      return base;
    };
  }

  load() {
    this.stateFile = this.stateDir ? join(this.stateDir, `${identity(this.cwd)}.json`) : undefined;
    if (!this.stateFile || !existsSync(this.stateFile)) return;
    const stored = JSON.parse(readFileSync(this.stateFile, 'utf8'));
    if (stored.workspace === this.cwd && stored.version === 1) {
      this.state = { ...stored, edits: stored.edits ?? {}, toggles: stored.toggles ?? {} };
    }
  }

  persist() {
    if (!this.stateFile) return;
    mkdirSync(this.stateDir, { recursive: true });
    const pending = `${this.stateFile}.tmp`;
    writeFileSync(pending, `${JSON.stringify(this.state, null, 2)}\n`, 'utf8');
    renameSync(pending, this.stateFile);
  }

  setEnabled(value) { this.enabled = Boolean(value); return this.refresh(); }
  setMetadata({ appendSources } = {}) {
    if (appendSources) this.appendSources = appendSources;
    return this.refresh();
  }

  setWidgetPrompts(sources) {
    const next = normalizeWidgetPrompts(sources);
    if (JSON.stringify(next) === JSON.stringify(this.widgetPrompts)) return;
    this.widgetPrompts = next;
    this.updateWidgetPrompt();
  }

  updateWidgetPrompt() {
    if (!this.session) return;
    // Pi's native prompt builder reads the same loader on reload/tool changes.
    // Update only the append section: keep tools, pending loadouts and history intact.
    this.session._baseSystemPromptOptions.appendSystemPrompt = this.loader.getAppendSystemPrompt().join('\n\n');
    this.runBase = undefined;
    this.modelPrompt = undefined;
    this.records = [];
    this.dynamic = false;
  }

  wrapExtension(extension) {
    for (const eventName of ['before_agent_start', 'context_with_system']) {
      const handlers = extension.handlers.get(eventName);
      if (!handlers) continue;
      extension.handlers.set(eventName, handlers.map((handler, ordinal) => {
        if (this.wrappedHandlers.has(handler)) return handler;
        const controller = this;
        const wrapped = async function(event, context) {
          const beforeOptions = eventName === 'before_agent_start' ? copyOptions(event.systemPromptOptions) : undefined;
          const before = eventName === 'before_agent_start'
            ? buildSystemPrompt(event.systemPromptOptions)
            : getCurrentSystemPrompt(event.messages);
          let result;
          try {
            result = await handler.call(this, event, context);
            return result;
          } finally {
            const afterOptions = eventName === 'before_agent_start'
              ? { ...event.systemPromptOptions,
                ...(result?.systemPrompt !== undefined ? { forceSystemPrompt: result.systemPrompt } : {}) }
              : undefined;
            const after = eventName === 'before_agent_start'
              ? buildSystemPrompt(afterOptions)
              : getCurrentSystemPrompt(result?.messages ?? event.messages);
            if (before !== after) controller.records.push({
              key: `${canonicalExtension(extension)}/${eventName}/${ordinal}`,
              extensionKey: canonicalExtension(extension), extensionName: extensionName(extension),
              name: `${eventName === 'before_agent_start' ? '启动时的提示词' : '请求上下文'}${ordinal ? ` · 片段 ${ordinal + 1}` : ''}`,
              path: extension.resolvedPath ?? extension.path, before, after,
              mode: beforeOptions && beforeOptions.forceSystemPrompt === undefined && afterOptions.forceSystemPrompt === undefined
                ? 'sections' : after.startsWith(before) ? 'append' : 'replace',
              ...(beforeOptions && beforeOptions.forceSystemPrompt === undefined && afterOptions.forceSystemPrompt === undefined
                ? { beforeSections: buildSystemPromptSections(beforeOptions), afterSections: buildSystemPromptSections(afterOptions) } : {}),
            });
          }
        };
        this.wrappedHandlers.set(wrapped, handler);
        return wrapped;
      }));
    }
  }

  attach(session, resourceLoader = session.resourceLoader) {
    if (this.session && this.session !== session) throw new Error('Prompt controller already belongs to a session');
    if (this.session) return this.refresh();
    this.session = session;
    this.loader = resourceLoader;
    const getAppend = resourceLoader.getAppendSystemPrompt.bind(resourceLoader);
    let previous, prompts, combined;
    resourceLoader.getAppendSystemPrompt = () => {
      const base = getAppend();
      if (!this.widgetPrompts.length) return base;
      if (base !== previous || prompts !== this.widgetPrompts) {
        previous = base;
        prompts = this.widgetPrompts;
        combined = [...base, ...prompts.map((source) => source.text)];
      }
      return combined;
    };
    if (this.widgetPrompts.length) this.updateWidgetPrompt();
    this.extensionsOverride(resourceLoader.getExtensions());
    const controller = this;
    const runner = session._extensionRunner;
    if (!runner || !session._baseSystemPromptOptions) {
      throw new Error('The installed Pi session does not expose the supported structured prompt hooks');
    }
    const emit = runner.emitBeforeAgentStart;
    runner.emitBeforeAgentStart = async function(trigger, promptOptions) {
      controller.records = [];
      controller.modelPrompt = undefined;
      controller.runBase = copyOptions(promptOptions);
      controller.dynamic = true;
      try { return await emit.call(this, trigger, promptOptions); }
      finally { controller.refresh(); }
    };
    // This runs after Pi's normal context handlers and exact forced-prompt projection.
    // Returning the original array when unchanged preserves Pi's request bytes and transcript.
    const transform = session.agent.transformContext;
    session.agent.transformContext = async function(messages, signal) {
      controller.records = controller.records.filter((record) => !record.key.includes('/context_with_system/'));
      const original = transform ? await transform.call(this, messages, signal) : messages;
      controller.modelPrompt = getCurrentSystemPrompt(original);
      const snapshot = controller.refresh();
      if (!controller.enabled || snapshot.effectiveText === controller.modelPrompt) return original;
      const current = getCurrentSystemMessage(original);
      if (!current && snapshot.effectiveText.length === 0) return original;
      const head = {
        role: 'system', content: snapshot.effectiveText,
        ...(current?.toolsAdded ? { toolsAdded: current.toolsAdded } : {}),
        timestamp: current?.timestamp ?? Date.now(),
      };
      return [head, ...original.filter((message) => message.role !== 'system')];
    };
    return this.refresh();
  }

  defineGroup(group, name = groupNames[group]) {
    const key = `group:${group}`;
    if (!this.definitions.has(key)) this.definitions.set(key, {
      key, id: identity(key), name, children: [], directory: true, labelKey: key,
    });
    return key;
  }

  sourceDirectory(group, sourceKey, name, metadata = {}) {
    const parentKey = this.defineGroup(group);
    const key = `${parentKey}/${sourceKey}`;
    if (!this.definitions.has(key)) {
      this.definitions.set(key, { key, id: identity(key), name, parentKey,
        children: [], directory: true, ...metadata });
      this.definitions.get(parentKey).children.push(key);
    }
    return key;
  }

  leaf(group, sourceKey, name, text, metadata = {}) {
    const parentKey = group.startsWith('group:') ? group : this.defineGroup(group);
    const key = `${parentKey}/${sourceKey}`;
    const definition = { key, id: identity(key), name, originalText: text, parentKey, ...metadata };
    this.definitions.set(key, definition);
    this.definitions.get(parentKey).children.push(key);
    return { type: 'leaf', key };
  }

  baseRepresentation(input) {
    const options = copyOptions(input);
    const sections = buildSystemPromptSections(options);
    const result = [];
    for (const [name, text] of Object.entries(sections)) {
      if (name === 'project_context' && !options.sections.project_context) {
        const files = options.contextFiles.map((file) => this.leaf('workspace',
          `context:${canonical(file.path)}`, basename(file.path),
          `<project_instructions path="${file.path}">\n${file.content}\n</project_instructions>`,
          { path: file.path, sourceText: file.content, contributionKind: 'project-context' }));
        result.push(wrap(joinParts(files, '\n\n'),
          '<project_context>\nProject-specific instructions and guidelines:\n\n', '\n</project_context>'));
      } else if (name === 'skills' && !options.sections.skills) {
        const readers = ['read', 'bash'];
        const declared = options.selectedTools.filter((tool) => !options.hiddenTools.includes(tool));
        const reader = readers.find((tool) => declared.includes(tool)) ?? 'indirect';
        const visible = options.skills.filter((skill) => !skill.disableModelInvocation);
        const formatted = formatSkillsForPrompt(visible, reader).trim();
        const start = formatted.indexOf('  <skill>');
        const end = formatted.lastIndexOf('\n</available_skills>');
        const skills = visible.map((skill) => {
          const one = formatSkillsForPrompt([skill], reader).trim();
          const contribution = one.slice(one.indexOf('  <skill>'), one.lastIndexOf('\n</available_skills>'));
          const parent = this.sourceDirectory('skills', `skill:${canonical(skill.filePath)}`, skill.name,
            { path: skill.filePath });
          return this.leaf(parent, 'segment:catalog', '技能简介', contribution,
            { path: skill.filePath, contributionKind: 'skill-catalog', labelKey: 'skill:catalog' });
        });
        result.push(wrap(joinParts(skills, '\n'), `<skills>\n${formatted.slice(0, start)}`,
          `${formatted.slice(end)}\n</skills>`));
      } else if (name === 'addendum' && !options.sections.addendum) {
        result.push(this.appendRepresentation(options.appendSystemPrompt));
      } else if (name === 'preamble' && options.customPrompt) {
        const path = this.loader?.getSystemPromptSource?.()?.path;
        result.push(this.leaf('workspace', `system:${path ? canonical(path) : 'configured'}`,
          path ? basename(path) : 'SYSTEM 提示词', text, { path, contributionKind: 'system-file' }));
      } else {
        result.push(this.leaf('core', `section:${name}`, sectionNames[name] ?? name, text,
          { contributionKind: 'pi-section', ...(sectionNames[name] ? { labelKey: `section:${name}` } : {}) }));
      }
    }
    return { ...joinParts(result, '\n\n'), sectionNames: Object.keys(sections) };
  }

  appendRepresentation(text) {
    const parts = [];
    const values = this.loader?.getAppendSystemPrompt?.() ?? [text];
    const loaded = values.join('\n\n') === text ? values : [text];
    let files = this.appendSourcesCache.get(values);
    if (!files) {
      const paths = this.loader?.getAppendSystemPromptSources?.() ?? [];
      files = new Map();
      if (paths.length === values.length) {
        paths.forEach((source, index) => files.set(index, source.path));
      } else {
        const claimed = new Set();
        for (const source of paths) {
          let content;
          try { content = readFileSync(source.path, 'utf8').replace(/^\uFEFF/, ''); } catch { continue; }
          const index = values.findIndex((value, ordinal) => ordinal < values.length - this.widgetPrompts.length && !claimed.has(ordinal) && value === content);
          if (index >= 0) { files.set(index, source.path); claimed.add(index); }
        }
      }
      this.appendSourcesCache.set(values, files);
    }
    loaded.forEach((value, ordinal) => {
      const separator = ordinal > 0 ? '\n\n' : '';
      if (value.length === 0) {
        if (separator) parts.push({ type: 'literal', text: separator });
        return;
      }
      const widget = loaded === values && this.widgetPrompts.length
        ? this.widgetPrompts[ordinal - (values.length - this.widgetPrompts.length)] : undefined;
      if (widget) {
        const parent = this.sourceDirectory('widgets', `widget:${widget.id}`, widget.name);
        parts.push(wrap(this.leaf(parent, 'prompt', '提示词', value,
          { contributionKind: 'widget-prompt', labelKey: 'widget:prompt' }), separator));
        return;
      }
      const file = loaded === values ? files.get(ordinal) : undefined;
      if (file) {
        parts.push(wrap(this.leaf('workspace', `append:${canonical(file)}`, basename(file), value,
          { path: file, contributionKind: 'append-file' }), separator));
        return;
      }
      let cursor = 0;
      let first = true;
      for (const source of this.appendSources) {
        if (!source.text) continue;
        const offset = value.indexOf(source.text, cursor);
        if (offset < 0) continue;
        const prefix = (first ? separator : '') + value.slice(cursor, offset);
        const leaf = this.leaf('umeko', `append:${source.id}`, source.name ?? source.id,
          source.text, { contributionKind: 'host-prompt', labelKey: `umeko:${source.id}` });
        parts.push(wrap(leaf, prefix));
        cursor = offset + source.text.length;
        first = false;
      }
      if (cursor < value.length) {
        const key = loaded.length === 1 ? 'configured' : `configured:${ordinal}`;
        const leaf = this.leaf('workspace', `append:${key}`, '附加系统提示词', value.slice(cursor),
          { contributionKind: 'append-literal' });
        parts.push(wrap(leaf, first ? separator : ''));
      }
    });
    if (!parts.length && text) {
      parts.push(this.leaf('workspace', 'append:configured', '附加系统提示词', text,
        { contributionKind: 'append-literal' }));
    }
    return wrap(joinParts(parts), '<addendum>\n', '\n</addendum>');
  }

  inheritedEnabled(key) {
    if (this.state.toggles[key] !== undefined) return this.state.toggles[key];
    const parent = this.definitions.get(key)?.parentKey;
    return parent ? this.inheritedEnabled(parent) : true;
  }

  render(part, effective, reached) {
    if (part.type === 'literal') return part.text;
    if (part.type === 'leaf') {
      const definition = this.definitions.get(part.key);
      reached?.add(part.key);
      if (!effective) return definition.originalText;
      if (!this.inheritedEnabled(part.key)) return '';
      return this.state.edits[part.key]?.text ?? definition.originalText;
    }
    if (part.type === 'join') return part.parts.map((child) => this.render(child, effective, reached))
      .filter((text) => text.length > 0).join(part.separator);
    if (part.type === 'wrap') {
      const text = this.render(part.part, effective, reached);
      return text.length > 0 ? `${part.prefix}${text}${part.suffix}` : '';
    }
    if (part.type === 'extension') {
      if (effective && !this.inheritedEnabled(part.leaf.key)) return this.render(part.previous, true, reached);
      const text = this.render(part.leaf, effective, reached);
      return part.mode === 'append' ? this.render(part.previous, effective, reached) + text : text;
    }
    return '';
  }

  refresh({ reload = true } = {}) {
    if (reload) this.load();
    this.definitions = new Map();
    for (const group of Object.keys(groupNames)) this.defineGroup(group);
    const base = this.runBase ?? this.session?._baseSystemPromptOptions;
    let representation = base ? this.baseRepresentation(base) : joinParts([]);
    if (base?.forceSystemPrompt !== undefined) {
      const leaf = this.leaf('extensions', 'configured-force', '完整系统提示词替换', base.forceSystemPrompt,
        { contributionKind: 'replacement' });
      representation = { type: 'extension', previous: representation, leaf, mode: 'replace' };
    }
    for (const record of this.records) {
      const widget = widgetOwner(record.path);
      const parent = widget
        ? this.sourceDirectory('widgets', `widget:${widget}`, widget, { path: record.path })
        : this.sourceDirectory('extensions', `extension:${record.extensionKey}`, record.extensionName, { path: record.path });
      const before = this.render(representation, false);
      if (record.before !== before) {
        const leaf = this.leaf(parent, `transition:${record.key}`, `${record.name} · 前置上下文`, record.before,
          { path: record.path, contributionKind: 'replacement' });
        representation = { type: 'extension', previous: representation, leaf, mode: 'replace' };
      }
      if (record.mode === 'sections' && representation.sectionNames) {
        const previous = new Map(representation.sectionNames.map((name, index) => [name, representation.parts[index]]));
        const names = [...Object.keys(record.afterSections),
          ...Object.keys(record.beforeSections).filter((name) => record.afterSections[name] === undefined)];
        const parts = names.map((name) => {
          if (record.beforeSections[name] === record.afterSections[name] && previous.has(name)) return previous.get(name);
          const leaf = this.leaf(parent, `segment:${record.key}/section:${name}`, `${record.name} · ${sectionNames[name] ?? name}`,
            record.afterSections[name] ?? '', { path: record.path, contributionKind: 'extension-section' });
          return { type: 'extension', previous: previous.get(name) ?? joinParts([]), leaf, mode: 'replace' };
        });
        representation = { ...joinParts(parts, '\n\n'), sectionNames: names };
        continue;
      }
      const text = record.mode === 'append' ? record.after.slice(record.before.length) : record.after;
      const leaf = this.leaf(parent, `segment:${record.key}`, record.name, text,
        { path: record.path, contributionKind: record.mode === 'append' ? 'extension-append' : 'extension-replacement' });
      representation = { type: 'extension', previous: representation, leaf, mode: record.mode };
    }
    const renderedOriginal = this.render(representation, false);
    if (this.modelPrompt !== undefined && this.modelPrompt !== renderedOriginal) {
      const leaf = this.leaf('extensions', 'request-projection', 'Pi 请求上下文变化', this.modelPrompt,
        { contributionKind: 'request-projection' });
      representation = { type: 'extension', previous: representation, leaf, mode: 'replace' };
    }
    this.representation = representation;
    const originalText = this.render(representation, false);
    const reached = new Set();
    const effectiveText = this.render(representation, this.enabled, reached);
    this.nodes = new Map();
    const makeNode = (key) => {
      const definition = this.definitions.get(key);
      const enabled = this.inheritedEnabled(key);
      let node;
      if (definition.directory) {
        const children = definition.children.map(makeNode);
        const checks = children.map((child) => child.checkState);
        const checkState = checks.length === 0 ? (enabled ? 2 : 0)
          : checks.every((state) => state === 2) ? 2 : checks.every((state) => state === 0) ? 0 : 1;
        const shadowed = children.length > 0 && children.every((child) => child.shadowed);
        const partlyShadowed = !shadowed && children.some((child) => child.shadowed || child.partlyShadowed);
        node = { id: definition.id, name: definition.name, children, enabled: checkState !== 0,
          checkState, modified: children.some((child) => child.modified), stale: children.some((child) => child.stale),
          shadowed, partlyShadowed,
          ...(shadowed ? { note: '被后续提示词替换覆盖，当前未注入模型。' }
            : partlyShadowed ? { note: '部分内容被后续提示词替换覆盖。' } : {}),
          ...(definition.labelKey ? { labelKey: definition.labelKey } : {}),
          ...(definition.path ? { path: definition.path } : {}) };
      } else {
        const edit = this.state.edits[key];
        const text = edit?.text ?? definition.originalText;
        const shadowed = !reached.has(key) && (!this.enabled || enabled);
        node = { id: definition.id, name: definition.name, enabled, checkState: enabled ? 2 : 0,
          modified: Boolean(edit), stale: Boolean(edit && edit.originalText !== definition.originalText),
          shadowed, ...(shadowed ? { note: '被后续提示词替换覆盖，当前未注入模型。' } : {}),
          originalText: definition.originalText, currentText: text,
          effectiveText: shadowed ? '' : !this.enabled ? definition.originalText : enabled ? text : '',
          ...(definition.labelKey ? { labelKey: definition.labelKey } : {}),
          ...(definition.path ? { path: definition.path } : {}), contributionKind: definition.contributionKind };
      }
      this.nodes.set(node.id, { key, node });
      return node;
    };
    const tree = Object.keys(groupNames)
      .filter((group) => !optionalGroups.has(group) || this.definitions.get(`group:${group}`).children.length)
      .map((group) => makeNode(`group:${group}`));
    this.snapshot = { tree, originalCharacters: originalText.length, effectiveCharacters: effectiveText.length,
      originalText, effectiveText, originalPrompt: originalText, effectivePrompt: effectiveText,
      enabled: this.enabled, dynamicStatus: this.dynamic ? 'last-run' : 'not-run' };
    try { this.onChange?.(this.snapshot); } catch {}
    return this.snapshot;
  }

  async mutate({ action, promptOperation, id, enabled, text } = {}) {
    action ??= promptOperation;
    this.refresh();
    const found = id ? this.nodes.get(id) : undefined;
    if (id && !found) throw new Error('Unknown system prompt source');
    if (action === 'restore' || action === 'reset') {
      const prefix = found ? `${found.key}/` : '';
      for (const collection of [this.state.edits, this.state.toggles]) {
        for (const key of Object.keys(collection)) {
          if (!found || key === found.key || key.startsWith(prefix)) delete collection[key];
        }
      }
    } else if (action === 'toggle') {
      if (!found || typeof enabled !== 'boolean') throw new Error('toggle needs a source and enabled flag');
      if (this.definitions.get(found.key).directory) {
        for (const key of Object.keys(this.state.toggles)) {
          if (key.startsWith(`${found.key}/`)) delete this.state.toggles[key];
        }
      }
      this.state.toggles[found.key] = enabled;
    } else if (action === 'save') {
      if (!found || found.node.children || typeof text !== 'string') throw new Error('save needs a leaf and text');
      const originalText = this.state.edits[found.key]?.originalText ?? found.node.originalText;
      if (text === found.node.originalText) delete this.state.edits[found.key];
      else this.state.edits[found.key] = { originalText, text };
    } else if (action !== 'refresh' && action !== 'inspect' && action !== undefined) {
      throw new Error('Unknown system prompt operation');
    }
    this.persist();
    return this.refresh({ reload: false });
  }
}

function canonicalExtension(extension) {
  const path = extension.resolvedPath ?? extension.path;
  return path.startsWith('<') || path.startsWith('builtin:') ? path : canonical(path);
}
// Extensions shipped inside a Widget package are listed under that Widget.
function widgetOwner(path) {
  const match = /(?:^|[\\/])(?:umeko-plugins|desktop-plugins[\\/]packages)[\\/]([^\\/]+)/i.exec(path ?? '');
  return match?.[1];
}
function extensionName(extension) {
  const path = extension.resolvedPath ?? extension.path;
  if (path.startsWith('<inline:')) {
    const name = path.slice('<inline:'.length, -1);
    return /^\d+$/.test(name) ? `内联扩展 ${name}` : name.replace(/[-_]/g, ' ');
  }
  if (path.startsWith('builtin:')) return path.slice('builtin:'.length);
  return basename(path);
}
