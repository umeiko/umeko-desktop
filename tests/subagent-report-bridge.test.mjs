import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { once } from "node:events";
import { createInterface } from "node:readline";
import { mkdtempSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const release = join(root, "runtime/releases/coding-1.3.0");
const CHILD_HINT = "notify_parent";

// A background subagent reports after its parent finished the turn, and Pi
// starts a new parent run by itself. Returns once that run is streaming.
async function reportRun(t) {
  assert.deepEqual(readFileSync(join(release, "bridge.mjs")), readFileSync(join(root, "runtime/bridge.mjs")),
    "Run prepare_runtime.py before testing a changed bridge");
  const dir = mkdtempSync(join(tmpdir(), "umeko-subagent-report-")), agentDir = join(dir, "agent");
  mkdirSync(agentDir);
  let releaseChild, releaseReport, reportStreaming;
  const childGate = new Promise(resolve => { releaseChild = resolve; });
  const reportGate = new Promise(resolve => { releaseReport = resolve; });
  const reportStarted = new Promise(resolve => { reportStreaming = resolve; });
  const parents = [];
  const server = createServer(async (req, res) => {
    let raw = ""; for await (const chunk of req) raw += chunk;
    const body = JSON.parse(raw);
    const system = body.messages.filter(m => ["system", "developer"].includes(m.role)).map(m => String(m.content || "")).join("\n");
    const child = system.includes(CHILD_HINT);
    if (!child) parents.push(body.messages.filter(m => m.role === "user").map(m => JSON.stringify(m.content ?? "")));
    const number = parents.length;
    const common = { id: "fixture", object: "chat.completion.chunk", created: 1, model: "test-model" };
    const chunk = (delta, finish = null) => `data: ${JSON.stringify({ ...common, choices: [{ index: 0, delta, finish_reason: finish }] })}\n\n`;
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    res.write(chunk({ role: "assistant" }));
    if (child) {
      await childGate;
      res.end(chunk({ content: "child report" }) + chunk({}, "stop") + "data: [DONE]\n\n");
    } else if (number === 1) {
      res.end(chunk({ tool_calls: [{ index: 0, id: "call-subagent", type: "function", function: { name: "subagent",
        arguments: JSON.stringify({ prompt: "child task", description: "Background probe", subagent_type: "general-purpose", run_in_background: true }) } }] })
        + chunk({}, "tool_calls") + "data: [DONE]\n\n");
    } else if (number === 3) {
      res.write(chunk({ content: "handling report" }));
      reportStreaming();
      await reportGate;
      if (!res.destroyed) res.end(chunk({}, "stop") + "data: [DONE]\n\n");
    } else res.end(chunk({ content: `parent ${number}` }) + chunk({}, "stop") + "data: [DONE]\n\n");
  });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  const bridge = spawn(process.execPath, [join(release, "bridge.mjs")], { cwd: dir, stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
  let stderr = "", pending;
  bridge.stderr.on("data", chunk => { stderr = (stderr + chunk).slice(-1500); });
  const lines = createInterface({ input: bridge.stdout })[Symbol.asyncIterator]();
  const events = [];
  const send = payload => bridge.stdin.write(JSON.stringify(payload) + "\n");
  const until = async (predicate, label = "expected bridge event") => {
    const deadline = Date.now() + 20000;
    for (;;) {
      const found = events.find(predicate);
      if (found) return found;
      pending ||= lines.next();
      let timer;
      const next = await Promise.race([pending, new Promise(resolve => { timer = setTimeout(resolve, Math.max(0, deadline - Date.now())); })]);
      clearTimeout(timer);
      assert.ok(next, `Timed out waiting for ${label}: ${JSON.stringify(events.slice(-6))}`);
      pending = undefined;
      assert.ok(!next.done, "Bridge exited: " + stderr);
      if (next.value.startsWith("{")) events.push(JSON.parse(next.value));
    }
  };
  t.after(async () => {
    releaseChild(); releaseReport();
    if (bridge.exitCode === null) { send({ type: "shutdown" }); await once(bridge, "exit"); }
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
    rmSync(dir, { recursive: true, force: true });
  });

  send({ type: "prompt", text: "delegate", gateway: `http://127.0.0.1:${server.address().port}/`, token: "fixture",
    workspace: dir, defaultCwd: dir, agentDir, sessionDir: join(dir, "sessions"),
    model: "test-model", models: [{ id: "test-model", contextWindow: 128000 }], agent: { safeMode: true } });
  await until(e => e.type === "done" && e.action === "prompt", "the parent's own turn");
  assert.equal(parents.length, 2, "The parent finished its own turn before the child reported");
  const finished = events.length;
  releaseChild();
  await reportStarted;
  const adopted = await until(e => e.type === "agent_run", "agent_run for the report");
  const start = events.indexOf(adopted);
  assert.ok(start >= finished, "The report run is announced after the parent's done");
  await until((e, index) => index > start && e.type === "delta", "the report draft");
  assert.equal(events.slice(start).some(e => e.type === "done"), false, "Busy until the report run ends");
  return { send, until, events, parents, start, finished, releaseReport };
}

test("a background subagent report runs as a tracked desktop action and queues input", { timeout: 90000 }, async t => {
  const run = await reportRun(t);
  // A prompt that crossed agent_run on the wire joins the native follow-up queue.
  run.send({ type: "prompt", text: "user message during report" });
  await run.until(e => e.type === "queue" && e.followUp?.includes("user message during report"), "the queued message");
  run.releaseReport();
  const done = await run.until((e, index) => index > run.start && e.type === "done", "done for the report run");
  assert.equal(done.action, "agent-run");
  assert.deepEqual(run.events.slice(run.finished).filter(e => e.type === "error"), []);
  assert.equal(run.parents.length, 4, "The queued message reached the model after the report");
  assert.ok(run.parents[3].some(text => text.includes("user message during report")));
  assert.ok(run.events.slice(run.start, run.events.indexOf(done)).some(e => e.type === "state"),
    "The desktop receives the refreshed transcript before done");
});

test("Stop ends a background subagent report run and the next prompt starts normally", { timeout: 90000 }, async t => {
  const run = await reportRun(t);
  run.send({ type: "abort" });
  const done = await run.until((e, index) => index > run.start && e.type === "done", "done after Stop");
  assert.equal(done.action, "agent-run");
  const after = run.events.length;
  run.send({ type: "prompt", text: "next prompt" });
  await run.until((e, index) => index >= after && e.type === "done" && e.action === "prompt", "the next prompt");
  assert.deepEqual(run.events.slice(run.finished).filter(e => e.type === "error"), []);
  assert.ok(run.parents.at(-1).some(text => text.includes("next prompt")));
});
