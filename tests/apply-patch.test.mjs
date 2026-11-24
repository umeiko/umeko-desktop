// The scenario fixtures and sequence cases are adapted from openai/codex,
// rust-v0.172.0, codex-rs/apply-patch. See ../licenses/codex-apply-patch-APACHE.txt.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {applyPatch, createApplyPatchExtension, parsePatch, resolvePatchPaths, seekSequence} from '../runtime/apply-patch.mjs';
import {createToolPermissionExtension} from '../runtime/tool-permissions.mjs';

const fixtures = JSON.parse(fs.readFileSync(new URL('./fixtures/codex-apply-patch.json', import.meta.url)));
const wrap = body => `*** Begin Patch\n${body}\n*** End Patch`;

function readTree(directory, prefix = '') {
  const entries = {};
  for (const item of fs.readdirSync(directory, {withFileTypes: true})) {
    const file = path.join(directory, item.name);
    const relative = prefix + item.name;
    if (item.isDirectory()) Object.assign(entries, readTree(file, relative + '/'));
    else entries[relative] = fs.readFileSync(file, 'utf8');
  }
  return entries;
}

function workspace(t, input = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'umeko-apply-patch-'));
  t.after(() => fs.rmSync(directory, {recursive: true, force: true}));
  for (const [name, content] of Object.entries(input)) {
    const file = path.join(directory, name);
    fs.mkdirSync(path.dirname(file), {recursive: true});
    fs.writeFileSync(file, content);
  }
  return directory;
}

function apply(directory, text) {
  const hunks = parsePatch(text);
  return applyPatch(hunks, resolvePatchPaths(hunks, directory));
}

const errors = {
  '005_rejects_empty_patch': /patch is empty/i,
  '006_rejects_missing_context': /Failed to find expected lines/,
  '007_rejects_missing_file_delete': /File to delete does not exist/,
  '008_rejects_empty_update_hunk': /Update for .* is empty/,
  '009_requires_existing_file_for_update': /File to update does not exist/,
  '012_delete_directory_fails': /Expected a regular file/,
  '013_rejects_invalid_hunk_header': /Add File: path/,
  '015_failure_after_partial_success_leaves_changes': /File to update does not exist/,
};

for (const [name, fixture] of Object.entries(fixtures)) {
  test(`Codex scenario ${name}`, t => {
    const directory = workspace(t, fixture.input);
    // Umeko rolls back the complete patch in scenario 015.
    if (errors[name]) assert.throws(() => apply(directory, fixture.patch), errors[name]);
    else assert.deepEqual(apply(directory, fixture.patch).warnings, []);
    assert.deepEqual(readTree(directory), fixture.expected);
  });
}

test('matches exact, then trailing whitespace, then both ends before normalizing punctuation', () => {
  assert.equal(seekSequence(['foo', 'bar', 'baz'], ['bar', 'baz']), 1);
  assert.equal(seekSequence(['foo   ', 'bar\t\t'], ['foo', 'bar']), 0);
  assert.equal(seekSequence(['    foo   ', '   bar\t'], ['foo', 'bar']), 0);
  assert.equal(seekSequence(['one'], ['too', 'many', 'lines']), -1);
  assert.equal(seekSequence(['   same', 'same  ', 'same'], ['same']), 2);
  assert.equal(seekSequence(['   same', 'same  '], ['same']), 1);
  assert.equal(seekSequence(['one–two'], ['one-two']), 0);
});

test('locates a repeated snippet via @@ and retains CRLF and untouched whitespace', t => {
  const directory = workspace(t, {'repeat.txt': 'first\r\n    same  \r\nsecond\r\n    same  \r\nend\t\r\n'});
  const result = apply(directory, wrap('*** Update File: repeat.txt\n@@ second\n-same\n+    replaced\n end'));
  assert.deepEqual(result.files, [{kind: 'modified', path: 'repeat.txt'}]);
  assert.equal(fs.readFileSync(path.join(directory, 'repeat.txt'), 'utf8'), 'first\r\n    same  \r\nsecond\r\n    replaced\r\nend\t\r\n');
});

