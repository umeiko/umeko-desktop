import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { createBackgroundJobsExtension, createJobManager } from "../runtime/background-jobs.mjs";
import { blockedProcessCommand } from "../runtime/process-guard.mjs";

const quote = value => `'${String(value).replace(/'/g, `'\\''`)}'`;
const nodeCommand = code => `${quote(process.execPath.replaceAll("\\", "/"))} -e ${quote(code)}`;

test("process guard blocks image-name and bulk kills, permits explicit positive PIDs", () => {
  const blocked = [
    "taskkill /F /IM python.exe", "taskkill.exe //IM node.exe //F", "taskkill /PID 123 /FI STATUS eq RUNNING",
    "taskkill /PID * /T /F", "taskkill /F", 'powershell -Command "Stop-Process -Name python -Force"',
    "Stop-Process python", "Get-Process python | Stop-Process", "gps node | spps",
    "pkill -f python", "killall node", "tskill python", "kill 0", "kill -1", "kill -9 -123",
    "kill -s KILL 0", "kill -- -1", "wmic process where name=python.exe delete",
    'wmic process where "(name=\'python.exe\')" delete', "wmic process delete",
  ];
  for (const command of blocked) assert.ok(blockedProcessCommand(command), command);
  const allowed = ["printf hello", "taskkill /PID 123 /T /F", "taskkill //PID 123 //T //F",
    "kill 123", "kill -9 123", "kill -s TERM 123", "kill -- 123", "Stop-Process -Id 123 -Force",
    "Get-Process -Id 123 | Stop-Process", "wmic process where processid=123 delete"];
  for (const command of allowed) assert.equal(blockedProcessCommand(command), undefined, command);
});

test("new guard case: one positive PID with redirection stays allowed; multiple PIDs are bulk", () => {
  for (const command of ["taskkill /PID 123 /T /F 2>/dev/null", "taskkill /PID 123 /T /F 2>&1",
    "kill -9 123 >/dev/null 2>&1", 'Stop-Process -Id 123 -Force > "output log.txt"']) {
    assert.equal(blockedProcessCommand(command), undefined, command);
  }
  for (const command of ["taskkill /PID 123 /PID 456 /F", "kill 123 456", "kill -s TERM 123 456",
    "Stop-Process -Id 123,456", "Stop-Process -Id 123 -Id 456", "taskkill /PID 123 /IM node.exe 2>/dev/null",
    "taskkill /PID 123 /F 2>/dev/null; pkill python"]) assert.ok(blockedProcessCommand(command), command);
});

test("guard allows literal arguments instead of treating them as executables", () => {
  for (const command of ["rg -n 'kill' runtime", "git commit -m 'fix kill handling'",
    "printf '%s\\n' 'pkill'", "echo taskkill", "echo 'pkill; killall node' | cat",
    'bash -c "echo taskkill"', `sh -c "printf '%s' 'pkill'"`,
    `powershell -Command "Write-Output 'Stop-Process -Name x'"`, "cmd /c echo taskkill"]) {
    assert.equal(blockedProcessCommand(command), undefined, command);
  }
});

test("guard follows command positions across operators and nested shell strings", () => {
  for (const command of ['bash -c "pkill python"', "sh -c 'killall node'",
    'bash -lc "echo ok; pkill python"', 'powershell -Command "Stop-Process -Name python"',
    "cmd /c taskkill /IM python.exe /F", 'wmic process where name="python.exe" delete',
    "echo ok | pkill python", "echo ok; killall node", "echo ok && taskkill /IM python.exe",
    "echo ok || Stop-Process -Name python", "Get-Process python | Stop-Process"]) {
    assert.ok(blockedProcessCommand(command), command);
  }
  for (const command of ['bash -c "kill -9 1234"', "cmd /c taskkill /PID 1234 /F",
    'powershell -Command "Stop-Process -Id 1234"']) {
    assert.equal(blockedProcessCommand(command), undefined, command);
  }
});

test("tool-call guard covers all bundled command tools, including native PowerShell", () => {
  const handlers = new Map();
  createBackgroundJobsExtension().extension({ on: (name, handler) => handlers.set(name, handler), registerTool() {} });
  const hook = handlers.get("tool_call");
  for (const toolName of ["bash", "powershell", "background_job"]) {
    const input = command => ({ command, ...(toolName === "background_job" ? { action: "start" } : {}) });
    for (const command of ["Stop-Process -Name python -Force", "Get-Process x | Stop-Process"]) {
      assert.equal(hook({ toolName, input: input(command) }).block, true, `${toolName}: ${command}`);
    }
    for (const command of ["Stop-Process -Id 1234", "Write-Output 'Stop-Process -Name x'"]) {
      assert.equal(hook({ toolName, input: input(command) }), undefined, `${toolName}: ${command}`);
    }
  }
  assert.equal(hook({ toolName: "powershell", parentToolCallId: "codemode-parent",
    input: { command: "Stop-Process -Name python" } }).block, true);
  assert.equal(hook({ toolName: "powershell", input: {
    command: `& 'C:\\Windows\\System32\\taskkill.exe' /IM python.exe /F` } }).block, true);
  assert.equal(hook({ toolName: "powershell", input: {
    command: `& 'C:\\Windows\\System32\\taskkill.exe' /PID 1234 /F` } }), undefined);
  assert.equal(hook({ toolName: "background_job", input: { action: "read", command: "pkill x" } }), undefined);
});

test("real background lifecycle: deadline, exit status, distinct files and byte cursors", async () => {
  const jobs = await createJobManager();
  try {
    const command = nodeCommand("console.log('first'); console.error('problem'); setTimeout(()=>{console.log('last'); process.exit(7)}, 450)");
    const [first, second] = await Promise.all([jobs.start({ command }), jobs.start({ command })]);
    assert.notEqual(first.id, second.id);
    assert.notEqual(first.stdoutPath, second.stdoutPath);
    assert.notEqual(first.stderrPath, second.stderrPath);
    assert.notEqual(first.stdoutPath, first.stderrPath);
    assert.equal(first.status, "running");
    const timeout = await jobs.wait(first.id, { timeoutMs: 1 });
    assert.equal(timeout.timedOut, true);
    assert.equal(timeout.status, "running");
    const done = await jobs.wait(first.id, { timeoutMs: 10000 });
    assert.equal(done.exitCode, 7);
    assert.equal(done.status, "failed");
    assert.equal(done.timedOut, false);
    const head = await jobs.read(first.id, { maxBytes: 5 });
    assert.equal(head.stdout, "first");
    assert.equal(head.stderr, "probl");
    const rest = await jobs.read(first.id, head);
    assert.equal(head.stdout + rest.stdout, "first\nlast\n");
    assert.equal(head.stderr + rest.stderr, "problem\n");
    const tail = await jobs.read(first.id, rest);
    assert.equal(tail.stdout, ""); assert.equal(tail.stderr, "");
    assert.equal(tail.stdoutOffset, rest.stdoutOffset);
    assert.equal(await readFile(first.stdoutPath, "utf8"), "first\nlast\n");
    assert.equal(await readFile(first.stderrPath, "utf8"), "problem\n");
    await jobs.wait(second.id, { timeoutMs: 10000 });
    const success = await jobs.start({ command: "printf complete" });
    assert.equal((await jobs.wait(success.id, { timeoutMs: 10000 })).exitCode, 0);
    assert.equal(jobs.status(success.id).status, "completed");
    await assert.rejects(jobs.kill("not-owned"), /Unknown/);
    assert.equal(jobs.list().length, 3);
  } finally {
    await jobs.dispose();
    await rm(jobs.directory, { recursive: true, force: true });
  }
});

test("kill by job ID stops only its owned tree; session disposal leaves another manager alone", async () => {
  const directory = await mkdtemp(join(tmpdir(), "umeko-job-test-"));
  const fixture = join(directory, "tree.cjs"), marker = join(directory, "tree-stopped.txt");
  // Grandchild would write a marker after the kill if tree termination failed.
  await writeFile(fixture, `const {spawn}=require('node:child_process');
