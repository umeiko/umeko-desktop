// JSONL presentation adapter for the official DeepSeek Harness ACP profile.
// Credentials belong to the inherited child environment, never this control stream.
import { spawn } from 'node:child_process';
import { Readable, Writable } from 'node:stream';
import { createInterface } from 'node:readline';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { mkdirSync, mkdtempSync, writeFileSync, unlinkSync, rmdirSync } from 'node:fs';
import { join } from 'node:path';
import { createRequire } from 'node:module';

export function resolveSdkEntry(runtimeDirectory) {
  return createRequire(import.meta.url).resolve('@agentclientprotocol/sdk', {
    paths: [runtimeDirectory, join(runtimeDirectory, 'releases', 'coding-1.3.0')],
  });
}

const { client, ndJsonStream } = await import(pathToFileURL(resolveSdkEntry(dirname(fileURLToPath(import.meta.url)))).href);

const textOf = blocks => (blocks ?? []).map(block => {
  if (block.type === 'content') return block.content?.type === 'text' ? block.content.text : '';
  return block.type === 'text' ? block.text : '';
}).filter(Boolean).join('\n');

export function advertisedModelValue(options, model) {
  const flatten = list => list.flatMap(option => option.options ? flatten(option.options) : [option]);
  const choices = flatten(options.find(option => option.id === 'model')?.options ?? []);
  return choices.find(option => {
    try {
      const pair = JSON.parse(option.value);
      return Array.isArray(pair) && pair[0] === model.provider && pair[1] === model.id;
    } catch { return false; }
  })?.value;
}

export function projectTool(previous = {}, update = {}) {
  const merged = { ...previous, ...update };
  const state = merged.status === 'failed' ? 'error' : merged.status === 'completed' ? 'done' : 'running';
  const output = textOf(merged.content);
  return {
    record: merged,
    event: {
      type: 'tool', id: merged.toolCallId,
      name: merged.title ?? previous.title ?? 'tool',
      args: merged.rawInput ?? previous.rawInput ?? {}, state,
      result: output || (merged.rawOutput === undefined ? '' : typeof merged.rawOutput === 'string' ? merged.rawOutput : JSON.stringify(merged.rawOutput)),
    },
  };
}

export class DshAcpBridge {
  constructor({ emit = () => {}, spawnProcess = spawn, env = process.env, onFatal = () => {} } = {}) {
    this.emit = emit;
    this.spawnProcess = spawnProcess;
    this.env = env;
    this.onFatal = onFatal;
    this.permissions = new Map();
    this.tools = new Map();
    this.sequence = 0;
    this.closing = false;
    this.busy = false;
    this.configTail = Promise.resolve();
    this.permissionTail = Promise.resolve();
    this.modeRequests = new Map();
    this.modeSequence = 0;
  }

  reportFailure(message) {
    this.busy = false;
    this.cancelPermissions();
    if (this.failureReported) return;
    this.failureReported = true;
    this.emit({ type: 'error', message });
    this.emit({ type: 'dsh_done', stopReason: 'error' });
  }

