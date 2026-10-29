// Execution and lifecycle belong to unmodified @gotgenes/pi-subagents.
// This adapter translates its public events/snapshots into existing tool rows.
import { AsyncLocalStorage } from "node:async_hooks";
import { createJiti } from "jiti";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { homedir } from "node:os";
import { createInputQueue } from "./input-queue.mjs";

const channels = ["created", "started", "resuming", "completed", "failed", "resumed", "update", "steered", "compacted"];
const active = new Set(["queued", "running"]);
const textOf = content => (content || []).filter(item => item.type === "text").map(item => item.text).join("\n");
const sessionHook = Symbol.for("umeko:subagent-session");
const boundedArgs = args => {
  const json = JSON.stringify(args || {});
  return json.length <= 16384 ? args || {} : {preview:json.slice(0,8192),truncated:true};
};

function modelSelectionHelp(message, args, ctx) {
  if (!args.model || !/(?:model not found|unknown model|invalid model|no model registry available)/i.test(message)) return;
  const models = [...new Map((ctx.modelRegistry?.getAvailable?.() || []).map(model=>[
    `${model.provider}/${model.id}`, {provider:model.provider,id:model.id,name:model.name || model.id,model:`${model.provider}/${model.id}`}])).values()]
    .sort((a,b)=>a.model.localeCompare(b.model));
  const reason = message.split(/\n\nAvailable models:/i)[0];
  const explanation = models.length
    ? `Umeko 统一包装了模型和供应商。model 参数请使用以下完整调用名称，不要使用设置中的原供应商 ID。\n可用供应商：${[...new Set(models.map(model=>model.provider))].join(", ")}\n可用模型（直接填入 model）：\n${models.map(model=>`- ${JSON.stringify(model.model)} · ${model.name}`).join("\n")}\n例如：${JSON.stringify({model:models[0].model})}。不需要指定模型时可省略 model。`
    : "当前没有可用模型，请先在 Umeko 中配置供应商、凭据和模型。";
  return {text:reason+"\n\n"+explanation,models};
}

// Bound the live snapshot crossing JSONL/QML. Complete transcripts remain in
// native files and are paged by the desktop when the child is not streaming.
export function childMessages(session) {
  const source = session.messages || [];
  const pending = session.agent?.state?.pendingToolCalls;
  const rows = [], tools = new Map();
  let budget = 512 * 1024, clipped = false;
  const take = value => { value = String(value || ""); const result = value.slice(0, Math.min(32768, budget)); clipped ||= result.length < value.length; budget -= result.length; return result; };
  for (const message of source.slice(-200)) {
    if (!budget) break;
    if (message.role === "toolResult") {
      const tool = tools.get(message.toolCallId);
      if (tool) Object.assign(tool, {state:message.isError ? "error" : "done", result:take(textOf(message.content))});
      continue;
    }
    if (!["user", "assistant"].includes(message.role)) continue;
    const content = typeof message.content === "string" ? [{type:"text",text:message.content}] : message.content || [];
    const row = {role:message.role, text:take(textOf(content)), timestamp:message.timestamp,
      error:message.stopReason === "error", stopReason:message.stopReason || ""};
    const thinking = take(content.filter(item => item.type === "thinking").map(item => item.thinking || "").join("\n"));
    if (thinking) row.thinking = thinking;
    for (const call of content.filter(item => item.type === "toolCall")) {
      const tool = {id:call.id, name:call.name, arguments:boundedArgs(call.arguments), path:"", state:pending?.has(call.id) ? "running" : "interrupted", result:""};
      tools.set(call.id,tool); (row.tools ||= []).push(tool);
    }
    rows.push(row);
  }
  return {messages:rows, truncated:source.length > 200 || budget <= 0 || clipped};
}

