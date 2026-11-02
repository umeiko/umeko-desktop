import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, readdirSync, unlinkSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { filterRecentImages, createRecentImagesExtension } from "../runtime/recent-images.mjs";

function image(id) {
  return { type: "image", data: `fixture-${id}`, mimeType: "image/png", fixtureId: id };
}

function freeze(value) {
  if (value && typeof value === "object") {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
}

function fixture(t) {
  const base = process.env.UMEKO_RECENT_IMAGES_TEST_ROOT || tmpdir();
  mkdirSync(base, { recursive: true });
  const directory = mkdtempSync(join(base, "umeko-recent-images-"));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const paths = new Map();
  return {
    directory,
    path(id) {
      if (!paths.has(id)) {
        const path = join(directory, `image ${id} 图.png`);
        writeFileSync(path, "readable image fixture");
        paths.set(id, path);
      }
      return paths.get(id);
    },
  };
}

function retainedIds(messages) {
  return messages
    .filter(message => message.role === "user" || message.role === "toolResult")
    .flatMap(message => Array.isArray(message.content) ? message.content : [])
    .filter(block => block.type === "image")
    .map(block => block.fixtureId);
}

function placeholder(path) {
  return {
    type: "text",
    text: `[Image removed from context to save space. Use read on ${JSON.stringify(path)} to see it again.]`,
  };
}

test("user and tool-result images share chronological pruning, preserving metadata and stored history", t => {
  const files = fixture(t);
  const messages = freeze([
    { role: "user", timestamp: 1, custom: { source: "attachment" }, content: [
      { type: "text", text: "before", annotation: { keep: true } }, image("old-user"),
      { type: "text", text: "after" },
    ] },
    { role: "assistant", timestamp: 2, model: "fixture", usage: { input: 10 }, content: [
      { type: "text", text: "I inspected the earlier picture." }, image("assistant-image"),
      { type: "toolCall", id: "read-1", name: "read", arguments: { path: "earlier.png" } },
    ] },
    { role: "toolResult", toolCallId: "read-1", toolName: "read", timestamp: 3,
      isError: false, details: { source: "disk", content: [image("nested-details")] },
      content: [{ type: "text", text: "tool before" }, image("old-tool"), { type: "text", text: "tool after" }] },
    { role: "user", timestamp: 4, content: [image("middle-user")] },
    { role: "toolResult", toolCallId: "read-2", toolName: "read", timestamp: 5,
      content: [image("middle-tool")] },
    { role: "user", timestamp: 6, content: [image("new-a"), { type: "text", text: "between" }, image("new-b")] },
  ]);
  const original = structuredClone(messages);
  const calls = [];
  const filtered = filterRecentImages(messages, {
    limit: 3,
    resolvePath(message, block, index, messageIndex) {
      calls.push({ message, block, index, messageIndex });
      return files.path(block.fixtureId);
    },
  });

  assert.deepEqual(retainedIds(filtered), ["new-a", "new-b"]);
  assert.deepEqual(calls.map(({ block, index, messageIndex }) => [block.fixtureId, index, messageIndex]), [
    ["old-user", 1, 0], ["old-tool", 1, 2], ["middle-user", 0, 3], ["middle-tool", 0, 4],
  ]);
  for (const call of calls) {
    assert.equal(call.message, messages[call.messageIndex]);
    assert.equal(call.block, messages[call.messageIndex].content[call.index]);
  }
  const expected = structuredClone(original);
  for (const call of calls) expected[call.messageIndex].content[call.index] = placeholder(files.path(call.block.fixtureId));
  assert.deepEqual(filtered, expected);
  assert.deepEqual(filtered[1], original[1], "earlier assistant replies remain complete");
  assert.deepEqual(messages, original, "the stored messages and image blocks remain unchanged");
});

for (const count of [0, 1, 2, 3]) {
  test(`${count} eligible images at or below the default limit need no path lookup`, () => {
    const messages = freeze([
      { role: "user", content: Array.from({ length: count }, (_, index) => image(`user-${index}`)) },
      { role: "assistant", content: [image("assistant-1"), image("assistant-2"), image("assistant-3"), image("assistant-4")] },
      { role: "toolResult", toolCallId: "nested", content: [
        { type: "text", text: "nested images are metadata", nested: [image("nested")] },
      ] },
    ]);
    const original = structuredClone(messages);
    const filtered = filterRecentImages(messages, {
      resolvePath() { assert.fail("nothing is being removed, so paths must not be resolved"); },
    });
    assert.deepEqual(filtered, original);
    assert.deepEqual(messages, original);
  });
}

test("an explicit limit above the image count leaves all content untouched", () => {
  const messages = freeze([{ role: "user", content: [image("a"), image("b"), image("c"), image("d")] }]);
  assert.deepEqual(filterRecentImages(messages, {
    limit: 10,
    resolvePath() { assert.fail("a larger limit must not resolve paths"); },
  }), messages);
});

for (const [count, remaining] of [[4, 2], [5, 3], [6, 2]]) {
  test(`limit 3 removes old images in pairs: ${count} images retain the newest ${remaining}`, t => {
    const files = fixture(t);
    const ids = Array.from({ length: count }, (_, index) => `image-${index}`);
    const messages = freeze(ids.map((id, index) => ({
      role: index % 2 ? "toolResult" : "user",
      ...(index % 2 ? { toolCallId: `read-${index}`, toolName: "read" } : {}),
      content: [image(id)],
    })));
    const resolved = [];
    const filtered = filterRecentImages(messages, {
      limit: 3,
      resolvePath(_message, block) { resolved.push(block.fixtureId); return files.path(block.fixtureId); },
    });
    assert.deepEqual(retainedIds(filtered), ids.slice(-remaining));
    assert.deepEqual(resolved, ids.slice(0, count - remaining));
  });
}

for (const limit of [1, 0, -2]) {
  test(`limit ${limit} retains one newest image and cannot disable pruning`, t => {
    const files = fixture(t);
    const messages = freeze([{ role: "user", content: [image("a"), image("b"), image("c")] }]);
    const filtered = filterRecentImages(messages, {
      limit,
      resolvePath(_message, block) { return files.path(block.fixtureId); },
    });
    assert.deepEqual(retainedIds(filtered), ["c"]);
    assert.deepEqual(filtered[0].content, [placeholder(files.path("a")), placeholder(files.path("b")), messages[0].content[2]]);
  });
}

test("replacement text quotes the exact readable path with spaces and Unicode", t => {
  const files = fixture(t);
  const path = files.path("old screenshot 中文");
  const messages = freeze([{ role: "user", content: [
    { type: "text", text: "first" }, image("old"), { type: "text", text: "middle" }, image("new"),
  ] }]);
  const filtered = filterRecentImages(messages, { limit: 1, resolvePath: () => path });
  assert.deepEqual(filtered[0].content, [messages[0].content[0], placeholder(path), messages[0].content[2], messages[0].content[3]]);
  assert.equal(JSON.parse(filtered[0].content[1].text.match(/Use read on (.*) to see it again\./)[1]), path);
});

function extensionFixture(files, messages, { getLimit = () => 1, sessionFile = join(files.directory, "session.jsonl") } = {}) {
  const entries = freeze(messages.map((message, index) => ({ type: "message", id: `entry-${index}`, message })));
  let onContext;
  createRecentImagesExtension({ getLimit })({
    on(event, handler) {
      assert.equal(event, "context");
      onContext = handler;
    },
  });
  assert.equal(typeof onContext, "function");
  const ctx = {
    cwd: files.directory,
    sessionManager: {
      getBranch: () => entries,
      getSessionFile: () => sessionFile,
      getSessionDir: () => files.directory,
      getSessionId: () => "fixture-session",
    },
  };
  return { entries, apply: () => onContext({ messages }, ctx).messages };
}

function reopenPath(block) {
  assert.equal(block.type, "text");
  const match = block.text.match(/^\[Image removed from context to save space\. Use read on (.*) to see it again\.\]$/);
  assert.ok(match, "removed images have the documented reopening instruction");
  return JSON.parse(match[1]);
}

test("extension reuses an existing attachment path without creating an archive", t => {
  const files = fixture(t);
  const path = files.path("original attachment 中文");
  const messages = freeze([{ role: "user", timestamp: 1, content: [
    { type: "text", text: `Attached files:\n- image: ${path}\n` }, image("old"), image("new"),
  ] }]);
  const extension = extensionFixture(files, messages);
  const filtered = extension.apply();
  assert.equal(reopenPath(filtered[0].content[1]), path);
  assert.deepEqual(filtered[0].content[0], messages[0].content[0]);
  assert.equal(existsSync(join(files.directory, "session.jsonl.images")), false);
});

test("extension resolves read-result images using their preceding tool call and working directory", t => {
  const files = fixture(t);
  const path = files.path("read original");
  const relativePath = "image read original 图.png";
  const messages = freeze([
    { role: "assistant", timestamp: 1, content: [
      { type: "text", text: "Opening the picture now." },
      { type: "toolCall", id: "read-old", name: "read", arguments: { path: relativePath } },
    ] },
    { role: "toolResult", timestamp: 2, toolCallId: "read-old", toolName: "read", details: { original: true },
      content: [{ type: "text", text: "read image" }, image("old-tool")] },
    { role: "user", timestamp: 3, content: [image("new")] },
  ]);
  const extension = extensionFixture(files, messages);
  const filtered = extension.apply();
  assert.equal(reopenPath(filtered[1].content[1]), path);
  assert.deepEqual(filtered[0], messages[0]);
  assert.deepEqual(filtered[1].details, messages[1].details);
  assert.equal(existsSync(join(files.directory, "session.jsonl.images")), false);
});

for (const withSessionFile of [true, false]) {
  test(`extension archives unlocated original bytes in a session-specific directory (${withSessionFile ? "session file" : "session ID"})`, t => {
    const files = fixture(t);
    const bytes = Buffer.from([0, 255, 137, 80, 78, 71, 13, 10, 34, 92, 128]);
    const messages = freeze([{ role: "user", timestamp: 1, metadata: { untouched: true }, content: [
      { type: "image", mimeType: "image/png", data: bytes.toString("base64") },
      { type: "text", text: "preserve this message" }, image("new"),
    ] }]);
    const original = structuredClone(messages);
    const extension = extensionFixture(files, messages, {
      sessionFile: withSessionFile ? join(files.directory, "session.jsonl") : null,
    });
    const originalEntries = structuredClone(extension.entries);
    const filtered = extension.apply();
    const directory = join(files.directory, withSessionFile ? "session.jsonl.images" : "fixture-session.images");
    const path = reopenPath(filtered[0].content[0]);
    assert.equal(path, join(directory, "entry-0-0.png"));
    assert.deepEqual(readFileSync(path), bytes, "archive preserves the exact source image bytes");
    assert.deepEqual(filtered[0].content.slice(1), messages[0].content.slice(1));
    assert.deepEqual(messages, original, "context filtering does not change stored image data");
    assert.deepEqual(extension.entries, originalEntries, "session branch is read-only");

    const repeated = extension.apply();
    assert.equal(reopenPath(repeated[0].content[0]), path);
    assert.deepEqual(readdirSync(directory), ["entry-0-0.png"], "a later context pass reuses the archive file");
  });
}

test("extension archives the stored image when the original attachment has been deleted", t => {
  const files = fixture(t);
  const originalPath = files.path("deleted original");
  const bytes = Buffer.from("original session image bytes", "utf8");
  const messages = freeze([{ role: "user", timestamp: 1, content: [
    { type: "text", text: `- image: ${originalPath}` },
    { type: "image", mimeType: "image/jpeg", data: bytes.toString("base64") }, image("new"),
  ] }]);
  const extension = extensionFixture(files, messages);
  unlinkSync(originalPath);
  const path = reopenPath(extension.apply()[0].content[1]);
  assert.equal(path, join(files.directory, "session.jsonl.images", "entry-0-1.jpg"));
  assert.deepEqual(readFileSync(path), bytes);
});

test("extension reads the current getLimit value on each context event", t => {
  const files = fixture(t);
  let limit = 4;
  const messages = freeze([{ role: "user", timestamp: 1, content: [image("a"), image("b"), image("c"), image("d")] }]);
  const extension = extensionFixture(files, messages, { getLimit: () => limit });
  assert.deepEqual(retainedIds(extension.apply()), ["a", "b", "c", "d"]);
  limit = 3;
  assert.deepEqual(retainedIds(extension.apply()), ["c", "d"]);
  limit = 1;
  assert.deepEqual(retainedIds(extension.apply()), ["d"]);
});
