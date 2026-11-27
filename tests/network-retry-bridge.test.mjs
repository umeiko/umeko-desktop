import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { once } from "node:events";
import { createInterface } from "node:readline";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const release = join(root, "runtime/releases/coding-1.5.2");

async function fixture(t, { compaction = false, streamMaxRetries = 5 } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "umeko-retry-")), agentDir = join(dir, "agent");
  mkdirSync(agentDir);
  writeFileSync(join(agentDir, "settings.json"), JSON.stringify({
    compaction: { reserveTokens: 16384, keepRecentTokens: 100 },
  }));
  writeFileSync(join(dir, "fixture.txt"), "fixture");
  // Observe real Pi events without modifying the installed SDK. Also keep any
  // native subprocesses invisible on Windows, like the bridge process itself.
  const observer = join(dir, "observer.mjs");
  writeFileSync(observer, `
    import cp from 'node:child_process';
    import {syncBuiltinESMExports} from 'node:module';
    for (const name of ['spawn','spawnSync','execFile','execFileSync']) {
      const original = cp[name];
      cp[name] = function(file, args, options, ...rest) {
        if (Array.isArray(args)) return original.call(this, file, args, {...options, windowsHide:true}, ...rest);
        return original.call(this, file, {...args, windowsHide:true}, options, ...rest);
      };
    }
    syncBuiltinESMExports();
    const {AgentSession} = await import(${JSON.stringify(pathToFileURL(join(release, "node_modules/@earendil-works/pi-coding-agent/dist/core/agent-session.js")).href)});
    const emit = AgentSession.prototype._emit;
    AgentSession.prototype._emit = function(event) {
      if (['turn_start','message_start','message_end','tool_execution_start','tool_execution_end','agent_end',
           'auto_retry_start','auto_retry_end','summarization_retry_scheduled',
           'summarization_retry_attempt_start','summarization_retry_finished'].includes(event.type))
        process.stdout.write(JSON.stringify({type:'pi_event', event:event.type,
          role:event.message?.role, stopReason:event.message?.stopReason,
          attempt:event.attempt, success:event.success, retryAttempt:this.retryAttempt})+'\\n');
      return emit.call(this, event);
    };
  `);
  // Parallel unittest modules share this prepared release. Never truncate a
  // bridge file that another worker may be importing.
  assert.deepEqual(readFileSync(join(release, "bridge.mjs")), readFileSync(join(root, "runtime/bridge.mjs")),
    "Run prepare_runtime.py before testing a changed bridge");
  const replies = [], calls = [];
  const server = createServer(async (req, res) => {
    let raw = ""; for await (const chunk of req) raw += chunk;
    const body = JSON.parse(raw); calls.push({ summary: !body.tools?.length, body });
    const next = replies.shift();
    if (next?.delayMs) await new Promise(resolve => setTimeout(resolve, next.delayMs));
    if (!next || next.error) {
      if (next?.partialText) {
        const common = { id: "fixture", object: "chat.completion.chunk", created: 1, model: "test-model" };
        res.writeHead(200, { "Content-Type": "text/event-stream" });
        res.write(`data: ${JSON.stringify({ ...common, choices: [{ index: 0, delta: { role: "assistant", content: next.partialText }, finish_reason: null }] })}\n\n`);
        res.end(`data: ${JSON.stringify({ type: "error", error: { message: next.error } })}\n\n`);
        return;
      }
      res.writeHead(next?.status || 503, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: { message: next?.error || "Unexpected fixture request" } }));
      return;
    }
    const delta = next.tool ? { role: "assistant", tool_calls: [{ index: 0, id: next.tool,
      type: "function", function: { name: "read", arguments: JSON.stringify({ path: join(dir, "fixture.txt") }) } }] }
      : { role: "assistant", content: next.content || "fixture success" };
    const common = { id: "fixture", object: "chat.completion.chunk", created: 1, model: "test-model" };
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    res.end(`data: ${JSON.stringify({ ...common, choices: [{ index: 0, delta, finish_reason: null }] })}\n\n` +
      `data: ${JSON.stringify({ ...common, choices: [{ index: 0, delta: {}, finish_reason: next.tool ? "tool_calls" : "stop" }],
        usage: { prompt_tokens: 1800, completion_tokens: 5, total_tokens: 1805 } })}\n\ndata: [DONE]\n\n`);
  });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  const child = spawn(process.execPath, ["--import", pathToFileURL(observer).href,
    "--import", new URL("./retry-clock.mjs", import.meta.url).href, join(release, "bridge.mjs")], {
    cwd: dir, stdio: ["pipe", "pipe", "pipe"], windowsHide: true,
    env: { ...process.env, QT_QPA_PLATFORM: "offscreen", QT_QUICK_BACKEND: "software" },
  });
  let stderr = "";
  child.stderr.on("data", chunk => { stderr = (stderr + chunk).slice(-1500); });
  const lines = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
  const command = async (payload, responses = []) => {
    replies.push(...responses);
    child.stdin.write(JSON.stringify(payload) + "\n");
    const events = [];
    for (;;) {
      const next = await lines.next();
      assert.ok(!next.done, "Bridge exited: " + stderr);
      const event = JSON.parse(next.value); events.push(event);
      if (event.type === "done") break;
    }
    assert.deepEqual(events.filter(e => e.type === "error"), []);
    assert.equal(replies.length, 0, "Pi consumed the expected request sequence");
    return events;
  };
  t.after(async () => {
    if (child.exitCode === null) {
      child.stdin.write('{"type":"shutdown"}\n'); await once(child, "exit");
    }
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
    rmSync(dir, { recursive: true, force: true });
  });
  await command({ type: "inspect", gateway: `http://127.0.0.1:${server.address().port}/`, token: "fixture",
    workspace: dir, defaultCwd: dir, agentDir, sessionDir: join(dir, "sessions"),
    model: "test-model", models: [{ id: "test-model", contextWindow: 128000, streamMaxRetries }],
    agent: { autoCompaction: false, safeMode: !compaction } });
  return { command, calls };
}