function childEvent(event) {
  const message = event.message;
  if (event.type === "message_start" && ["user", "assistant"].includes(message?.role))
    return {type:message.role === "user" ? "user_start" : "assistant_start", text:(typeof message.content === "string" ? message.content : textOf(message.content)).slice(-131072),timestamp:message.timestamp};
  if (event.type === "message_update") {
    const update = event.assistantMessageEvent;
    if (["text_delta","thinking_delta"].includes(update?.type)) return {type:update.type === "text_delta" ? "delta" : "thinking_delta",text:update.delta};
  }
  if (event.type === "message_end" && message?.role === "assistant")
    return {type:"message",text:textOf(message.content).slice(-131072),thinking:(message.content || []).filter(item=>item.type==="thinking").map(item=>item.thinking || "").join("\n").slice(-131072),error:message.stopReason === "error",stopReason:message.stopReason,timestamp:message.timestamp};
  if (event.type.startsWith("tool_execution_")) return {type:"tool",id:event.toolCallId,name:event.toolName,args:boundedArgs(event.args),
    state:event.type === "tool_execution_end" ? event.isError ? "error" : "done" : "running",
    result:event.type === "tool_execution_end" ? textOf(event.result?.content).slice(0,8192) : undefined};
}

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
    task: String(old.task || invocation.prompt || record.description || event.description || "").slice(0,2000),
    status, isBackground: record.isBackground ?? event.isBackground ?? old.isBackground ?? !!invocation.run_in_background,
    toolUses: record.toolUses ?? event.toolUses ?? old.toolUses ?? 0,
    activity: event.activity ?? event.message ?? (continuing ? "Continuing" : old.activity || ""),
    continued: continuing || old.continued || false,
    result: active.has(status) ? "" : String(record.result ?? event.result ?? old.result ?? "").slice(0,8192),
    error: active.has(status) ? "" : String(record.error ?? event.error ?? old.error ?? "").slice(0,8192),
    outputFile: record.outputFile || old.outputFile || "",
    startedAt: record.startedAt || old.startedAt || Date.now(),
    completedAt: record.completedAt || (active.has(status) ? undefined : old.completedAt),
    avatarSlot: old.avatarSlot,
    turnBudget: record.turnBudget || old.turnBudget,
  };
  return {
    id: "subagent:" + event.id, name: "subagent", path: "",
    arguments: { type: subagent.type, task: subagent.task, mode: subagent.isBackground ? "background" : "foreground" },
    state: active.has(status) ? "running" : status === "error" ? "error" : ["aborted", "stopped"].includes(status) ? "interrupted" : "done",
    result: subagent.error || subagent.result, subagent,
  };
}

