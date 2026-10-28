import test from "node:test";
import assert from "node:assert/strict";
import { createSubagentExtension, projectSubagents, subagentTool } from "../runtime/subagents.mjs";

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
