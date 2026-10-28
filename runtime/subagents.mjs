// Execution and lifecycle belong to unmodified @gotgenes/pi-subagents.
// This adapter translates its public events/snapshots into existing tool rows.
import { AsyncLocalStorage } from "node:async_hooks";
import { createJiti } from "jiti";
import { fileURLToPath } from "node:url";

const channels = ["created", "started", "resuming", "completed", "failed", "resumed", "update", "steered", "compacted"];
const active = new Set(["queued", "running"]);
const textOf = content => (content || []).filter(item => item.type === "text").map(item => item.text).join("\n");

export function projectSubagents(branch, messages) {
  const owners = new Map(messages.filter(row => row.role === "assistant").map(row => [row.entryId, row]));
  const calls = new Map();
  for (const entry of branch) {
    if (entry.type !== "message" || entry.message?.role !== "assistant") continue;
    const owner = owners.get(entry.id);
    if (!owner || !Array.isArray(entry.message.content)) continue;
    for (const call of entry.message.content) if (call.type === "toolCall") calls.set(call.id, owner);
  }
  const callOwner = id => {
    if (typeof id !== "string") return;
    if (calls.has(id)) return calls.get(id);
    // code_execution's nested subagent calls retain the outer tool-call prefix.
    return [...calls.keys()].filter(call => id.startsWith(call + "/"))
      .sort((a, b) => b.length - a.length).map(call => calls.get(call))[0];
  };
  const launches = new Set(branch.filter(entry => entry.type === "custom" &&
    entry.customType === "umeko-subagent-link" && entry.data?.version === 1 &&
    typeof entry.data.toolCallId === "string").map(entry => entry.data.toolCallId));
  const children = new Map();
  let previousAssistant;
  for (const entry of branch) {
    if (entry.type === "message" && entry.message?.role === "assistant") {
      previousAssistant = owners.get(entry.id);
      continue;
    }
    const data = entry.data, snapshot = data?.tool;
    if (entry.type !== "custom" || entry.customType !== "umeko-subagent" || data?.version !== 1 ||
        snapshot?.name !== "subagent" || typeof snapshot.id !== "string" ||
        !snapshot.subagent || typeof snapshot.subagent !== "object") continue;
    let child = children.get(snapshot.id);
    if (!child) {
      const owner = owners.get(data.ownerEntryId) || callOwner(data.toolCallId) || previousAssistant;
      if (!owner) continue;
      const tools = owner.tools ||= [];
      const position = tools.findIndex(tool => tool.id === data.toolCallId);
      child = {};
      children.set(snapshot.id, child);
      tools.splice(position < 0 ? tools.length : position, 0, child);
    }
    Object.assign(child, snapshot, { arguments: { ...snapshot.arguments }, subagent: { ...snapshot.subagent },
      path: snapshot.path || "" });
    if (typeof data.toolCallId === "string") launches.add(data.toolCallId);
  }
  for (const row of messages) if (row.tools) row.tools = row.tools.filter(tool =>
    !(tool.name === "subagent" && launches.has(tool.id) && !children.has(tool.id)));
  return messages;
}

export function subagentTool(previous, channel, event, record = {}, invocation = {}) {
  const old = previous?.subagent || {};
  const continuing = channel === "resuming";
  const status = continuing || channel === "started" ? "running"
    : channel === "failed" ? "error"
    : record.status || event.status || (channel === "completed" || channel === "resumed" ? "completed" : old.status || "queued");
  const subagent = {
    ...old, id: event.id, type: event.type || record.type || old.type || invocation.subagent_type || "general-purpose",
    task: old.task || invocation.prompt || record.description || event.description || "",
    status, isBackground: record.isBackground ?? event.isBackground ?? old.isBackground ?? !!invocation.run_in_background,
    toolUses: record.toolUses ?? event.toolUses ?? old.toolUses ?? 0,
    activity: event.activity ?? event.message ?? (continuing ? "Continuing" : old.activity || ""),
    continued: continuing || old.continued || false,
    result: active.has(status) ? "" : record.result ?? event.result ?? old.result ?? "",
    error: active.has(status) ? "" : record.error ?? event.error ?? old.error ?? "",
  };
  return {
    id: "subagent:" + event.id, name: "subagent", path: "",
    arguments: { type: subagent.type, task: subagent.task, mode: subagent.isBackground ? "background" : "foreground" },
    state: active.has(status) ? "running" : status === "error" ? "error" : ["aborted", "stopped"].includes(status) ? "interrupted" : "done",
    result: subagent.error || subagent.result, subagent,
  };
}

