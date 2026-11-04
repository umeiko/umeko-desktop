"""Link scanners cannot access Qt owners after virtualized text is destroyed."""
import os
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QObject
from PySide6.QtGui import QGuiApplication, QTextDocument
from PySide6.QtTest import QTest
import shiboken6

from app import text_links


class WorkerQtAccess(BaseException):
    """Stop an unsafe old worker before it can emit through a deleted QObject."""


class QuickDocument(QObject):
    def __init__(self, document, parent):
        super().__init__(parent)
        self.document = document

    def textDocument(self):
        return self.document


class TextLinksLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def wait_for(self, predicate, errors):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.assertFalse(errors, str(errors))
            if predicate(): return
            QTest.qWait(10)
        self.fail('Link scanner did not complete its requested state')

    def guarded_owner(self, text):
        gui_thread = threading.get_ident()
        violations = []
        valid = shiboken6.isValid

        def gui_valid(obj):
            if threading.get_ident() != gui_thread:
                violations.append('worker called shiboken6.isValid')
                raise WorkerQtAccess(violations[-1])
            return valid(obj)

        class GuardedLinks(text_links.TextLinks):
            def __getattribute__(self, name):
                if name in ('resolved', 'changed') and threading.get_ident() != gui_thread:
                    violations.append('worker accessed Qt signal ' + name)
                    raise WorkerQtAccess(violations[-1])
                return super().__getattribute__(name)

        parent = QObject()
        document = QTextDocument(parent)
        document.setPlainText(text)
        quick = QuickDocument(document, parent)
        links = GuardedLinks(parent)
        links.document = quick
        return parent, document, links, gui_thread, violations, gui_valid, valid

    def test_destroyed_parent_discards_a_blocked_scanner_without_worker_qt_access(self):
        parent, document, links, gui_thread, violations, gui_valid, valid = self.guarded_owner('old')
        started, release = threading.Event(), threading.Event()
        workers, cancellations, deliveries, errors = [], [], [], []

        def scan(plain, fragments, workspace, previous, cancelled):
            workers.append(threading.current_thread())
            started.set()
            if not release.wait(5): raise AssertionError('Blocked scanner was not released')
            cancellations.append(cancelled())
            return []

        links.resolved.connect(lambda *args: deliveries.append(threading.get_ident()))
        with patch.object(text_links, 'resolve_spans', side_effect=scan), \
                patch.object(text_links.shiboken6, 'isValid', side_effect=gui_valid), \
                patch.object(threading, 'excepthook', side_effect=lambda args: errors.append(args.exc_value)):
            try:
                links.enabled = True
                self.wait_for(started.is_set, errors)
                shiboken6.delete(parent)
                self.assertFalse(valid(links))
                self.assertFalse(valid(document))
                release.set()
                for worker in workers:
                    worker.join(5)
                    self.assertFalse(worker.is_alive())
                self.assertEqual(cancellations, [True])
                self.assertEqual(deliveries, [])
                self.assertEqual(violations, [])
                self.assertEqual(errors, [])
            finally:
                release.set()
                for worker in workers: worker.join(5)
                if valid(parent): shiboken6.delete(parent)

    def test_stale_scan_cannot_replace_current_links_and_delivery_stays_on_gui_thread(self):
        parent, document, links, gui_thread, violations, gui_valid, valid = self.guarded_owner('old')
        started, release = threading.Event(), threading.Event()
        workers, scans, cancellations, deliveries, errors = [], [], [], [], []

        def scan(plain, fragments, workspace, previous, cancelled):
            workers.append(threading.current_thread())
            scans.append(plain)
            if plain == 'old':
                started.set()
                if not release.wait(5): raise AssertionError('Blocked scanner was not released')
            cancellations.append(cancelled())
            # Return the obsolete result as well: GUI delivery must reject it.
            return [(0, len(plain), {'kind': 'url', 'target': 'https://' + plain + '.invalid', '_source': plain})]

        def delivered(generation, spans):
            deliveries.append((threading.get_ident(), spans[0][2]['target'],
                               links.linkInfo('umeko-conversation:0')))

        links.resolved.connect(delivered)
        with patch.object(text_links, 'resolve_spans', side_effect=scan), \
                patch.object(text_links.shiboken6, 'isValid', side_effect=gui_valid), \
                patch.object(threading, 'excepthook', side_effect=lambda args: errors.append(args.exc_value)):
            try:
                links.enabled = True
                self.wait_for(started.is_set, errors)
                document.setPlainText('new')
                release.set()
                self.wait_for(lambda: links.linkInfo('umeko-conversation:0').get('target') == 'https://new.invalid', errors)
                self.assertEqual(scans, ['old', 'new'])
                self.assertEqual(cancellations, [True, False])
                self.assertEqual([row[0] for row in deliveries], [gui_thread, gui_thread])
                self.assertEqual(deliveries[0][1:], ('https://old.invalid', {}))
                self.assertEqual(deliveries[1][1], 'https://new.invalid')
                self.assertEqual(document.toPlainText(), 'new')
                self.assertFalse(links.pending)
                self.assertEqual(violations, [])
                self.assertEqual(errors, [])
            finally:
                release.set()
                for worker in workers:
                    worker.join(5)
                    self.assertFalse(worker.is_alive())
                if valid(parent): shiboken6.delete(parent)
