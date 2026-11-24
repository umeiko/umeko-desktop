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
      const run = () => session.prompt(input.text, {images: input.images || []});
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
