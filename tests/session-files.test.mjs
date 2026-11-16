import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { createHash } from 'node:crypto';
import { importSession, deleteSession, execute } from '../runtime/session-files.mjs';

const stamp = '2026-11-12T12:00:00Z';
const header = { type: 'session', version: 3, id: 'source-id', timestamp: stamp, cwd: '/original/project' };
const entry = (id = 'a', parentId = null) => ({ type: 'message', id, parentId, timestamp: stamp,
  message: { role: 'user', content: 'Private conversation', timestamp: 1 } });
const encode = rows => rows.map(row => JSON.stringify(row)).join('\n') + '\n';
async function fixture(t) {
  const root = await fs.mkdtemp(join(tmpdir(), 'umeko-session-files-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const profile = join(root, 'profile'), sessionDir = join(profile, 'pi/sessions'), cwd = join(root, 'project');
  await fs.mkdir(sessionDir, { recursive: true }); await fs.mkdir(cwd);
  const source = join(root, 'backup.jsonl'); await fs.writeFile(source, encode([header, entry()]));
  return { root, profile, sessionDir, cwd, source };
}

test('import copies history into the requested project, preserves source and prevents ID collisions', async t => {
  const f = await fixture(t), original = await fs.readFile(f.source, 'utf8');
  const a = await importSession(f), b = await importSession(f);
  assert.notEqual(a.id, b.id); assert.notEqual(a.file, b.file);
  assert.equal(await fs.readFile(f.source, 'utf8'), original);
  for (const value of [a, b]) {
    const rows = (await fs.readFile(value.file, 'utf8')).trim().split('\n').map(JSON.parse);
    assert.equal(rows[0].id, value.id); assert.equal(rows[0].cwd, f.cwd);
    assert.equal(rows[1].message.content, entry().message.content);
    assert.equal(rows[1].id, 'a'); assert.equal(rows[1].parentId, null);
  }
});

test('import retains complete branches and self-referencing retain-none compaction', async t => {
  const f = await fixture(t);
  await fs.writeFile(f.source, encode([header, entry('a'), entry('b', 'a'), entry('c', 'a'),
    { type: 'compaction', id: 'd', parentId: 'c', timestamp: stamp, firstKeptEntryId: 'd', summary: 'Compacted', tokensBefore: 20 }]));
  const result = await importSession(f);
  const rows = (await fs.readFile(result.file, 'utf8')).trim().split('\n').map(JSON.parse);
  assert.equal(rows.length, 5); assert.equal(rows[3].parentId, 'a'); assert.equal(rows[4].firstKeptEntryId, 'd');
});

for (const [name, data] of [
  ['truncated last line', encode([header, entry()]) + '{"type":"message"'],
  ['non-session JSONL', encode([{ role: 'user', content: 'unwrapped data' }])],
  ['missing parent', encode([header, entry('a', 'missing')])],
  ['cycle', encode([header, entry('a', 'a')])],
  ['duplicate entry ID', encode([header, entry(), entry()])],
  ['missing compaction reference', encode([header, entry(), { type: 'compaction', id: 'b', parentId: 'a', timestamp: stamp, summary: 'x', firstKeptEntryId: 'gone' }])],
  ['unknown version', encode([{ ...header, version: 99 }, entry()])],
  ['invalid message shape', encode([header, { ...entry(), message: { role: 'assistant', content: 42 } }])],
  ['empty', ''],
  ['header only', encode([header])],
  ['invalid UTF-8', Buffer.concat([Buffer.from(encode([header, entry()])), Buffer.from([0xff])])],
]) test('invalid import publishes no session: ' + name, async t => {
  const f = await fixture(t); await fs.writeFile(f.source, data);
  await assert.rejects(importSession(f));
  assert.deepEqual(await fs.readdir(f.sessionDir), []);
  assert.deepEqual(await fs.readFile(f.source), Buffer.from(data));
});

test('legacy v1 imports migrate IDs without discarding history', async t => {
  const f = await fixture(t);
  const a = entry(), b = entry(); delete a.id; delete a.parentId; delete b.id; delete b.parentId;
  await fs.writeFile(f.source, encode([{ ...header, version: 1 }, a, b]));
  const result = await importSession(f), rows = (await fs.readFile(result.file, 'utf8')).trim().split('\n').map(JSON.parse);
  assert.equal(rows[0].version, 3); assert.equal(rows[1].parentId, null); assert.equal(rows[2].parentId, rows[1].id);
});

test('batch imports report bad files individually and leave no partial artifacts', async t => {
  const f = await fixture(t), bad = join(f.root, 'bad.jsonl'); await fs.writeFile(bad, '{');
  const result = await execute({ ...f, operation: 'import', sources: [f.source, bad] });
  assert.equal(result.sessions.length, 1); assert.equal(result.errors.length, 1); assert.equal(result.errors[0].name, 'bad.jsonl');
  assert.equal((await fs.readdir(f.sessionDir)).length, 1);
});

test('delete removes private sidecars, nested child sessions and derived indexes, preserves project files', async t => {
  const f = await fixture(t), session = await importSession(f), file = session.file;
  await fs.mkdir(file + '.images'); await fs.writeFile(join(file + '.images', 'private.png'), 'private');
  const childDir = join(file.slice(0, -6), 'tasks'); await fs.mkdir(childDir, { recursive: true });
  const child = join(childDir, 'child.jsonl'); await fs.writeFile(child, encode([header, entry()]));
  const index = join(f.profile, 'cache/chat-index'); await fs.mkdir(index, { recursive: true });
  for (const path of [file, child]) for (const suffix of ['.sqlite', '.sqlite-wal', '.sqlite-shm'])
    await fs.writeFile(join(index, createHash('sha256').update(path).digest('hex') + suffix), 'private');
  const h = value => createHash('sha256').update(value).digest('hex').slice(0, 32);
  const cache = join(f.profile, 'cache/conversation-search-v1', h(f.cwd)); await fs.mkdir(cache, { recursive: true });
  const key = h(session.id + '\0' + file); for (const suffix of ['.txt', '.json']) await fs.writeFile(join(cache, key + suffix), 'private');
  const projectFile = join(f.cwd, 'keep.txt'); await fs.writeFile(projectFile, 'source file');
  await deleteSession({ profile: f.profile, session });
  for (const path of [file, childDir, file + '.images']) await assert.rejects(fs.stat(path), { code: 'ENOENT' });
  assert.deepEqual(await fs.readdir(index), []); assert.deepEqual(await fs.readdir(cache), []);
  assert.equal(await fs.readFile(projectFile, 'utf8'), 'source file');
  assert.ok(await fs.stat(f.source));
});

test('project deletion discovers owned sessions missing from the UI index and preserves other projects', async t => {
  const f = await fixture(t), session = await importSession(f);
  const hidden = join(f.sessionDir, 'unindexed.jsonl'); await fs.writeFile(hidden, encode([{ ...header, cwd: f.cwd, id: 'unindexed' }, entry()]));
  const other = join(f.sessionDir, 'other.jsonl'); await fs.writeFile(other, encode([header, entry()]));
  const result = await execute({ operation: 'delete', profile: f.profile, workspace: f.cwd, sessions: [session] });
  assert.deepEqual(result.errors, []); assert.deepEqual(new Set(result.deleted.map(s => s.id)), new Set([session.id, 'unindexed']));
  assert.ok(await fs.stat(other)); await assert.rejects(fs.stat(hidden));
});

test('deleting a missing transcript remains retryable and rejects external and prefix-alias paths', async t => {
  const f = await fixture(t);
  await deleteSession({ profile: f.profile, session: { id: 'missing', file: join(f.sessionDir, 'missing.jsonl') } });
  for (const file of [f.source, join(f.profile, 'pi/sessions-other/source.jsonl')])
    await assert.rejects(deleteSession({ profile: f.profile, session: { id: 'external', file } }));
  assert.ok(await fs.stat(f.source));
});

test('sidecar links are removed without following their targets; linked parent directories are rejected', async t => {
  const f = await fixture(t), session = await importSession(f);
  const outside = join(f.root, 'external'); await fs.mkdir(outside); await fs.writeFile(join(outside, 'keep'), 'keep');
  try { await fs.symlink(outside, session.file + '.images', 'dir'); }
  catch (error) { if (['EPERM', 'EACCES'].includes(error.code)) { t.skip('Symlink privilege unavailable'); return; } throw error; }
  await deleteSession({ profile: f.profile, session }); assert.equal(await fs.readFile(join(outside, 'keep'), 'utf8'), 'keep');
  const alias = join(f.sessionDir, 'alias'); await fs.symlink(outside, alias, 'dir');
  await assert.rejects(deleteSession({ profile: f.profile, session: { id: 'alias', file: join(alias, 'keep.jsonl') } }));
});

test('linked cache directories cannot redirect erasure outside the profile', async t => {
  const f = await fixture(t), session = await importSession(f);
  const outside = join(f.root, 'outside'); await fs.mkdir(outside);
  try { await fs.symlink(outside, join(f.profile, 'cache'), 'dir'); }
  catch (error) { if (['EPERM', 'EACCES'].includes(error.code)) { t.skip('Symlink privilege unavailable'); return; } throw error; }
  await assert.rejects(deleteSession({ profile: f.profile, session }));
  assert.ok(await fs.stat(session.file));
});


test('duplicate native IDs never discard the failed catalog entry', async t => {
  const f = await fixture(t), good = await importSession(f);
  const external = { ...good, file: f.source };
  const result = await execute({ ...f, operation: 'delete', sessions: [external, good] });
  assert.equal(result.deleted.length, 0); assert.equal(result.errors.length, 1);
  assert.equal(result.errors[0].id, good.id); assert.equal(await fs.readFile(f.source, 'utf8'), encode([header, entry()]));
});

test('DSH deletion drains the owned transcript and isolated home without needing a catalog file path', async t => {
  const f = await fixture(t), home = join(f.profile, 'dsh/profiles/dsh-a');
  const file = join(f.profile, 'dsh/transcripts/dsh-a.json');
  await fs.mkdir(home, { recursive: true }); await fs.mkdir(join(f.profile, 'dsh/transcripts'));
  await fs.writeFile(join(home, 'private.json'), '{}'); await fs.writeFile(file, '{}');
  await deleteSession({ ...f, session: { id: 'dsh-a', backend: 'dsh', dshHome: home } });
  await assert.rejects(fs.stat(file)); await assert.rejects(fs.stat(home));
});

test('context edits must contain valid replacement content', async t => {
  const f = await fixture(t);
  await fs.writeFile(f.source, encode([header, entry(), { type: 'context_edit', id: 'edit', parentId: 'a', targetId: 'a', timestamp: stamp, replacement: { content: 42 } }]));
  await assert.rejects(importSession(f), /上下文编辑/); assert.deepEqual(await fs.readdir(f.sessionDir), []);
});


test('delete also purges migrated plaintext history backups and preserves other chats', async t => {
  const f = await fixture(t), session = await importSession(f), legacy = join(f.profile, 'sessions-legacy.json');
  await fs.writeFile(legacy, JSON.stringify([{ id: session.id, history: ['private'] }, { id: 'keep', history: ['kept'] }]));
  const result = await execute({ ...f, operation: 'delete', sessions: [session] });
  assert.equal(result.deleted.length, 1); assert.deepEqual(JSON.parse(await fs.readFile(legacy, 'utf8')), [{ id: 'keep', history: ['kept'] }]);
});
