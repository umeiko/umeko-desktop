"""Session retention and shutdown using local state and a model-free Node fixture."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from PySide6.QtCore import QCoreApplication, QObject, QProcess

from app.pi_runtime import node_executable
from app.pi_sessions import PiSessionPool, SessionState


class CachedKernel(QObject):
    """An owned QObject kernel stand-in for state/call tests without Node startup."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.alive = True
        self.writes = []

    def write(self, payload):
        self.writes.append(payload)
        self.alive = False
        return len(payload)

    def state(self):
        return QProcess.Running if self.alive else QProcess.NotRunning

    def kill(self):
        self.alive = False

    def waitForFinished(self, _timeout):
        return not self.alive


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
        self.retired = []
        retire = self.pool.retire
        def observe_retire(record):
            self.retired.append(record)
            return retire(record)
        self.pool.retire = Mock(side_effect=observe_retire)
        self.addCleanup(self.pool.close)

    def record(self, name, **values):
        return SessionState(id=name, file=name + '.jsonl', messages=[{'text': name}], **values)

    def kernel_record(self, name, **values):
        return self.record(name, process=CachedKernel(self.pool), **values)

    def cached(self):
        return [record.id for record in self.pool.records.values()
                if record.process is not None]

    def test_capacity_zero_one_three_counts_current_idle_and_preserves_current(self):
        for capacity, expected in ((0, ['d']), (1, ['d']), (3, ['b', 'c', 'd'])):
            with self.subTest(capacity=capacity):
                self.pool.limit = capacity
                self.pool.records.clear()
                for name in 'abcd':
                    self.pool.touch(self.kernel_record(name), current=True)
                self.assertEqual(self.cached(), expected)
                self.assertEqual(self.pool.current.id, 'd')

    def test_empty_project_drafts_do_not_take_cache_slots(self):
        self.pool.limit = 1
        previous = self.kernel_record('previous')
        self.pool.touch(previous, current=True)
        draft = SessionState(draft='keep this', workspace='project')
        self.pool.touch(draft, current=True)
        self.assertEqual(self.cached(), ['previous'])
        self.assertTrue(previous.loaded)
        self.assertEqual(draft.draft, 'keep this')

    def test_lru_touch_updates_order_and_evicted_placeholder_is_not_recounted(self):
        self.pool.limit = 3
        a, b, c, d = [self.kernel_record(name) for name in 'abcd']
        for record in (a, b, c):
            self.pool.touch(record, current=True)
        self.pool.touch(a, current=True, dirty=False)
        self.pool.touch(d, current=True)
        self.assertEqual(self.cached(), ['c', 'a', 'd'])
        self.assertIsNone(b.process)
        count = len(self.retired)
        self.pool.trim()
        self.assertEqual(len(self.retired), count)
        self.assertEqual(b.messages, [{'text': 'b'}])
        b.process = CachedKernel(self.pool)
        self.pool.touch(b, current=True)
        self.assertEqual(self.cached(), ['a', 'd', 'b'])

    def test_running_loading_operation_approval_and_subagents_are_protected(self):
        self.pool.limit = 0
        current = self.kernel_record('current')
        self.pool.touch(current, current=True)
        records = [self.kernel_record('running', phase='running'), self.kernel_record('loading', phase='loading'),
                   self.kernel_record('operation', operation=True), self.kernel_record('approval', approval={'id': 'question'}),
                   self.kernel_record('subagents', subagents_active=True)]
        for record in records:
            self.pool.touch(record)
        self.assertEqual(self.cached(), ['current'] + [record.id for record in records])
        self.assertFalse(self.retired)

    def test_finished_protected_session_is_evicted_when_over_budget(self):
        self.pool.limit = 1
        current, running = self.kernel_record('current'), self.kernel_record('running', phase='running')
        self.pool.touch(current, current=True)
        self.pool.touch(running)
        running.phase = 'idle'
        self.pool.trim()
        self.assertEqual(self.cached(), ['current'])
        self.assertTrue(running.loaded)
        self.assertEqual(running.messages, [{'text': 'running'}])

    def test_five_saved_histories_survive_kernel_retirement_with_draft_and_viewport(self):
        records = [self.kernel_record(str(index), draft='unsent', scroll_index=12, scroll_y=7, follow_tail=False,
                                      transcript=object(), history=[{'role': 'user'}], tree=[{'id': 'entry'}])
                   for index in range(5)]
        bodies = [(record.messages, record.history, record.tree, record.transcript) for record in records]
        for record in records:
            self.pool.touch(record, current=True)
        self.assertEqual(self.cached(), ['2', '3', '4'])
        self.assertEqual(self.retired, records[:2])
        for record, body in zip(records, bodies):
            self.assertTrue(record.loaded)
            for actual, expected in zip((record.messages, record.history, record.tree, record.transcript), body):
                self.assertIs(actual, expected)
            self.assertEqual((record.draft, record.scroll_index, record.scroll_y, record.follow_tail), ('unsent', 12, 7, False))

    def test_processless_loaded_histories_do_not_take_kernel_slots(self):
        self.pool.limit = 0
        records = [self.record(str(index)) for index in range(5)]
        for record in records:
            self.pool.touch(record, current=True)
        self.assertEqual(self.cached(), [])
        self.assertFalse(self.retired)
        self.assertTrue(all(record.loaded and record.messages for record in records))

    def test_body_budget_drops_oldest_history_after_its_kernel_was_already_evicted(self):
        from app.transcript_index import memory_weight
        records = [self.kernel_record(str(index)) for index in range(5)]
        for record in records:
            self.pool.touch(record, current=True)
        self.assertIsNone(records[0].process)
        self.assertTrue(all(record.loaded for record in records))
        total = sum(record.body_bytes for record in records)
        self.pool.body_limit = total - memory_weight((records[0].messages, records[0].history, records[0].tree, records[0].resources))
        self.pool.trim_bodies()
        self.assertFalse(records[0].loaded)
        self.assertEqual(records[0].messages, [])
        self.assertTrue(all(record.loaded and record.messages for record in records[1:]))
        self.assertEqual(self.cached(), ['2', '3', '4'])

    def test_unsaved_authoritative_messages_survive_eviction_without_repeated_release(self):
        self.pool.limit = 1
        old = SessionState(id='unsaved', messages=[{'text': 'authoritative'}], draft='unsent', process=CachedKernel(self.pool))
        self.pool.touch(old, current=True)
        self.pool.touch(self.kernel_record('new'), current=True)
        self.assertIsNone(old.process)
        self.assertEqual(old.messages, [{'text': 'authoritative'}])
        count = len(self.retired)
        self.pool.trim()
        self.assertEqual(len(self.retired), count)

    def test_memory_budget_keeps_current_and_approval_protected(self):
        self.pool.body_limit = 1
        current = self.record('current')
        self.pool.touch(current, current=True)
        waiting = self.record('waiting', approval={'id': 'question'})
        self.pool.touch(waiting)
        old = self.record('old')
        self.pool.touch(old)
        self.assertEqual(self.cached(), [])
        self.assertFalse(old.loaded)
        self.assertIsNone(old.process)
        self.assertTrue(waiting.loaded)

    def test_invalidation_retires_idle_kernel_and_defers_every_protected_record(self):
        idle = self.kernel_record('idle')
        self.pool.touch(idle, current=True)
        protected = [self.record('running', phase='running'), self.record('waiting', approval={'id': 'confirm'}),
                     self.record('child', subagents_active=True)]
        for record in protected:
            self.pool.touch(record)
        self.pool.invalidate()
        self.assertEqual(self.retired, [idle])
        self.assertIsNone(idle.process)
        self.assertTrue(idle.loaded)
        self.assertEqual(idle.messages, [{'text': 'idle'}])
        self.assertTrue(all(record.stale for record in protected))

    def test_processless_retire_preserves_body_and_clears_intentional_crash_flag(self):
        record = self.record('cold', crashed=True, ready=True, stale=True)
        self.pool.retire(record)
        self.assertEqual(self.retired, [record])
        self.assertFalse(record.crashed)
        self.assertFalse(record.ready)
        self.assertFalse(record.stale)
        self.assertTrue(record.loaded)
        self.assertEqual(record.messages, [{'text': 'cold'}])

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
        self.assertIn(record, self.retired)

    def test_real_node_crash_sets_flag_and_start_resets_it(self):
        record, process, tracked = self.start_node()
        self.pool.write(record, {'type': 'crash'})
        self.wait_until(lambda: record.process is None)
        self.assertFalse(tracked.is_running())
        self.assertTrue(record.crashed)
        # start_node's crashed=True record and ready assertion cover the start reset.

    def test_close_preserves_body_and_kills_stubborn_exact_process(self):
        record, process, tracked = self.start_node('stubborn')
        cold = self.record('body-only')
        self.pool.touch(cold)
        self.pool.close()
        self.assertFalse(tracked.is_running())
        self.assertIsNone(record.process)
        self.assertIsNone(cold.process)
        self.assertTrue(cold.loaded)
        self.assertEqual(cold.messages, [{'text': 'body-only'}])
        self.assertFalse(record.crashed)
        count = len(self.retired)
        self.pool.close()
        self.assertEqual(len(self.retired), count)

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
                self.assertFalse(record.crashed)


if __name__ == '__main__':
    unittest.main()