const failure = { error: "Network error: stream interrupted" };
const attempts = events => events.filter(e => e.type === "pi_event" && e.event === "auto_retry_start").map(e => e.attempt);

function recovered(events) {
  let active = false, awaitingStart = false, sawRecovery = false;
  for (const e of events) {
    if (e.type === "network_retry") { active = e.active; if (active && e.waiting) awaitingStart = true; }
    if (e.type === "assistant_start" && awaitingStart) {
      assert.equal(e.retry, true, "Recovered draft still replaces the failed assistant draft");
      assert.equal(active, false, "New attempt replaces the retry indicator, like Pi's interactive UI");
      awaitingStart = false; sawRecovery = true;
    }
    if (e.type === "delta") assert.equal(active, false, "Successful streaming must not show Reconnecting");
  }
  assert.ok(sawRecovery);
  assert.equal(active, false);
  assert.equal(events.findLast(e => e.type === "pi_event" && e.event === "agent_end").retryAttempt, 0);
}

test("N transient failures then success hides retry before streaming; exhausted retries retain the final error", { timeout: 60000 }, async t => {
  const f = await fixture(t);
  const events = await f.command({ type: "prompt", text: "fixture" }, [failure, failure, {}]);
  assert.deepEqual(attempts(events), [1, 2]);
  recovered(events);
  const final = await f.command({ type: "prompt", text: "exhausted" }, Array(6).fill(failure));
  assert.deepEqual(attempts(final), [1, 2, 3, 4, 5]);
  assert.equal(final.filter(e => e.type === "message" && e.role === "assistant" && e.error).length, 1);
  assert.equal(final.find(e => e.type === "pi_event" && e.event === "auto_retry_end").success, false);
  assert.equal(final.findLast(e => e.type === "network_retry").active, false);
});

test("reconnecting status stays visible while retry HTTP request is in flight", { timeout: 60000 }, async t => {
  const f = await fixture(t);
  const events = await f.command({ type: "prompt", text: "slow reconnect" }, [failure, { delayMs: 80 }]);
  assert.deepEqual(attempts(events), [1]);
  const reconnecting = events.findIndex(e => e.type === "network_retry" && e.active === true && e.waiting === false);
  const cleared = events.findIndex((e, i) => i > reconnecting && e.type === "network_retry" && e.active === false);
  const started = events.findLastIndex(e => e.type === "assistant_start");
  assert.ok(reconnecting >= 0, "Expected in-flight reconnecting state");
  assert.ok(cleared > reconnecting && cleared < started, "Reconnecting should clear right before assistant_start");
  recovered(events);
});

