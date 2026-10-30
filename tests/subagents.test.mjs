import test from "node:test";
import assert from "node:assert/strict";
import { createSubagentExtension, projectSubagents, subagentTool } from "../runtime/subagents.mjs";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import http from "node:http";
import { NETWORK_RETRY } from "../runtime/network-retry.mjs";
import { upstreamFailure } from "../runtime/network-retry.mjs";

test("state projection preserves nested children, latest snapshots and continuation ownership", () => {
  const call = (id, name = "subagent") => ({ type: "toolCall", id, name, arguments: {} });
  const message = (id, content) => ({ id, type: "message", message: { role: "assistant", content } });
  const snapshot = (id, toolCallId, status, extra = {}) => ({ type: "custom", customType: "umeko-subagent",
    data: { version: 1, toolCallId, ...extra, tool: { id: "subagent:" + id, name: "subagent", state: status,
      result: status === "error" ? "Provider failed" : "", arguments: { mode: "background" },
      subagent: { id, status, isBackground: true, toolUses: status === "error" ? 2 : 0 } } } });
  const branch = [
    snapshot("unowned", undefined, "running"),
    message("nested-owner", [call("code-1", "code_execution")]),
    snapshot("nested", "code-1/worker-1", "running"),
    message("direct-owner", [call("direct")]), snapshot("direct", "direct", "running"),
    message("explicit-owner", [{ type: "text", text: "Explicit owner" }]),
    message("later", [call("resume"), call("ordinary"), call("read", "read")]),
    snapshot("explicit", "unrelated", "error", { ownerEntryId: "explicit-owner" }),
    snapshot("nested", "code-1/worker-1", "error"),
    { type: "custom", customType: "umeko-subagent-link", data: { version: 1,
      toolCallId: "resume", subagentId: "subagent:nested" } },
    snapshot("direct", "resume", "error"),
    message("fallback-owner", [{ type: "text", text: "Fallback" }]),
    snapshot("fallback", undefined, "error"),
  ];
  const messages = branch.filter(entry => entry.type === "message").map(entry => ({
    role: "assistant", entryId: entry.id, text: "",
    tools: entry.message.content.filter(block => block.type === "toolCall").map(block => ({ id: block.id, name: block.name })),
  }));
  assert.equal(projectSubagents(branch, messages), messages);
  assert.deepEqual(messages[0].tools.map(tool => tool.id), ["code-1", "subagent:nested"]);
  assert.equal(messages[0].tools[1].state, "error");
  assert.equal(messages[0].tools[1].subagent.toolUses, 2);
  assert.equal(messages[0].tools[1].result, "Provider failed");
  assert.deepEqual(messages[1].tools.map(tool => tool.id), ["subagent:direct"]);
  assert.equal(messages[1].tools[0].state, "error");
  assert.deepEqual(messages[2].tools.map(tool => tool.id), ["subagent:explicit"]);
  assert.deepEqual(messages[3].tools.map(tool => tool.id), ["ordinary", "read"]);
  assert.deepEqual(messages[4].tools.map(tool => tool.id), ["subagent:fallback"]);
  assert.equal(messages.flatMap(row => row.tools).some(tool => tool.id === "subagent:unowned"), false);
  assert.equal(branch[8].data.tool.path, undefined);
});

test("one stable row covers queue, progress, continuation and a final error", () => {
  const event = { id: "child-1", type: "Explore", description: "Compare files", isBackground: true };
  let row = subagentTool(undefined, "created", event, {}, { prompt: "Inspect directory a" });
  assert.equal(row.state, "running");
  assert.equal(row.arguments.task, "Inspect directory a");
  assert.equal(row.arguments.mode, "background");
  row = subagentTool(row, "started", event, { status: "running", toolUses: 2 });
  row = subagentTool(row, "progress", { id: event.id, activity: "reading a/file.py" }, { status: "running", toolUses: 3 });
  assert.equal(row.subagent.toolUses, 3);
  assert.match(row.subagent.activity, /reading/);
  row = subagentTool(row, "completed", { ...event, result: "First result" }, { status: "completed" });
  assert.equal(row.state, "done");
  assert.equal(row.result, "First result");
  row = subagentTool(row, "resuming", event, { isBackground: false });
  assert.equal(row.id, "subagent:child-1");
  assert.equal(row.subagent.continued, true);
  assert.equal(row.arguments.mode, "foreground");
  assert.equal(row.result, "");
  row = subagentTool(row, "resumed", { ...event, status: "error", error: "Provider failed" });
  assert.equal(row.state, "error");
  assert.equal(row.result, "Provider failed");
});

