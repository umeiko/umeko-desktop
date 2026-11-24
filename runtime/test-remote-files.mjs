import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { createHash } from 'node:crypto';
import { createRemoteFiles, resolveRemotePath, remotePathUri, REMOTE_FILE_CHUNK_BYTES } from './remote-files.mjs';
import { remoteFileHelperCommand } from './remote-files-native.mjs';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
async function fixture(t, platform = 'linux') {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'umeko-remote-files-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const remote = path.join(root, 'remote'), local = path.join(root, 'local');
  await fs.mkdir(remote); await fs.mkdir(local);
  const handles = new Map(), readOffsets = [], writes = [];
  let expired = false, expireAt = null;
  const mapped = uri => path.join(remote, decodeURIComponent(new URL(uri).pathname).replace(/^\/[A-Za-z]:/, ''));
  const connection = {
    sessionId: 'original', sessionGeneration: 1, platform,
    async waitForReady(signal) { signal?.throwIfAborted(); return this.ready(); },
    async ready() { return platform === 'windows' ? { cwd: 'file:///C:/work', userHomeDir: 'file:///C:/Users/test', platformOs: platform } : { cwd: 'file:///work', userHomeDir: 'file:///home/test', platformOs: platform }; },
    async rpc(method, params) {
      const name = params.path ? mapped(params.path) : null;
      if (method === 'fs/createDirectory') { await fs.mkdir(name, { recursive: params.recursive }); return {}; }
      if (method === 'fs/writeFile') {
        const data = Buffer.from(params.dataBase64, 'base64'); writes.push({ path: name, bytes: data.length });
        await fs.writeFile(name, data); return {};
      }
      if (method === 'fs/getMetadata') {
        const stat = await fs.lstat(name);
        return { isFile: stat.isFile(), isDirectory: stat.isDirectory(), isSymlink: stat.isSymbolicLink(), size: stat.size };
      }
      if (method === 'fs/readDirectory') return { entries: (await fs.readdir(name, { withFileTypes: true })).map(row => ({ fileName: row.name, isFile: row.isFile(), isDirectory: row.isDirectory() })) };
      if (method === 'fs/open') { assert.equal(params.mode, 'read'); assert.match(params.handleId, /^[0-9a-f]{32}$/); handles.set(params.handleId, name); return { handleId: params.handleId }; }
      if (method === 'fs/readBlock') {
        readOffsets.push(params.offset);
        if (!expired && expireAt !== null && params.offset >= expireAt) {
          // Represents an outage beyond the fixed executor retention. Handles
          // from the old session no longer exist when the RPC is replayed.
          expired = true; connection.sessionId = 'replacement-after-80s'; connection.sessionGeneration++; handles.clear();
        }
        if (!handles.has(params.handleId)) throw new Error('Unknown file handle');
        const file = await fs.open(handles.get(params.handleId), 'r');
        try {
          const buffer = Buffer.alloc(params.len), { bytesRead } = await file.read(buffer, 0, buffer.length, params.offset);
          return { chunk: buffer.subarray(0, bytesRead).toString('base64'), eof: bytesRead < params.len };
        } finally { await file.close(); }
      }
      if (method === 'fs/close') { handles.delete(params.handleId); return {}; }
      throw new Error(`Unexpected RPC ${method}`);
    },
  };
  const native = async task => {
    const source = value => mapped(remotePathUri(value, platform));
    if (task.kind === 'hash') return hash(await fs.readFile(source(task.path)));
    const chunks = [];
    for (let i = 0; i < task.chunks; i++) chunks.push(await fs.readFile(path.join(source(task.directory), String(i).padStart(10, '0'))));
    const content = Buffer.concat(chunks), actual = hash(content);
    assert.equal(actual, task.sha256);
    await fs.writeFile(source(task.part), content);
    await fs.rename(source(task.part), source(task.target));
    for (let i = 0; i < task.chunks; i++) await fs.unlink(path.join(source(task.directory), String(i).padStart(10, '0')));
    await fs.rmdir(source(task.directory));
    return actual;
  };
  return { root, remote, local, connection, native, writes, readOffsets, expireAt(offset) { expireAt = offset; }, files: createRemoteFiles(connection, { runNative: native }) };
}

