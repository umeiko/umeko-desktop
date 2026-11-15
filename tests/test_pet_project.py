"""Explicit native record dispatch and recovery without main composer mutation."""
import unittest
from unittest.mock import Mock,patch
from pathlib import Path
from tests import test_pet_timer as fixtures

class PetProjectTests(unittest.TestCase):
    setUpClass=classmethod(lambda cls:fixtures.PetTimerTests.setUpClass())
    owner=fixtures.PetTimerTests.owner
    open=fixtures.PetTimerTests.open
    def setUp(self):
        fixtures.PetTimerTests.setUp(self)
        self.p=self.pet.projectEntry;self.h.openSession=Mock();self.h._write_pi=Mock()
        self.p.openCommand('/项目 帮我检查构建',self.pet.assistantStatus['id'])

    def test_target_drafts_conflict_cancel_and_same_target_command(self):
        self.p.select('b');self.p.setBody('B 草稿')
        self.p.openCommand('/项目',self.pet.assistantStatus['id']);self.p.select('a');self.p.setBody('A 草稿')
        self.p.openCommand('/项目 新正文',self.pet.assistantStatus['id'])
        self.assertFalse(self.p.select('b')['ok']);self.assertEqual(self.p.selected,'a')
        self.assertEqual(self.p.drafts['b'],'B 草稿');self.assertEqual(self.p.body,'A 草稿')
        self.p.close();self.assertEqual(self.p.drafts['a'],'A 草稿')
        self.p.openCommand('/项目',self.pet.assistantStatus['id']);self.assertEqual(self.p.select('b')['text'],'B 草稿')
        self.p.setBody('/项目 保留正文');self.p.openCommand('/项目 保留正文',self.pet.assistantStatus['id'])
        self.assertEqual(self.p.select('b')['text'],'保留正文')
        self.p.setBody('/项目');self.p.openCommand('/项目',self.pet.assistantStatus['id'])
        self.assertEqual(self.p.select('b')['text'],'')

    def test_default_mode_cannot_overwrite_previously_selected_project(self):
        self.p.select('a');self.p.setBody('A 原有桌宠草稿')
        self.p.leaveProject()
        self.assertFalse(self.p.selected);self.assertIsNone(self.p.captured)
        self.p.openCommand('/项目 新正文',self.pet.assistantStatus['id'])
        self.assertFalse(self.p.select('a')['ok'])
        self.assertEqual(self.p.drafts['a'],'A 原有桌宠草稿')
        self.assertEqual(self.p.incoming,'新正文');self.assertFalse(self.p.selected)
        self.p.openCommand('/项目',self.pet.assistantStatus['id'])
        self.assertEqual(self.p.select('a')['text'],'A 原有桌宠草稿')
        self.assertEqual(self.a.draft,'主窗口草稿')

    def test_returned_project_draft_survives_submission_save_failure(self):
        self.p.select('a');self.p.setBody('A 待发送正文');self.p.leaveProject()
        self.p.openCommand('/项目',self.pet.assistantStatus['id']);self.p.select('a')
        with patch.object(Path,'write_text',side_effect=OSError('disk full')):
            result=self.p.submitText(self.p.body,self.pet.assistantStatus['id'])
        self.assertFalse(result['ok']);self.assertIn('无法保存',result['error'])
        self.assertEqual(self.p.body,'A 待发送正文');self.assertEqual(self.p.drafts['a'],'A 待发送正文')
        self.assertEqual(self.a.draft,'主窗口草稿');self.assertEqual(self.a.attachments,['untouched'])
        self.h._command_pi.assert_not_called();self.h._write_pi.assert_not_called()

    def test_explicit_background_send_no_main_or_target_draft_changes(self):
        self.b.draft='项目自己的草稿';self.b.attachments=['project-attachment']
        self.p.send();self.h._command_pi.assert_not_called()
        self.p.select('b');self.p.send();self.p.send()
        self.h._command_pi.assert_called_once_with('prompt',record=self.b,text='帮我检查构建',images=[])
        self.assertIs(self.h._view,self.a);self.assertEqual(self.a.draft,'主窗口草稿');self.assertEqual(self.a.attachments,['untouched'])
        self.assertEqual(self.b.draft,'项目自己的草稿');self.assertEqual(self.b.attachments,['project-attachment'])
        self.h.openSession.assert_not_called()

    def test_native_follow_up_queue_and_receipt(self):
        self.b.phase='running';self.b.ready=True;self.b.process=object()
        self.p.select('b');self.p.send()
        self.h._command_pi.assert_not_called()
        self.h._write_pi.assert_called_once_with({'type':'follow-up','text':'帮我检查构建','images':[]},self.b)
        self.h._pool.event.emit(self.b,{'type':'queue','items':[{'text':'帮我检查构建','mode':'followUp'}]})
        self.assertIn('已进入原生队列',self.p.submission['status'])
        self.h._pool.event.emit(self.a,{'type':'queue_returned'});self.assertIn('已进入原生队列',self.p.submission['status'])

    def test_path_change_and_cancel_preserve_body(self):
        self.p.select('b');self.b.workspace='changed';self.p.send()
        self.h._command_pi.assert_not_called();self.p.close();self.assertEqual(self.p.body,'帮我检查构建')

    def test_approval_loading_and_attempt_block_without_loss(self):
        self.p.select('b')
        for attr,value in [('approval',{'id':'approval'}),('phase','loading'),('prepared_task','attempt')]:
            before=getattr(self.b,attr);setattr(self.b,attr,value);self.p.send();setattr(self.b,attr,before)
            self.h._command_pi.assert_not_called();self.assertFalse(self.p.submission)
        self.assertEqual(self.p.body,'帮我检查构建')

    def test_restart_does_not_replay_and_requires_explicit_acknowledgement(self):
        self.p.select('b');self.p.send()
        from app.pet_project import PetProject
        restored=PetProject(self.pet)
        restored.openCommand('/项目 帮我检查构建',self.pet.assistantStatus['id']);restored.select('b');restored.send()
        self.assertEqual(self.h._command_pi.call_count,1)
        restored.acknowledge();self.assertEqual(self.h._command_pi.call_count,1)
        restored.close()

    def test_unloaded_target_restores_its_permissions_without_using_view(self):
        self.h._pool.records.pop(self.b.key)
        self.h.store.data['sessionMeta']={'b':{'blockedTools':['bash'],'skillModes':{'/skill':False},'extensionModes':{'/extension':'disabled'},'piCapabilities':{'tools':{'bash':False}}}}
        self.p.select('b');self.p.send()
        target=self.h._command_pi.call_args.kwargs['record']
        self.assertEqual(target.id,'b');self.assertEqual(target.blocked_tools,['bash'])
        self.assertEqual(target.skill_modes,{'/skill':False});self.assertEqual(target.extension_modes,{'/extension':'disabled'})
        self.assertIs(self.h._view,self.a)

    def test_hidden_dialog_cannot_send(self):
        self.p.select('b');self.p.close();self.p.send();self.h._command_pi.assert_not_called()

    def test_save_failure_prevents_send(self):
        self.p.select('b')
        with patch.object(Path,'write_text',side_effect=OSError('full')):self.p.send()
        self.h._command_pi.assert_not_called();self.assertIn('无法保存',self.p.error)

    def test_start_failure_keeps_drafts_and_uncertain_marker(self):
        self.p.select('b');self.h._command_pi.return_value=False
        old=list(self.b.messages);self.p.send()
        self.assertEqual(self.b.messages,old);self.assertTrue(self.p.submission);self.assertEqual(self.p.body,'帮我检查构建')
