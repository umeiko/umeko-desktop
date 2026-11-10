import test from 'node:test';
import assert from 'node:assert/strict';
import { bindHttpRetryBoundary } from '../runtime/http-retry-boundary.mjs';

function fixture(initial = true) {
  let enabled = initial;
  const calls = [];
  // Expose only AgentSession's documented public retry methods/properties.
  const session = Object.freeze({
    get autoRetryEnabled() { return enabled; },
    setAutoRetryEnabled(value) { calls.push(value); enabled = value; },
  });
  return { session, calls, boundary: bindHttpRetryBoundary(session) };
}

const failed = (errorMessage = '429: {"code":"umeko_http_retry_finished","message":"rate limited"}') =>
  ({ type: 'message_end', message: { role: 'assistant', stopReason: 'error', errorMessage } });

test('managed HTTP final error suppresses the outer retry until settled, then restores once', () => {
  const { session, calls, boundary } = fixture();
  boundary.observe(failed());
  assert.equal(session.autoRetryEnabled, false);
  boundary.observe(failed());
  boundary.observe({ type: 'agent_end' });
  assert.deepEqual(calls, [false]);
  boundary.observe({ type: 'agent_settled', aborted: false });
  boundary.observe({ type: 'agent_settled', aborted: false });
  assert.equal(session.autoRetryEnabled, true);
  assert.deepEqual(calls, [false, true]);
});

test('ordinary connection resets, successful messages and other roles keep their retry policy', () => {
  const { session, calls, boundary } = fixture();
  for (const event of [
    failed('Network error: ECONNRESET'),
    failed('umeko_http_retry_finished_extra'),
    failed('prefix_umeko_http_retry_finished'),
    { type: 'message_end', message: { role: 'user', stopReason: 'error', errorMessage: 'umeko_http_retry_finished' } },
    { type: 'message_end', message: { role: 'assistant', stopReason: 'stop', errorMessage: 'umeko_http_retry_finished' } },
    { type: 'message_update', message: failed().message },
    { type: 'message_end', message: { role: 'assistant', stopReason: 'error' } },
    { type: 'agent_settled' },
  ]) boundary.observe(event);
  assert.equal(session.autoRetryEnabled, true);
  assert.deepEqual(calls, []);
});

test('previously disabled auto retry remains disabled without changing settings', () => {
  const { session, calls, boundary } = fixture(false);
  boundary.observe(failed());
  boundary.observe({ type: 'agent_settled' });
  boundary.close();
  assert.equal(session.autoRetryEnabled, false);
  assert.deepEqual(calls, []);
});

test('close restores a pending boundary once and ignores subsequent events', () => {
  const { session, calls, boundary } = fixture();
  boundary.observe(failed('503 umeko_http_retry_finished'));
  boundary.close();
  boundary.close();
  boundary.observe(failed());
  boundary.observe({ type: 'agent_settled' });
  assert.equal(session.autoRetryEnabled, true);
  assert.deepEqual(calls, [false, true]);
});

test('another turn retains ordinary retries and can enter its own managed boundary', () => {
  const { session, calls, boundary } = fixture();
  boundary.observe(failed());
  boundary.observe({ type: 'agent_settled', aborted: true });
  boundary.observe(failed('Network error: socket closed'));
  assert.equal(session.autoRetryEnabled, true);
  boundary.observe(failed());
  assert.equal(session.autoRetryEnabled, false);
  boundary.observe({ type: 'agent_settled' });
  assert.deepEqual(calls, [false, true, false, true]);
});
