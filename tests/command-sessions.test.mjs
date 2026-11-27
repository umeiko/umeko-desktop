import assert from "node:assert/strict";
import { readFile, rm } from "node:fs/promises";
import { test } from "node:test";
import { createBackgroundJobsExtension, createJobManager, DEFAULT_YIELD_MS } from "../runtime/background-jobs.mjs";

test("background commands keep interactive stdin while foreground commands start at EOF", async () => {
  const adapter = createBackgroundJobsExtension();
  const jobs = await adapter.getManager("owner");
  const chunks = [];
  try {
    const result = await adapter.foreground({
      sessionId: "owner", command: 'cat; printf "stdin closed\\n"',
      onData: chunk => chunks.push(chunk), cwd: process.cwd(),
    });
    assert.equal(result.exitCode, 0);
    assert.equal(result.commandSession, undefined);
    assert.match(Buffer.concat(chunks).toString(), /stdin closed/);
    const session = await jobs.start({
      command: 'printf "Confirm?\\n"; read -r answer; printf "answer=%s\\n" "$answer"',
      cwd: process.cwd(), stdinOpen: true,
    });
    assert.equal(session.status, "running");
    const other = await adapter.getManager("other");
    try { await assert.rejects(other.write(session.id, "y\n"), /Unknown/); }
    finally { await adapter.dispose("other"); await rm(other.directory, { recursive: true, force: true }); }
    await jobs.write(session.id, "y\n");
    assert.equal((await jobs.wait(session.id)).exitCode, 0);
    assert.match((await jobs.read(session.id)).stdout, /answer=y/);
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
    await assert.rejects(jobs.write(result.commandSession.id, "y\n"), /Standard input is closed/);
    const completed = await jobs.wait(result.commandSession.id, { timeoutMs: 5000 });
    assert.equal(completed.status, "killed");
    assert.equal(completed.reason, "timeout");
  } finally {
    await adapter.disposeAll();
    await rm(jobs.directory, { recursive: true, force: true });
  }
});

test("a completed long command supplies its beginning and end without a session", async () => {
  const adapter = createBackgroundJobsExtension();
  const jobs = await adapter.getManager("large-result");
  const output = [];
  try {
    const result = await adapter.foreground({
      sessionId: "large-result", command: "printf 'FIRST\\n%070000d\\nLAST\\n' 0",
      onData: chunk => output.push(chunk), cwd: process.cwd(),
    });
    const preview = Buffer.concat(output);
    assert.equal(result.exitCode, 0);
    assert.equal(result.commandSession, undefined);
    assert.ok(preview.length <= 50 * 1024);
    assert.match(preview.toString(), /Total output lines: 3/);
    assert.match(preview.toString(), /FIRST[\s\S]*…[0-9]+ tokens truncated…[\s\S]*LAST/);
    assert.match(await readFile(result.outputPreview.fullOutputPath, "utf8"), /LAST/);
  } finally {
    await adapter.disposeAll();
    await rm(jobs.directory, { recursive: true, force: true });
  }
});
