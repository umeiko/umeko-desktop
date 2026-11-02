import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { createInterface } from "node:readline";
import { once } from "node:events";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, existsSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const release = join(root, "runtime/releases/coding-1.3.0");
const png = "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAACXBIWXMAAA9hAAAPYQGoP6dpAAAAKElEQVRIie3NMQEAAAjDMMC/ZzDBvlRA01vZJvwHAAAAAAAAAAAAbx2jxAE/0VKtIwAAAABJRU5ErkJggg==";

test("real bridge completes 25 mixed images, reopens an archived image, and preserves history", { timeout: 120000 }, async t => {
  const base = process.env.UMEKO_RECENT_IMAGES_TEST_ROOT || tmpdir();
  mkdirSync(base, { recursive: true });
  const dir = mkdtempSync(join(base, "recent-images-")), agentDir = join(dir, "agent");
  mkdirSync(agentDir, { recursive: true });
  writeFileSync(join(agentDir, "settings.json"), JSON.stringify({ retry: { enabled: false }, cacheWarming: "off" }));
  const counts = [], errors = [], readPaths = [];
  let reopening = false, sessionFile, child, stderr = "";
  const server = createServer(async (req, res) => {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    const body = JSON.parse(raw);
    const count = body.messages.reduce((n, message) => n + (Array.isArray(message.content)
      ? message.content.filter(block => block.type === "image_url").length : 0), 0);
    counts.push(count);
    if (count > 3) {
      errors.push(count);
      res.writeHead(400, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: { message: "At most 3 image(s) may be provided in one prompt. (parameter=image)", type: "invalid_request_error" } }));
      return;
    }
    const last = body.messages.at(-1);
    let delta = { role: "assistant", content: "seen" }, finish = "stop";
    const text = typeof last.content === "string" ? last.content : (last.content || []).filter(b => b.type === "text").map(b => b.text).join("\n");
    let path;
    if (last.role === "user" && text.startsWith("Read image ")) path = JSON.parse(text.slice("Read image ".length));
    if (last.role === "user" && text === "What was on image 1? Open it again.") {
      const placeholder = body.messages.flatMap(m => typeof m.content === "string" ? [m.content] : (m.content || []).filter(b => b.type === "text").map(b => b.text))
        .find(value => value.includes("[Image removed from context"));
      assert.ok(placeholder, "First image must have a reopen placeholder");
      path = JSON.parse(placeholder.match(/Use read on (.+) to see it again\./)[1]);
      assert.ok(existsSync(path));
      assert.equal(readFileSync(path).toString("base64"), png);
      reopening = true;
    }
    if (path) {
      readPaths.push(path);
      delta = { role: "assistant", tool_calls: [{ index: 0, id: `read-${readPaths.length}`, type: "function", function: { name: "read", arguments: JSON.stringify({ path }) } }] };
      finish = "tool_calls";
    } else if (reopening) {
      assert.ok(body.messages.some(m => m.role === "tool" && m.tool_call_id === `read-${readPaths.length}`));
      assert.ok(count > 0, "Native read must return the reopened image to the provider");
      delta.content = "reopened image 1";
    }
    const common = { id: "fixture", object: "chat.completion.chunk", created: 1, model: "test-model" };
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    res.end(`data: ${JSON.stringify({ ...common, choices: [{ index: 0, delta, finish_reason: null }] })}\n\ndata: ${JSON.stringify({ ...common, choices: [{ index: 0, delta: {}, finish_reason: finish }], usage: { prompt_tokens: 100, completion_tokens: 5, total_tokens: 105 } })}\n\ndata: [DONE]\n\n`);
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  child = spawn(process.execPath, [join(release, "bridge.mjs")], {
    cwd: dir, stdio: ["pipe", "pipe", "pipe"], windowsHide: true,
    env: { ...process.env, QT_QPA_PLATFORM: "offscreen", QT_QUICK_BACKEND: "software" },
  });
  child.stderr.on("data", chunk => { stderr = (stderr + chunk).slice(-2000); });
  const lines = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
  const command = async payload => {
    child.stdin.write(JSON.stringify(payload) + "\n");
    const events = [];
    for (;;) {
      const next = await lines.next();
      assert.ok(!next.done, `Bridge exited: ${stderr}`);
      const event = JSON.parse(next.value);
      events.push(event);
      if (event.type === "done") break;
    }
    assert.equal(events.filter(e => e.type === "error").length, 0, "No bridge errors");
    return events;
  };
  t.after(async () => {
    if (child.exitCode === null) {
      child.stdin.write(JSON.stringify({ type: "shutdown" }) + "\n");
      await once(child, "exit");
    }
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
    rmSync(dir, { recursive: true, force: true });
  });
  const init = await command({ type: "inspect", gateway: `http://127.0.0.1:${server.address().port}/`, token: "test-only",
    workspace: dir, defaultCwd: dir, agentDir, sessionDir: join(dir, "sessions"),
    models: [{ id: "test-model", input: ["text", "image"], contextWindow: 128000 }], model: "test-model", agent: { autoCompaction: false } });
  const resources = init.find(e => e.type === "state").resources;
  assert.deepEqual(resources.contextFiles, [], "Isolated fixture must load no ancestor context files");
  for (let i = 1; i <= 25; i++) {
    const path = join(dir, `image-${i}.png`);
    if (i !== 1) writeFileSync(path, Buffer.from(png, "base64"));
    if (i % 2) {
      // First attachment deliberately has no original file: archive session bytes.
      await command({ type: "prompt", text: i === 1 ? "Image 1" : `Image ${i}\n\n附件（用户提供的路径；按需使用原生工具读取）：\n- image: ${path}`,
        images: [{ type: "image", data: png, mimeType: "image/png" }] });
    } else await command({ type: "prompt", text: `Read image ${JSON.stringify(path)}` });
  }
  const final = await command({ type: "prompt", text: "What was on image 1? Open it again." });
  sessionFile = final.find(e => e.type === "session").session.file;
  assert.deepEqual(errors, []);
  assert.equal(Math.max(...counts), 3);
  assert.equal(readPaths.length, 13, "12 native tool reads plus reopening image 1");
  const entries = readFileSync(sessionFile, "utf8").trim().split("\n").map(line => JSON.parse(line));
  const messages = entries.filter(e => e.type === "message").map(e => e.message);
  const images = messages.flatMap(m => Array.isArray(m.content) ? m.content.filter(b => b.type === "image") : []);
  assert.equal(images.length, 26, "25 original images and the reopened image remain stored");
  assert.ok(!messages.some(m => JSON.stringify(m.content).includes("[Image removed from context")));
  assert.ok(messages.some(m => m.role === "assistant" && m.content.some(b => b.text === "seen")));
  console.log(`25-image conversation: ${counts.length} requests; maximum ${Math.max(...counts)} images; ${errors.length} provider errors; context files: []`);
});
