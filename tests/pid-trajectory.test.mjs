import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const pid = vm.createContext({});
vm.runInContext(readFileSync(new URL('../app/qml/PidTrajectory.js', import.meta.url), 'utf8').replace('.pragma library', ''), pid);

test('original PID response retains damped overshoot and bounded control state', () => {
  assert.deepEqual([pid.kp, pid.ki, pid.kd], [280, 60, 20]);
  for (const distance of [34, 144, 1200, -1200]) {
    const path = pid.plan(0, 0, 0, distance);
    assert(path.samples.some(([position]) => Math.sign(distance) * (position - distance) > 1));
    assert(path.samples.every(([, velocity, integral]) => Math.abs(velocity) <= 1800 && Math.abs(integral) <= 60));
    assert.deepEqual(Array.from(pid.sample(path, path.duration)), [distance, 0, 0]);
    assert(path.curve.length <= 60, 'Qt BezierEase supports at most ten cubic segments');
    assert.deepEqual(Array.from(path.curve.slice(-2)), [1, 1]);
    assert(path.segments.every(segment => segment.error < 2.5), 'Rendered path deviates visibly from the original controller');
    assert(path.curve.every(Number.isFinite));
  }
});

test('reversal preserves current position, velocity and integral instead of restarting', () => {
  const outward = pid.plan(20, 0, 0, 500);
  const state = pid.sample(outward, 90);
  const reversed = pid.plan(...state, 0);
  assert.deepEqual(Array.from(reversed.samples[0]), Array.from(state));
  assert(reversed.samples[1][0] > state[0], 'Retarget discarded the existing forward momentum');
  assert.deepEqual(Array.from(pid.sample(reversed, reversed.duration)), [0, 0, 0]);
});

test('retargeting to the current position still decelerates and returns without invalid easing', () => {
  const path = pid.plan(400, 500, 15, 400);
  assert(path.end !== path.start);
  assert(path.samples.some(([position]) => position > 405));
  assert(path.curve.every(Number.isFinite));
  assert.deepEqual(Array.from(pid.sample(path, path.duration)), [400, 0, 0]);
});