test('remote native paths resolve independently of the local Windows host', () => {
  const linux = { cwd: 'file:///work/a', userHomeDir: 'file:///home/user' };
  assert.equal(resolveRemotePath('../b/中文.txt', linux, 'linux'), '/work/b/中文.txt');
  assert.equal(resolveRemotePath('~/a', linux, 'linux'), '/home/user/a');
  const windows = { cwd: 'file:///C:/Users/A/work', userHomeDir: 'file:///C:/Users/A' };
  assert.equal(resolveRemotePath('..\\file.txt', windows, 'windows'), 'C:\\Users\\A\\file.txt');
  assert.equal(resolveRemotePath('D:\\data\\x', windows, 'windows'), 'D:\\data\\x');
  assert.equal(resolveRemotePath('file://server/share/a%20b', windows, 'windows'), '\\\\server\\share\\a b');
  assert.equal(remotePathUri('C:\\data\\a #%.txt', 'windows'), 'file:///C:/data/a%20%23%25.txt');
  assert.throws(() => resolveRemotePath('D:relative', windows, 'windows'), /Drive-relative/);
});

test('write, bounded read, recursive listing and literal search use filesystem RPC', async t => {
  const f = await fixture(t);
  const result = await f.files.execute({ action: 'write', path: 'notes/中文.txt', content: 'one\nNeedle here\nthree' });
  assert.equal(result.files, 1);
  const read = await f.files.execute({ action: 'read', path: 'notes/中文.txt', maxBytes: 4 });
  assert.deepEqual({ content: read.content, truncated: read.truncated, bytes: read.bytes }, { content: 'one\n', truncated: true, bytes: 4 });
  const listing = await f.files.execute({ action: 'list', path: '.', recursive: true });
  assert.deepEqual(listing.entries.map(row => row.path).sort(), ['/work/notes', '/work/notes/中文.txt']);
  const search = await f.files.execute({ action: 'search', path: '.', query: 'needle' });
  assert.deepEqual(search.matches, [{ path: '/work/notes/中文.txt', line: 2, text: 'Needle here' }]);
});

test('recursive chunked roundtrip resumes at confirmed byte offset after executor expiration', async t => {
  const f = await fixture(t);
  const source = path.join(f.local, 'input');
  await fs.mkdir(path.join(source, 'empty'), { recursive: true });
  const bytes = Buffer.alloc(REMOTE_FILE_CHUNK_BYTES * 3 + 71);
  for (let i = 0; i < bytes.length; i++) bytes[i] = i % 251;
  await fs.writeFile(path.join(source, 'large.bin'), bytes);
  await fs.writeFile(path.join(source, 'small.txt'), 'roundtrip');
  const upload = await f.files.execute({ action: 'upload', path: 'tree', localPath: 'input' }, { cwd: f.local });
  assert.equal(upload.files, 2); assert.equal(upload.directories, 2);
  assert(f.writes.every(row => row.bytes <= REMOTE_FILE_CHUNK_BYTES));
  f.expireAt(REMOTE_FILE_CHUNK_BYTES);
  const download = await f.files.execute({ action: 'download', path: 'tree', localPath: 'output' }, { cwd: f.local });
  assert.equal(download.bytes, bytes.length + 9);
  assert.deepEqual(await fs.readFile(path.join(f.local, 'output', 'large.bin')), bytes);
  assert.equal(await fs.readFile(path.join(f.local, 'output', 'small.txt'), 'utf8'), 'roundtrip');
  assert((await fs.stat(path.join(f.local, 'output', 'empty'))).isDirectory());
  assert.equal(f.connection.sessionId, 'replacement-after-80s');
  assert.equal(f.readOffsets.filter(offset => offset === REMOTE_FILE_CHUNK_BYTES).length, 2);
  assert.equal(download.cwd, f.local);
});

