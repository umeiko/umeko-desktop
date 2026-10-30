import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { createRequire } from 'node:module';
import { gzipSync } from 'node:zlib';
import { createMarketplace } from '../runtime/releases/coding-1.3.0/marketplace.mjs';
import { createRegistryClient } from '../runtime/releases/coding-1.3.0/marketplace-source.mjs';
import { createPiCommandController } from '../runtime/releases/coding-1.3.0/pi-commands.mjs';
import * as Pi from '../runtime/releases/coding-1.3.0/node_modules/@earendil-works/pi-coding-agent/dist/index.js';

const require = createRequire(new URL('../runtime/releases/coding-1.3.0/package.json', import.meta.url));
const { Header } = require('tar');
const name = 'umeko-version-boundary-fixture';

function packageArchive(version) {
  const manifest = { name, version, type: 'module', keywords: ['pi-package'], pi: { extensions: ['./index.js'] } };
  const files = { 'package/package.json': JSON.stringify(manifest), 'package/index.js': `export default pi => {}; // version ${version}\n` };
  const chunks = [];
  for (const [path, content] of Object.entries(files)) {
    const data = Buffer.from(content);
    const header = new Header({ path, type: 'File', size: data.length, mode: 0o644, mtime: new Date(0) });
    header.encode();
    chunks.push(header.block, data, Buffer.alloc((512 - data.length % 512) % 512));
  }
  return { manifest, body: gzipSync(Buffer.concat([...chunks, Buffer.alloc(1024)])) };
}

test('latest audit stays pinned through the real registry, source scan and native Pi npm install', { timeout: 90000 }, async () => {
  const root = await mkdtemp(join(tmpdir(), 'umeko-market-version-'));
  const cwd = join(root, 'project'), agentDir = join(root, 'agent'), cache = join(root, 'npm-cache');
  for (const path of [cwd, agentDir, cache, join(root, 'tmp')]) await mkdir(path);
  const userconfig = join(root, 'npmrc'), globalconfig = join(root, 'global-npmrc');
  const archives = new Map(['1.0.0', '2.0.0'].map(version => [version, packageArchive(version)]));
  const requests = [], downloads = [], events = [], customEntries = [], nativeCommands = [];
  let latest = '1.0.0', origin, client, reloaded = 0;
  const server = createServer((req, res) => {
    const path = new URL(req.url, origin).pathname;
    requests.push(path);
    const version = /^\/source-(1\.0\.0|2\.0\.0)\.tgz$/.exec(path)?.[1];
    if (version) {
      downloads.push(version);
      // The unversioned audit already selected v1; advance latest during its download.
      latest = '2.0.0';
      res.setHeader('content-type', 'application/octet-stream');
      res.end(archives.get(version).body);
      return;
    }
    const versions = Object.fromEntries([...archives].map(([version, fixture]) => [version, {
      ...fixture.manifest, description: `Local exact-version fixture ${version}`, license: 'MIT',
      dist: { tarball: `${origin}/source-${version}.tgz` },
    }]));
    res.setHeader('content-type', 'application/json');
    if (path === `/${name}`) res.end(JSON.stringify({ name, 'dist-tags': { latest }, versions }));
    else if (path.startsWith(`/${name}/`) && versions[path.split('/').at(-1)]) res.end(JSON.stringify(versions[path.split('/').at(-1)]));
    else { res.writeHead(404); res.end(JSON.stringify({ error: 'No such local fixture route' })); }
  });
  const overrides = {
    npm_config_registry: '', npm_config_cache: cache, npm_config_userconfig: userconfig,
    npm_config_globalconfig: globalconfig, npm_config_audit: 'false', npm_config_fund: 'false',
    npm_config_update_notifier: 'false', npm_config_fetch_retries: '0', npm_config_proxy: '',
    npm_config_https_proxy: '', npm_config_noproxy: '127.0.0.1,localhost',
    PI_CODING_AGENT_DIR: agentDir, TMP: join(root, 'tmp'), TEMP: join(root, 'tmp'), TMPDIR: join(root, 'tmp'),
  };
  const previous = new Map(Object.keys(overrides).map(key => [key, process.env[key]]));
  try {
    server.listen(0, '127.0.0.1'); await once(server, 'listening');
    origin = `http://127.0.0.1:${server.address().port}`;
    overrides.npm_config_registry = origin;
    await writeFile(userconfig, `registry=${origin}\naudit=false\nfund=false\n`);
    await writeFile(globalconfig, '');
    Object.assign(process.env, overrides);
    const config = { workspace: cwd, agentDir, agent: { npmRegistry: origin, npmUserconfig: userconfig, installPermission: 'automatic' } };
    const session = {
      isIdle: false,
      sessionManager: {
        getSessionId: () => 'version-boundary-session', getSessionFile: () => join(root, 'session.jsonl'),
        getCwd: () => cwd, appendCustomEntry: (type, value) => customEntries.push({ type, ...value }),
      },
      extensionRunner: { getCommand: () => null },
    };
    const controller = createPiCommandController({
      Pi, getRuntime: () => ({ session }), getConfig: () => config,
      reload: async target => { assert.equal(target, session); reloaded++; },
      notify: () => {}, emit: event => events.push(event),
    });
    const tools = new Map();
    createMarketplace({
      getConfig: () => config,
      registryFactory: options => client = createRegistryClient({ ...options, fetch: globalThis.fetch }),
      runPiCommand: (command, options) => { nativeCommands.push(command); return controller.run(command, options); },
      emit: event => events.push(event),
    }).extension({ registerTool: tool => tools.set(tool.name, tool) });

    const audit = await tools.get('marketplace_audit').execute('audit-v1', { name });
    assert.equal(audit.isError, undefined, JSON.stringify(audit.details));
    assert.equal(audit.details.version, '1.0.0');
    assert.equal(audit.details.deepScanned, true);
    assert.equal(latest, '2.0.0');

    const installed = await tools.get('marketplace_install').execute('install-v1', {
      name, version: audit.details.version, reason: 'Exercise the exact audited package version',
    });
    assert.equal(installed.isError, undefined, JSON.stringify(installed.details));
    assert.equal(installed.details.status, 'completed');
    assert.equal(installed.details.reload, 'queued');
    assert.deepEqual(nativeCommands, [`pi install npm:${name}@1.0.0`]);
    const event = events.find(event => event.type === 'package_install');
    assert.ok(event, 'native installation must emit its installed-package identity');
    assert.equal(event.source, `npm:${name}@1.0.0`);
    assert.equal(event.version, '1.0.0');
    assert.equal(event.audit.version, '1.0.0');
    const manifest = JSON.parse(await readFile(join(event.packageRoot, 'package.json'), 'utf8'));
    assert.equal(manifest.name, name);
    assert.equal(manifest.version, '1.0.0');
    assert.ok(downloads.length >= 2, 'audit and native npm must both download the source archive');
    assert.ok(downloads.every(version => version === '1.0.0'), JSON.stringify(downloads));
    assert.equal(reloaded, 0, 'busy native session must retain its queued reload');
    session.isIdle = true;
    const reports = await controller.flush();
    assert.equal(reports[0].command, '/reload');
    assert.equal(reports[0].status, 'completed');
    assert.equal(reloaded, 1);
    assert.equal(customEntries[0].command, '/reload');
    assert.ok(requests.includes(`/${name}`));
  } finally {
    for (const [key, value] of previous) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    await client?.close();
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
    await rm(root, { recursive: true, force: true });
  }
});