test("community events and foreground progress use existing tool events and durable entries", async () => {
  const events = [], entries = [], handlers = new Map(), tools = [], commands = [];
  let record = { id: "child", type: "Explore", status: "running", toolUses: 0, isBackground: false };
  const adapter = createSubagentExtension({ emit: e => events.push(e), loadPackage: async () => ({
    getService: () => ({ getRecord: () => record }),
    factory: async pi => {
      pi.registerCommand("subagents:settings", {});
      pi.registerTool({ name: "subagent", execute: async (_id, _args, _signal, onUpdate) => {
        handlers.get("subagents:started")({ id: "child", type: "Explore" });
        record.toolUses = 1;
        onUpdate({ content: [], details: { toolUses: 1, activity: "reading sample.py" } });
        record = { ...record, status: "completed", result: "Compared" };
        handlers.get("subagents:completed")({ id: "child", type: "Explore", result: "Compared" });
        return { content: [{ type: "text", text: "Compared" }] };
      } });
    },
  }) });
  try {
    await adapter.extension({ events: { on: (name, fn) => { handlers.set(name, fn); return () => handlers.delete(name); } },
      on() {}, registerCommand: name => commands.push(name), registerTool: tool => tools.push(tool),
      appendEntry: (type, data) => entries.push({ type, data }) });
    await tools[0].execute("launch", { prompt: "Compare sample", subagent_type: "Explore" }, undefined, () => {}, {});
    assert.deepEqual(commands, []);
    assert.ok(events.some(e => e.subagent?.activity === "reading sample.py"));
    assert.equal(events.at(-1).state, "done");
    assert.equal(events.at(-1).result, "Compared");
    assert.ok(entries.every(e => e.type === "umeko-subagent" && e.data.toolCallId === "launch"));
    assert.equal(new Set(events.map(e => e.id)).size, 1);
  } finally { adapter.dispose(); }
});

test("resuming through the tool persists an alias to its original history row", async () => {
  const entries = [], handlers = new Map();
  let execute, first = true;
  let record = { id: "a", type: "Explore", status: "running", toolUses: 0 };
  const adapter = createSubagentExtension({ emit() {}, loadPackage: async () => ({
    getService: () => ({ getRecord: () => record }),
    factory: pi => pi.registerTool({ name: "subagent", execute: async () => {
      record = { ...record, status: "running" };
      handlers.get(first ? "subagents:started" : "subagents:resuming")({ id: "a", type: "Explore" });
      record = { ...record, status: "completed", result: "Finished" };
      handlers.get(first ? "subagents:completed" : "subagents:resumed")({ id: "a", type: "Explore" });
      first = false;
      return { content: [] };
    } }),
  }) });
  try {
    await adapter.extension({ events: { on: (name, handler) => { handlers.set(name, handler); return () => {}; } },
      on() {}, registerTool: tool => { execute = tool.execute; },
      appendEntry: (customType, data) => entries.push({ customType, data }) });
    const ctx = { sessionManager: { getBranch: () => [{ id: "owner", type: "message", message: {
      content: [{ type: "toolCall", id: "launch" }] } }] } };
    await execute("launch", { prompt: "Inspect" }, undefined, undefined, ctx);
    await execute("resume", { prompt: "Continue", resume: "a" }, undefined, undefined, ctx);
    const link = entries.find(e => e.customType === "umeko-subagent-link");
    assert.equal(link.data.toolCallId, "resume");
    assert.equal(link.data.subagentId, "subagent:a");
    const final = entries.at(-1).data;
    assert.equal(final.toolCallId, "launch");
    assert.equal(final.ownerEntryId, "owner");
    assert.equal(final.tool.subagent.continued, true);
  } finally { adapter.dispose(); }
});