test('failed integrity check preserves existing local destination', async t => {
  const f = await fixture(t);
  await fs.mkdir(path.join(f.remote, 'work'));
  await fs.writeFile(path.join(f.remote, 'work', 'source'), 'remote data');
  const destination = path.join(f.local, 'destination');
  await fs.writeFile(destination, 'existing good data');
  const files = createRemoteFiles(f.connection, { runNative: async () => '0'.repeat(64) });
  await assert.rejects(files.execute({ action: 'download', path: 'source', localPath: 'destination' }, { cwd: f.local }), /SHA-256 mismatch/);
  assert.equal(await fs.readFile(destination, 'utf8'), 'existing good data');
  assert.deepEqual(await fs.readdir(f.local), ['destination']);
});

test('native helpers quote paths and assemble fixed numeric chunk filenames', () => {
  const task = { kind: 'assemble', directory: "/tmp/a'$(x)", part: '/tmp/staged.part', target: '/tmp/final', chunks: 3, sha256: 'a'.repeat(64) };
  const linux = remoteFileHelperCommand(task, 'linux');
  assert(linux.includes("'/tmp/a'\\''$(x)'"));
  assert(linux.includes('mv -fT --'));
  const windows = remoteFileHelperCommand({ ...task, directory: "C:\\a'b", part: 'C:\\part', target: 'C:\\final' }, 'windows');
  assert(windows.includes("'C:\\a''b'"));
  assert(windows.includes('[IO.File]::Replace'));
});

test('recovery: disconnect-mid-upload opts into exact uncertain-chunk replay', async t => {
  const f = await fixture(t);
  const content = Buffer.alloc(REMOTE_FILE_CHUNK_BYTES * 2 + 19, 173);
  await fs.writeFile(path.join(f.local, 'upload.bin'), content);
  const original = f.connection.rpc.bind(f.connection);
  let disconnected = false, replayed;
  f.connection.rpc = async (method, params, options) => {
    if (method === 'fs/createDirectory') assert.equal(options.retry, true);
    if (method === 'fs/writeFile' && !disconnected && params.path.endsWith('/0000000001')) {
      // The remote write commits, then its reply is lost. Model the transport's
      // opt-in admission and replay in a replacement executor session.
      await original(method, params, options);
      disconnected = true;
      if (options.retry !== true) throw Object.assign(new Error('Write response lost'), { transport: true });
      replayed = JSON.stringify(params);
      f.connection.sessionId = 'replacement-during-upload';
      const result = await original(method, JSON.parse(replayed), options);
      assert.equal(JSON.stringify(params), replayed);
      return result;
    }
    return original(method, params, options);
  };
  const result = await f.files.execute({ action: 'upload', localPath: 'upload.bin', path: 'received.bin' }, { cwd: f.local });
  assert.equal(disconnected, true);
  assert.equal(result.bytes, content.length);
  assert.deepEqual(await fs.readFile(path.join(f.remote, 'work', 'received.bin')), content);
  const chunkNames = f.writes.map(row => path.basename(row.path));
  assert.deepEqual(chunkNames, ['0000000000', '0000000001', '0000000001', '0000000002']);
});

