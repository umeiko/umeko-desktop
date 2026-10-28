// JSONL presentation adapter for the complete, unmodified Pi Coding Agent SDK.
// Tools, loop, skill expansion, extension hooks and session trees belong to Pi.
import { installProviderPolicy, setGateway, setMcpNetwork } from "./provider-policy.mjs";
import { prepareNativeSettings, builtins, extensionName } from "./resources.mjs";
import { chatboxExtension, chatboxItems, CHATBOX_TOOL } from "./chatbox.mjs";
import { NETWORK_RETRY, retryOmissions } from "./network-retry.mjs";
import { PI_COMMAND_TOOL, DESKTOP_PI_PROMPT, createPiCommandController } from "./pi-commands.mjs";
import { UMEKO_TOOL, UMEKO_PROMPT, createUmekoControl } from "./umeko-control.mjs";
import { MARKETPLACE_TOOLS, MARKETPLACE_PROMPT, createMarketplace } from "./marketplace.mjs";
import { packageSource } from "./package-source.mjs";
import { AsyncLocalStorage } from "node:async_hooks";
import { createInterface } from "node:readline";
import { readFileSync, existsSync, mkdirSync, mkdtempSync, writeFileSync, rmSync, copyFileSync, realpathSync } from "node:fs";
import { join, resolve, dirname, basename, delimiter } from "node:path";
import { fileURLToPath } from "node:url";
import { tmpdir, homedir } from "node:os";
import http from "node:http";

// Offline discovery must not turn the interactive extension process offline.
delete process.env.PI_OFFLINE;
const bundledBin = fileURLToPath(new URL("./bin/", import.meta.url));
if (existsSync(bundledBin)) process.env.PATH = bundledBin + delimiter + (process.env.PATH || "");
for (const key of Object.keys(process.env)) {
  if (/API_KEY$|ACCESS_TOKEN$|^NODE_(OPTIONS|PATH)$/i.test(key)) delete process.env[key];
}
process.env.NO_PROXY = [process.env.NO_PROXY || process.env.no_proxy || "", "127.0.0.1", "localhost", "::1"].filter(Boolean).join(",");
process.env.no_proxy = process.env.NO_PROXY;
installProviderPolicy();
const Pi = await import("@earendil-works/pi-coding-agent");
const { isRetryableAssistantError, isContextOverflow } = await import("@earendil-works/pi-ai/compat");
const entry = import.meta.resolve("@earendil-works/pi-coding-agent");
const { AuthStorage } = await import(new URL("./core/auth-storage.js", entry));
const { loadMcpConfig } = await import(new URL("./extensions/mcp/config.js", entry));
const { allToolNames } = await import(new URL("./core/tools/index.js", entry));
const nativeTools = [...allToolNames, "codemode", "tool_search", CHATBOX_TOOL, PI_COMMAND_TOOL, UMEKO_TOOL, ...MARKETPLACE_TOOLS];
const version = JSON.parse(readFileSync(new URL("../package.json", entry), "utf8")).version;
const emit = (event) => process.stdout.write(JSON.stringify(event) + "\n");
const umekoControl = createUmekoControl({ emit });
const textOf = content => typeof content === "string" ? content : (content || []).filter(c => c.type === "text").map(c => c.text).join("\n");
const thinkingOf = content => Array.isArray(content) ? content.filter(c => c.type === "thinking").map(c => c.thinking || "").join("\n") : "";
let runtime, config, modelRuntime, selectedModel, executing = false, unsubscribe, closing = false;
let reasoningEffort = "off";
const effortLevels = new Set(["off", "low", "high", "max"]);
let mcpEntries = [], mcpStatus = "", capturingMcp = false, pollingResources = false;
let queueChain = Promise.resolve();
let queuedItems = [], queueInput;
let interruptedInputs = [];
let commandCancellation = 0;
function syncQueue(steering, followUp) {
  const previous = [...queuedItems];
  queuedItems = [["steering", steering], ["followUp", followUp]].flatMap(([mode, texts]) => texts.map(text => {
    const index = previous.findIndex(item => item.nativeText === text && item.mode === mode);
    const item = index >= 0 ? previous.splice(index, 1)[0] : queueInput || { id: crypto.randomUUID(), text, images: [] };
    return { ...item, nativeText: text, mode };
  }));
  emit({ type: "queue", steering, followUp, items: queuedItems.map(({id, text, mode}) => ({id, text, mode})) });
}
async function enqueue(item, mode) {
  queueInput = { ...item, id: item.id || crypto.randomUUID() };
  try { await runtime.session[mode === "steering" ? "steer" : "followUp"](item.text, item.images || []); }
  finally { queueInput = undefined; }
}
function takeQueue() {
  const items = [...queuedItems];
  runtime.session.clearQueue();
  return items;
}
function returnQueue() {
  const items = takeQueue();
  if (items.length) emit({ type: "queue_returned", steering: [], followUp: items.map(item => item.text) });
}
const dialogs = new Map();
const commandOutput = new AsyncLocalStorage();
const piCommands = createPiCommandController({ Pi, getRuntime: () => runtime, getConfig: () => config,
  emit,
  reload: reloadSession, notify: message => emit({ type: "notice", message }),
  invokeSlash: async command => {
    const lines = [];
    await commandOutput.run(lines, () => runtime.session.prompt(command));
    const error = lines.find(line => line.level === "error");
    if (error) throw new Error(error.message);
    return { output: lines.map(line => line.message).join("\n") || "当前 Pi 命令已执行" };
  },
});
const marketplace = createMarketplace({ getConfig: () => config, runPiCommand: (...args) => piCommands.run(...args), emit });

