"""Real off-thread lifecycle operations in disposable application profiles."""
import json
import os
import tempfile
import time
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QCoreApplication, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from app.controller import Controller
from app.storage import Store

_APP = None
ROOT = Path(__file__).resolve().parents[1]

def wait(predicate, seconds=15):
    global _APP
    app = QCoreApplication.instance()
    if app is None:
        _APP = app = QCoreApplication([])
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents(); QTest.qWait(5)
        if predicate(): return
    raise AssertionError('Session lifecycle did not finish')

def history(identifier, workspace, messages=1):
    stamp = '2026-11-12T12:00:00Z'
    entries = [{'type': 'session', 'version': 3, 'id': identifier, 'timestamp': stamp, 'cwd': str(workspace)}]
    for i in range(messages):
        entries.append({'type': 'message', 'id': 'm'+str(i), 'parentId': 'm'+str(i-1) if i else None,
            'timestamp': stamp, 'message': {'role': 'user', 'content': 'private '+('x'*2048), 'timestamp': i}})
    return ''.join(json.dumps(entry)+'\n' for entry in entries)

class SessionFilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_preview_channel import qt_application
        cls.app = qt_application()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name);self.profile = self.root/'profile';self.workspace = self.root/'source-project';self.workspace.mkdir()
        env=patch.dict(os.environ, {'UMEKO_DATA_DIR': str(self.profile)});env.start();self.addCleanup(env.stop)
        bundle=patch('app.provider_plugins.BundledProviders.sync', return_value=[]);bundle.start();self.addCleanup(bundle.stop)
        self.b=Controller(ROOT);self.addCleanup(self.b.close)
        self.files=self.b.sessionFiles
        self.project=self.b._ensure_project(str(self.workspace), reopen=True)

    def session(self, identifier, workspace=None):
        path=self.profile/'pi/sessions'/(identifier+'.jsonl');path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(history(identifier, workspace or self.workspace), encoding='utf-8')
        row={'id':identifier,'title':identifier,'file':str(path),'workspace':str(workspace or self.workspace)}
        self.b._sessions.append(row);return row

    def finished(self):
        wait(lambda:not self.files.busy)

    def test_project_delete_erases_archived_and_unindexed_sessions_and_keeps_source_files(self):
        a=self.session('first');b=self.session('archived');self.b.store.data['sessionMeta']['archived']={'archived':True,'dangerousAllowed':True}
        hidden=self.profile/'pi/sessions/unindexed.jsonl';hidden.write_text(history('unindexed',self.workspace))
        images=Path(a['file']+'.images');images.mkdir();(images/'private.png').write_bytes(b'private')
        child=Path(a['file'][:-6])/'tasks/child.jsonl';child.parent.mkdir(parents=True);child.write_text(history('child',self.workspace))
        source=self.workspace/'keep.txt';source.write_text('keep')
        self.b.store.save();self.b.store.save_sessions(self.b._sessions)
        self.b.removeProject(self.project['id']);self.finished()
        self.assertFalse(self.files.failure,self.files.failure)
        self.assertFalse(self.b._sessions);self.assertNotIn(self.project,self.b.store.data['projects'])
        for path in [Path(a['file']),Path(b['file']),hidden,images,child]:self.assertFalse(path.exists(),path)
        self.assertEqual(source.read_text(),'keep');self.assertEqual(Store(self.profile).data['sessionMeta'],{})
        self.assertEqual(Store(self.profile).load_sessions(),[])
        self.b._merge_native_sessions([a,b]);self.assertEqual(self.b._sessions,[],'A stale discovery result resurrected deleted history')

    def test_running_subagent_blocks_whole_project_before_any_file_is_erased(self):
        a=self.session('first');b=self.session('second')
        live=self.b._new_view(str(self.workspace));live.id=b['id'];live.subagents_active=True;self.b._pool.touch(live)
        self.b.removeProject(self.project['id'])
        self.assertFalse(self.files.busy);self.assertEqual(len(self.b._sessions),2)
        self.assertTrue(Path(a['file']).exists());self.assertTrue(Path(b['file']).exists())
        live.subagents_active=False

    def test_failed_deletion_keeps_the_project_and_failed_session_reachable(self):
        row=self.session('external');external=self.workspace/'external.jsonl';external.write_text('user source file');row['file']=str(external)
        self.b.removeProject(self.project['id']);self.finished()
        self.assertTrue(self.files.failure);self.assertIn(row,self.b._sessions)
        self.assertIn(self.project,self.b.store.data['projects']);self.assertEqual(external.read_text(),'user source file')

    def test_archiving_a_project_hides_its_entry_and_restoring_reveals_it(self):
        self.session('chat');self.b.archiveProject(self.project['id'],True)
        self.assertFalse(self.b.projectRows)
        self.b.toggleArchived();self.assertTrue(any(row['kind']=='project' for row in self.b.projectRows))
        self.b.archiveProject(self.project['id'],False);self.b.toggleArchived()
        self.assertTrue(any(row['id']=='chat' for row in self.b.projectRows));self.assertTrue((self.profile/'pi/sessions/chat.jsonl').exists())

    def test_legacy_hidden_chats_are_discoverable_in_global_archive_and_can_be_restored(self):
        self.session('old-hidden');self.b.store.data['projects'].clear();self.b.store.data['removedProjects']=[self.project['id']]
        self.assertEqual(self.b.projectRows,[])
        self.b.toggleArchived();self.assertTrue(next(row for row in self.b.projectRows if row['kind']=='session')['archived'])
        self.b.archiveSession('old-hidden',False);self.b.toggleArchived()
        self.assertTrue(any(row['id']=='old-hidden' for row in self.b.projectRows));self.assertNotIn(self.project['id'],self.b.store.data['removedProjects'])

    def test_dropped_jsonl_uses_captured_target_and_retains_original_file(self):
        source=self.root/'import.jsonl';source.write_text(history('original',self.root/'untrusted-cwd'))
        raw=json.dumps([QUrl.fromLocalFile(str(source)).toString()])
        self.b.dropProjects(raw,self.project['id']);self.b.store.data['workspace']='';self.finished()
        self.assertFalse(self.files.failure,self.files.failure)
        imported=next(row for row in self.b._sessions if row['title'].startswith('private'))
        self.assertEqual(imported['workspace'],str(self.workspace));self.assertNotEqual(imported['id'],'original')
        self.assertTrue(Path(imported['file']).is_relative_to(self.profile/'pi/sessions'));self.assertTrue(source.exists())

    def test_broken_drop_is_reported_without_adding_any_session(self):
        source=self.root/'broken.jsonl';source.write_text(history('original',self.workspace)+'{"type":')
        self.b.dropProjects(json.dumps([QUrl.fromLocalFile(str(source)).toString()]),self.project['id']);self.finished()
        self.assertTrue(self.files.failure);self.assertEqual(self.b._sessions,[])
        self.assertEqual(list((self.profile/'pi/sessions').iterdir()),[])

    def test_large_import_keeps_gui_event_processing_alive(self):
        source=self.root/'large.jsonl';source.write_text(history('large',self.workspace,messages=3000))
        ticks=[];timer=QTimer();timer.setInterval(5);timer.timeout.connect(lambda:ticks.append(time.monotonic()));timer.start()
        started=time.monotonic();self.files.importFiles(json.dumps([QUrl.fromLocalFile(str(source)).toString()]),self.project['id'])
        elapsed=time.monotonic()-started;self.finished();timer.stop()
        self.assertLess(elapsed,.1);self.assertGreater(len(ticks),3)
        self.assertFalse(self.files.failure,self.files.failure)
        gaps=[b-a for a,b in zip(ticks,ticks[1:])];self.assertLess(max(gaps,default=0),.25)
        print('IMPORT_RESPONSIVENESS',{'bytes':source.stat().st_size,'dispatchMs':round(elapsed*1000,2),'ticks':len(ticks),'maxGapMs':round(max(gaps,default=0)*1000,2)})

def load_tests(loader, tests, pattern):
    if __name__ == '__main__': return tests
    from tests.test_preview_channel import isolated_test_module
    class Isolated(unittest.TestCase):
        def runTest(self): isolated_test_module(self, Path(__file__))
    return unittest.TestSuite([Isolated()])

if __name__=='__main__':unittest.main()