test("invalid explicit model returns the current complete wrapped model catalog, only on model-selection errors", async () => {
  let execute, response={isError:true,content:[{type:"text",text:'Model not found: "original-provider/fast".\n\nAvailable models:\n  stale/model'}]};
  let models=[{provider:"umeko",id:"fast",name:"Fast",apiKey:"must-not-be-returned"},
    {provider:"umeko",id:"careful",name:"Careful"}];
  const adapter=createSubagentExtension({emit(){},loadPackage:async()=>({getService:()=>undefined,
    factory:pi=>pi.registerTool({name:"subagent",execute:async()=>response})})});
  try {
    await adapter.extension({events:{on:()=>()=>{}},on(){},registerTool:tool=>{execute=tool.execute;}});
    const ctx={modelRegistry:{getAvailable:()=>models}};
    const result=await execute("bad",{model:"original-provider/fast"},undefined,undefined,ctx);
    assert.equal(result.isError,true);
    assert.deepEqual(result.details.availableModels.map(model=>model.model),["umeko/careful","umeko/fast"]);
    assert.match(result.content[0].text,/原供应商 ID/);
    assert.match(result.content[0].text,/"model":"umeko\/careful"/);
    assert.ok(!JSON.stringify(result).includes("must-not-be-returned"));
    assert.ok(!JSON.stringify(result).includes("stale/model"));
    models.push({provider:"umeko",id:"new-model",name:"New"});
    const refreshed=await execute("again",{model:"bad/model"},undefined,undefined,ctx);
    assert.equal(refreshed.details.availableModels.length,3);
    response={isError:true,content:[{type:"text",text:"Network timeout"}]};
    assert.equal(await execute("network",{model:"umeko/fast"},undefined,undefined,ctx),response);
    response={content:[{type:"text",text:"Started"}]};
    assert.equal(await execute("ok",{model:"umeko/fast"},undefined,undefined,ctx),response);
  } finally { adapter.dispose(); }
});