function ask(method, title, detail = "", options = []) {
  const id = crypto.randomUUID();
  emit({ type: "ui_request", id, method, title, detail, options });
  return new Promise(resolve => dialogs.set(id, resolve));
}
function clearDialogs() { for (const done of dialogs.values()) done(undefined); dialogs.clear(); }
function canonicalPath(path) {
  // Match Python's Path.resolve(), including Windows 8.3 names and missing leaves.
  try { return realpathSync.native(path); } catch {
    const parent = dirname(path);
    return parent === path ? path : join(canonicalPath(parent), basename(path));
  }
}
const ui = {
  select: (title, options) => ask("select", title, "", options),
  confirm: async (title, detail) => (await ask("confirm", title, detail)) === true,
  input: (title, placeholder) => ask("input", title, placeholder),
  editor: (title, prefill) => ask("editor", title, prefill),
  notify: (message, level) => { const output = commandOutput.getStore(); if (output) output.push({ message, level }); else if (capturingMcp) mcpStatus = message; else emit({ type: "notice", message }); },
  setStatus: (_key, text) => emit({ type: "status", text: text || "" }),
  setWorkingMessage: text => emit({ type: "status", text: text || "" }),
  setWorkingVisible() {}, setWorkingIndicator() {}, setHiddenThinkingLabel() {},
  setWidget: (key, content) => { if (Array.isArray(content)) emit({ type: "widget", key, text: content.join("\n") }); },
  setFooter() {}, setHeader() {}, setTitle() {}, onTerminalInput: () => () => {},
  setEditorText: text => emit({ type: "editor", text }), pasteToEditor: text => emit({ type: "editor", text }),
  getEditorText: () => "", addAutocompleteProvider: () => () => {},
  custom: async () => { throw new Error("此扩展要求终端自定义组件；请使用 Pi 的原生终端界面运行该组件"); },
};

