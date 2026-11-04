import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// Load the bridge's pure policy without starting Pi, stdin, or a model request.
const bridge = readFileSync(new URL("../runtime/bridge.mjs", import.meta.url), "utf8");
const start = bridge.indexOf("export function resolveReasoningState(");
const end = bridge.indexOf("\n// End reasoning policy.", start);
assert.ok(start >= 0 && end > start);
const { resolveReasoningState } = await import("data:text/javascript," + encodeURIComponent(bridge.slice(start, end)));

const models = [
  { id: "alpha", provider: "one", reasoningLevels: ["low", "medium", "xhigh"] },
  { id: "beta", provider: "two", reasoningLevels: ["high"] },
  { id: "unknown", provider: "two", reasoningLevels: [] },
];

test("bridge keeps raw medium/xhigh values and always supports off", () => {
  for (const effort of ["medium", "xhigh", "off"]) {
    const state = resolveReasoningState({ model: "alpha", provider: "one", reasoningEffort: effort }, {}, models);
    assert.equal(state.effort, effort);
    assert.deepEqual(state.levels, ["low", "medium", "xhigh"]);
  }
  assert.equal(resolveReasoningState({ model: "alpha", provider: "one", reasoningEffort: "max" }, {}, models).effort, "off");
});

test("each command uses its current model and empty capabilities clear an old selection", () => {
  const first = resolveReasoningState({ model: "alpha", provider: "one", reasoningEffort: "xhigh" }, {}, models);
  const second = resolveReasoningState({ model: "beta", provider: "two", reasoningEffort: "xhigh" }, first, models);
  assert.deepEqual(second, { model: "beta", provider: "two", levels: ["high"], effort: "off" });
  assert.equal(resolveReasoningState({ value: "high", reasoningLevels: ["high"] }, second, models).effort, "high");
  const unknown = resolveReasoningState({ model: "unknown", provider: "two", reasoningEffort: "high" }, second, models);
  assert.deepEqual(unknown.levels, []);
  assert.equal(unknown.effort, "off");
  const cleared = resolveReasoningState({ reasoningLevels: [], value: "xhigh" }, first, models);
  assert.equal(cleared.effort, "off");
  assert.deepEqual(cleared.levels, []);
});

test("provider identity and command capability updates take priority over the initial catalog", () => {
  const sharedAlias = [
    { id: "shared", provider: "one", reasoningLevels: ["medium"] },
    { id: "shared", provider: "two", reasoningLevels: ["xhigh"] },
  ];
  assert.equal(resolveReasoningState({ model: "shared", provider: "one", value: "xhigh" }, {}, sharedAlias).effort, "off");
  assert.equal(resolveReasoningState({ model: "shared", provider: "two", value: "xhigh" }, {}, sharedAlias).effort, "xhigh");
  assert.equal(resolveReasoningState({ model: "shared", value: "medium" }, {}, sharedAlias).effort, "off");
  const updated = resolveReasoningState({ model: "alpha", provider: "one", reasoningLevels: ["off", "custom", "custom"], value: "custom" }, {}, models);
  assert.deepEqual(updated.levels, ["custom"]);
  assert.equal(updated.effort, "custom");
});