test("community child uses Umeko settings and native retry without changing saved settings", { timeout: 90000 }, async () => {
  const Pi = await import("../runtime/node_modules/@earendil-works/pi-coding-agent/dist/index.js");
  const { AuthStorage } = await import("../runtime/node_modules/@earendil-works/pi-coding-agent/dist/core/auth-storage.js");
  const { SettingsManager } = await import("../runtime/subagent-sdk.mjs");
  const { createJiti } = await import("../runtime/node_modules/jiti/lib/jiti.mjs");
  const directory = mkdtempSync(join(tmpdir(), "umeko-child-retry-"));
  const agentDir = join(directory, "agent"); mkdirSync(agentDir);
  const settingsFile = join(agentDir, "settings.json");
  const saved = JSON.stringify({ retry: { enabled: false, maxRetries: 1,
    provider: { maxRetries: 7, timeoutMs: 12345 } }, compaction: { enabled: false }, cacheWarming: "off" });
  writeFileSync(settingsFile, saved);
  const settings = SettingsManager.create(directory, agentDir, { projectTrusted: true });
  assert.deepEqual(settings.getRetrySettings(), NETWORK_RETRY);
  assert.equal(settings.getProviderRetrySettings().maxRetries, 0);
  assert.equal(settings.getProviderRetrySettings().timeoutMs, 12345);
  const previousDirectory = process.cwd(), previousAgentDir = process.env.PI_CODING_AGENT_DIR;
  process.env.PI_CODING_AGENT_DIR = agentDir; process.chdir(directory);
  let requests = 0, session, modelRuntime;
  const events = [];
  const adapter = createSubagentExtension({ emit: event => events.push(event) });
  const server = http.createServer(async (request, response) => {
    for await (const _chunk of request) { /* consume the real provider request */ }
    if (++requests === 1) {
      response.writeHead(200, { "Content-Type": "text/event-stream" });
      response.end(`data: ${JSON.stringify({ error: upstreamFailure({ retryable: true }) })}\n\n`); return;
    }
    response.writeHead(200, { "Content-Type": "text/event-stream" });
    const common = { id: "child-retry", object: "chat.completion.chunk", created: 1, model: "retry-test" };
    response.end(`data: ${JSON.stringify({ ...common, choices: [{ index: 0, delta: { role: "assistant", content: "Recovered child" }, finish_reason: null }] })}\n\ndata: ${JSON.stringify({ ...common, choices: [{ index: 0, delta: {}, finish_reason: "stop" }] })}\n\ndata: [DONE]\n\n`);
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  try {
    modelRuntime = await Pi.ModelRuntime.create({ credentials: AuthStorage.inMemory(), modelsPath: null,
      allowModelNetwork: false, refreshOnCreate: false });
    modelRuntime.registerProvider("umeko-retry-test", { api: "openai-completions",
      baseUrl: `http://127.0.0.1:${server.address().port}/v1`, apiKey: "local-test-only",
      models: [{ id: "retry-test", name: "retry-test", api: "openai-completions", reasoning: false,
        input: ["text"], contextWindow: 128000, maxTokens: 256,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        compat: { supportsDeveloperRole: false, supportsStore: false } }] });
    await modelRuntime.refresh({ allowNetwork: false });
    const loader = new Pi.DefaultResourceLoader({ cwd: directory, agentDir,
      settingsManager: Pi.SettingsManager.inMemory({}), noExtensions: true, noSkills: true,
      noPromptTemplates: true, noThemes: true, noContextFiles: true,
      additionalExtensionPaths: ["builtin:subagents"],
      extensionFactories: [{ name: "subagents", builtin: true, factory: adapter.extension }] });
    await loader.reload();
    assert.deepEqual(loader.getExtensions().errors, []);
    ({ session } = await Pi.createAgentSession({ cwd: directory, agentDir, modelRuntime,
      settingsManager: Pi.SettingsManager.inMemory({ compaction: { enabled: false }, cacheWarming: "off" }),
      resourceLoader: loader, sessionManager: Pi.SessionManager.create(directory, join(directory, "sessions")),
      model: modelRuntime.getModel("umeko-retry-test", "retry-test") }));
    await session.bindExtensions({});
    const jiti = createJiti(new URL("../runtime/subagents.mjs", import.meta.url).href, {
      moduleCache: false, tryNative: false, fsCache: join(agentDir, "cache", "test-service") });
    const { getSubagentsService } = await jiti.import("@gotgenes/pi-subagents");
    const service = getSubagentsService(); assert.ok(service);
    const id = service.spawn("general-purpose", "Reply briefly", { foreground: true });
    await service.waitForAll();
    const record = service.getRecord(id);
    assert.equal(record.status, "completed", record.error);
    assert.match(record.result, /Recovered child/);
    assert.equal(requests, 2);
    // Raw native history preserves the failed agent attempt. If a provider SDK
    // had retried invisibly, only the successful assistant would be present.
    const entries = readFileSync(record.outputFile, "utf8").trim().split("\n").map(line => JSON.parse(line));
    const assistants = entries.filter(entry => entry.type === "message" && entry.message.role === "assistant");
    assert.equal(assistants.filter(entry => entry.message.stopReason === "error").length, 1);
    assert.equal(assistants.at(-1).message.stopReason, "stop");
    assert.ok(events.some(event => event.subagent?.id === id && event.state === "done"));
    assert.equal(readFileSync(settingsFile, "utf8"), saved);
  } finally {
    adapter.dispose();
    await session?.extensionRunner.emit({ type: "session_shutdown" });
    await session?.dispose(); await modelRuntime?.dispose?.();
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
    process.chdir(previousDirectory);
    if (previousAgentDir === undefined) delete process.env.PI_CODING_AGENT_DIR; else process.env.PI_CODING_AGENT_DIR = previousAgentDir;
    rmSync(directory, { recursive: true, force: true });
  }
});