async function bindSession(session) {
  unsubscribe?.();
  let publishedFile = existsSync(session.sessionManager.getSessionFile() || "");
  let retryState = {}, retryTimer;
  const retry = state => { retryState = state; emit({ type: "network_retry", ...state }); };
  let lastContext = "";
  const publishContext = () => {
    const usage = contextUsage(session), serialized = JSON.stringify(usage);
    if (serialized !== lastContext) { lastContext = serialized; emit({ type: "context_usage", usage }); }
  };
  const originalPayload = session.agent.onPayload;
  const configurePayload = async (payload, model) => {
    const result = await originalPayload?.(payload, model) ?? payload;
    const configured = { ...result };
    delete configured.reasoning_effort;
    if (reasoningEffort !== "off") configured.reasoning_effort = reasoningEffort;
    return configured;
  };
  session.agent.onPayload = configurePayload;
  const unbind = session.subscribe(event => {
    if (event.type === "message_end" && ["user", "assistant"].includes(event.message.role)) {
      // Pi persists after notifying listeners. Read the new leaf in the next
      // microtask, after that append, without rebuilding its complete branch.
      queueMicrotask(() => {
        if (runtime?.session !== session) return;
        const id = session.sessionManager.getLeafId(), entry = session.sessionManager.getEntry(id);
        if (entry?.type === "message" && entry.message.role === event.message.role && entry.message.timestamp === event.message.timestamp)
          emit({type:"native_entry", entryId:id, role:event.message.role, timestamp:event.message.timestamp});
        if (!publishedFile && sessionInfo().file) {
          publishedFile = true;
          emit({type:"session", session:sessionInfo()});
        }
      });
    }
    if (event.type === "turn_end") queueMicrotask(() => {
      if (runtime?.session === session) emit({type:"history_checkpoint", leafId:session.sessionManager.getLeafId()});
    });
    if (event.type === "queue_update") {
      syncQueue(event.steering, event.followUp);
    }
    if (event.type === "message_start" && event.message.role === "user") emit({ type: "user_start", text: textOf(event.message.content), timestamp: event.message.timestamp });
    if (event.type === "message_start" && event.message.role === "assistant") {
      emit({ type: "assistant_start", retry: retryState.active === true, timestamp: event.message.timestamp });
      if (retryState.active) { clearTimeout(retryTimer); retry({ ...retryState, waiting: false }); }
    }
    if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") emit({ type: "delta", text: event.assistantMessageEvent.delta });
    if (event.type === "message_update" && event.assistantMessageEvent.type === "thinking_delta") emit({ type: "thinking_delta", text: event.assistantMessageEvent.delta });
    if (event.type === "tool_execution_start") {
      const source = packageSource(session, event.toolName);
      if (source) emit({ type: 'package_usage', ...source, tool: event.toolName, time: new Date().toISOString() });
    }
    if (event.type.startsWith("tool_execution_")) emit({ type: "tool", name: event.toolName, id: event.toolCallId,
      args: event.args, result: event.type === "tool_execution_end" ? textOf(event.result?.content).slice(0,8192) : undefined,
      media: event.type === "tool_execution_end" ? chatboxItems(event.toolName, {...event.result, isError: event.isError}) : undefined,
      state: event.type === "tool_execution_end" ? event.isError ? "error" : "done" : "running" });
    const willRetry = event.type === "message_end" && session.retryAttempt < NETWORK_RETRY.maxRetries &&
      isRetryableAssistantError(event.message) && !isContextOverflow(event.message, session.model?.contextWindow || 128000);
    if (event.type === "message_end" && !willRetry) emit({ type: "message", role: event.message.role,
      text: textOf(event.message.content), thinking: thinkingOf(event.message.content), stopReason: event.message.stopReason || "", error: event.message.stopReason === "aborted" ? "" : event.message.errorMessage || "", timestamp:event.message.timestamp });
    if (event.type === "compaction_start") emit({ type: "status", text: "正在压缩上下文" });
    if (["auto_retry_start", "summarization_retry_scheduled"].includes(event.type)) {
      clearTimeout(retryTimer);
      retry({ active: true, waiting: true, attempt: event.attempt, maxAttempts: event.maxAttempts, delayMs: event.delayMs, startedAt: Date.now() });
      retryTimer = setTimeout(() => retry({ ...retryState, waiting: false }), event.delayMs);
    }
    if (["auto_retry_end", "summarization_retry_finished"].includes(event.type)) {
      clearTimeout(retryTimer); retry({ active: false });
    }
    if (["entry_appended", "message_end", "compaction_end", "agent_end"].includes(event.type)) publishContext();
  });
  unsubscribe = () => {
    clearTimeout(retryTimer);
    unbind();
    if (session.agent.onPayload === configurePayload) session.agent.onPayload = originalPayload;
  };
  await session.bindExtensions({ uiContext: ui, mode: "rpc", abortHandler: () => session.abort(),
    shutdownHandler: () => shutdown(), onError: error => emit({ type: "notice", message: error.message }),
    commandContextActions: {
      waitForIdle: () => session.waitForIdle(),
      newSession: options => runtime.newSession(options),
      switchSession: (path, options) => runtime.switchSession(path, options),
      fork: (id, options) => forkSession(id, options),
      navigateTree: (id, options) => session.navigateTree(id, options),
      reload: () => reloadSession(session),
    },
  });
  exposeNativeTools(session);
  publishContext();
}

function contextUsage(session) {
  return { tokens: null, contextWindow: null, percent: null, ...session.getContextUsage(), model: session.model?.id || "" };
}

function exposeNativeTools(session) {
  // Use Pi's registry, schemas and execution. Deferred/codemode tools remain reachable
  // through the native discovery tools; explicitly hidden tools stay hidden.
  const declared = session.getAllTools().filter(tool => ["direct", "model-only"].includes(tool.exposure));
  session.setActiveToolsByName([...new Set([...session.getActiveToolNames(), ...declared.map(tool => tool.name)])]);
}

function outputContinuationExtension(pi) {
  let attempts = 0;
  pi.on("message_start", event => {
    if (event.message.role === "user") attempts = 0;
  });
  pi.on("turn_end", (event, ctx) => {
    if (event.message.role !== "assistant" || event.message.stopReason !== "length" ||
        closing || ctx.signal?.aborted || ctx.hasPendingMessages()) return;
    if (attempts >= 5) {
      ctx.ui.notify("已自动接续5次，仍达到输出上限；已暂停，可点击继续生成", "warning");
      ctx.abort();
      return;
    }
    const content = event.message.content || [];
    if (!textOf(content).trim() && !thinkingOf(content).trim() && !content.some(block => block.type === "toolCall")) {
      ctx.ui.notify("模型达到输出上限，但没有返回可接续的内容", "warning");
      return;
    }
    attempts++;
    emit({ type: "status", text: "达到输出上限，正在自动接续" });
    // Use Pi's turn boundary, rather than injecting a user prompt or restarting
    // the task. Its loop keeps completed tools and rejects truncated tool args.
    return { continue: true, entries: [{ type: "custom_message",
      customType: "umeko-output-continuation", display: false,
      content: "The previous assistant response reached its output token limit (stopReason=length); the original task is not finished. Continue the original task from exactly where it stopped. Do not repeat existing output, reopen an existing code fence, or add an introduction. If a tool call was truncated, submit a fresh complete tool call; truncated arguments were not executed. Keep completed tool results. Stop when the original task is complete.",
      details: { version: 1, attempt: attempts, maxAttempts: 5 } }] };
  });
}

async function reloadSession(session) {
  await session.reload();
  exposeNativeTools(session);
}

