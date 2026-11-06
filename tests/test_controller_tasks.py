import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtTest import QTest
from app.controller_tasks import TaskRecords


class Host(QObject):
    toast = Signal(str)


class TaskUpdatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_live_events_refresh_in_bounded_batches_and_finish_flushes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            host = Host()
            host.store = SimpleNamespace(directory=root, data={'workspace':str(root)})
            record = SimpleNamespace(workspace=str(root), busy=False, approval=None,
                global_agent='', prepared_task='', task_attempt=0, task_record_error=False,
                id='fixture', file='', cancelled=False, failed=False, messages=[])
            host._view = record
            ledger = TaskRecords(host)
            changes = []
            ledger.changed.connect(lambda: changes.append(True))
            try:
                task = ledger.create('Produce a report', 'Only fixture files')
                self.assertTrue(ledger.prepare(task))
                self.assertTrue(ledger.start(record, []))
                changes.clear()
                for index in range(12):
                    ledger.observe(record, {'type':'tool', 'id':str(index), 'name':'read', 'state':'done'})
                self.assertEqual(changes, [])
                QTest.qWait(250)
                self.assertEqual(len(changes), 1)
                self.assertEqual(len(ledger.store.details(task, record.task_attempt)['steps']), 12)
                ledger.observe(record, {'type':'native_entry', 'entryId':'reply', 'role':'assistant'})
                ledger.end_turn(record, False)
                self.assertEqual(len(changes), 2)
                QTest.qWait(250)
                self.assertEqual(len(changes), 2)
                self.assertEqual(ledger.store.tasks()[0]['state'], 'finished')
            finally:
                ledger.close()
