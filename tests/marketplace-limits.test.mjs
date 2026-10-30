import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { createRequire } from 'node:module';
import { gzipSync } from 'node:zlib';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { rootCertificates } from 'node:tls';
import {
  ARCHIVE_LIMITS, CACHE_LIMITS, createBoundedCache, createRegistryClient,
} from '../runtime/marketplace-source.mjs';

const require = createRequire(new URL('../runtime/package.json', import.meta.url));
const { Header } = require('tar');

// Build tiny in-memory fixtures without spawning tar or touching a package source.
function archive(entries) {
  const chunks = [];
  for (const { path, content = '', type = 'File' } of entries) {
    const data = Buffer.from(content);
    const header = new Header({ path, size: data.length, mode: 0o644, type, mtime: new Date(0) });
    header.encode();
    chunks.push(header.block, data, Buffer.alloc((512 - data.length % 512) % 512));
  }
  return gzipSync(Buffer.concat([...chunks, Buffer.alloc(1024)]));
}

function metadataRecord(key, value) {
  const suffix = ` ${key}=${value}\n`;
  let length = suffix.length + 1;
  while (String(length).length + suffix.length !== length) length = String(length).length + suffix.length;
  return `${length}${suffix}`;
}

function noise(size) {
  let state = 123456789;
  return Buffer.from(Array.from({ length: size }, () => {
    state ^= state << 13; state ^= state >>> 17; state ^= state << 5;
    return state & 255;
  }));
}