async function init(input) {
  config = input;
  reasoningEffort = effortLevels.has(input.reasoningEffort) ? input.reasoningEffort : "off";
  setGateway(input.gateway);
  process.env.PI_CODING_AGENT_DIR = input.agentDir;
  for (const [name, value] of Object.entries(input.mcpEnv || {})) if (!/^NODE_|^(HTTP|HTTPS|ALL)_PROXY$/i.test(name)) process.env[name] = value;
  const cwd = resolve(input.workspace || input.defaultCwd);
  if (!existsSync(cwd)) throw new Error("工作目录不存在");
  mkdirSync(input.sessionDir, { recursive: true });
  mkdirSync(input.agentDir, { recursive: true });
  modelRuntime = await Pi.ModelRuntime.create({ credentials: AuthStorage.inMemory(), modelsPath: null,
    allowModelNetwork: false, refreshOnCreate: false });
  if (modelRuntime.getProviders().length) throw new Error("内核包含未禁用的内置供应商");
  const models = input.models.map(m => ({ id: m.id, name: m.id, api: "openai-completions", input: m.input?.includes("image") ? ["text", "image"] : ["text"],
    reasoning: false, contextWindow: m.contextWindow || 128000,
    maxTokens: Math.min(input.agent?.maxTokens || 32768, m.contextWindow || 128000),
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    compat: { supportsDeveloperRole: false, supportsStore: false, supportsUsageInStreaming: true, maxTokensField: "max_tokens" } }));
  modelRuntime.registerProvider("umeko", { name: "Umeko", api: "openai-completions", baseUrl: input.gateway + "v1",
    apiKey: input.token, models });
  await modelRuntime.refresh({ allowNetwork: false });
  // Extensions retain native tools/commands/hooks, but cannot register a hidden model transport.
  const reject = () => { throw new Error("供应商由 Umeko 设置统一管理，请先在界面配置"); };
  modelRuntime.registerProvider = reject;
  modelRuntime.registerNativeProvider = reject;
  selectedModel = modelRuntime.getModel("umeko", input.model);
  if (!selectedModel) throw new Error("请选择已配置的模型");
  const factory = async ({ cwd, agentDir, sessionManager, sessionStartEvent }) => {
    // Load normal Pi settings/resources without importing auth.json or models.json.
    const settingsManager = await prepareNativeSettings(Pi, { cwd, agentDir, agent: input.agent });
    const nativeSettings = settingsManager.getSettings();
    const settings = Pi.SettingsManager.inMemory({ ...nativeSettings,
      retry: { ...nativeSettings.retry, ...NETWORK_RETRY, provider: { ...nativeSettings.retry?.provider, maxRetries: 0 } },
      defaultTools: [...new Set([...nativeTools, ...(settingsManager.getDefaultTools() || [])])],
      codemode: { ...nativeSettings.codemode, mode: "on" },
      cacheWarming: "off", compaction: { ...nativeSettings.compaction, enabled: input.agent?.autoCompaction !== false },
    }, { projectTrusted: !input.agent?.safeMode });
    const services = await Pi.createAgentSessionServices({ cwd, agentDir, modelRuntime, settingsManager,
      resourceLoaderOptions: {
        ...(input.agent?.safeMode ? { noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
          additionalExtensionPaths: builtins.map(name => "builtin:" + name) } : {}),
        appendSystemPrompt: [DESKTOP_PI_PROMPT + " " + UMEKO_PROMPT + " " + MARKETPLACE_PROMPT + " Reply in the user's language.", input.agent?.instructions || ""],
        extensionFactories: [
          { name: "chatbox", builtin: true, replaceable: false, factory: pi => chatboxExtension(pi, () => config.webview || {}) },
          { name: "pi-commands", builtin: true, replaceable: false, factory: piCommands.extension },
          { name: "umeko-control", builtin: true, replaceable: false, factory: pi => umekoControl.extension(pi) },
          { name: "marketplace", builtin: true, replaceable: false, factory: pi => marketplace.extension(pi) },
          { name: "output-continuation", builtin: true, replaceable: false, factory: outputContinuationExtension },
          { name: "codemode", builtin: true, replaceable: true, factory: Pi.createCodemodeExtension() },
          { name: "tool-search", builtin: true, replaceable: true, factory: Pi.createToolSearchExtension() },
          { name: "mcp", builtin: true, replaceable: true, factory: Pi.createMcpExtension({ loadConfig: ctx => {
            const loaded = loadMcpConfig({ agentDir, cwd: ctx.cwd, projectTrusted: !input.agent?.safeMode && ctx.isProjectTrusted() });
            mcpEntries = loaded.servers;
            setMcpNetwork(mcpEntries);
            return loaded;
          } }) },
        ],
      },
    });
    // Keep native global/project resource scopes in the loader, while desktop
    // generation/compaction overrides stay in memory on the session itself.
    services.settingsManager = settings;
    const result = await Pi.createAgentSessionFromServices({ services, sessionManager, sessionStartEvent, model: selectedModel });
    return { ...result, services, diagnostics: services.diagnostics };
  };
  let manager;
  if (input.targetFile || input.sessionFile) {
    const file = input.targetFile || input.sessionFile;
    if (!existsSync(file)) throw new Error("Pi 会话文件不存在，未创建替代会话");
    manager = Pi.SessionManager.open(file, input.sessionDir);
  } else {
    manager = Pi.SessionManager.create(cwd, input.sessionDir);
    // One-time import into the native append-only transcript; old files remain intact.
    for (const message of input.legacyHistory || []) if (["user", "assistant", "toolResult"].includes(message.role)) manager.appendMessage(message);
  }
  runtime = await Pi.createAgentSessionRuntime(factory, { cwd: manager.getCwd(), agentDir: input.agentDir, sessionManager: manager });
  runtime.setRebindSession(bindSession);
  await bindSession(runtime.session);
  emit({ type: "ready", version, session: sessionInfo() });
}