const child=spawn(process.execPath,['-e',${JSON.stringify(`setTimeout(()=>require('node:fs').writeFileSync(${JSON.stringify(marker)},'still alive'),1500);setInterval(()=>{},1000)`)}],{stdio:'ignore',windowsHide:true});
console.log(child.pid);setInterval(()=>{},1000);`);
  const jobs = await createJobManager(), other = await createJobManager();
  try {
    const tree = await jobs.start({ command: `${quote(process.execPath.replaceAll("\\", "/"))} ${quote(fixture.replaceAll("\\", "/"))}` });
    const survivor = await other.start({ command: nodeCommand("setInterval(()=>{},1000)") });
    // Wait for actual grandchild creation using bounded new-output reads.
    let childPid;
    const deadline = Date.now() + 5000;
    while (!childPid && Date.now() < deadline) {
      const output = await jobs.read(tree.id);
      childPid = Number(output.stdout.trim());
      if (!childPid) await new Promise(resolve => setTimeout(resolve, 25));
    }
    assert.ok(Number.isInteger(childPid) && childPid > 0);
    assert.equal((await jobs.kill(tree.id)).status, "killed");
    try {
      process.kill(childPid, 0);
      // Linux can retain a terminated orphan as a zombie until init reaps it.
      // Z proves exit even though signal 0 can still find its process-table row.
      if (process.platform !== "linux") assert.fail("Owned child is still alive");
      assert.match(await readFile(`/proc/${childPid}/stat`, "utf8"), /^\d+ \(.*\) Z /);
    } catch (error) {
      if (!['ESRCH', 'ENOENT'].includes(error.code)) throw error;
    }
    const ownSecond = await jobs.start({ command: nodeCommand("setInterval(()=>{},1000)") });
    await jobs.dispose();
    assert.equal(jobs.status(ownSecond.id).status, "killed");
    assert.equal((await other.wait(survivor.id, { timeoutMs: 1 })).status, "running");
    await assert.rejects(jobs.start({ command: "printf closed" }), /closed/);
  } finally {
    await jobs.dispose(); await other.dispose();
    await rm(directory, { recursive: true, force: true });
    await rm(jobs.directory, { recursive: true, force: true });
    await rm(other.directory, { recursive: true, force: true });
  }
});

test("new byte-cursor case: a one-byte page preserves multibyte output", async () => {
  const jobs = await createJobManager();
  try {
    const job = await jobs.start({ command: nodeCommand("process.stdout.write('中文🙂x')") });
    await jobs.wait(job.id, { timeoutMs: 10000 });
    const first = await jobs.read(job.id, { maxBytes: 1 });
    assert.equal(first.stdout, "中"); assert.equal(first.stdoutOffset, 3);
    const second = await jobs.read(job.id, { ...first, maxBytes: 1 });
    assert.equal(second.stdout, "文"); assert.equal(second.stdoutOffset, 6);
    const third = await jobs.read(job.id, { ...second, maxBytes: 1 });
    assert.equal(third.stdout, "🙂"); assert.equal(third.stdoutOffset, 10);
    const last = await jobs.read(job.id, third);
    assert.equal(last.stdout, "x"); assert.equal(last.stdoutOffset, 11);
  } finally {
    await jobs.dispose(); await rm(jobs.directory, { recursive: true, force: true });
  }
});

test("completed output consumes incomplete or invalid UTF-8 instead of holding its cursor", async () => {
  const jobs = await createJobManager();
  try {
    for (const bytes of [[0xe9], [0xe9, 0x80], [0xff]]) {
      const job = await jobs.start({ command: nodeCommand(`process.stdout.write(Buffer.from(${JSON.stringify(bytes)}))`) });
      assert.equal((await jobs.wait(job.id, { timeoutMs: 10000 })).status, "completed");
      const output = await jobs.read(job.id, { maxBytes: 1 });
      assert.equal(output.stdout, "\ufffd");
      assert.equal(output.stdoutOffset, bytes.length);
      assert.equal(output.hasMore, false);
      const next = await jobs.read(job.id, output);
      assert.equal(next.stdout, "");
      assert.equal(next.stdoutOffset, bytes.length);
      assert.equal(next.hasMore, false);
    }
  } finally {
    await jobs.dispose(); await rm(jobs.directory, { recursive: true, force: true });
  }
});

test("running output retains a partial UTF-8 character until its remaining bytes arrive", async () => {
  const jobs = await createJobManager();
  try {
    const job = await jobs.start({ command: nodeCommand(
      "process.stdout.write(Buffer.from([0xe9]));setTimeout(()=>process.stdout.write(Buffer.from([0x80,0x80])),700)") });
    const deadline = Date.now() + 5000;
    while (!(await readFile(job.stdoutPath)).length && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 10));
    assert.equal(jobs.status(job.id).status, "running");
    const partial = await jobs.read(job.id, { maxBytes: 1 });
    assert.equal(partial.stdout, ""); assert.equal(partial.stdoutOffset, 0);
    assert.equal(partial.hasMore, true);
    await jobs.wait(job.id, { timeoutMs: 10000 });
    const complete = await jobs.read(job.id, { ...partial, maxBytes: 1 });
    assert.equal(complete.stdout, "退"); assert.equal(complete.stdoutOffset, 3);
    assert.equal(complete.hasMore, false);
  } finally {
    await jobs.dispose(); await rm(jobs.directory, { recursive: true, force: true });
  }
});

test("extension registers a natural-language tool, pre-execution hook and per-session cleanup", async () => {
  const handlers = new Map(), tools = [];
  const adapter = createBackgroundJobsExtension();
  adapter.extension({ on: (name, handler) => handlers.set(name, handler), registerTool: tool => tools.push(tool) });
  assert.equal(tools.length, 1);
  assert.equal(tools[0].name, "background_job");
  assert.ok(handlers.has("session_before_switch")); assert.ok(handlers.has("session_shutdown"));
  const hook = handlers.get("tool_call");
  assert.equal(hook({ toolName: "bash", input: { command: "pkill node" } }).block, true);
  assert.equal(hook({ toolName: "background_job", input: { action: "start", command: "killall python" } }).block, true);
  assert.equal(hook({ toolName: "bash", input: { command: "taskkill /PID 123 /F" } }), undefined);
  const execute = args => tools[0].execute("test", args, undefined, undefined, { cwd: fileURLToPath(new URL("../", import.meta.url)) });
  let manager;
  try {
    const start = await execute({ action: "start", command: nodeCommand("setInterval(()=>{},1000)") });
    assert.equal(start.details.status, "running");
    manager = await adapter.getManager();
    await handlers.get("session_before_switch")();
    assert.equal(manager.status(start.details.id).status, "killed");
    const next = await adapter.getManager();
    assert.notEqual(next.directory, manager.directory);
    await handlers.get("session_shutdown")();
    await rm(next.directory, { recursive: true, force: true });
  } finally {
    await adapter.dispose();
    if (manager) await rm(manager.directory, { recursive: true, force: true });
  }
});