export function createSubagentExtension({ emit, loadPackage, restoreSession } = {}) {
  const calls = new AsyncLocalStorage();
  const rows = new Map();
  const sessions = new Map(), contexts = new Map(), restoring = new Map();
  const pendingSessions = new Set(), observed = new Set();
  let api, getService, timer, unbind = [], watching = "", hook, generation = 0, resumeTools;

  function publishContext(id) {
    const observed = sessions.get(id), session = observed?.session;
    if (watching !== id) return;
    observed?.queue.publish();
    const row = rows.get(id)?.tool.subagent;
    emit({type:"subagent_context",id,...(session && active.has(row?.status) ? childMessages(session) : {file:row?.outputFile || "",messages:[]})});
  }
  function observe(session, options = {}, explicitId) {
    let id = explicitId || calls.getStore()?.agentId;
    const identify = () => id ||= getService?.()?.listAgents?.().find(row => row.outputFile === session.sessionManager.getSessionFile())?.id
      || [...rows.values()].find(row => row.tool.subagent.outputFile === session.sessionManager.getSessionFile())?.tool.subagent.id;
    let prompting=false;
    const queue=createInputQueue({getSession:()=>session,isRunning:()=>prompting || !session.isIdle,
      onQueue:(_steering,_followUp,items)=>{if (identify()) emit({type:"subagent_queue",id,items});},
      onEdited:item=>{if (identify()) emit({type:"subagent_queue_edited",id,item});},
      onReturned:items=>{if (identify()) emit({type:"subagent_queue_returned",id,items});}});
    const nativePrompt=session.prompt.bind(session);
    const prompt=async(text,promptOptions)=>{
      if (prompting || session.isStreaming) return nativePrompt(text,promptOptions);
      prompting=true;
      try {
        await queue.run({text,options:promptOptions},item=>nativePrompt(item.text,
          {...promptOptions,...item.options,images:item.images ?? item.options?.images ?? promptOptions?.images}));
      } finally {
        await queue.chain;
        if (queue.items.length || queue.hasInterrupts) queue.returnQueue();
        prompting=false;
      }
    };
    session.prompt=prompt;
    const attach = () => {
      if (!identify() || sessions.get(id)?.session === session) return;
      sessions.get(id)?.unsubscribe();
      const metadata = {systemPrompt:session.systemPrompt, tools:session.getActiveToolNames(),
        model:session.model?.id,thinkingLevel:session.thinkingLevel,cwd:session.sessionManager.getCwd()};
      contexts.set(id,metadata);
      api?.appendEntry("umeko-subagent-context",{version:1,id,context:metadata});
      sessions.set(id,{session,queue,unsubscribe:cleanup});
      pendingSessions.delete(attach);
      const row = rows.get(id);
      if (row) update("progress",{id},{...row.tool.subagent,outputFile:session.sessionManager.getSessionFile()});
      publishContext(id);
    };
    const unsubscribe = session.subscribe(event => {
      attach();
      if (!id) return;
      if (event.type==="queue_update") queue.sync(event.steering,event.followUp);
      const projected = childEvent(event);
      if (projected && watching === id) emit({type:"subagent_event",id,event:projected});
      if (["tool_execution_start","tool_execution_end"].includes(event.type)) {
        const row = rows.get(id);
        if (row) update("progress",{id,activity:event.toolName + " · " + String(event.args?.path || event.args?.command || "").slice(0,160)},
          restoring.has(id) ? {...row.tool.subagent,toolUses:row.tool.subagent.toolUses + (event.type === "tool_execution_end" ? 1 : 0)} : undefined);
      }
    });
    let cleaned=false;
    const cleanup=()=>{
      if (cleaned) return;
      cleaned=true; observed.delete(cleanup);
      unsubscribe(); queue.cancel();
      if (session.prompt===prompt) session.prompt=nativePrompt;
    };
    observed.add(cleanup);
    pendingSessions.add(attach);
    attach();
  }

  function hydrate(branch = []) {
    for (const entry of branch) {
      if (entry.type !== "custom") continue;
      if (entry.customType === "umeko-subagent-context" && entry.data?.version === 1) contexts.set(entry.data.id,entry.data.context);
      const tool = entry.customType === "umeko-subagent" && entry.data?.version === 1 && entry.data.tool;
      if (tool?.subagent?.id) rows.set(tool.subagent.id,{tool:structuredClone(tool),toolCallId:entry.data.toolCallId,ownerEntryId:entry.data.ownerEntryId});
    }
    for (const entry of branch) if (entry.type === "custom" && entry.customType === "subagents:record" && entry.data?.id && rows.has(entry.data.id)) {
      const child = rows.get(entry.data.id).tool.subagent;
      if (entry.data.outputFile) child.outputFile = entry.data.outputFile;
    }
    for (const [id,row] of rows) if (active.has(row.tool.subagent.status) && !getService?.()?.getRecord(id)) {
      row.tool.state = "interrupted"; row.tool.subagent.status = "stopped";
    }
    emit({type:"subagents",agents:[...rows.values()].map(row=>row.tool.subagent)});
  }

  function ensureSlot(id) {
    const old = rows.get(id)?.tool.subagent.avatarSlot;
    if (Number.isInteger(old) && old >= 0 && old < 4) return old;
    const counts = [0,0,0,0];
    for (const row of rows.values()) if (active.has(row.tool.subagent.status)) counts[row.tool.subagent.avatarSlot || 0]++;
    return counts.indexOf(Math.min(...counts));
  }

  async function command(input) {
    const {action,id} = input;
    const reply = (ok, message = "") => emit({type:"subagent_command",requestId:input.requestId,id,action,ok,message});
    try {
      if (action === "unwatch") { watching = ""; return; }
      const row = rows.get(id);
      if (!row) throw new Error("当前会话中没有这个子代理。");
      if (action === "watch") { watching = id; publishContext(id); return; }
      const service = getService?.(), live = service?.getRecord(id);
      const observed=sessions.get(id);
      if (["edit-queue","delete-queue","steer-queued","promote-queue"].includes(action)) {
        if (!observed) throw new Error("这个子代理的输入队列已不可用。");
        await observed.queue.submit({type:action,id:input.queueId});
        reply(true); return;
      }
      if (action === "stop") {
        observed?.queue.cancel();
        if (restoring.has(id)) { restoring.get(id).abort(); await sessions.get(id)?.session.abort(); }
        else if (!service?.abort(id)) throw new Error("这个子代理已经停止。");
        reply(true); return;
      }
      if (action !== "send") throw new Error("未知的子代理操作。");
      const text = String(input.text || "").trim();
      if (!text || text.length > 65536) throw new Error("请输入消息，长度不得超过 64K 字符。");
      if (row.tool.subagent.status === "running") {
        if (!observed) throw new Error("暂时无法连接子代理的输入队列，请稍后重试。");
        await observed.queue.submit({type:input.mode==="interrupt" ? "steer" : input.mode==="steering" ? "native-steer" : "follow-up",
          text,messageId:input.messageId || input.requestId});
        reply(true); return;
      }
      if (active.has(row.tool.subagent.status)) throw new Error("子代理正在排队，请在开始运行后发送指引。");
      const slot = ensureSlot(id);
      if (live && !live.resumeRefusal) {
        const work = service.resume(id,text,{claimOutcome:true});
        reply(true);
        void work.then(outcome => { if (outcome.kind === "refused") reply(false,"无法继续子代理：" + outcome.reason); }).catch(error=>reply(false,error.message));
        return;
      }
      if (!restoreSession || !row.tool.subagent.outputFile) throw new Error("没有可继续的原生子代理会话文件。");
      const cancellation = new AbortController(), token = generation;
      restoring.set(id,cancellation);
      update("progress",{id,activity:"Continuing"},{...row.tool.subagent,status:"queued",avatarSlot:slot});
      reply(true);
      void (async () => {
        let session;
        try {
          const report = text => {
            update("progress",{id,activity:text});
            api.sendMessage?.({customType:"subagent-update",content:`Subagent ${id}: ${text}`,display:true},{triggerTurn:false});
          };
          session = await restoreSession(row.tool.subagent,contexts.get(id),resumeTools?.(report) || []);
          if (token !== generation || cancellation.signal.aborted) return;
          observe(session,{},id);
          update("started",{id},{...rows.get(id).tool.subagent,status:"running"});
          let turns = 0;
          const ceiling = row.tool.subagent.turnBudget?.maxTurns;
          const unlimit = session.subscribe(event => { if (event.type === "turn_end" && ceiling && ++turns >= ceiling && event.toolResults?.length) void session.abort(); });
          try { await session.prompt(text); } finally { unlimit(); }
          const failure = [...session.messages].reverse().find(message=>message.role === "assistant");
          update(cancellation.signal.aborted ? "progress" : failure?.stopReason === "error" ? "failed" : "completed",{id},
            {...rows.get(id).tool.subagent,status:cancellation.signal.aborted ? "stopped" : failure?.stopReason === "error" ? "error" : "completed",
              result:textOf(failure?.content),error:failure?.errorMessage || "",completedAt:Date.now()});
        } catch (error) { if (token === generation) update("failed",{id,error:error.message},{...rows.get(id)?.tool.subagent,status:"error",error:error.message}); }
        finally {
          await session?.dispose?.();
          if (token === generation) {
            if (active.has(rows.get(id)?.tool.subagent.status)) update("progress",{id},{...rows.get(id).tool.subagent,status:"stopped"});
            sessions.get(id)?.unsubscribe(); sessions.delete(id); restoring.delete(id);
          }
        }
      })();
    } catch (error) { reply(false,error.message); }
  }

  function dispose() {
    generation++;
    for (const [id,cancellation] of restoring) { cancellation.abort(); void sessions.get(id)?.session.abort(); }
    restoring.clear();
    for (const unsubscribe of observed) unsubscribe();
    observed.clear(); pendingSessions.clear();
    sessions.clear(); contexts.clear(); watching = "";
    if (globalThis[sessionHook] === hook) delete globalThis[sessionHook];
    clearInterval(timer); timer = undefined;
    for (const stop of unbind.splice(0)) stop();
    rows.clear();
  }
  function update(channel, event, snapshot, scope = calls.getStore()) {
    if (!event?.id) return;
    const previous = rows.get(event.id);
    if (scope) scope.agentId = event.id;
    const record = snapshot ?? (restoring.has(event.id) ? previous?.tool.subagent : getService?.()?.getRecord(event.id)) ?? {};
    if (channel === "resuming" && scope?.toolCallId) {
      api?.appendEntry("umeko-subagent-link", { version: 1, toolCallId: scope.toolCallId,
        subagentId: "subagent:" + event.id });
    }
    const tool = subagentTool(previous?.tool, channel, event, record, scope?.args);
    if (channel === "resuming") tool.subagent.avatarSlot = ensureSlot(event.id);
    if (!Number.isInteger(tool.subagent.avatarSlot)) tool.subagent.avatarSlot = ensureSlot(event.id);
    if (record.avatarSlot !== undefined) tool.subagent.avatarSlot = record.avatarSlot;
    const owner = previous?.toolCallId || scope?.toolCallId;
    if (JSON.stringify(previous?.tool) === JSON.stringify(tool)) return;
    const ownerEntryId = previous?.ownerEntryId || scope?.ownerEntryId;
    rows.set(event.id, { tool, toolCallId: owner, ownerEntryId });
    for (const attach of [...pendingSessions]) attach();
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
    hook = (session,options) => observe(session,options);
    globalThis[sessionHook] = hook;
    const loaded = loadPackage ? await loadPackage() : await (async () => {
      // Keep generated TypeScript cache out of the signed/read-only app bundle.
      const cache = join(process.env.PI_CODING_AGENT_DIR || join(homedir(),".pi","agent"),"cache","umeko-subagents");
      const jiti = createJiti(import.meta.url, { moduleCache: false, tryNative: false, fsCache:cache,
        alias: { "#src/settings": fileURLToPath(new URL("./subagent-settings.mjs", import.meta.url)), "@earendil-works/pi-coding-agent": fileURLToPath(new URL("./subagent-sdk.mjs", import.meta.url)) } });
      const root = new URL("../", import.meta.resolve("@gotgenes/pi-subagents"));
      const factory = await jiti.import(fileURLToPath(new URL("index.ts", root)), { default: true });
      const service = await jiti.import("@gotgenes/pi-subagents");
      const { AskParentTool } = await jiti.import(fileURLToPath(new URL("session/ask-parent-tool.ts",root)));
      const { NotifyParentTool } = await jiti.import(fileURLToPath(new URL("session/notify-parent-tool.ts",root)));
      return { factory, getService: service.getSubagentsService,
        resumeTools:report=>[new AskParentTool(report).toToolDefinition(),new NotifyParentTool(report).toToolDefinition()] };
    })();
    getService = loaded.getService;
    resumeTools = loaded.resumeTools;
    for (const channel of channels) unbind.push(pi.events.on("subagents:" + channel, event => update(channel, event)));
    unbind.push(pi.events.on("subagents:child:disposed", event => {
      for (const [id,entry] of sessions) if (entry.session.sessionManager.getSessionId() === event.sessionId) {
        entry.unsubscribe(); observed.delete(entry.unsubscribe); sessions.delete(id); publishContext(id);
      }
    }));
    pi.on("session_before_switch", dispose);
    pi.on("session_shutdown", dispose);
    pi.on("session_start", (_event,ctx) => hydrate(ctx.sessionManager?.getBranch()));
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
                let result = await tool.execute(toolCallId, args, signal, progress => {
                  onUpdate?.(progress);
                  const details = progress.details;
                  const id = details?.agentId || scope.agentId;
                  if (id) update("progress", { id, activity: details?.activity },
                    { ...getService?.()?.getRecord(id), toolUses: details?.toolUses }, scope);
                }, ctx);
                const guidance = result.isError && modelSelectionHelp(textOf(result.content), args, ctx);
                if (guidance) result = {...result, content:[{type:"text",text:guidance.text}],
                  details:{...result.details,availableModels:guidance.models}};
                // Invalid invocations can fail before the package creates an agent.
                if (!scope.agentId) emit({ type: "tool", name: "subagent", id: toolCallId,
                  args, state: result.isError ? "error" : "done", result: textOf(result.content) });
                return result;
              } catch (error) {
                const guidance = modelSelectionHelp(error.message || "",args,ctx);
                if (guidance) error.message = guidance.text;
                if (!scope.agentId) emit({ type: "tool", name: "subagent", id: toolCallId,
                  args, state: "error", result: error.message });
                throw error;
              }
            });
          } });
        };
      },
    }));
    const service = getService?.();
    getService = () => service;
  }
  return { extension, dispose, command, hydrate };
}
