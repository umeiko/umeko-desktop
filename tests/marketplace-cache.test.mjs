import test from 'node:test';
import assert from 'node:assert/strict';
import { createMarketplace } from '../runtime/marketplace.mjs';

function fixture(registry, cacheOptions) {
  const tools = new Map(), installs = [];
  createMarketplace({
    getConfig: () => ({ workspace: 'fixture', agent: {} }),
    registryFactory: () => registry,
    cacheOptions,
    runPiCommand: async (command, options) => {
      installs.push({ command, options });
      return { status: 'completed' };
    },
  }).extension({ registerTool: tool => tools.set(tool.name, tool) });
  return {
    installs,
    run: (name, params, signal) => tools.get(`marketplace_${name}`).execute('fixture', params, signal),
  };
}

const detail = (name, version = '1.0.0') => ({ name, version, keywords: ['pi-package'] });
const installParams = { name: 'fixture', version: '1.0.0', reason: 'Use its tool' };

test('oversized marketplace results return a bounded error instead of breaking the host frame', async () => {
  const f=fixture({getPackageDetail:async name=>({...detail(name),description:'x'.repeat(300*1024)})});
  const result=await f.run('detail',{name:'fixture'});
  assert.equal(result.isError,true);
  assert.match(result.details.error,/result exceeds 262144 bytes/);
  assert.ok(Buffer.byteLength(JSON.stringify(result))<1024);
});

test('failed detail and audit promises are evicted so the same request can retry', async () => {
  let detailCalls = 0, auditCalls = 0;
  const f = fixture({
    getPackageDetail: async (name, version) => {
      if (++detailCalls === 1) throw new Error('temporary detail failure');
      return detail(name, version);
    },
    fullAudit: async (_name, _deep, version) => {
      if (++auditCalls === 1) throw new Error('temporary audit failure');
      return { version, summary: 'notes' };
    },
  });
  const params = { name: 'fixture', version: '1.0.0' };
  assert.equal((await f.run('detail', params)).isError, true);
  assert.equal((await f.run('detail', params)).details.version, '1.0.0');
  assert.equal((await f.run('audit', params)).isError, true);
  assert.equal((await f.run('audit', params)).details.version, '1.0.0');
  assert.equal(detailCalls, 2);
  assert.equal(auditCalls, 2);
});

test('detail and audit caches honor count, byte and TTL options', async () => {
  for (const mode of ['count', 'bytes', 'ttl']) {
    let now = 0, detailCalls = 0, auditCalls = 0;
    const payload = mode === 'bytes' ? 'x'.repeat(2048) : '';
    const f = fixture({
      getPackageDetail: async (name, version) => { detailCalls++; return { ...detail(name, version), payload }; },
      fullAudit: async (_name, _deep, version) => { auditCalls++; return { version, payload }; },
    }, { maxEntries: mode === 'count' ? 1 : 64, maxBytes: 1024, ttlMs: 10, now: () => now });
    const params = { name: 'fixture', version: '1.0.0' };
    await f.run('audit', params);
    const firstDetailCalls = detailCalls;
    if (mode === 'count') await f.run('audit', { ...params, name: 'other' });
    if (mode === 'ttl') now = 11;
    await f.run('audit', params);
    assert.ok(detailCalls > firstDetailCalls, `${mode}: detail must be loaded again`);
    assert.equal(auditCalls, mode === 'count' ? 3 : 2, `${mode}: audit must be loaded again`);
  }
});

test('a report with a failed source scan is returned but not retained', async () => {
  let auditCalls = 0;
  const f = fixture({
    getPackageDetail: async (name, version) => detail(name, version),
    fullAudit: async (_name, _deep, version) => ++auditCalls === 1
      ? { version, scanError: 'temporary scan failure', deepScanned: false }
      : { version, deepScanned: true },
  });
  const params = { name: 'fixture', version: '1.0.0' };
  assert.equal((await f.run('audit', params)).details.scanError, 'temporary scan failure');
  assert.equal((await f.run('audit', params)).details.deepScanned, true);
  assert.equal(auditCalls, 2);
});

test('all registry operations receive the caller signal', async () => {
  const signal = new AbortController().signal, observed = [];
  const f = fixture({
    searchPackages: async (_query, options) => { observed.push(options.signal); return { packages: [] }; },
    getPackageDetail: async (name, version, options) => { observed.push(options.signal); return detail(name, version); },
    fullAudit: async (_name, _deep, version, options) => { observed.push(options.signal); return { version }; },
  });
  await f.run('search', { query: 'fixture' }, signal);
  await f.run('audit', { name: 'fixture', version: '1.0.0' }, signal);
  await f.run('install', installParams, signal);
  assert.deepEqual(observed, [signal, signal, signal]);
  assert.equal(f.installs[0].options.signal, signal);
});

test('a wrong detail version or audit version blocks installation and can be retried', async () => {
  let wrongDetail = true, wrongAudit = true;
  const f = fixture({
    getPackageDetail: async (name, version) => detail(name, wrongDetail ? '2.0.0' : version),
    fullAudit: async (_name, _deep, version) => ({ version: wrongAudit ? '2.0.0' : version }),
  });
  assert.match((await f.run('install', installParams)).details.error, /Registry.*exact version/);
  wrongDetail = false;
  assert.match((await f.run('install', installParams)).details.error, /Audit.*exact version/);
  assert.equal(f.installs.length, 0);
  wrongAudit = false;
  assert.equal((await f.run('install', installParams)).details.status, 'completed');
  assert.equal(f.installs[0].options.audit.version, installParams.version);
});

test('a latest audit stays pinned when latest advances before audit and installation', async () => {
  let latest = '1.0.0';
  const auditVersions = [];
  const f = fixture({
    getPackageDetail: async (name, version) => {
      const selected = version || latest;
      latest = '2.0.0';
      return detail(name, selected);
    },
    fullAudit: async (_name, _deep, version) => {
      auditVersions.push(version);
      return { version: version || latest };
    },
  });
  assert.equal((await f.run('audit', { name: 'fixture' })).details.version, '1.0.0');
  await f.run('install', installParams);
  assert.deepEqual(auditVersions, ['1.0.0']);
  assert.equal(f.installs[0].command, 'pi install npm:fixture@1.0.0');
  assert.equal(f.installs[0].options.audit.version, '1.0.0');
});
