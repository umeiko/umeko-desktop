import assert from 'node:assert/strict';
import test from 'node:test';
import { createGenerationMeter } from '../runtime/generation-metrics.mjs';

test('speed excludes initial waiting and uses reported output tokens when available', () => {
  let clock = 0;
  const events = [];
  const meter = createGenerationMeter(event => events.push(event), { now: () => clock });
  meter.start();
  assert.equal(events.at(-1).tokensPerSecond, null);
  clock = 5000; meter.update({ type: 'text_delta', delta: '测试文字' });
  assert.equal(events.at(-1).elapsedMs, 0);
  assert.equal(events.at(-1).tokensPerSecond, null);
  clock = 6000; meter.tick();
  assert.equal(events.at(-1).tokensPerSecond, 4);
  assert.equal(events.at(-1).estimated, true);
  clock = 7000; meter.update({ type: 'text_delta', delta: 'more', partial: { usage: { output: 20 } } });
  assert.equal(events.at(-1).tokensPerSecond, 10);
  assert.equal(events.at(-1).estimated, false);
  meter.finish({ usage: { output: 24 } });
  assert.equal(events.at(-1).active, false);
  assert.equal(events.at(-1).tokensPerSecond, 12);
});

test('chunk boundaries do not change estimates; thinking and function arguments count', () => {
  const run = chunks => {
    let clock = 0;
    const events = [];
    const meter = createGenerationMeter(e => events.push(e), { now: () => clock });
    meter.start();
    for (const delta of chunks) meter.update({ type: 'thinking_delta', delta });
    meter.update({ type: 'toolcall_delta', delta: '{"x":123}' });
    clock = 1000; meter.tick(); meter.stop();
    return events.at(-1).tokens;
  };
  assert.equal(run(['你好test']), run(['你', '好', 't', 'es', 't']));
  assert.equal(run(['你好test']), 6);
});

test('cancellation stops updates and the next response starts with empty counters', () => {
  let clock = 0;
  const events = [];
  const meter = createGenerationMeter(e => events.push(e), { now: () => clock });
  meter.start(); meter.update({ type: 'text_delta', delta: 'hello' });
  meter.stop();
  const count = events.length;
  clock = 1000; meter.update({ type: 'text_delta', delta: 'ignored' }); meter.tick();
  assert.equal(events.length, count);
  meter.start();
  assert.equal(events.at(-1).tokens, 0);
  assert.equal(events.at(-1).tokensPerSecond, null);
  assert.equal(events.at(-1).active, true);
  meter.update({ type: 'text_delta', delta: 'a', partial: { usage: { output: Infinity } } });
  clock = 2000; meter.tick();
  assert.equal(events.at(-1).estimated, true);
  assert.equal(events.at(-1).tokensPerSecond, 1);
  meter.stop();
});
