import test from "node:test";
import assert from "node:assert/strict";
import { createSubagentExtension, subagentTool } from "../runtime/subagents.mjs";

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
