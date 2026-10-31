import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const qml = readFileSync(new URL('../umeko-plugins/desktop-pet/qml/Settings.qml', import.meta.url), 'utf8');
const start = qml.indexOf('function resolveLocalTime(){');
const end = qml.indexOf('function saveItem(){', start);
assert.ok(start >= 0 && end > start, 'Locate the real QML local-time resolver');
const resolver = qml.slice(start, end).trim();

// An independent US/Pacific fixture: the 2026 transitions occur at these UTC
// instants. Its getters expose local wall time without changing the host zone.
const NativeDate = Date;
const spring = NativeDate.parse('2026-03-08T10:00:00Z');
const fall = NativeDate.parse('2026-11-01T09:00:00Z');
class PacificDate {
  constructor(epoch) { this.epoch = new NativeDate(epoch).getTime(); }
  static UTC(...parts) { return NativeDate.UTC(...parts); }
  getTimezoneOffset() { return this.epoch >= spring && this.epoch < fall ? 420 : 480; }
  wall() { return new NativeDate(this.epoch - this.getTimezoneOffset() * 60000); }
  getFullYear() { return this.wall().getUTCFullYear(); }
  getMonth() { return this.wall().getUTCMonth(); }
  getDate() { return this.wall().getUTCDate(); }
  getHours() { return this.wall().getUTCHours(); }
  getMinutes() { return this.wall().getUTCMinutes(); }
}

function resolve(date, time) {
  const sandbox = {
    Date: PacificDate,
    dateField: { text: date },
    timeField: { text: time },
    offsetPicker: { currentIndex: 99 },
    localCandidates: [],
  };
  vm.runInNewContext(`(${resolver})()`, sandbox, { timeout: 1000 });
  return {
    candidates: Array.from(sandbox.localCandidates, row => ({ epoch: row.epoch, label: row.label })),
    selected: sandbox.offsetPicker.currentIndex,
  };
}

test('QML rejects the nonexistent local time in the spring DST gap', () => {
  assert.deepEqual(resolve('2026-03-08', '02:30'), { candidates: [], selected: -1 });
});

test('QML exposes both fall DST occurrences and requires an explicit offset', () => {
  assert.deepEqual(resolve('2026-11-01', '01:30'), {
    candidates: [
      { epoch: NativeDate.parse('2026-11-01T08:30:00Z'), label: 'UTC-07:00' },
      { epoch: NativeDate.parse('2026-11-01T09:30:00Z'), label: 'UTC-08:00' },
    ],
    selected: -1,
  });
});

test('QML selects the sole UTC candidate for an ordinary local time', () => {
  assert.deepEqual(resolve('2026-07-15', '12:34'), {
    candidates: [{ epoch: NativeDate.parse('2026-07-15T19:34:00Z'), label: 'UTC-07:00' }],
    selected: 0,
  });
});

test('QML rejects an invalid calendar date instead of normalizing it', () => {
  assert.deepEqual(resolve('2026-02-30', '12:34'), { candidates: [], selected: -1 });
});
