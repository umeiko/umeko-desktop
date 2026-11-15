"""Explicit owner selection, confirmation, isolation and uncertain-result recovery."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PySide6.QtCore import QCoreApplication
from app.desktop_plugins import DesktopPlugins
from app.pi_sessions import SessionState
from tests.test_desktop_plugins import Host


class PetTimerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.h=Host(Path(self.tmp.name));self.h.gateway=SimpleNamespace(models=lambda:[{'id':'fixture-model'}])
        self.h._pool.retire=Mock();self.h._command_pi=Mock(return_value=True)
        self.h._sessions=[];self.h._pool.records={}
        self.h._pool.touch=lambda r:self.h._pool.records.__setitem__(r.key,r)
        self.m=DesktopPlugins(self.h);self.addCleanup(self.m.close)
        self.pet=self.m.pet;self.pet.configure({'visible':True});self.t=self.pet.taskSchedule
        self.a=self.owner('a');self.b=self.owner('b');self.h._view=self.a
        self.h.store.data['projects']=[{'id':'project-a','path':self.a.workspace}]
        self.a.draft='主窗口草稿';self.a.attachments=['untouched']
        self.m.call_for=Mock(return_value='request-one')
        self.open()

    def owner(self,key):
        file=Path(self.tmp.name)/(key+'.jsonl');file.write_text('{}')
        r=SessionState(id=key,file=str(file),title=key,workspace=self.h._view.workspace)
        self.h._pool.touch(r);self.h._sessions.append({'id':key,'file':r.file,'title':key,'workspace':r.workspace})
        return r

    def open(self,text='/定时任务 检查构建'):
        self.assertTrue(self.t.openCommand(text,self.pet.assistantStatus['id'])['ok'])

    def ready(self,owner='b'):
        self.t.selectOwner(owner)
        for k,v in {'name':'检查','target':'main','first_date':'2035-01-02','local_time':'09:30','zone':'Asia/Shanghai'}.items():self.t.setField(k,v)
        self.t.review();self.assertTrue(self.t.preview,self.t.error)

    def test_missing_owner_and_fields_never_create_or_adopt_view(self):
        self.t.review();self.t.confirm();self.assertIn('显式选择',self.t.error)
        self.t.selectOwner('b');self.t.review();self.assertIn('名称',self.t.error)
        self.t.setField('name','检查');self.t.review();self.assertIn('执行对象',self.t.error)
        self.t.setField('target','main');self.t.review();self.assertIn('日期',self.t.error)
        self.m.call_for.assert_not_called();self.h._command_pi.assert_not_called()

    def test_confirm_once_explicit_source_main_unchanged(self):
        self.ready();self.m.call_for.assert_not_called()
        self.t.confirm();self.t.confirm()
        self.m.call_for.assert_called_once()
        args=self.m.call_for.call_args
        self.assertEqual(args.args[:2],('scheduled-tasks','save'))
        self.assertEqual(args.kwargs['session']['id'],'b')
        self.assertIs(self.h._view,self.a);self.assertEqual(self.a.draft,'主窗口草稿');self.assertEqual(self.a.attachments,['untouched'])
        self.t.response('request-one',{'ok':True,'result':{'task_id':'test-id'}})
        self.t.confirm();self.assertEqual(self.m.call_for.call_count,1)
        self.assertIn('不是执行完成',self.t.state['outcome'])

    def test_owner_workspace_change_rejects_and_preserves_message(self):
        self.ready();self.b.workspace='changed';self.t.confirm()
        self.m.call_for.assert_not_called();self.assertIn('目录已变化',self.t.error)
        self.assertEqual(self.t.draft()['message'],'检查构建')

    def test_project_definition_path_change_rejects_old_directory(self):
        self.ready();self.h.store.data['projects'][0]['path']='new-path'
        self.t.confirm();self.m.call_for.assert_not_called()
        self.assertEqual(self.t.draft()['message'],'检查构建')

    def test_permission_loss_binding_loss_and_deleted_owner_rejected(self):
        self.ready();self.m.settings.setdefault('enabled',{})['scheduled-tasks']=False
        self.t.confirm();self.m.call_for.assert_not_called()
        self.m.settings['enabled']['scheduled-tasks']=True
        self.t.binding_id='stale';self.t.confirm();self.m.call_for.assert_not_called()
        self.t.binding_id=self.pet.assistantStatus['id'];Path(self.b.file).unlink()
        self.t.confirm();self.m.call_for.assert_not_called()

    def test_global_archived_and_unpersisted_cannot_own(self):
        self.b.global_agent='global';self.h.store.data['sessionMeta']={'a':{'archived':True}}
        self.assertEqual(self.t.rows(),[]);self.t.selectOwner('b');self.assertFalse(self.t.owner)

    def test_isolated_drafts_restore_with_notice_and_no_replay(self):
        self.ready();self.t.setField('message','旧指令');self.t.close()
        self.open('/定时任务 新指令');self.assertFalse(self.t.owner)
        self.t.selectOwner('b');self.assertEqual(self.t.draft()['message'],'旧指令');self.assertIn('新输入未替换',self.t.notice)
        self.t.selectOwner('a');self.assertEqual(self.t.draft()['message'],'新指令')
        self.t.selectOwner('b');self.assertEqual(self.t.draft()['message'],'旧指令')
        self.t.close_service();saved=json.loads(self.t.path.read_text());self.assertEqual(saved['a']['message'],'新指令')
        self.m.call_for.assert_not_called()

    def test_uncertain_create_persists_before_dispatch_and_never_replays(self):
        self.ready();self.t.confirm();self.t.close_service()
        self.assertIn('待核对',json.loads(self.t.path.read_text())['b']['outcome'])
        from app.pet_timer import PetTimer
        recovered=PetTimer(self.pet)
        recovered.openCommand('/定时任务 新指令',self.pet.assistantStatus['id']);recovered.selectOwner('b')
        recovered.review();recovered.confirm();self.assertEqual(self.m.call_for.call_count,1)
        recovered.close_service();recovered.deleteLater()

    def test_unwritable_marker_blocks_dispatch(self):
        self.ready()
        with patch.object(Path,'write_text',side_effect=OSError('full')):self.t.confirm()
        self.m.call_for.assert_not_called();self.assertIn('无法保存',self.t.error)

    def test_daily_is_not_silently_converted_and_interval_minimum(self):
        self.ready();self.t.setField('frequency','daily');self.t.review();self.assertIsNone(self.t.preview)
        self.t.setField('frequency','interval');self.t.setField('interval_value','0.1');self.t.review();self.assertIsNone(self.t.preview)

if __name__=='__main__':unittest.main()