async function registry(t, { tarball, onTarball, onDocument, cacheOptions, limits, agent = {} } = {}) {
  const counts = { docs: new Map(), tarballs: 0 };
  let origin;
  const server = createServer((req, res) => {
    if (req.url === '/source.tgz') {
      counts.tarballs++;
      if (onTarball) return onTarball(req, res, counts.tarballs);
      res.end(tarball);
      return;
    }
    const name = decodeURIComponent(req.url.slice(1));
    counts.docs.set(name, (counts.docs.get(name) || 0) + 1);
    if (onDocument?.(req, res, name, counts.docs.get(name))) return;
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({
      'dist-tags': { latest: '1.0.0' },
      versions: { '1.0.0': {
        name, version: '1.0.0', keywords: ['pi-package'], pi: { extensions: ['index.js'] },
        dist: { tarball: `${origin}/source.tgz` },
      } },
    }));
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  origin = `http://127.0.0.1:${server.address().port}`;
  const client = createRegistryClient({
    agent: { npmRegistry: origin, ...agent }, fetch: globalThis.fetch, cacheOptions, limits,
  });
  t.after(async () => { await client.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  return { client, counts };
}

function assertBounded(stats, maxEntries, maxBytes) {
  for (const value of Object.values(stats)) {
    assert.ok(value.entries <= maxEntries, JSON.stringify(stats));
    assert.ok(value.bytes <= maxBytes, JSON.stringify(stats));
  }
}

test('published archive and cache budgets are explicit', () => {
  assert.deepEqual(ARCHIVE_LIMITS, { compressedBytes: 32 * 1024 * 1024, entries: 20000, expandedBytes: 128 * 1024 * 1024 });
  assert.deepEqual(CACHE_LIMITS, { maxEntries: 64, maxBytes: 8 * 1024 * 1024, ttlMs: 300000 });
});

test('small compressed sources cannot amplify into unbounded audit findings', async t => {
  const {client}=await registry(t,{tarball:archive([{path:'package/index.js',content:'process.env.X;\n'.repeat(30000)}])});
  const report=await client.fullAudit('fixture',true,'1.0.0');
  assert.equal(report.deepScanned,false);
  assert.match(report.scanError,/finding count limit exceeded: 500/);
  assert.equal(report.findings.length,500);
  assert.ok(Buffer.byteLength(JSON.stringify(report))<256*1024);
  assert.match(report.summary,/scan incomplete/);
  assert.equal(report.overallRisk,'medium');
});

test('finding byte and per-file budgets preserve explicit incomplete results', async t => {
  const body=archive([{path:'package/index.js',content:'process.env.X;\n'.repeat(100)}]);
  for(const [limits,pattern] of [[{findingBytes:128},/finding bytes limit exceeded: 128/],
                               [{sourceFileBytes:128},/file bytes limit exceeded: 128/]]){
    const {client}=await registry(t,{tarball:body,limits});
    const report=await client.fullAudit('fixture',true,'1.0.0');
    assert.equal(report.deepScanned,false);
    assert.match(report.scanError,pattern);
    assert.ok(Buffer.byteLength(JSON.stringify(report))<4096);
  }
});

test('registry JSON budget rejects oversized documents and permits a later retry', async t => {
  let requests=0;
  const {client}=await registry(t,{limits:{metadataBytes:1024},onDocument(_req,res){
    if(requests++===0){res.end(JSON.stringify({oversized:'x'.repeat(2048)}));return true;}
  }});
  await assert.rejects(client.getPackageDetail('fixture'),/Registry JSON response limit exceeded: 1024 bytes/);
  assert.equal((await client.getPackageDetail('fixture')).version,'1.0.0');
});

test('bounded cache enforces LRU count, settled byte size, TTL, deletion and clear', () => {
  let now = 0;
  const cache = createBoundedCache({ maxEntries: 2, maxBytes: 400, ttlMs: 10, now: () => now });
  cache.set('a', 1); cache.set('b', 2);
  assert.equal(cache.get('a'), 1);
  cache.set('c', 3);
  assert.equal(cache.get('b'), undefined);
  assert.equal(cache.stats().entries, 2);
  cache.set('oversized', 'x'.repeat(500));
  assert.deepEqual(cache.stats(), { entries: 0, bytes: 0 });
  cache.set('expired', 1); now = 10;
  assert.equal(cache.get('expired'), undefined);
  assert.deepEqual(cache.stats(), { entries: 0, bytes: 0 });
  cache.set('remove', 1); cache.delete('remove');
  cache.set('clear', 1); cache.clear();
  assert.deepEqual(cache.stats(), { entries: 0, bytes: 0 });
});

test('bounded cache deduplicates pending loads, drops rejection and accounts resolved bytes', async () => {
  const cache = createBoundedCache({ maxEntries: 1, maxBytes: 100 });
  let calls = 0;
  const first = cache.getOrCreate('retry', async () => { calls++; throw new Error('offline'); });
  assert.equal(cache.getOrCreate('retry', () => { throw new Error('must be deduplicated'); }), first);
  assert.equal(cache.stats().entries, 1);
  await assert.rejects(first, /offline/);
  assert.deepEqual(cache.stats(), { entries: 0, bytes: 0 });
  assert.equal(await cache.getOrCreate('retry', () => { calls++; return 7; }), 7);
  assert.equal(calls, 2);
  await cache.getOrCreate('large', () => 'x'.repeat(200));
  assert.deepEqual(cache.stats(), { entries: 0, bytes: 0 });
});

test('compressed limit terminates an HTTP stream before downloading the whole archive', async t => {
  const body = archive([{ path: 'package/index.js', content: noise(16384) }]);
  let sent = 0, closed;
  const disconnected = new Promise(resolve => { closed = resolve; });
  const { client } = await registry(t, {
    limits: { compressedBytes: 128 },
    onTarball(_req, res) {
      const timer = setInterval(() => {
        const end = Math.min(sent + 64, body.length);
        res.write(body.subarray(sent, end)); sent = end;
        if (sent === body.length) { clearInterval(timer); res.end(); }
      }, 2);
      res.on('close', () => { clearInterval(timer); closed(); });
    },
  });
  const report = await client.fullAudit('fixture', true, '1.0.0');
  await disconnected;
  assert.equal(report.deepScanned, false);
  assert.match(report.scanError, /compressed download limit exceeded: 128 bytes/);
  assert.ok(sent < body.length, `downloaded ${sent} of ${body.length} bytes`);
});

test('entry cap counts source files and physical PAX metadata headers', async t => {
  const fixtures = [
    { entries: [0, 1, 2].map(i => ({ path: `package/${i}.js`, content: '' })), limit: 2 },
    { entries: [
      { path: 'PaxHeader', type: 'ExtendedHeader', content: metadataRecord('comment', 'metadata-only') },
      { path: 'package/index.js', content: 'export const value = 1;' },
    ], limit: 1 },
  ];
  for (const fixture of fixtures) {
    const { client } = await registry(t, { tarball: archive(fixture.entries), limits: { entries: fixture.limit } });
    const report = await client.fullAudit('fixture', true, '1.0.0');
    assert.equal(report.deepScanned, false);
    assert.match(report.scanError, new RegExp(`entry count limit exceeded: ${fixture.limit} entries`));
  }
});

test('expanded limit includes decoded tar data even when gzip is very small', async t => {
  const body = archive([{ path: 'package/index.js', content: ' '.repeat(8192) }]);
  assert.ok(body.length < 2048);
  const { client } = await registry(t, { tarball: body, limits: { expandedBytes: 2048 } });
  const report = await client.fullAudit('fixture', true, '1.0.0');
  assert.equal(report.deepScanned, false);
  assert.match(report.scanError, /expanded archive limit exceeded: 2048 bytes/);
});

test('caller cancellation stops a live download and rejects as AbortError', async t => {
  const controller = new AbortController();
  const body = archive([{ path: 'package/index.js', content: noise(16384) }]);
  let sent = 0, closed;
  const disconnected = new Promise(resolve => { closed = resolve; });
  const { client } = await registry(t, { onTarball(_req, res) {
    const timer = setInterval(() => {
      res.write(body.subarray(sent, sent + 64)); sent += 64;
      if (sent >= 128) controller.abort();
    }, 2);
    res.on('close', () => { clearInterval(timer); closed(); });
  } });
  await assert.rejects(client.fullAudit('fixture', true, '1.0.0', { signal: controller.signal }), { name: 'AbortError' });
  await disconnected;
  assert.ok(sent < body.length);
});

test('caller cancellation interrupts a running regex scan at its cooperative yield', async t => {
  const controller = new AbortController();
  const marker = '// bounded-scan-cancellation-fixture\n';
  const body = archive([{ path: 'package/index.js', content: marker + 'rm -rf example\n'.repeat(10000) }]);
  const { client, counts } = await registry(t, { tarball: body });
  const originalExec = RegExp.prototype.exec;
  let matches = 0;
  RegExp.prototype.exec = function (value) {
    const result = originalExec.call(this, value);
    if (typeof value === 'string' && value.startsWith(marker) && this.source.startsWith('\\brm\\s+') && result) {
      matches++;
      if (matches === 256) setImmediate(() => controller.abort());
    }
    return result;
  };
  try {
    await assert.rejects(client.fullAudit('fixture', true, '1.0.0', { signal: controller.signal }), { name: 'AbortError' });
    assert.equal(counts.tarballs, 1);
    assert.equal(matches, 256, 'abort timer must run before the remaining matches are scanned');
  } finally { RegExp.prototype.exec = originalExec; }
});

test('a failed source download is visible and the same audit retries successfully', async t => {
  const body = archive([{ path: 'package/index.js', content: 'export const okay = 1;' }]);
  const { client, counts } = await registry(t, { onTarball(_req, res, attempt) {
    if (attempt === 1) { res.writeHead(503); res.end('try later'); } else res.end(body);
  } });
  const failed = await client.fullAudit('fixture', true, '1.0.0');
  assert.match(failed.scanError, /HTTP 503/);
  assert.equal(failed.deepScanned, false);
  assert.equal(client.cacheStats().audits.entries, 0);
  const recovered = await client.fullAudit('fixture', true, '1.0.0');
  assert.equal(recovered.deepScanned, true);
  assert.equal(recovered.scanError, undefined);
  assert.equal(counts.tarballs, 2);
});

test('registry document, detail and audit caches honor entry count and TTL', async t => {
  let now = 0;
  const { client, counts } = await registry(t, { cacheOptions: { maxEntries: 1, maxBytes: 8192, ttlMs: 10, now: () => now } });
  await client.fullAudit('first', false, '1.0.0');
  await client.fullAudit('first', false, '1.0.0');
  assert.equal(counts.docs.get('first'), 1);
  await client.fullAudit('second', false, '1.0.0');
  assertBounded(client.cacheStats(), 1, 8192);
  await client.fullAudit('first', false, '1.0.0');
  assert.equal(counts.docs.get('first'), 2);
  now = 10;
  await client.fullAudit('first', false, '1.0.0');
  assert.equal(counts.docs.get('first'), 3);
  assertBounded(client.cacheStats(), 1, 8192);
});

test('registry caches evict oversized settled JSON instead of retaining it', async t => {
  const { client, counts } = await registry(t, { cacheOptions: { maxEntries: 64, maxBytes: 100 } });
  await client.fullAudit('fixture', false, '1.0.0');
  assert.deepEqual(client.cacheStats(), { docs: { entries: 0, bytes: 0 }, details: { entries: 0, bytes: 0 }, audits: { entries: 0, bytes: 0 } });
  const previous = counts.docs.get('fixture');
  await client.getPackageDetail('fixture', '1.0.0');
  assert.equal(counts.docs.get('fixture'), previous + 1);
});

test('registry document failure can recover without recreating the client', async t => {
  const { client, counts } = await registry(t, { onDocument(_req, res, _name, attempt) {
    if (attempt !== 1) return false;
    res.writeHead(503); res.end('offline'); return true;
  } });
  await assert.rejects(client.getPackageDetail('fixture', '1.0.0'), /HTTP 503/);
  assert.equal(client.cacheStats().docs.entries, 0);
  assert.equal(client.cacheStats().details.entries, 0);
  assert.equal((await client.getPackageDetail('fixture', '1.0.0')).version, '1.0.0');
  assert.equal(counts.docs.get('fixture'), 2);
});

test('failed registry configuration is retried after its CA file becomes available', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'umeko-marketplace-config-retry-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const cafile = join(dir, 'available-later.pem');
  const { client, counts } = await registry(t, { agent: { npmCafile: cafile } });
  await assert.rejects(client.getPackageDetail('fixture', '1.0.0'), /ENOENT/);
  assert.equal(counts.docs.size, 0);
  await writeFile(cafile, rootCertificates[0]);
  assert.equal((await client.getPackageDetail('fixture', '1.0.0')).version, '1.0.0');
  assert.equal(counts.docs.get('fixture'), 1);
});