test("one session, three turns: each interruption starts at one and each stream hides retry", { timeout: 60000 }, async t => {
  const f = await fixture(t);
  for (let turn = 0; turn < 3; turn++) {
    const events = await f.command({ type: "prompt", text: `turn ${turn}` }, [failure, {}]);
    assert.deepEqual(attempts(events), [1]); recovered(events);
  }
});

test("several tool calls: a mid-turn interruption hides retry and resets before the next interruption", { timeout: 60000 }, async t => {
  const f = await fixture(t);
  const events = await f.command({ type: "prompt", text: "tool sequence" }, [
    { tool: "read-1" }, { tool: "read-2" }, failure, { tool: "read-3" }, failure, {},
  ]);
  assert.deepEqual(attempts(events), [1, 1]);
  const toolEnds = events.filter(e => e.type === "pi_event" && e.event === "tool_execution_end");
  assert.equal(toolEnds.length, 3);
  assert.ok(events.indexOf(toolEnds[1]) < events.findIndex(e => e.type === "network_retry"));
  recovered(events);
});

test("compaction retries replace the retry indicator at attempt start and restart their count", { timeout: 60000 }, async t => {
  const f = await fixture(t, { compaction: true });
  for (let round = 0; round < 2; round++) {
    await f.command({ type: "prompt", text: "older history ".repeat(1000) }, [{}]);
    await f.command({ type: "prompt", text: "recent history ".repeat(80) }, [{}]);
    const events = await f.command({ type: "compact" }, [failure, {}]);
    assert.deepEqual(events.filter(e => e.type === "pi_event" && e.event === "summarization_retry_scheduled").map(e => e.attempt), [1]);
    const start = events.findIndex(e => e.type === "pi_event" && e.event === "summarization_retry_attempt_start");
    const finished = events.findIndex(e => e.type === "pi_event" && e.event === "summarization_retry_finished");
    assert.ok(start >= 0 && finished > start);
    const between = events.slice(start + 1, finished);
    assert.ok(between.some(e => e.type === "network_retry" && e.active === false), "Pi restores its compaction indicator when the attempt starts");
    assert.equal(events.findLast(e => e.type === "compaction_event").state, "success");
  }
  assert.equal(f.calls.filter(c => c.summary).length, 4);
});

test("provider streamMaxRetries caps retries and staged-continue preserves partial reply without re-running confirmed tools", { timeout: 60000 }, async t => {
  const f = await fixture(t, { streamMaxRetries: 2 });
  const partialFailure = { error: "Network error: stream interrupted", partialText: "Partial stage draft..." };
  // Step 1 succeeds with a confirmed read tool; Step 2 fails with partial output and exhausts streamMaxRetries=2 (3 attempts total).
  const failed = await f.command({ type: "prompt", text: "staged task" }, [
    { tool: "read-confirmed" },
    partialFailure,
    partialFailure,
    partialFailure,
  ]);
  assert.deepEqual(attempts(failed), [1, 2]);
  const toolEnds = failed.filter(e => e.type === "pi_event" && e.event === "tool_execution_end");
  assert.equal(toolEnds.length, 1);
  const failedState = failed.findLast(e => e.type === "state");
  assert.ok(failedState.messages.some(m => m.role === "assistant" && m.error && m.text.includes("Partial stage draft...")));

  // Trigger staged-continue in the same conversation.
  const continued = await f.command({ type: "staged-continue" }, [{ content: "Stage 2 completed cleanly." }]);
  assert.equal(continued.filter(e => e.type === "pi_event" && e.event === "tool_execution_end").length, 0);
  const continuationCall = f.calls[f.calls.length - 1].body;
  const serialized = JSON.stringify(continuationCall.messages);
  assert.match(serialized, /Partial output preserved as incomplete/);
  assert.match(serialized, /DO NOT re-execute.*read\(/);
  assert.match(serialized, /Partial stage draft/);
  const finalState = continued.findLast(e => e.type === "state");
  assert.ok(finalState.messages.some(m => m.role === "assistant" && m.error && m.text.includes("Partial stage draft...")));
  assert.ok(finalState.messages.some(m => m.role === "assistant" && !m.error && m.text.includes("Stage 2 completed cleanly.")));
});
