"""Real process failures and cancellation must leave the updater usable."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication, QObject, QProcess
from PySide6.QtTest import QTest
from app.update import AppUpdater
from app.pi_runtime import node_executable

APP = QCoreApplication.instance() or QCoreApplication([])

class UpdateTests(unittest.TestCase):
    def setup_updater(self, root):
        host = QObject(); host.root = root
        updater = AppUpdater(host)
        runtime = root / 'runtime'; runtime.mkdir()
        updater.job_file = root / 'job.json'; updater.job = {}
        updater.job_file.write_text('{}')
        return host, updater, runtime / 'update-engine.mjs'

    def wait(self, predicate):
        for _ in range(300):
            QTest.qWait(10)
            if predicate(): return
        self.fail('update process timed out')

    def test_cancel_stops_the_worker_and_removes_partial_download(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); host, updater, script = self.setup_updater(root)
            script.write_text('setInterval(()=>{},1000)')
            updater.run('download')
            self.wait(lambda: updater.process.state() == QProcess.Running)
            updater.cancel()
            self.assertIsNone(updater.process)
            self.assertEqual(updater.state, 'available')
            self.assertFalse(updater.job_file.exists())
            self.assertFalse(root.exists())

    def test_failed_start_can_retry_and_preserves_verified_job(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); host, updater, script = self.setup_updater(root)
            with patch('app.update.node_executable', return_value=str(root/'missing-node')):
                updater.run('download')
                self.wait(lambda: updater.process is None)
            self.assertEqual(updater.state, 'error')
            event = dict(state='ready',message='verified',archive=str(root/'update.zip'),sha256='a'*64)
            script.write_text('process.stdout.write('+json.dumps(json.dumps(event)+'\n')+')')
            updater.run('download')
            self.wait(lambda: updater.process is None)
            self.assertEqual(updater.state, 'ready')
            self.assertEqual(json.loads(updater.job_file.read_text())['sha256'], 'a'*64)

if __name__ == '__main__': unittest.main()
