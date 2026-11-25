// One queue policy for desktop parent and child conversations. Pi owns native
// same-model follow-ups; model changes wait for the next prompt boundary.
// Priority input aborts the current run before the next prompt.
/**
 * Same-session handoff adapted from @signalridge/pi-plan-mode 1.6.1,
 * src/message-transform.ts (proposed plan parsing and handoff).
 * MIT notice: ../licenses/pi-plan-mode-MIT.txt.
 */
const PLAN_TOOLS = new Set(["read", "grep", "find", "ls"]);
const PLANNING_PROMPT = [
  "Plan the user's latest task. Use the available read-only tools to investigate.",
  "If you need a decision from the user, ask it and wait for a reply.",
  "When ready, return one complete implementation plan between <proposed_plan> and </proposed_plan>, with each tag on its own line.",
  "The implementation model receives this plan and this conversation automatically.",
].join(" ");

export function proposedPlan(message) {
  if (message?.stopReason !== "stop") return "";
  const text = message.content.filter(block => block.type === "text").map(block => block.text).join("\n");
  if (text.match(/<proposed_plan>/gi)?.length !== 1 || text.match(/<\/proposed_plan>/gi)?.length !== 1) return "";
  return text.match(/^<proposed_plan>[\t ]*\r?\n([\s\S]*?)\r?\n<\/proposed_plan>[\t ]*$/m)?.[1].trim() || "";
}

export function createModelRoles() {
  const planning = new WeakSet();
  return {
    extension(pi) {
      pi.on("before_agent_start", (event, ctx) => {
        if (!planning.has(ctx.sessionManager)) return;
        return {systemPrompt: `${event.systemPrompt}\n\n${PLANNING_PROMPT}`};
      });
      pi.on("tool_call", (event, ctx) => {
        if (planning.has(ctx.sessionManager) && !PLAN_TOOLS.has(event.toolName))
          return {block: true, reason: "Planning uses read-only tools"};
      });
    },
    async prompt(session, input, select, canExecute) {
      const {planningModel, executionModel, coordinatorModel} = input.modelRoles || {};
      const implementation = executionModel || coordinatorModel || input.model;
      const run = () => session.prompt(input.text, {images: input.images || [], expandPromptTemplates: !input.literalSlash});
      if (!planningModel || input.text.startsWith("/")) {
        await select(implementation);
        await run();
        return;
      }
      await select(planningModel);
      const tools = session.getActiveToolNames();
      let lastAssistant;
      const unsubscribe = session.subscribe(event => {
        if (event.type === "message_end" && event.message.role === "assistant") lastAssistant = event.message;
      });
      planning.add(session.sessionManager);
      try {
        session.setActiveToolsByName(tools.filter(name => PLAN_TOOLS.has(name)));
        await run();
      } finally {
        planning.delete(session.sessionManager);
        unsubscribe();
        session.setActiveToolsByName(tools);
      }
      const plan = proposedPlan(lastAssistant);
      if (!plan || !canExecute()) return;
      await select(implementation);
      if (!canExecute()) return;
      await session.sendCustomMessage({
        customType: "umeko-model-plan",
        content: "Implement this proposed plan for the user's latest task:\n\n" + plan,
        display: false,
      }, {triggerTurn: true});
    },
  };
}

// Terminal commands are dispatched at an idle boundary so Pi can interpret
// them as commands. They also delimit a batch of steering messages.
const terminalCommand = text => text.startsWith("!");
const literalSlash = text => text.startsWith("/");