  async connect({ runtime, home, workspace, patchFiles = [], permissionMode, useOwnConfig = false }) {
    if (this.child) throw new Error('DeepSeek Harness 已启动');
    if (!runtime || (!useOwnConfig && !home) || !workspace) throw new Error('DeepSeek Harness 的运行入口、独立目录或工作区缺失');
    this.workspace = resolve(workspace);
    this.permissionManaged = permissionMode !== undefined;
    this.permissionMode = permissionMode;
    const isScript = /\.[cm]?js$/i.test(runtime);
    this.child = this.spawnProcess(isScript ? process.execPath : runtime,
      [...(isScript ? [runtime] : []), '--profile', 'acp', ...patchFiles.flatMap(file => ['--patch', file])], {
        cwd: this.workspace, env: useOwnConfig ? { ...this.env } : { ...this.env, DSH_HOME: resolve(home) },
        windowsHide: true, stdio: ['pipe', 'pipe', 'pipe', ...(this.permissionManaged ? ['ipc'] : [])],
      });
    const child = this.child;
    child.on('message', message => {
      if (message?.type !== 'umeko_tool_permission_mode_applied') return;
      const request = this.modeRequests.get(message.id);
      if (!request) return;
      request.finish(!message.error && message.mode === request.mode);
    });
    // Do not echo runtime stderr: it may contain upstream request details.
    child.stderr?.on('data', () => {});
    this.exited = new Promise(done => {
      child.once('exit', (code, signal) => {
        this.exitObserved = true;
        for (const request of [...this.modeRequests.values()]) request.finish(false);
        this.cancelPermissions();
        if (!this.closing) {
          this.reportFailure('DeepSeek Harness 进程已退出，请检查运行环境后重新打开会话');
          this.connection?.close();
          this.onFatal();
        }
        done({ code, signal });
      });
      child.once('error', () => {
        this.exitObserved = true;
        for (const request of [...this.modeRequests.values()]) request.finish(false);
        this.cancelPermissions();
        if (!this.closing) {
          this.reportFailure('DeepSeek Harness 无法启动，请检查运行入口');
          this.connection?.close();
          this.onFatal();
        }
        done({ code: 1 });
      });
    });
    const app = client({ name: 'umeko-dsh-acp' })
      .onNotification('session/update', ({ params }) => this.update(params))
      .onRequest('session/request_permission', ({ params, signal }) => this.permission(params, signal));
    this.connection = app.connect(ndJsonStream(Writable.toWeb(child.stdin), Readable.toWeb(child.stdout)));
    this.agent = this.connection.agent;
    return this.agent.request('initialize', {
      protocolVersion: 1, clientInfo: { name: 'umeko', version: '1' },
      clientCapabilities: { fs: { readTextFile: false, writeTextFile: false }, terminal: false },
    }, { signal: AbortSignal.timeout(30000) });
  }

  async start(spec) {
    this.failureReported = false;
    this.starting = true;
    try {
    const initialized = await this.connect(spec);
    if (this.permissionManaged) {
      this.permissionInitialized = true;
      await this.setPermissionMode(this.permissionMode);
    }
    this.capabilities = initialized.agentCapabilities ?? {};
    let session;
    if (spec.sessionId) {
      if (!this.capabilities.sessionCapabilities?.resume) throw new Error('当前 DeepSeek Harness 不支持恢复会话');
      session = await this.agent.request('session/resume', { sessionId: spec.sessionId, cwd: this.workspace, mcpServers: [] }, { signal: AbortSignal.timeout(30000) });
      this.sessionId = spec.sessionId;
    } else {
      session = await this.agent.request('session/new', { cwd: this.workspace, mcpServers: [] }, { signal: AbortSignal.timeout(30000) });
      this.sessionId = session.sessionId;
    }
    this.configOptions = session.configOptions ?? [];
    for (const config of spec.config ?? []) await this.setConfig(config, false);
    if (!spec.useOwnConfig && spec.model?.provider && spec.model?.id) {
      const value = advertisedModelValue(this.configOptions, spec.model);
      if (value === undefined) throw new Error('DeepSeek Harness 没有提供所选模型');
      await this.setConfig({ configId: 'model', value }, false);
    }
    if (!spec.useOwnConfig && spec.reasoningEffort !== undefined) {
      const reasoning = this.configOptions.find(option => option.id === 'reasoning_effort');
      if (reasoning?.options?.some(option => option.value === spec.reasoningEffort)) {
        await this.setConfig({ configId: 'reasoning_effort', value: spec.reasoningEffort }, false);
      }
    }
    this.emit({ type: 'dsh_session', sessionId: this.sessionId, configOptions: this.configOptions, capabilities: this.capabilities });
    this.emit({ type: 'dsh_ready' });
    if (this.cancelRequested || this.closing) {
      await this.cancel();
      this.emit({ type: 'dsh_done', stopReason: 'cancelled' });
      return;
    }
    if (spec.action === 'prompt') return this.prompt(spec.text ?? '', [], spec.interruptionNotice ?? '');
    this.emit({ type: 'dsh_done', stopReason: 'end_turn' });
    } catch (error) {
      this.reportFailure('DeepSeek Harness 启动会话失败，请检查运行环境、模型设置或会话状态');
      await this.shutdown();
      error.dshReported = true;
      throw error;
    } finally {
      this.starting = false;
    }
  }

