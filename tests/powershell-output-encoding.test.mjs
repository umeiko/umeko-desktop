import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { fileURLToPath, pathToFileURL } from "node:url";
import { join } from "node:path";
import { test } from "node:test";

const root = fileURLToPath(new URL("../", import.meta.url));
const quote = value => "'" + value.replaceAll("'", "''") + "'";
const release = process.env.UMEKO_TEST_PI_RELEASE || join(root, "runtime", "releases", "coding-1.5.2");
const python = process.env.UMEKO_TEST_HOST_PYTHON || join(root, ".venv", "Scripts", "python.exe");
const hostScript = join(root, "main.py");
const hostKey = Symbol.for("umeko:bash-job");

test("Windows Pi PowerShell opt-in decodes CP936 on both streams without changing default UTF-8", {
  skip: process.platform !== "win32", timeout: 45000,
}, async () => {
  const cwd = await mkdtemp(join(tmpdir(), "Umeko 中文-CP936-"));
  const priorAgent = process.env.PI_CODING_AGENT_DIR;
  const priorPath = process.env.PATH;
  process.env.PI_CODING_AGENT_DIR = cwd;
  let adapter, manager;
  try {
    const { createBackgroundJobsExtension } = await import(pathToFileURL(join(release, "background-jobs.mjs")));
    const tools = join(release, "node_modules", "@earendil-works", "pi-coding-agent", "dist", "core", "tools");
    const { createPowerShellToolDefinition } = await import(pathToFileURL(join(tools, "powershell.js")));
    const { createBashToolDefinition } = await import(pathToFileURL(join(tools, "bash.js")));
    const { getPowerShellConfig } = await import(pathToFileURL(join(tools, "../../utils/shell.js")));
    const tool = createPowerShellToolDefinition(cwd);
    assert.ok(tool.parameters.properties.output_encoding);
    assert.equal(createBashToolDefinition(cwd).parameters.properties.output_encoding, undefined);
    assert.equal(createPowerShellToolDefinition(cwd, { operations: {} }).parameters.properties.output_encoding, undefined);

    const selected = getPowerShellConfig().shell;
    const legacy = join(process.env.SystemRoot, "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
    assert.ok(existsSync(legacy), "Windows PowerShell 5.1 should be available on Windows CI");
    const shells = [...new Set([selected, legacy].map(path => path.toLowerCase()))];
    adapter = createBackgroundJobsExtension({ cwd, host: python, hostScript });
    manager = await adapter.getManager("encoding-fixture");
    const fixture = join(cwd, "native.cjs");
    await writeFile(fixture, 'process.stdout.write(Buffer.from(process.argv[2], "hex"));process.stderr.write(Buffer.from(process.argv[3], "hex"));\n');
    const command = (out, err) => ["&", quote(process.execPath), quote(fixture), out, err].join(" ");
    for (const [n, shell] of shells.entries()) {
      process.env.PATH = shell === selected.toLowerCase()
        ? priorPath
        : [join(process.env.SystemRoot, "System32"), join(legacy, "..")].join(";");
      assert.equal(getPowerShellConfig().shell.toLowerCase(), shell);
      globalThis[hostKey] = req => {
        assert.equal(req.shellConfig.shell.toLowerCase(), shell);
        return adapter.foreground({ ...req, sessionId: "encoding-fixture", waitForExit: true });
      };
      const run = async (command, output_encoding) =>
        (await tool.execute("test-" + n, { command, timeout: 12, ...(output_encoding && { output_encoding }) })).structuredContent;
      const nativeUnicode = await run(command("e4b8ade69687", "e6b58be8af95"));
      assert.equal(nativeUnicode.exit_code, 0, shell);
      assert.equal(nativeUnicode.output, "中文\n测试", shell);
      const shellUnicode = await run("Write-Output ([string][char]0x4e2d+[char]0x6587)");
      assert.equal(shellUnicode.output.trim(), "中文", shell);
      const original = await run(command("d6d0cec4", "b2e2cad4"));
      assert.equal(original.exit_code, 0, shell);
      assert.match(original.output, /\uFFFD/u);
      const fixed = await run(command("d6d0cec4", "b2e2cad4"), "gbk");
      assert.equal(fixed.exit_code, 0, shell);
      assert.equal(fixed.output, "中文\n测试", shell);
      const last = manager.list().at(-1);
      assert.equal((await readFile(last.stdoutPath)).toString("hex"), "d6d0cec4");
      assert.equal((await readFile(last.stderrPath)).toString("hex"), "b2e2cad4");
      const page = await manager.read(last.id, { maxBytes: 1 });
      assert.deepEqual([page.stdout, page.stderr, page.stdoutOffset, page.stderrOffset, page.hasMore], ["中", "测", 2, 2, true]);
      const tail = await manager.read(last.id, { ...page, maxBytes: 1 });
      assert.deepEqual([tail.stdout, tail.stderr, tail.stdoutOffset, tail.stderrOffset, tail.hasMore], ["文", "试", 4, 4, false]);
      const incomplete = await run(command("d6", "b2"), "gbk");
      assert.match(incomplete.output, /^\uFFFD\n\uFFFD$/u);
      console.log("PowerShell CP936 verified:", shell);
    }
    const delayed = join(cwd, "delayed.cjs");
    const gate = join(cwd, "continue");
    await writeFile(delayed, 'const fs=require("node:fs");process.stdout.write(Buffer.from([0xd6]));process.stderr.write("ready");const t=setInterval(()=>{if(fs.existsSync(' +
      JSON.stringify(gate) + ')){clearInterval(t);process.stdout.write(Buffer.from([0xd0]));}},20);\n');
    const live = await manager.start({
      command: "& " + quote(process.execPath) + " " + quote(delayed),
      shellName: "powershell", outputEncoding: "gbk", timeoutMs: 6000,
    });
    const deadline = Date.now() + 4000;
    let page;
    do {
      page = await manager.read(live.id, { maxBytes: 5 });
      if (page.stderr === "ready") break;
      await new Promise(resolve => setTimeout(resolve, 30));
    } while (Date.now() < deadline);
    assert.equal(page.stderr, "ready");
    assert.deepEqual([page.stdout, page.stdoutOffset, page.hasMore], ["", 0, true]);
    await writeFile(gate, "continue");
    assert.equal((await manager.wait(live.id, { timeoutMs: 6000 })).exitCode, 0);
    const rest = await manager.read(live.id, { ...page, maxBytes: 1 });
    assert.deepEqual([rest.stdout, rest.stdoutOffset, rest.hasMore], ["中", 2, false]);
  } finally {
    delete globalThis[hostKey];
    process.env.PATH = priorPath;
    if (priorAgent === undefined) delete process.env.PI_CODING_AGENT_DIR;
    else process.env.PI_CODING_AGENT_DIR = priorAgent;
    await adapter?.disposeAll();
    if (manager) await rm(manager.directory, { recursive: true, force: true });
    await rm(cwd, { recursive: true, force: true });
  }
});