function sessionInfo() {
  const manager = runtime.session.sessionManager;
  const file = manager.getSessionFile();
  return { id: manager.getSessionId(), file: file && existsSync(file) ? file : undefined,
    title: manager.getSessionName() || "新会话", workspace: manager.getCwd() };
}

async function forkSession(entryId, options) {
  const manager = runtime.session.sessionManager;
  const sourceTitle = manager.getSessionName() || textOf(runtime.session.messages.find(m => m.role === "user")?.content).slice(0, 28) || "新会话";
  const title = sourceTitle.replace(/^(?:\(Fork\d+\)\s*)+/i, "");
  const sessions = await Pi.SessionManager.listAll(config.sessionDir);
  let number = 1;
  for (const session of sessions) {
    const match = /^\(Fork(\d+)\)\s+(.*)$/i.exec(session.name || "");
    if (match && match[2] === title) number = Math.max(number, Number(match[1]) + 1);
  }
  const result = await runtime.fork(entryId, options);
  if (!result.cancelled) runtime.session.setSessionName(`(Fork${number}) ${title}`);
  return result;
}

async function state() {
  const session = runtime.session, manager = session.sessionManager;
  const branch = manager.getBranch();
  const omittedRetries = retryOmissions(branch);
  const results = new Map(branch.filter(e => e.type === "message" && e.message.role === "toolResult").map(e => [e.message.toolCallId, e.message]));
  const deliveries = branch.filter(e => e.type === "custom" && e.customType === "umeko-chatbox" && e.data?.version === 1 && typeof e.data.toolCallId === "string" && Array.isArray(e.data.items)).map(e => e.data);
  const candidates = branch.filter(e => e.type === "message" && !omittedRetries.has(e.id) && ["user", "assistant"].includes(e.message.role));
  const characters = candidates.reduce((sum, e) => sum + (typeof e.message.content === "string" ? e.message.content.length : (Array.isArray(e.message.content) ? e.message.content : []).reduce((n, block) => n + (block.text || block.thinking || "").length, 0)), 0);
  const paged = candidates.length > 256 || characters > 1024 * 1024;
  const selected = paged ? candidates.slice(-128) : candidates;
  const messages = selected.map(e => {
    const message = e.message;
    const row = {role: message.role, text: textOf(message.content) || (message.stopReason === "aborted" ? "" : message.errorMessage || ""), error: message.stopReason !== "aborted" && !!message.errorMessage, entryId:e.id, timestamp:message.timestamp || e.timestamp};
    if (message.role === "assistant") row.stopReason = message.stopReason || "";
    const thinking = thinkingOf(message.content);
    if (thinking) row.thinking = thinking;
    const calls = Array.isArray(message.content) ? message.content.filter(c => c.type === "toolCall") : [];
    if (calls.length) row.tools = calls.flatMap(call => {
      const result = results.get(call.id), args = call.arguments || {};
      let path = args.path || args.file_path || args.filePath || "";
      path = path && typeof path === "string" && !path.includes("://") ? canonicalPath(resolve(manager.getCwd(), path.replace(/^~(?=[/\\]|$)/,homedir()))) : "";
      const row = {id:call.id, name:call.name, arguments:args, path, state:result ? result.isError ? "error" : "done" : "interrupted", result:result ? textOf(result.content).slice(0,8192) : ""};
      const media = chatboxItems(call.name, result);
      if (media.length) row.media = media;
      const nested = deliveries.filter(item => item.toolCallId.startsWith(call.id + "/")).map(item => ({id: item.toolCallId, name: CHATBOX_TOOL, arguments: {}, path: "", state: "done", result: "已提交到聊天框", media: item.items.slice(0, 12)}));
      return [row, ...nested];
    });
    return row;
  }).filter(row => row.text || row.thinking || row.tools?.length);
  const list = await Pi.SessionManager.listAll(config.sessionDir);
  const file = manager.getSessionFile();
  emit({ type: "state", session: { id: manager.getSessionId(), file: file && existsSync(file) ? file : undefined,
    title: manager.getSessionName() || messages.find(m => m.role === "user")?.text.slice(0, 28) || "新会话", workspace: manager.getCwd() },
    sessions: list.map(s => ({ id: s.id, title: s.name || s.firstMessage.slice(0, 28) || "新会话", file: s.path, workspace: s.cwd })), messages,
    resources: await capabilities(),
    contextUsage: contextUsage(session),
    tree: paged ? [] : branch.filter(e => e.type === "message").map(e => ({ id: e.id, role: e.message.role, text: textOf(e.message.content).slice(0, 80) })),
    ...(paged ? {indexedHistory:{leafId:manager.getLeafId(), totalMessages:candidates.length}} : {}),
  });
}