  update({ sessionId, update }) {
    if (this.sessionId && sessionId !== this.sessionId) return;
    switch (update.sessionUpdate) {
      case 'agent_message_chunk':
      case 'agent_thought_chunk':
        if (update.content?.type === 'text') {
          const thought = update.sessionUpdate === 'agent_thought_chunk';
          if (!this.assistantStarted || (!thought && this.assistantTextSeen)) {
            this.emit({ type: 'assistant_start' });
            this.assistantStarted = true;
            this.assistantTextSeen = false;
          }
          if (!thought) this.assistantTextSeen = true;
          this.emit({ type: thought ? 'thinking_delta' : 'delta', text: update.content.text });
        }
        break;
      case 'tool_call':
      case 'tool_call_update': {
        const projected = projectTool(this.tools.get(update.toolCallId), update);
        this.tools.set(update.toolCallId, projected.record);
        this.emit(projected.event);
        this.assistantStarted = false;
        this.assistantTextSeen = false;
        break;
      }
      case 'config_option_update':
        this.configOptions = update.configOptions ?? [];
        this.emit({ type: 'dsh_config', configOptions: this.configOptions });
        break;
      case 'usage_update': {
        const used = Number(update.used), size = Number(update.size);
        if (Number.isFinite(used) && Number.isFinite(size)) this.emit({
          type: 'context_usage', usage: { tokens: used, contextWindow: size, percent: size > 0 ? used / size * 100 : 0 },
        });
        break;
      }
    }
  }

  permission(params, signal) {
    const id = `dsh-permission-${++this.sequence}`;
    return new Promise(resolvePermission => {
      const finish = value => {
        if (!this.permissions.delete(id)) return;
        signal?.removeEventListener('abort', abort);
        resolvePermission(value);
      };
      const abort = () => finish({ outcome: { outcome: 'cancelled' } });
      this.permissions.set(id, { params, finish });
      signal?.addEventListener('abort', abort, { once: true });
      if (signal?.aborted || this.closing) return abort();
      const offeredTool = params.toolCall ?? {};
      const cachedTool = this.tools.get(offeredTool.toolCallId) ?? {};
      const tool = {
        ...cachedTool, ...offeredTool,
        title: typeof offeredTool.title === 'string' && offeredTool.title.trim() ? offeredTool.title : cachedTool.title,
        rawInput: offeredTool.rawInput ?? cachedTool.rawInput,
      };
      const note = textOf(tool.content);
      const detail = [tool.title || '工具调用', tool.rawInput == null ? '' : JSON.stringify(tool.rawInput), note].filter(Boolean).join('\n');
      // The structured copies only feed the readable dialog; detail stays the full record.
      this.emit({
        type: 'ui_request', backend: 'dsh', id, toolCallId: tool.toolCallId, method: 'confirm', title: 'DeepSeek Harness 请求授权',
        message: detail, detail, options: params.options,
        toolTitle: tool.title || '', toolKind: tool.kind || '', rawInput: tool.rawInput ?? null, toolContent: note,
      });
    });
  }

