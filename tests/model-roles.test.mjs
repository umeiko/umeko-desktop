import assert from "node:assert/strict";
import test from "node:test";
import {createModelRoles, proposedPlan} from "../runtime/input-queue.mjs";

const assistant = (text, stopReason = "stop") => ({role:"assistant", stopReason, content:[{type:"text", text}]});
const plan = "<proposed_plan>\nRead the input and write the summary.\n</proposed_plan>";

test("only a complete, nonempty plan in a successful response starts implementation", () => {
  assert.equal(proposedPlan(assistant(plan)), "Read the input and write the summary.");
  for (const text of ["What should I do?", plan + "\n" + plan, "<proposed_plan>\nunfinished", "<proposed_plan>\n\n</proposed_plan>"]) {
    assert.equal(proposedPlan(assistant(text)), "");
  }
  assert.equal(proposedPlan(assistant(plan, "aborted")), "");
});

test("the execution model receives the plan on the same session with its tools restored", async () => {
  const roles = createModelRoles(), trace = [];
  const handlers = new Map(), tools = ["read", "write", "bash"];
  let activeTools = tools, subscribe;
  roles.extension({on:(event, callback) => handlers.set(event, callback)});
  const session = {
    sessionManager:{},
    getActiveToolNames:() => activeTools,
    setActiveToolsByName(value) { activeTools = value; },
    subscribe(callback) { subscribe = callback; return () => { subscribe = null; }; },
    async prompt(text) {
      assert.deepEqual(activeTools, ["read"]);
      assert.equal(handlers.get("tool_call")({toolName:"write"}, this).block, true);
      assert.match(handlers.get("before_agent_start")({systemPrompt:"base"}, this).systemPrompt, /Plan the user's latest task/);
      trace.push(text);
      subscribe({type:"message_end", message:assistant(plan)});
    },
    async sendCustomMessage(message, options) {
      assert.deepEqual(activeTools, tools);
      assert.equal(options.triggerTurn, true);
      trace.push(message.content);
    },
  };
  await roles.prompt(session, {text:"Summarize the input", model:"chat",
    modelRoles:{planningModel:"planner", executionModel:"executor"}}, async model => trace.push(model), () => true);
  assert.deepEqual(trace, ["planner", "Summarize the input", "executor",
    "Implement this proposed plan for the user's latest task:\n\nRead the input and write the summary."]);
});