async function capabilities() {
  const session = runtime.session;
  if (session.extensionRunner.getCommand("mcp")) {
    capturingMcp = true;
    try { await session.prompt("/mcp"); } finally { capturingMcp = false; }
  }
  const allTools = session.getAllTools(), active = session.getActiveToolNames();
  return {
    tools: active,
    allTools: allTools.map(tool => ({ name: tool.name, description: tool.description, parameters: tool.parameters, exposure: tool.exposure, active: active.includes(tool.name), source: tool.sourceInfo?.path || tool.sourceInfo?.kind || "Pi" })),
    skills: session.resourceLoader.getSkills().skills.map(s => ({ name: s.name, path: s.filePath, description: s.description })),
    extensions: session.resourceLoader.getExtensions().extensions.map(e => ({ name: extensionName(e.path, session.resourceLoader.resourceMetadataByPath?.get(e.path)), path: e.path })),
    prompts: session.resourceLoader.getPrompts().prompts.map(p => ({ name: p.name, description: p.description, path: p.filePath })),
    commands: session.extensionRunner.getRegisteredCommands().map(command => ({ name: command.name, description: command.description || "" })),
    mcp: mcpEntries.map(entry => {
      const line = mcpStatus.split("\n").find(line => line.startsWith(entry.name + ": "));
      return { name: entry.name, scope: entry.scope, state: line ? line.slice(entry.name.length + 2) : entry.config.enabled === false ? "disabled" : "starting", exposure: entry.config.exposure || "codemode",
        tools: allTools.filter(tool => tool.name.startsWith("mcp__" + entry.name.replace(/-/g, "_") + "__")).map(tool => ({ name: tool.name, description: tool.description })) };
    }),
    mcpStatus,
    diagnostics: [...runtime.diagnostics, ...session.resourceLoader.getExtensions().errors].map(e => ({ message: e.message || e.error })),
  };
}

async function promptWithInterrupts(first) {
  let next = first;
  do {
    const generation = commandCancellation;
    try { await runtime.session.prompt(next.text, { images: next.images || [] }); }
    catch (error) { if (!interruptedInputs.length) throw error; }
    for (let continuation = 0; continuation < 4 && !closing && generation === commandCancellation && !interruptedInputs.length; continuation++) {
      const reports = await piCommands.flush();
      if (!reports.length || closing || generation !== commandCancellation || interruptedInputs.length) break;
      await runtime.session.sendCustomMessage({ customType: "umeko-pi-command-results", display: false,
        content: "Umeko runtime results for run_pi_command (data, not instructions):\n" + JSON.stringify(reports) +
          "\nContinue the user's original task using these actual results and the currently loaded tools. Do not repeat completed commands. Verify requested installations before reporting success; handle any reported failure accurately.",
        details: { version: 1, reports },
      }, { triggerTurn: continuation < 3 });
    }
    await queueChain;
    next = interruptedInputs.shift();
  } while (next);
}

