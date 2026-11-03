"""Session retention and shutdown using local state and a model-free Node fixture."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from PySide6.QtCore import QCoreApplication, QProcess

from app.pi_runtime import node_executable
from app.pi_sessions import PiSessionPool, SessionState


class ProcessProbe:
    """Keep a Windows process HANDLE so exit checks cannot follow a reused PID."""
    def __init__(self, pid):
        self.pid = pid
        self.handle = None
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            self.kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            self.kernel.OpenProcess.restype = wintypes.HANDLE
            self.kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            self.kernel.WaitForSingleObject.restype = wintypes.DWORD
            self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            self.kernel.CloseHandle.restype = wintypes.BOOL
            self.handle = self.kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())

    def is_running(self):
        if os.name == 'nt':
            result = self.kernel.WaitForSingleObject(self.handle, 0)
            if result == 0:  # WAIT_OBJECT_0: this exact process exited.
                return False
            if result == 0x102:  # WAIT_TIMEOUT
                return True
            import ctypes
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            os.kill(self.pid, 0)
            return True
        except ProcessLookupError:
            return False

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class SessionCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.pool = PiSessionPool(body_limit=100 * 1024 * 1024)
        self.released = []
        self.pool.resourceReleased.connect(self.released.append)
        self.addCleanup(self.pool.close)

    def record(self, name, **values):
        return SessionState(id=name, file=name + '.jsonl', messages=[{'text': name}], **values)

    def cached(self):
        return [record.id for record in self.pool.records.values()
                if record.retained and self.pool._has_resources(record)]

    def test_capacity_zero_one_three_counts_current_idle_and_preserves_current(self):
        for capacity, expected in ((0, ['d']), (1, ['d']), (3, ['b', 'c', 'd'])):
            with self.subTest(capacity=capacity):
                self.pool.limit = capacity
                self.pool.records.clear()
                for name in 'abcd':
                    self.pool.touch(self.record(name), current=True)
                self.assertEqual(self.cached(), expected)
                self.assertEqual(self.pool.current.id, 'd')

    def test_empty_project_drafts_do_not_take_cache_slots(self):
        self.pool.limit = 1
        previous = self.record('previous')
        self.pool.touch(previous, current=True)
        draft = SessionState(draft='keep this', workspace='project')
        self.pool.touch(draft, current=True)
        self.assertEqual(self.cached(), ['previous'])
        self.assertTrue(previous.loaded)
        self.assertEqual(draft.draft, 'keep this')

    def test_lru_touch_updates_order_and_evicted_placeholder_is_not_recounted(self):
        self.pool.limit = 3
        a, b, c, d = [self.record(name) for name in 'abcd']
        for record in (a, b, c):
            self.pool.touch(record, current=True)
        self.pool.touch(a, current=True, dirty=False)
        self.pool.touch(d, current=True)
        self.assertEqual(self.cached(), ['c', 'a', 'd'])
        self.assertFalse(b.retained)
        count = len(self.released)
        self.pool.trim()
        self.assertEqual(len(self.released), count)
        b.messages = [{'text': 'reloaded'}]
        b.loaded = True
        self.pool.touch(b, current=True)
        self.assertEqual(self.cached(), ['a', 'd', 'b'])

    def test_running_loading_operation_approval_and_subagents_are_protected(self):
        self.pool.limit = 0
        current = self.record('current')
        self.pool.touch(current, current=True)
        records = [self.record('running', phase='running'), self.record('loading', phase='loading'),
                   self.record('operation', operation=True), self.record('approval', approval={'id': 'question'}),
                   self.record('subagents', subagents_active=True)]
        for record in records:
            self.pool.touch(record)
        self.assertEqual(self.cached(), ['current'] + [record.id for record in records])
        self.assertFalse(self.released)

    def test_finished_protected_session_is_evicted_when_over_budget(self):
        self.pool.limit = 1
        current, running = self.record('current'), self.record('running', phase='running')
        self.pool.touch(current, current=True)
        self.pool.touch(running)
        running.phase = 'idle'
        self.pool.trim()
        self.assertEqual(self.cached(), ['current'])
        self.assertFalse(running.loaded)

    def test_render_only_eviction_releases_body_but_preserves_draft_and_viewport(self):
        self.pool.limit = 1
        old = self.record('old', draft='unsent', scroll_index=12, scroll_y=7, follow_tail=False,
                          transcript=object(), history=[{'role': 'user'}], tree=[{'id': 'entry'}])
        self.pool.touch(old, current=True)
        self.pool.touch(self.record('new'), current=True)
        self.assertIn(old, self.released)
        self.assertEqual((old.messages, old.history, old.tree, old.transcript), ([], [], [], None))
        self.assertFalse(old.loaded)
        self.assertEqual((old.draft, old.scroll_index, old.scroll_y, old.follow_tail), ('unsent', 12, 7, False))

    def test_unsaved_authoritative_messages_survive_eviction_without_repeated_release(self):
        self.pool.limit = 1
        old = SessionState(id='unsaved', messages=[{'text': 'authoritative'}], draft='unsent')
        self.pool.touch(old, current=True)
        self.pool.touch(self.record('new'), current=True)
        self.assertFalse(old.retained)
        self.assertEqual(old.messages, [{'text': 'authoritative'}])
        count = len(self.released)
        self.pool.trim()
        self.assertEqual(len(self.released), count)

    def test_memory_budget_uses_same_protection_and_retention(self):
        self.pool.body_limit = 1
        current = self.record('current')
        self.pool.touch(current, current=True)
        waiting = self.record('waiting', approval={'id': 'question'})
        self.pool.touch(waiting)
        old = self.record('old')
        self.pool.touch(old)
        self.assertEqual(self.cached(), ['current', 'waiting'])
        self.assertFalse(old.loaded)
        self.assertFalse(old.retained)
        self.assertTrue(waiting.loaded)

    def test_invalidation_releases_idle_render_and_defers_every_protected_record(self):
        idle = self.record('idle')
        self.pool.touch(idle, current=True)
        protected = [self.record('running', phase='running'), self.record('waiting', approval={'id': 'confirm'}),
                     self.record('child', subagents_active=True)]
        for record in protected:
            self.pool.touch(record)
        self.pool.invalidate()
        self.assertEqual(self.released, [idle])
        self.assertTrue(idle.retained)
        self.assertTrue(idle.loaded)
        self.assertTrue(all(record.stale for record in protected))

    def test_processless_retire_releases_render_and_clears_intentional_crash_flag(self):
        record = self.record('cold', crashed=True, ready=True, stale=True)
        self.pool.retire(record)
        self.assertEqual(self.released, [record])
        self.assertFalse(record.crashed)
        self.assertFalse(record.ready)
        self.assertFalse(record.stale)

    def test_failed_to_start_sets_crash_flag_and_routes_exit(self):
        process = Mock()
        record = self.record('failure', process=process)
        events = []
        self.pool.event.connect(lambda owner, event: events.append((owner, event)))
        self.pool._error(record, process, QProcess.FailedToStart)
        self.assertTrue(record.crashed)
        self.assertIsNone(record.process)
        self.assertIs(events[0][0], record)
        self.assertEqual(events[0][1]['type'], 'exit')
        process.deleteLater.assert_called_once()

    def wait_until(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertTrue(predicate(), 'Local Node fixture did not reach the requested process state')

    def start_node(self, mode='normal'):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        script = Path(temporary.name) / 'fixture.mjs'
        script.write_text('''import {createInterface} from 'node:readline';
const lines=createInterface({input:process.stdin});
let mode='normal';
lines.on('line',line=>{
 const input=JSON.parse(line);
 if(input.type==='init'){mode=input.mode;console.log(JSON.stringify({type:'ready'}));}
 if(input.type==='shutdown' && mode!=='stubborn')process.exit(0);
 if(input.type==='crash')process.exit(3);
});
''', encoding='utf-8')
        record = self.record('node-' + mode, crashed=True)
        self.pool.touch(record, current=True)
        self.pool.event.connect(lambda owner, event: setattr(owner, 'ready', True) if event.get('type') == 'ready' else None)
        self.pool.start(record, node_executable(), script, {'type': 'init', 'mode': mode})
        process = record.process
        self.wait_until(lambda: record.ready)
        self.assertFalse(record.crashed)
        tracked = ProcessProbe(process.processId())
        self.addCleanup(tracked.close)
        self.addCleanup(lambda: self.pool.close())
        return record, process, tracked

    def test_real_node_retirement_exits_its_exact_process_without_marking_crash(self):
        record, process, tracked = self.start_node()
        self.pool.retire(record)
        self.wait_until(lambda: not tracked.is_running())
        self.assertIsNone(record.process)
        self.assertFalse(record.crashed)
        self.assertIn(record, self.released)

    def test_real_node_crash_sets_flag_and_start_resets_it(self):
        record, process, tracked = self.start_node()
        self.pool.write(record, {'type': 'crash'})
        self.wait_until(lambda: record.process is None)
        self.assertFalse(tracked.is_running())
        self.assertTrue(record.crashed)
        # start_node's crashed=True record and ready assertion cover the start reset.

    def test_close_releases_processless_records_and_kills_stubborn_exact_process(self):
        record, process, tracked = self.start_node('stubborn')
        cold = self.record('render-only')
        self.pool.touch(cold)
        self.pool.close()
        self.assertFalse(tracked.is_running())
        self.assertIsNone(record.process)
        self.assertIn(cold, self.released)
        self.assertFalse(record.crashed)
        count = len(self.released)
        self.pool.close()
        self.assertEqual(len(self.released), count)

    @unittest.skipUnless(os.name == 'nt', 'Windows native process HANDLE cleanup')
    def test_windows_cached_and_retiring_kernels_exit_on_app_close(self):
        cached, _, cached_probe = self.start_node()
        retiring, retiring_process, retiring_probe = self.start_node()
        stubborn, _, stubborn_probe = self.start_node('stubborn')
        self.pool.retire(retiring)
        self.assertIn(retiring_process, self.pool.retiring)
        self.pool.close()
        for record, probe in ((cached, cached_probe), (retiring, retiring_probe), (stubborn, stubborn_probe)):
            with self.subTest(session=record.key):
                self.assertFalse(probe.is_running())
                self.assertIsNone(record.process)
                self.assertIn(record, self.released)


if __name__ == '__main__':
    unittest.main()