export function createSubagentExtension({ emit, loadPackage } = {}) {
  const calls = new AsyncLocalStorage();
  const rows = new Map();
  let api, getService, timer, unbind = [];

  function dispose() {
    clearInterval(timer); timer = undefined;
    for (const stop of unbind.splice(0)) stop();
    rows.clear();
  }
  function update(channel, event, snapshot, scope = calls.getStore()) {
    if (!event?.id) return;
    const previous = rows.get(event.id);
    if (scope) scope.agentId = event.id;
    const record = snapshot ?? getService?.()?.getRecord(event.id) ?? {};
    if (channel === "resuming" && scope?.toolCallId) {
      api?.appendEntry("umeko-subagent-link", { version: 1, toolCallId: scope.toolCallId,
        subagentId: "subagent:" + event.id });
    }
    const tool = subagentTool(previous?.tool, channel, event, record, scope?.args);
    const owner = previous?.toolCallId || scope?.toolCallId;
    if (JSON.stringify(previous?.tool) === JSON.stringify(tool)) return;
    const ownerEntryId = previous?.ownerEntryId || scope?.ownerEntryId;
    rows.set(event.id, { tool, toolCallId: owner, ownerEntryId });
    emit({ type: "tool", id: tool.id, name: tool.name, args: tool.arguments,
      state: tool.state, result: tool.result, subagent: tool.subagent });
    // Keep durable state/tool-use transitions; spinner/text changes are transient.
    const before = previous?.tool.subagent;
    if (!before || channel !== "progress" || before.toolUses !== tool.subagent.toolUses ||
        before.status !== tool.subagent.status || before.isBackground !== tool.subagent.isBackground) {
      api?.appendEntry("umeko-subagent", { version: 1, tool, toolCallId: owner, ownerEntryId });
    }
    if (tool.state === "running" && !timer) {
      // Public background snapshots expose counters, deliberately not partial text.
      // Match the package widget's self-driven observation without a terminal UI.
      timer = setInterval(() => {
        const service = getService?.();
        for (const [id, row] of rows) if (row.tool.state === "running") {
          const record = service?.getRecord(id);
          if (record) update("progress", { id }, record, undefined);
        }
        if (![...rows.values()].some(row => row.tool.state === "running")) {
          clearInterval(timer); timer = undefined;
        }
      }, 250);
      timer.unref?.();
    }
  }

  async function extension(pi) {
    dispose(); api = pi;
    const loaded = loadPackage ? await loadPackage() : await (async () => {
      const jiti = createJiti(import.meta.url, { moduleCache: false });
      const root = new URL("../", import.meta.resolve("@gotgenes/pi-subagents"));
      const factory = await jiti.import(fileURLToPath(new URL("index.ts", root)), { default: true });
      const service = await jiti.import("@gotgenes/pi-subagents");
      return { factory, getService: service.getSubagentsService };
    })();
    getService = loaded.getService;
    for (const channel of channels) unbind.push(pi.events.on("subagents:" + channel, event => update(channel, event)));
    pi.on("session_before_switch", dispose);
    pi.on("session_shutdown", dispose);
    await loaded.factory(new Proxy(pi, {
      get(target, property) {
        // The desktop exposes delegation through natural language, not new commands.
        if (property === "registerCommand") return () => {};
        if (property !== "registerTool") return target[property];
        return tool => {
          if (tool.name !== "subagent") return target.registerTool(tool);
          target.registerTool({ ...tool, execute: async (toolCallId, args, signal, onUpdate, ctx) => {
            const ownerEntryId = ctx.sessionManager?.getBranch().find(entry => entry.type === "message" &&
              Array.isArray(entry.message.content) && entry.message.content.some(block => block.type === "toolCall" && block.id === toolCallId))?.id;
            const scope = { toolCallId, args, ownerEntryId };
            return calls.run(scope, async () => {
              try {
                const result = await tool.execute(toolCallId, args, signal, progress => {
                  onUpdate?.(progress);
                  const details = progress.details;
                  const id = details?.agentId || scope.agentId;
                  if (id) update("progress", { id, activity: details?.activity },
                    { ...getService?.()?.getRecord(id), toolUses: details?.toolUses }, scope);
                }, ctx);
                // Invalid invocations can fail before the package creates an agent.
                if (!scope.agentId) emit({ type: "tool", name: "subagent", id: toolCallId,
                  args, state: result.isError ? "error" : "done", result: textOf(result.content) });
                return result;
              } catch (error) {
                if (!scope.agentId) emit({ type: "tool", name: "subagent", id: toolCallId,
                  args, state: "error", result: error.message });
                throw error;
              }
            });
          } });
        };
      },
    }));
  }
  return { extension, dispose };
}