  respond({ id, value }) {
    const request = this.permissions.get(id);
    if (!request) return;
    const kind = value === true ? 'allow_once' : value === false ? 'reject_once' : undefined;
    const choice = request.params.options.find(option => option.kind === kind);
    request.finish(choice ? { outcome: { outcome: 'selected', optionId: choice.optionId } } : { outcome: { outcome: 'cancelled' } });
  }

  cancelPermissions() {
    for (const { finish } of [...this.permissions.values()]) finish({ outcome: { outcome: 'cancelled' } });
  }

  async prompt(text, config = [], interruptionNotice = '') {
    if (!this.sessionId || this.closing) throw new Error('DeepSeek Harness 会话尚未就绪');
    if (this.busy) throw new Error('DeepSeek Harness 正在处理上一条消息');
    this.busy = true;
    this.failureReported = false;
    this.cancelRequested = false;
    this.assistantStarted = false;
    this.assistantTextSeen = false;
    try {
      await this.configTail;
      await this.permissionTail;
      for (const option of config) await this.setConfig(option);
      if (this.cancelRequested || this.closing) {
        const result = { stopReason: 'cancelled' };
        this.emit({ type: 'dsh_done', ...result });
        return result;
      }
      // ACP has no host status-message role. Keep the persisted Stop note in
      // its own standard block, separate from the unchanged user text. DSH
      // joins adjacent text blocks, so the boundary includes blank lines.
      const prompt = [...(interruptionNotice ? [{ type: 'text', text: interruptionNotice + '\n\n' }] : []),
        { type: 'text', text }];
      const result = await this.agent.request('session/prompt', { sessionId: this.sessionId, prompt });
      this.emit({ type: 'dsh_done', stopReason: result.stopReason });
      return result;
    } catch (error) {
      this.reportFailure('DeepSeek Harness 处理消息失败，请检查模型设置或重新打开会话');
      error.dshReported = true;
      throw error;
    } finally {
      this.busy = false;
      this.cancelPermissions();
    }
  }

  async cancel() {
    this.cancelRequested = true;
    this.cancelPermissions();
    if (this.agent && this.sessionId) await this.agent.notify('session/cancel', { sessionId: this.sessionId });
  }

  setConfig(option, publish = true) {
    const operation = this.configTail.catch(() => {}).then(() => this.applyConfig(option, publish));
    this.configTail = operation;
    return operation;
  }

  setPermissionMode(mode) {
    if (mode !== 'auto' && mode !== 'ask') return Promise.reject(new Error('工具权限模式只能为 auto 或 ask'));
    this.permissionMode = mode;
    // Latch changes during official profile startup. Initialization completes
    // only after the profile's permission extension has registered its channel.
    if (!this.permissionInitialized) return Promise.resolve();
    const operation = this.permissionTail.catch(() => {}).then(() => this.applyPermissionMode(mode));
    this.permissionTail = operation;
    return operation;
  }

  async applyPermissionMode(mode) {
    try {
      if (!this.permissionManaged || !this.child?.connected || this.closing) throw new Error('permission channel unavailable');
      const id = `mode-${++this.modeSequence}`;
      await new Promise((resolveMode, rejectMode) => {
        const finish = ok => {
          if (!this.modeRequests.delete(id)) return;
          clearTimeout(timer);
          if (ok) resolveMode();
          else rejectMode(new Error('permission mode was not applied'));
        };
        const timer = setTimeout(() => finish(false), 30000);
        this.modeRequests.set(id, { mode, finish });
        try {
          this.child.send({ type: 'umeko_tool_permission_mode', id, value: mode }, error => { if (error) finish(false); });
        } catch { finish(false); }
      });
    } catch (error) {
      this.reportFailure('DeepSeek Harness 权限同步失败，已停止此运行时；请重新打开会话。');
      await this.shutdown();
      error.dshReported = true;
      throw error;
    }
  }

