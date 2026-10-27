import test from "node:test";
import assert from "node:assert/strict";
import { compactionSettings } from "../runtime/compaction-settings.mjs";

test("explicit threshold maps Pi reserve and clamps recent tokens", () => {
  assert.deepEqual(compactionSettings({contextWindow:128000,compactionThreshold:40000}),
    {reserveTokens:88000,keepRecentTokens:20000});
  assert.deepEqual(compactionSettings({contextWindow:8000,compactionThreshold:1024}, {enabled:false}),
    {enabled:false,reserveTokens:6976,keepRecentTokens:512});
  assert.equal(compactionSettings({contextWindow:128000,compactionThreshold:10001}).keepRecentTokens, 5000);
  assert.equal(compactionSettings({contextWindow:128000,compactionThreshold:40000}, {keepRecentTokens:500}).keepRecentTokens, 500);
  assert.equal(compactionSettings({contextWindow:128000,compactionThreshold:128000}).reserveTokens, 0);
});

test("empty thresholds preserve native compaction settings without mutating them", () => {
  const native = {enabled:true,reserveTokens:16384,keepRecentTokens:20000};
  for (const compactionThreshold of [null,undefined,""]) {
    assert.deepEqual(compactionSettings({contextWindow:128000,compactionThreshold}, native),native);
    assert.deepEqual(compactionSettings({contextWindow:128000,compactionThreshold}),{});
  }
  const model = {contextWindow:128000,compactionThreshold:40000,maxTokens:32768};
  compactionSettings(model,native);
  assert.equal(native.reserveTokens,16384);
  assert.equal(model.maxTokens,32768);
});

test("invalid explicit thresholds cannot silently select another policy", () => {
  for (const compactionThreshold of [0,1023,130000,1024.5,"1200"])
    assert.throws(() => compactionSettings({contextWindow:128000,compactionThreshold}), /1024/);
});