test('accepts an absolute path, a CRLF heredoc and a first chunk without @@', t => {
  const directory = workspace(t, {'example.txt': 'import foo\r\n'});
  const patch = wrap(`*** Update File: ${path.join(directory, 'example.txt')}\n import foo\n+bar`);
  apply(directory, `<<'EOF'\n${patch}\nEOF\n`.replaceAll('\n', '\r\n'));
  assert.deepEqual(readTree(directory), {'example.txt': 'import foo\r\nbar\r\n'});
});

test('a malformed hunk and a filesystem staging error each leave every target untouched', t => {
  const directory = workspace(t, {'first.txt': 'one\n', 'regular.txt': 'file\n'});
  const prefix = '*** Update File: first.txt\n@@\n-one\n+two\n';
  assert.throws(() => apply(directory, wrap(prefix + '*** Update File: regular.txt\n@@\nunprefixed')), /line 8.*Prefix each change line/);
  assert.throws(() => apply(directory, wrap(prefix + '*** Add File: new/directory.txt\n+one\n*** Add File: new/directory.txt/child\n+two')), /directory/);
  assert.deepEqual(readTree(directory), {'first.txt': 'one\n', 'regular.txt': 'file\n'});
  assert.equal(fs.existsSync(path.join(directory, 'new')), false);
});

test('rolls back an earlier replacement when installing a later file fails', t => {
  const directory = workspace(t, {'first.txt': 'one\n', 'second.txt': 'two\n'});
  const second = fs.realpathSync.native(path.join(directory, 'second.txt'));
  const rename = fs.renameSync;
  t.mock.method(fs, 'renameSync', (source, destination) => {
    if (path.basename(source) === 'next' && destination === second) throw new Error('fixture write failure');
    return rename(source, destination);
  });
  const first = '*** Update File: first.txt\n@@\n-one\n+first';
  const next = '*** Update File: second.txt\n@@\n-two\n+second';
  assert.throws(() => apply(directory, wrap(`${first}\n${next}`)), /fixture write failure/);
  assert.deepEqual(readTree(directory), {'first.txt': 'one\n', 'second.txt': 'two\n'});
});

test('permission gate covers every patch path and a denied move blocks the whole call', async t => {
  const cwd = workspace(t, {'old.txt': 'one\n'});
  const protectedPath = process.platform === 'win32' ? path.join(process.env.SystemRoot, 'umeko-patch-test.txt') : '/etc/umeko-patch-test.txt';
  const input = {patch: wrap(`*** Add File: first.txt\n+first\n*** Update File: old.txt\n*** Move to: ${protectedPath}\n@@\n-one\n+two`)};
  const event = {toolName: 'apply_patch', input};
  let gate, tool, details;
  createToolPermissionExtension({getPolicy: () => ({mode: 'auto'})})({on: (_name, handler) => { gate = handler; }});
  createApplyPatchExtension(() => true)({on() {}, registerTool: definition => { tool = definition; }});
  const ctx = {cwd, hasUI: true, ui: {confirm() {}, confirmDangerous(_title, body, category) {
    details = {body, category};
    return false;
  }}};
  assert.match((await gate(event, ctx)).reason, /User denied execution.*system directory/);
  assert.equal(details.category, 7);
  for (const name of ['first.txt', 'old.txt', protectedPath]) assert.ok(details.body.includes(name));
  await assert.rejects(tool.execute('call', input, undefined, undefined, ctx), /write-permission check/);
  assert.deepEqual(readTree(cwd), {'old.txt': 'one\n'});
});

test('a permitted patch returns structured file changes', async t => {
  const cwd = workspace(t);
  const input = {patch: wrap('*** Add File: new.txt\n+one')};
  let gate, tool;
  createToolPermissionExtension({getPolicy: () => ({mode: 'auto'})})({on: (_name, handler) => { gate = handler; }});
  createApplyPatchExtension(model => model?.id === 'enabled')({on() {}, registerTool: definition => { tool = definition; }});
  const ctx = {cwd, model: {id: 'enabled'}};
  assert.equal(await gate({toolName: 'apply_patch', input}, ctx), undefined);
  const result = await tool.execute('call', input, undefined, undefined, ctx);
  assert.deepEqual(result.details.patchFiles, [{path: 'new.txt', kind: 'added'}]);
  assert.deepEqual(readTree(cwd), {'new.txt': 'one\n'});
});
