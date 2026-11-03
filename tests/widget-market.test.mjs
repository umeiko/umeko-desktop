import test from 'node:test';
import assert from 'node:assert/strict';
import {Readable} from 'node:stream';
import {mkdtemp, mkdir, readFile, rm} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {marketRequest, officialURL} from '../runtime/widget-market.mjs';

const api = 'https://api.github.com/repos/umeiko/umeko-desktop-widgets/releases?per_page=100&page=1';
const raw = 'https://raw.githubusercontent.com/umeiko/umeko-desktop-widgets/widget-v1/widgets/sample-widget/manifest.json';
const asset = 'https://github.com/umeiko/umeko-desktop-widgets/releases/download/widget-v1/sample-widget-1.0.0.zip';

test('public GET metadata uses updater fetch transport and only the ETag header', async () => {
  const calls = [];
  const fetcher = async (url, options) => {
    calls.push({url, options});
    const stream = Readable.from([Buffer.from('[]')]);
    stream.statusCode = 200; stream.headers = {etag:'"release"'};
    return stream;
  };
  const reply = await marketRequest({url:api, headers:{'If-None-Match':'"previous"',Authorization:'must-not-send'}}, fetcher);
  assert.equal(reply.body, '[]');
  assert.equal(reply.headers.etag, '"release"');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.headers['If-None-Match'], '"previous"');
  assert.equal(calls[0].options.headers.Authorization, undefined);
  assert.equal(calls[0].options.method, undefined, 'updateRequest supplies the fixed HTTPS GET');
  assert.equal(officialURL(raw), raw);
});

test('unofficial sources are rejected before any request', async () => {
  let calls = 0;
  const fetcher = async () => { calls++; throw Error('must not fetch'); };
  for (const url of ['https://example.com/widget.zip',api.replace('umeiko','other'),api + '&token=secret',
                     raw.replace('https:','http:'),asset + '?download=1',asset + '#fragment']) {
    await assert.rejects(marketRequest({url}, fetcher));
  }
  assert.equal(calls, 0);
});

test('download streams into its caller-owned temporary archive without updater install work', async () => {
  const parent = fileURLToPath(new URL('../build/widget-market-tests/', import.meta.url));
  await mkdir(parent, {recursive:true});
  const directory = await mkdtemp(path.join(parent, 'node-'));
  try {
    const destination = path.join(directory, 'package.zip');
    const fetcher = async () => {
      const stream = Readable.from([Buffer.from('local '),Buffer.from('archive')]);
      stream.statusCode = 200; stream.headers = {};
      return stream;
    };
    const result = await marketRequest({url:asset,destination}, fetcher);
    assert.equal(result.status, 200);
    assert.equal(await readFile(destination, 'utf8'), 'local archive');
    assert.equal(result.body, undefined);
  } finally { await rm(directory, {recursive:true,force:true}); }
});

test('304 response remains available to the catalog cache', async () => {
  const result = await marketRequest({url:api}, async () => {
    const stream = Readable.from([]);stream.statusCode = 304;stream.headers = {etag:'"same"'};return stream;
  });
  assert.equal(result.status, 304);
  assert.equal(result.body, '');
});
