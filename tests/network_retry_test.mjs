import test from 'node:test';
import assert from 'node:assert/strict';
import { NETWORK_RETRY, transientFailure, upstreamFailure, retryOmissions } from '../runtime/network-retry.mjs';

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
  assert.match(upstreamFailure({retryable:true,reportId:'fixture',message:'safe detail'}).message, /^Network error:/);
  assert.ok(!upstreamFailure({retryable:false,reportId:'fixture',message:'safe detail'}).message.includes('Network error'));
});
test('recovered drafts stay in raw history but disappear from presentation', () => {
  assert.deepEqual([...retryOmissions([{id:'bad',type:'message',message:{role:'assistant',stopReason:'error'}}, {type:'context_edit',targetId:'bad',replacement:null}])], ['bad']);
});