  async applyConfig({ configId, value }, publish = true) {
    if (!this.sessionId || this.closing) throw new Error('DeepSeek Harness 会话尚未就绪');
    const response = await this.agent.request('session/set_config_option', { sessionId: this.sessionId, configId, value }, { signal: AbortSignal.timeout(30000) });
    this.configOptions = response.configOptions ?? [];
    if (publish) this.emit({ type: 'dsh_config', configOptions: this.configOptions });
    return response;
  }

  async shutdown() {
    if (this.shutdownPromise) return this.shutdownPromise;
    this.closing = true;
    this.shutdownPromise = (async () => {
      this.cancelPermissions();
      if (this.agent && this.sessionId) {
        try { await this.agent.request('session/close', { sessionId: this.sessionId }, { signal: AbortSignal.timeout(5000) }); } catch {}
      }
      this.connection?.close();
      this.child?.stdin.end();
      if (this.child?.connected) this.child.disconnect();
      if (this.child && !this.exitObserved) {
        let timer;
        await Promise.race([this.exited, new Promise(resolveTimeout => { timer = setTimeout(resolveTimeout, 5000); })]);
        clearTimeout(timer);
        if (!this.exitObserved) {
          this.child.kill();
          await this.exited;
        }
      }
    })();
    return this.shutdownPromise;
  }
}

export async function runCli(argv = process.argv.slice(2)) {
  const emit = event => process.stdout.write(JSON.stringify(event) + '\n');
  let input;
  const bridge = new DshAcpBridge({ emit, onFatal: () => input?.close() });
  const fail = error => {
    if (!error?.dshReported) emit({ type: 'error', message: 'DeepSeek Harness 操作失败，请检查运行环境、模型设置或会话状态' });
  };
  if (argv.includes('--health')) {
    bridge.emit = () => {};
    const arg = key => { const index = argv.indexOf(key); return index < 0 ? undefined : argv[index + 1]; };
    let overlay, overlayDirectory;
    try {
      const home = arg('--dsh-home');
      if (!home) throw new Error('missing isolated home');
      mkdirSync(home, { recursive: true });
      overlayDirectory = mkdtempSync(join(home, '.umeko-health-'));
      overlay = join(overlayDirectory, 'telemetry.patch.yml');
      writeFileSync(overlay, '- id: session-telemetry-otel\n  disabled: true\n', 'utf8');
      const result = await bridge.connect({ runtime: arg('--dsh-bin'), home, workspace: process.cwd(), patchFiles: [overlay] });
      emit({ type: 'health', ok: true, result });
    } catch {
      emit({ type: 'health', ok: false, message: 'DeepSeek Harness 初始化失败，请检查运行入口与独立配置目录' });
      process.exitCode = 1;
    } finally {
      await bridge.shutdown();
      if (overlay) { try { unlinkSync(overlay); } catch {} }
      if (overlayDirectory) { try { rmdirSync(overlayDirectory); } catch {} }
    }
    return;
  }
  input = createInterface({ input: process.stdin, crlfDelay: Infinity });
  let started = false;
  input.on('line', line => {
    let message;
    try { message = JSON.parse(line); } catch { fail(); return; }
    let work;
    try {
      switch (message.type) {
        case 'start':
          if (started) throw new Error('already started');
          started = true;
          work = bridge.start(message).catch(error => { input.close(); throw error; });
          break;
        case 'prompt': work = bridge.prompt(message.text ?? '', message.config ?? [], message.interruptionNotice ?? ''); break;
        case 'cancel': work = bridge.cancel(); break;
        case 'set_config': work = bridge.setConfig(message); break;
        case 'tool_permission_mode': work = bridge.setPermissionMode(message.mode); break;
        case 'ui_response': bridge.respond(message); break;
        case 'shutdown': work = bridge.shutdown().then(() => input.close()); break;
        default: throw new Error('unsupported command');
      }
      Promise.resolve(work).catch(fail);
    } catch { fail(); }
  });
  input.on('close', () => { bridge.shutdown().catch(fail); });
  for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => { input.close(); });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await runCli();
