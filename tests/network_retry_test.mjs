import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createServer, get } from 'node:https';
import { NETWORK_RETRY, certificateFailure, transientFailure, upstreamFailure, retryOmissions } from '../runtime/network-retry.mjs';

test('five bounded exponential backoffs', () => {
  assert.equal(NETWORK_RETRY.maxRetries, 5);
  assert.deepEqual([1,2,3,4,5].map(i => Math.min(NETWORK_RETRY.baseDelayMs * 2**(i-1), NETWORK_RETRY.maxAgentDelayMs)), [2000,4000,8000,16000,30000]);
});
test('transient streams retry, login, quota and configuration failures do not', () => {
  for (const text of ['供应商流已中断', 'ECONNRESET', 'fetch failed', 'socket hang up', 'stream interrupted']) assert.ok(transientFailure(text), text);
  for (const status of [408,425,429,500,502,503,504]) assert.ok(transientFailure('HTTP failed', [{response:{status}}]));
  for (const status of [400,401,403,404,422]) assert.ok(!transientFailure('stream failed', [{response:{status}}]));
  for (const text of ['insufficient_quota', 'billing exhausted', 'certificate validation failed']) assert.ok(!transientFailure(text));
  assert.ok(!transientFailure('HTTP429', [{response:{status:429,body:'insufficient_quota'}}]));
  assert.ok(transientFailure('ECONNRESET', [{response:{status:200,body:'data: {"content":"billing and quota exceeded explained"}'}}]));
  assert.match(upstreamFailure({retryable:true,reportId:'fixture',message:'safe detail'}).message, /^Network error:/);
  assert.ok(!upstreamFailure({retryable:false,reportId:'fixture',message:'safe detail'}).message.includes('Network error'));
});
test('recovered drafts stay in raw history but disappear from presentation', () => {
  assert.deepEqual([...retryOmissions([{id:'bad',type:'message',message:{role:'assistant',stopReason:'error'}}, {type:'context_edit',targetId:'bad',replacement:null}])], ['bad']);
});

test('certificate words and paths do not hide transient timeouts', () => {
  for (const detail of ['timed out reading certificate request details',
    String.raw`timed out opening C:\certificate\CERT_HAS_EXPIRED\request.json`,
    'timed out reading self-signed certificate notes']) {
    const error = new Error(detail);
    assert.equal(certificateFailure(error), null, detail);
    assert.ok(transientFailure(error), detail);
  }
  assert.ok(transientFailure(new Error('timed out'), [{response: {status: 503, body: 'certificate processing timed out'}}]));
});

test('nested structured TLS codes preserve trust recovery and fatal precedence', () => {
  const trust = Object.assign(new Error('verification failed'), {code: 'SELF_SIGNED_CERT_IN_CHAIN'});
  const error = new Error('fetch failed', {cause: new AggregateError([trust], 'connection failed')});
  assert.deepEqual(certificateFailure(error), {code: 'SELF_SIGNED_CERT_IN_CHAIN', recoverable: true});
  assert.ok(!transientFailure(error, [{response: {status: 503}}]));
  const expired = Object.assign(new Error('verification failed'), {code: 'CERT_HAS_EXPIRED'});
  assert.deepEqual(certificateFailure(new AggregateError([trust, expired])), {code: 'CERT_HAS_EXPIRED', recoverable: false});
  assert.deepEqual(certificateFailure(Object.assign(new Error('invalid CA file'), {code: 'UMEKO_CA_INVALID'})),
    {code: 'UMEKO_CA_INVALID', recoverable: false});
});

test('native Node TLS verification errors remain terminal when nested', async () => {
  const fixture = new URL('./fixtures/update-tls/', import.meta.url);
  const server = createServer({cert: await readFile(new URL('server.pem', fixture)),
    key: await readFile(new URL('server-key.pem', fixture))}, (_request, response) => response.end('fixture'));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const tlsError = await new Promise((resolve, reject) => {
      get(`https://127.0.0.1:${server.address().port}`, response => {
        response.resume();
        reject(new Error('untrusted fixture unexpectedly succeeded'));
      }).on('error', resolve);
    });
    assert.ok(['UNABLE_TO_VERIFY_LEAF_SIGNATURE', 'SELF_SIGNED_CERT_IN_CHAIN', 'UNABLE_TO_GET_ISSUER_CERT_LOCALLY'].includes(tlsError.code), tlsError.code);
    const error = new Error('fetch failed', {cause: tlsError});
    assert.deepEqual(certificateFailure(error), {code: tlsError.code, recoverable: true});
    assert.ok(!transientFailure(error));
  } finally {
    await new Promise(resolve => server.close(resolve));
  }
});
