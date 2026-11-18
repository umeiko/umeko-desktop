import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import vm from 'node:vm';

const qml = readFileSync(new URL('../app/qml/DesktopPetReminders.qml', import.meta.url), 'utf8');
const start = qml.indexOf('function resolveLocalTime(){');
const end = qml.indexOf('function saveItem(){', start);
assert.ok(start >= 0 && end > start, 'Locate the real QML local-time resolver');
const resolver = qml.slice(start, end).trim();

// The reminder editor now asks the host's IANA-zone resolver. Exercise that
// real boundary, while keeping the expected UTC instants independent below.
const root = fileURLToPath(new URL('../', import.meta.url));
const python = process.env.UMEKO_TEST_PYTHON || fileURLToPath(new URL(
  process.platform === 'win32' ? '../.venv/Scripts/python.exe' : '../.venv/bin/python', import.meta.url));
const hostResolver = `
import json, sys, tempfile
from PySide6.QtCore import QCoreApplication
from app.pet_reminders import PetReminders
app = QCoreApplication([])
with tempfile.TemporaryDirectory() as directory:
    service = PetReminders(directory)
    print(json.dumps(service.resolve_local_time(json.load(sys.stdin))))
`;
const NativeDate = Date;

function resolve(date, time, originalZone = '') {
  const sandbox = {
    originalZone,
    snapshot: { timeZone: 'America/Los_Angeles' },
    pet: { ui(method, args) {
      assert.equal(method, 'resolveReminderTime');
      assert.deepEqual(JSON.parse(JSON.stringify(args)), {
        date, time, timeZone: originalZone || 'America/Los_Angeles',
      });
      const result = spawnSync(python, ['-c', hostResolver], {
        cwd: root, input: JSON.stringify(args), encoding: 'utf8', timeout: 5000,
      });
      assert.equal(result.status, 0, result.stderr || String(result.error));
      return { ok: true, result: JSON.parse(result.stdout) };
    } },
    dateField: { text: date },
    timeField: { text: time },
    offsetPicker: { currentIndex: 99 },
    localCandidates: [],
  };
  vm.runInNewContext(`(${resolver})()`, sandbox, { timeout: 6000 });
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

test('editing preserves the reminder zone even when the current host zone differs', () => {
  assert.deepEqual(resolve('2026-11-01', '01:30', 'America/New_York'), {
    candidates: [
      { epoch: NativeDate.parse('2026-11-01T05:30:00Z'), label: 'UTC-04:00' },
      { epoch: NativeDate.parse('2026-11-01T06:30:00Z'), label: 'UTC-05:00' },
    ],
    selected: -1,
  });
});
