import assert from "node:assert/strict";
import { readFile, rm } from "node:fs/promises";
import { test } from "node:test";
import { createBackgroundJobsExtension, createJobManager, DEFAULT_YIELD_MS } from "../runtime/background-jobs.mjs";

test("command stdin remains available after the command is handed off", async () => {
  const adapter = createBackgroundJobsExtension();
  const jobs = await adapter.getManager("owner");
  const chunks = [];
  try {
    const result = await adapter.foreground({
      sessionId: "owner", command: 'printf "Confirm?\\n"; read -r answer; printf "answer=%s\\n" "$answer"',
      onData: chunk => chunks.push(chunk), cwd: process.cwd(),
    });
    assert.equal(result.exitCode, null);
    const session = result.commandSession;
    assert.equal(session.status, "running");
    assert.match(Buffer.concat(chunks).toString(), /Confirm\?/);
    const other = await adapter.getManager("other");
    try { await assert.rejects(other.write(session.id, "y\n"), /Unknown/); }
    finally { await adapter.dispose("other"); await rm(other.directory, { recursive: true, force: true }); }
    await jobs.write(session.id, "y\n");
    assert.equal((await jobs.wait(session.id)).exitCode, 0);
    assert.match((await jobs.read(session.id, session)).stdout, /answer=y/);
    assert.match(await readFile(session.stdoutPath, "utf8"), /Confirm\?\nanswer=y/);
  } finally {
    await adapter.disposeAll();
    await rm(jobs.directory, { recursive: true, force: true });
  }
});

test("a long explicit timeout remains a hard deadline after yielding", async () => {
  const adapter = createBackgroundJobsExtension();
  const jobs = await adapter.getManager("deadline");
  try {
    const result = await adapter.foreground({
      sessionId: "deadline", command: "sleep 45", cwd: process.cwd(), onData() {},
      timeoutMs: DEFAULT_YIELD_MS + 1500,
    });
    assert.equal(result.commandSession.status, "running");
    const completed = await jobs.wait(result.commandSession.id, { timeoutMs: 5000 });
    assert.equal(completed.status, "killed");
    assert.equal(completed.reason, "timeout");
  } finally {
    await adapter.disposeAll();
    await rm(jobs.directory, { recursive: true, force: true });
  }
});
