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
        for k,v in {'frequency':'once','name':'检查','target':'main','first_date':'2035-01-02','local_time':'09:30','zone':'Asia/Shanghai'}.items():self.t.setField(k,v)
        self.t.review();self.assertTrue(self.t.preview,self.t.error)

    def test_missing_owner_and_fields_never_create_or_adopt_view(self):
        self.t.review();self.t.confirm();self.assertIn('显式选择',self.t.error)
        self.t.selectOwner('b');self.t.review();self.assertIn('名称',self.t.error)
        self.t.setField('name','检查');self.t.review();self.assertIn('执行对象',self.t.error)
        self.t.setField('target','main');self.t.setField('frequency','once');self.t.review();self.assertIn('日期',self.t.error)
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

    def test_inline_questions_skip_filled_message_and_do_not_navigate(self):
        from PySide6.QtTest import QSignalSpy
        restored=QSignalSpy(self.pet.restoreRequested)
        self.open('/定时任务 检查构建')
        self.assertEqual(self.t.state['question']['key'],'owner')
        for answer,step in [('b','name'),('构建检查','target'),('main','frequency'),('once','first_date'),('2035-01-02','local_time'),('09:30','review')]:
            self.assertTrue(self.t.answer(answer)['ok'],self.t.error)
            self.assertEqual(self.t.state['question']['key'],step)
        self.assertTrue(self.t.preview)
        self.assertEqual(restored.count(),0)
        self.m.call_for.assert_not_called()
        self.t.confirm();self.t.confirm();self.m.call_for.assert_called_once()

    def test_inline_validation_cancellation_and_resume(self):
        self.t.answer('b');self.t.answer('任务');self.t.answer('main');self.t.answer('once')
        self.assertFalse(self.t.answer('tomorrow-ish')['ok'])
        self.assertEqual(self.t.state['question']['key'],'first_date')
        self.t.answer('2035-01-02')
        self.assertFalse(self.t.answer('25:99')['ok'])
        self.assertEqual(self.t.state['question']['key'],'local_time')
        self.assertTrue(self.t.answer('/取消')['closed'])
        self.assertFalse(self.t.opened)
        self.m.call_for.assert_not_called()
        self.open();self.t.answer('b')
        self.assertEqual(self.t.state['question']['key'],'local_time')
        self.t.answer('09:30');self.assertTrue(self.t.preview)
        self.t.editStep('name');self.t.answer('改名')
        self.assertEqual(self.t.preview['args']['name'],'改名')
        self.t.editStep('name');self.t.setAnswer('尚未确认的新名');self.t.close()
        self.open();self.t.answer('b')
        self.assertEqual(self.t.state['question']['key'],'name')
        self.assertEqual(self.t.state['answer'],'尚未确认的新名')

    def test_inline_interval_and_unknown_outcome_no_replay(self):
        for answer in ['b','任务','main','interval']:self.assertTrue(self.t.answer(answer)['ok'])
        self.assertFalse(self.t.answer('0.1')['ok'])
        self.assertFalse(self.t.answer('NaN')['ok'])
        self.assertTrue(self.t.answer('10')['ok'])
        self.assertEqual(self.t.preview['args']['schedule']['interval_unit'],'minutes')
        self.t.confirm();self.t.response('request-one',{'ok':False,'error':'timeout'})
        self.assertEqual(self.t.state['question']['key'],'outcome')
        self.assertFalse(self.t.answer('10')['ok']);self.t.confirm()
        self.assertEqual(self.m.call_for.call_count,1)
        self.t.acknowledgeNotCreated()
        self.assertTrue(self.t.preview)
        self.assertEqual(self.m.call_for.call_count,1)

    def test_prefilled_fields_skip_questions_and_normalize(self):
        self.open('/定时任务 名称：检查；指令：检查构建；时间：2035-1-2 9:30；时区：Asia/Shanghai')
        self.t.answer('b');self.assertEqual(self.t.state['question']['key'],'target')
        self.t.answer('main');self.assertTrue(self.t.preview,self.t.error)
        self.assertEqual(self.t.preview['args']['schedule']['local_time'],'09:30')
        self.m.call_for.assert_not_called()

    def test_daily_request_prompts_for_supported_plan_without_guess(self):
        self.open('/定时任务 每天 9 点检查构建');self.t.answer('b');self.t.answer('检查');self.t.answer('main')
        self.assertEqual(self.t.state['question']['key'],'frequency')
        self.assertEqual(self.t.draft()['local_time'],'09:00');self.assertEqual(self.t.draft()['message'],'检查构建')
        self.assertIn('不会自动改成',self.t.notice)
        self.assertFalse(self.t.preview);self.m.call_for.assert_not_called()
        self.t.answer('once');self.t.answer('2035-1-2')
        self.assertTrue(self.t.preview,self.t.error)
        self.assertEqual(self.t.preview['args']['schedule']['first_date'],'2035-01-02')

    def test_schedule_phrase_answer_skips_interval_amount(self):
        self.t.answer('b');self.t.answer('任务');self.t.answer('main')
        self.t.answer('每隔10分钟');self.assertTrue(self.t.preview,self.t.error)
        self.assertEqual(self.t.preview['args']['schedule']['interval_value'],'10')

    def test_new_parsed_input_does_not_overwrite_partial_draft(self):
        self.open('/定时任务');self.t.selectOwner('b')
        self.t.setField('name','已确认名称');self.t.setField('first_date','2036-01-02');self.t.close()
        self.open('/定时任务 名称：新名称；时间：2035-01-02 09:30；指令：新指令');self.t.selectOwner('b')
        self.assertEqual(self.t.draft()['name'],'已确认名称')
        self.assertEqual(self.t.draft()['first_date'],'2036-01-02')
        self.assertEqual(self.t.draft()['message'],'')
        self.assertIn('新输入未替换',self.t.notice)

    def test_direct_project_owner_selection_restores_complete_review(self):
        self.ready('b');self.t.close()
        self.open('/定时任务');self.t.selectOwner('b')
        self.assertEqual(self.t.state['question']['key'],'review')
        self.assertTrue(self.t.preview)
        self.m.call_for.assert_not_called()

    def test_frequency_answer_with_constraints_is_rejected_without_mutation(self):
        self.t.answer('b');self.t.answer('任务');self.t.answer('main')
        before=dict(self.t.draft())
        result=self.t.answer('每隔2小时；但不要修改代码')
        self.assertFalse(result['ok']);self.assertIn('未应用',self.t.error)
        self.assertEqual(self.t.draft(),before)
        self.assertEqual(self.t.state['question']['key'],'frequency')
        self.m.call_for.assert_not_called()

    def test_unsupported_zone_suffix_requires_time_and_zone_in_wizard(self):
        self.open('/定时任务 2035-01-02 09:30+08:00 检查');self.t.answer('b')
        self.assertEqual(self.t.draft()['zone'],'')
        self.assertEqual(self.t.draft()['local_time'],'')
        self.assertEqual(self.t.draft()['frequency'],'')
        self.assertFalse(self.t.preview);self.m.call_for.assert_not_called()

if __name__=='__main__':unittest.main()