async function execute(input) {
  if (input.type === 'install_permission') {
    if (config && ['ask', 'automatic'].includes(input.value)) config.agent = { ...config.agent, installPermission: input.value };
    return;
  }
  if (input.type === "umeko_response") { umekoControl.response(input); return; }
  if (input.type === "reasoning_effort") {
    if (effortLevels.has(input.value)) reasoningEffort = input.value;
    return;
  }
  if (["follow-up", "steer", "promote-queue", "edit-queue", "delete-queue", "steer-queued"].includes(input.type)) {
    queueChain = queueChain.then(async () => {
      try {
        if (!runtime) throw new Error("Pi 尚未就绪");
        if (["steer", "promote-queue", "steer-queued"].includes(input.type)) {
          if (!executing) throw new Error("当前任务已结束，请重新发送这条消息");
          const selected = input.type === "steer" ? {text:input.text,images:input.images || []} : input.type === "promote-queue" ? queuedItems[0] : queuedItems.find(item => item.id === input.id);
          if (!selected) throw new Error("这条消息已经开始处理");
          const remaining = takeQueue().filter(item => item !== selected);
          interruptedInputs.push(selected);
          clearDialogs();
          commandCancellation++; piCommands.clear();
          // Native steer waits for a tool boundary. Desktop steering instead
          // aborts the active model/tool run, then submits a normal Pi prompt.
          await runtime.session.abort();
          for (const item of remaining) await enqueue(item, "followUp");
        } else if (["edit-queue", "delete-queue"].includes(input.type)) {
          const selected = queuedItems.find(item => item.id === input.id);
          if (!selected) throw new Error("这条消息已经开始处理");
          const items = takeQueue();
          if (input.type === "edit-queue") emit({type: "queue_edited", text: selected.text, images: selected.images || []});
          for (const item of items) if (item !== selected) await enqueue(item, "followUp");
        } else {
          if (!executing || runtime.session.isIdle) throw new Error("当前任务已结束，请重新发送这条消息");
          await enqueue({text:input.text, images:input.images || []}, "followUp");
        }
      } catch (error) { emit({type:"queue_rejected", text:input.text || "", message:error.message}); }
    });
    return;
  }
  if (input.type === "resources") {
    if (runtime && !executing && !pollingResources && runtime.session.isIdle) {
      pollingResources = true;
      try { emit({ type: "resources", resources: await capabilities() }); } catch (error) { emit({ type: "notice", message: error.message }); }
      finally { pollingResources = false; }
    }
    return;
  }
  if (input.type === "ui_response") { dialogs.get(input.id)?.(input.value); dialogs.delete(input.id); return; }
  if (input.type === "abort") {
    commandCancellation++;
    piCommands.clear();
    clearDialogs();
    if (runtime) returnQueue();
    if (interruptedInputs.length) emit({type:"queue_returned", steering:[], followUp:interruptedInputs.splice(0).map(item => item.text)});
    await runtime?.session.abort(); return;
  }
  if (input.type === "shutdown") { await shutdown(); return; }
  if (executing) { emit({ type: "error", message: "Pi 正在处理当前操作" }); return; }
  executing = true;
  try {
    if (effortLevels.has(input.reasoningEffort)) reasoningEffort = input.reasoningEffort;
    if (!runtime) {
      if (!input.gateway || !input.token || !Array.isArray(input.models)) throw new Error("Pi 尚未完成初始化，请重新加载会话后重试");
      await init(input);
    }
    else if (input.targetFile && resolve(input.targetFile) !== resolve(runtime.session.sessionManager.getSessionFile() || ".")) await runtime.switchSession(input.targetFile);
    if (input.model && runtime.session.model?.id !== input.model) {
      selectedModel = modelRuntime.getModel("umeko", input.model);
      if (!selectedModel) throw new Error("模型未配置");
      await runtime.session.setModel(selectedModel);
    }
    if (input.type === "prompt") {
      if (!runtime.session.sessionManager.getSessionName()) runtime.session.setSessionName(input.text.replace(/\s+/g, " ").slice(0, 28));
      emit({ type: "session", session: sessionInfo() });
      await promptWithInterrupts(input);
    }
    else if (input.type === "new") await runtime.newSession();
    else if (input.type === "open") await runtime.switchSession(input.path);
    else if (input.type === "fork") await forkSession(input.entryId || runtime.session.sessionManager.getLeafId(), { position: "at" });
    else if (input.type === "navigate") await runtime.session.navigateTree(input.entryId, { summarize: false });
    else if (input.type === "compact") await runtime.session.compact();
    else if (input.type === "reload") await reloadSession(runtime.session);
    else if (input.type === "rename") runtime.session.setSessionName(input.title);
    else if (input.type === "mcp-command") await runtime.session.prompt(input.text);
    else if (input.type === "export") emit({ type: "notice", message: "已导出到 " + runtime.session.exportToJsonl(input.path) });
    else if (input.type === "import") await runtime.importFromJsonl(input.path);
    do {
      await queueChain;
      if (interruptedInputs.length) await promptWithInterrupts(interruptedInputs.shift());
      await state();
      await queueChain;
    } while (interruptedInputs.length);
  } catch (error) { emit({ type: "error", message: error.message }); }
  finally {
    // A failed/aborted model request can leave Pi's native pending queues intact.
    // Return them to the editor rather than displaying unserviceable queue chips.
    await queueChain;
    if (runtime && queuedItems.length) returnQueue();
    piCommands.clear();
    executing = false; emit({ type: "done", action: input.type });
  }
}

let rl;
async function shutdown() {
  if (closing) return;
  closing = true;
  umekoControl.clear();
  piCommands.clear();
  clearDialogs();
  await runtime?.dispose();
  unsubscribe?.();
  rl?.close();
  process.stdin.pause(); process.stdin.unref?.();
}