test('recovery: read open lost reply and typed session expiration reopen safely', async t => {
  const f = await fixture(t);
  await fs.mkdir(path.join(f.remote, 'work'));
  await fs.writeFile(path.join(f.remote, 'work', 'source'), 'recovered read');
  const original = f.connection.rpc.bind(f.connection);
  let openLost = false, readLost = false, opens = 0;
  f.connection.rpc = async (method, params, options) => {
    if (method === 'fs/open') {
      opens++;
      const result = await original(method, params, options);
      if (!openLost) { openLost = true; throw Object.assign(new Error('Open response lost'), { transport: true }); }
      return result;
    }
    if (method === 'fs/readBlock' && !readLost) {
      readLost = true;
      throw Object.assign(new Error('Executor changed'), { code: 'REMOTE_SESSION_CHANGED' });
    }
    return original(method, params, options);
  };
  const result = await f.files.execute({ action: 'read', path: 'source' });
  assert.equal(result.content, 'recovered read');
  assert.equal(opens, 3);
});

test('Windows transfer resumes immutable upload chunks and confirmed download offsets across outages', async t => {
  const f = await fixture(t, 'windows');
  const content = Buffer.alloc(REMOTE_FILE_CHUNK_BYTES * 3 + 17, 91);
  await fs.writeFile(path.join(f.local, 'source.bin'), content);
  const original = f.connection.rpc.bind(f.connection);
  let uploadLost = false;
  const expiredOffsets = new Set();
  f.connection.rpc = async (method, params, options) => {
    if (method === 'fs/writeFile' && !uploadLost && params.path.endsWith('/0000000001')) {
      await original(method, params, options);
      uploadLost = true;
      assert.equal(options.retry, true);
      f.connection.sessionGeneration++;
      f.connection.sessionId = 'upload-replacement';
      return original(method, structuredClone(params), options);
    }
    if (method === 'fs/readBlock') {
      assert.equal(options.sessionGeneration, f.connection.sessionGeneration);
      if (params.offset && !expiredOffsets.has(params.offset)) {
        expiredOffsets.add(params.offset);
        f.readOffsets.push(params.offset);
        f.connection.sessionGeneration++;
        f.connection.sessionId = `download-replacement-${params.offset}`;
        throw Object.assign(new Error('Executor replaced while awaiting block'), { code: 'REMOTE_SESSION_CHANGED' });
      }
    }
    if (method === 'fs/close') assert.equal(options.wait, false);
    return original(method, params, options);
  };
  await f.files.execute({ action: 'upload', path: 'folder with spaces/中文.bin', localPath: 'source.bin' }, { cwd: f.local });
  assert.deepEqual(f.writes.map(row => path.basename(row.path)), ['0000000000', '0000000001', '0000000001', '0000000002', '0000000003']);
  const download = await f.files.execute({ action: 'download', path: 'folder with spaces/中文.bin', localPath: 'result.bin' }, { cwd: f.local });
  assert.deepEqual(await fs.readFile(path.join(f.local, 'result.bin')), content);
  assert.equal(download.bytes, content.length);
  assert.equal(f.readOffsets.filter(offset => offset === 0).length, 1);
  for (const offset of expiredOffsets) assert.equal(f.readOffsets.filter(value => value === offset).length, 2);
});

test('reconnect timeout stops this read without reopening or waiting during cleanup', async t => {
  const f = await fixture(t);
  await fs.mkdir(path.join(f.remote, 'work'));
  await fs.writeFile(path.join(f.remote, 'work', 'source'), 'data');
  const original = f.connection.rpc.bind(f.connection);
  let opens = 0, readyCalls = 0, closes = 0;
  f.connection.waitForReady = async () => { readyCalls++; return f.connection.ready(); };
  f.connection.rpc = async (method, params, options) => {
    if (method === 'fs/open') opens++;
    if (method === 'fs/readBlock') throw Object.assign(new Error('Relay still reconnecting'), { code: 'REMOTE_RECONNECT_TIMEOUT', transport: true });
    if (method === 'fs/close') { closes++; assert.equal(options.wait, false); }
    return original(method, params, options);
  };
  await assert.rejects(f.files.execute({ action: 'read', path: 'source' }), { code: 'REMOTE_RECONNECT_TIMEOUT' });
  assert.equal(opens, 1);
  assert.equal(readyCalls, 1);
  assert.equal(closes, 1);
});