export function createInputQueue({getSession,isRunning,onQueue=()=>{},onEdited=()=>{},onReturned=()=>{},beforeInterrupt=()=>{}}) {
  let chain=Promise.resolve(), items=[], adding, interrupts=[], deferred=[], epoch=0;
  function sync(steering,followUp) {
    const previous=[...items];
    items=[["steering",steering],["followUp",followUp]].flatMap(([mode,texts])=>texts.map(text=>{
      const index=previous.findIndex(item=>item.nativeText===text && item.mode===mode);
      const item=index>=0 ? previous.splice(index,1)[0] : adding || {id:crypto.randomUUID(),text,images:[]};
      return {...item,nativeText:text,mode};
    })).concat(deferred.map(item=>({...item,mode:"followUp"})));
    onQueue(steering,[...followUp,...deferred.map(item=>item.text)],items.map(({id,text,mode,hold})=>({id,text,mode,...(hold ? {hold} : {})})));
  }
  function publish() {
    const session=getSession();
    sync(session.getSteeringMessages(),session.getFollowUpMessages());
  }
  async function enqueue(item,mode="followUp") {
    const nextModel=interrupts.at(-1)?.model || getSession().model?.id;
    if (mode === "followUp" && (deferred.length || item.terminalCommand || item.literalSlash || (item.model && item.model !== nextModel))) {
      deferred.push({...item,id:item.id || crypto.randomUUID()});
      publish();
      return;
    }
    adding={...item,id:item.id || crypto.randomUUID()};
    try { await getSession()[mode==="steering" ? "steer" : "followUp"](item.text,item.images || []); }
    finally { adding=undefined; }
  }
  function take() {
    const pending=[...items];
    items=[];
    deferred=[];
    getSession().clearQueue();
    return pending;
  }
  function returnQueue() {
    const pending=[...take(),...interrupts.splice(0)];
    if (pending.length) onReturned(pending);
  }
  function cancel() { epoch++; returnQueue(); }
  function submit(input) {
    const token=epoch;
    const work=chain.then(async()=>{
      if (token!==epoch) throw new Error("当前任务已停止，请重新发送这条消息");
      const session=getSession();
      if (!session) throw new Error("Pi 尚未就绪");
      if (input.type === "terminal-steer") {
        if (!isRunning() || session.isIdle) throw new Error("当前回合已结束，请重新发送这条消息");
        const draft = input.text && !terminalCommand(input.text) ? input : null;
        const selected = [];
        const target = items[0] || draft;
        if (target && !terminalCommand(target.text) && !target.images?.length) {
          for (const item of items) {
            if (terminalCommand(item.text) || item.images?.length || item.model !== target.model ||
                item.reasoningEffort !== target.reasoningEffort ||
                JSON.stringify(item.modelRoles) !== JSON.stringify(target.modelRoles)) break;
            selected.push(item);
          }
        }
        // A draft can still steer when an actual shell/skill command is at
        // the queue front. The command remains queued for normal dispatch.
        const includeDraft = draft && (!selected.length ||
            (selected.length === items.length && draft.model === target.model &&
             draft.reasoningEffort === target.reasoningEffort &&
             JSON.stringify(draft.modelRoles) === JSON.stringify(target.modelRoles)));
        const batch = includeDraft ? [...selected, draft] : selected;
        if (!batch.length) {
          if (input.text) await enqueue({...input, id: input.messageId, terminalCommand: terminalCommand(input.text), literalSlash: literalSlash(input.text)});
          return;
        }
        const remaining = take().filter(item => !selected.includes(item));
        if (input.text && !includeDraft) remaining.push({...input, id: input.messageId, terminalCommand: terminalCommand(input.text), literalSlash: literalSlash(input.text)});
        interrupts.push({...batch[0], text: batch.map(item => item.text).join("\n\n"),
          literalSlash: literalSlash(batch[0].text)});
        beforeInterrupt();
        await session.abort();
        if (token === epoch) for (const item of remaining) await enqueue(item);
        else if (remaining.length) onReturned(remaining);
      } else if (["steer","promote-queue","steer-queued"].includes(input.type)) {
        if (!isRunning()) throw new Error("当前任务已结束，请重新发送这条消息");
        const selected=input.type==="steer" ? {id:input.messageId,text:input.text,images:input.images || [],model:input.model,reasoningEffort:input.reasoningEffort,modelRoles:input.modelRoles}
          : input.type==="promote-queue" ? items[0] : items.find(item=>item.id===input.id);
        if (!selected) throw new Error("这条消息已经开始处理");
        const remaining=take().filter(item=>item!==selected);
        interrupts.push(selected);
        beforeInterrupt();
        await session.abort();
        if (token===epoch) for (const item of remaining) await enqueue(item);
        else if (remaining.length) onReturned(remaining);
      } else if (["edit-queue","delete-queue"].includes(input.type)) {
        const selected=items.find(item=>item.id===input.id);
        if (!selected) throw new Error("这条消息已经开始处理");
        const pending=take();
        if (input.type==="edit-queue") onEdited(selected);
        for (const item of pending) if (item!==selected) await enqueue(item);
      } else if (["follow-up","native-steer","terminal-follow-up"].includes(input.type)) {
        if (!isRunning() || session.isIdle) throw new Error("当前任务已结束，请重新发送这条消息");
        await enqueue({id:input.messageId,text:input.text,images:input.images || [],model:input.model,reasoningEffort:input.reasoningEffort,modelRoles:input.modelRoles, hold:input.hold, literalSlash: input.type === "terminal-follow-up" && literalSlash(input.text), terminalCommand: input.type === "terminal-follow-up" && terminalCommand(input.text)},input.type==="native-steer" ? "steering" : "followUp");
      } else throw new Error("未知的排队操作");
    });
    chain=work.catch(()=>{});
    return work;
  }
  async function run(first,invoke) {
    const token=epoch;
    let next=first;
    do {
      try { await invoke(next); }
      catch (error) { if (!interrupts.length) throw error; }
      await chain;
      next=token===epoch ? shiftNext() : undefined;
    } while (next);
  }
  function shiftNext() {
    const next=interrupts.shift() || deferred.shift();
    if (next) publish();
    return next;
  }
  return {sync,publish,submit,run,returnQueue,cancel,
    get chain(){return chain;}, get items(){return items;},
    get hasInterrupts(){return interrupts.length>0 || deferred.length>0;}, shiftInterrupt:shiftNext};
}