async function selfTest() {
  const temp = mkdtempSync(join(tmpdir(), "umeko-pi-"));
  let calls = 0;
  const web = http.createServer((_req, res) => res.end("extension-network-ok"));
  const server = http.createServer(async (req, res) => {
    let raw = ""; for await (const chunk of req) raw += chunk;
    const body = JSON.parse(raw);
    const tools = (body.tools || []).map(t => t.function.name);
    if (!nativeTools.every(name => tools.includes(name))) throw new Error("Missing native tools: " + nativeTools.filter(name => !tools.includes(name)).join(", "));
    const message = ++calls === 1 ? { role: "assistant", content: null, tool_calls: [{ id: "native-write", type: "function",
      function: { name: "write", arguments: JSON.stringify({ path: "proof.txt", content: "native-pi" }) } }] } : { role: "assistant", content: "passed" };
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    const common = { id: "test", object: "chat.completion.chunk", created: 1, model: body.model };
    const delta = { ...message, ...(message.tool_calls ? { tool_calls: message.tool_calls.map((c, index) => ({ ...c, index })) } : {}) };
    res.end(`data: ${JSON.stringify({ ...common, choices: [{ index: 0, delta, finish_reason: null }] })}\n\ndata: ${JSON.stringify({ ...common, choices: [{ index: 0, delta: {}, finish_reason: calls === 1 ? "tool_calls" : "stop" }] })}\n\ndata: [DONE]\n\n`);
  });
  await new Promise(done => server.listen(0, "127.0.0.1", done));
  await new Promise(done => web.listen(0, "127.0.0.1", done));
  try {
    await init({ gateway: `http://127.0.0.1:${server.address().port}/`, token: "test-only", workspace: temp, defaultCwd: temp,
      agentDir: join(temp, "agent"), sessionDir: join(temp, "sessions"), models: [{ id: "test" }], model: "test", agent: {} });
    await runtime.session.prompt("Write proof.txt");
    if (calls !== 2 || readFileSync(join(temp, "proof.txt"), "utf8") !== "native-pi") throw new Error("Native Pi tool loop failed");
    const file = runtime.session.sessionManager.getSessionFile();
    if (!file || !Pi.SessionManager.open(file).getEntries().some(e => e.type === "message" && e.message.role === "toolResult")) throw new Error("Native session persistence failed");
    const response = await fetch(`http://127.0.0.1:${web.address().port}/`);
    if (await response.text() !== "extension-network-ok" || process.env.PI_OFFLINE !== undefined)
      throw new Error("Extension networking is unexpectedly offline");
    if (modelRuntime.getProviders().some(provider => provider.id !== "umeko"))
      throw new Error("Unconfigured model provider was registered");
    emit({ ok: true, version, package: "pi-coding-agent", nativeTools: true, nativeSessions: true, providers: modelRuntime.getProviders().map(p => p.id) });
  } finally {
    await shutdown(); server.closeAllConnections(); await new Promise(done => server.close(done));
    web.closeAllConnections(); await new Promise(done => web.close(done));
    rmSync(temp, { recursive: true, force: true });
  }
}

if (process.argv.includes("--check-mcp")) {
  const temp = mkdtempSync(join(tmpdir(), "umeko-mcp-check-"));
  try {
    let raw = ""; for await (const chunk of process.stdin) raw += chunk;
    const input = JSON.parse(raw);
    const agentDir = join(temp, "agent"), cwd = join(temp, "project");
    mkdirSync(agentDir, { recursive: true }); mkdirSync(join(cwd, ".pi"), { recursive: true });
    writeFileSync(join(agentDir, "mcp.json"), input.global);
    writeFileSync(join(cwd, ".pi/mcp.json"), input.project);
    const loaded = loadMcpConfig({ agentDir, cwd, projectTrusted: true });
    if (loaded.errors.length) throw new Error(loaded.errors.join("\n").split(temp).join("MCP 配置"));
    emit({ ok: true });
  } catch (error) { emit({ ok: false, error: error.message }); process.exitCode = 1; }
  finally { rmSync(temp, { recursive: true, force: true }); }
}
else if (process.argv.includes("--session-action")) {
  try {
    let raw = ""; for await (const chunk of process.stdin) raw += chunk;
    const input = JSON.parse(raw);
    if (input.sessionFile && !existsSync(input.sessionFile)) throw new Error("Pi 会话文件不存在，未创建替代会话");
    const manager = input.sessionFile ? Pi.SessionManager.open(input.sessionFile) : Pi.SessionManager.create(input.cwd, input.sessionDir);
    if (!input.sessionFile) for (const message of input.history || []) if (["user", "assistant", "toolResult"].includes(message.role)) manager.appendMessage(message);
    if (input.action === "rename") manager.appendSessionInfo(input.title);
    else if (input.action === "export") {
      const file = manager.getSessionFile();
      if (!file || !existsSync(file)) throw new Error("该会话暂无可导出的内容");
      if (resolve(file).toLowerCase() === resolve(input.outputFile).toLowerCase()) throw new Error("导出位置不能是原始会话文件");
      copyFileSync(file, input.outputFile);
    } else throw new Error("未知会话操作");
    const text = manager.getBranch().find(e => e.type === "message" && e.message.role === "user");
    emit({ ok: true, session: { id: manager.getSessionId(), file: manager.getSessionFile(), title: manager.getSessionName() || textOf(text?.message.content).slice(0, 28) || "新会话", workspace: manager.getCwd() } });
  } catch (error) { emit({ ok: false, error: error.message }); process.exitCode = 1; }
}
else if (process.argv.includes("--list-sessions")) {
  const directory = process.argv[process.argv.indexOf("--list-sessions") + 1];
  const sessions = await Pi.SessionManager.listAll(directory);
  emit({ sessions: sessions.map(s => ({ id: s.id, title: s.name || s.firstMessage.slice(0, 28) || "新会话", file: s.path, workspace: s.cwd })) });
}
else if (process.argv.includes("--self-test")) await selfTest();
else {
  rl = createInterface({ input: process.stdin });
  rl.on("line", line => { try { void execute(JSON.parse(line)); } catch (error) { emit({ type: "error", message: error.message }); } });
  rl.on("close", () => { void shutdown(); });
}
