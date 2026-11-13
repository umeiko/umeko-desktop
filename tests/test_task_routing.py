"""Routing identity, authorization, persistence and cancellation boundaries."""
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QCoreApplication
from app.controller_tasks import TaskRecords
from app.global_agents import GlobalAgents
from app.pi_sessions import SessionState
from app.task_records import TaskStore, SCHEMA
from tests.test_global_agents import Backend, Manager


class RoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.b = Backend(self.temp.name)
        self.b._task_records = TaskRecords(self.b)
        self.cwd = Path(self.temp.name)/'worktree'
        self.cwd.mkdir()
        self.target = self.b._view
        self.target.workspace = str(self.cwd)
        self.target.model = 'test'
        self.g = GlobalAgents(Manager(self.b))
        self.g.start()
        self.agent = self.g.handle('create', {'name':'协调者'})['id']
        self.caller = self.g.ensure(self.agent)
        self.connect()
        self.store = self.b._task_records._storage()

    def tearDown(self):
        self.g.close()
        self.b._task_records.lock.unlock()
        self.temp.cleanup()

    def connect(self, enabled=True, target=None):
        self.g.handle('setBridge', {'id':self.g.identifier(target or self.target),'agentId':self.agent,'enabled':enabled})

    def submit(self, key='request', **fields):
        args = dict(requestKey=key,objective='检查测试',scope='只读检查',cwd=str(self.cwd),
                    coordinator=self.agent,requestedTask='')
        args.update(fields)
        return self.g.handle('submitTask',args)

    def route(self, row, **fields):
        args = dict(routeId=row['id'],decision='new',reason='独立目标',taskId='',targetId=self.g.identifier(self.target))
        args.update(fields)
        return self.g.execute('agent_bus.route',args,self.caller)

    def test_duplicate_input_and_duplicate_model_decision_are_one_work(self):
        row = self.submit()
        self.assertEqual(self.submit(),row)
        self.assertEqual(self.b._command_pi.call_count,1)
        accepted = self.route(row)
        self.assertEqual(self.route(row),accepted)
        self.assertEqual(self.submit()['id'],row['id'])
        self.assertEqual(accepted['execution'],'queued')
        self.assertEqual(len(self.store.tasks()),1)
        self.assertEqual(len(self.g.requests),1)
        self.assertEqual(len(self.g.outbox),1)
        with self.assertRaisesRegex(ValueError,'不同内容'):
            self.submit(objective='别的目标')

    def test_dsh_target_is_rejected_without_creating_a_pi_replacement(self):
        self.target.backend = 'dsh'
        self.assertEqual(self.submit()['status'], 'rejected')
        self.assertFalse(self.g.requests)
        self.assertEqual(self.b._command_pi.call_count, 0)
        self.target.backend = 'pi'
        self.b._sessions.append({'id':'saved-dsh', 'backend':'dsh', 'workspace':str(self.cwd), 'model':'test'})
        with patch.object(self.g, 'record', wraps=self.g.record) as lookup:
            with self.assertRaisesRegex(ValueError, 'Pi'):
                self.g.task_routing.target({'cwd':str(self.cwd), 'coordinator':self.agent}, 'session:saved-dsh')
            lookup.assert_not_called()

    def test_backend_change_before_delivery_blocks_the_old_route(self):
        row = self.submit()
        self.route(row)
        self.target.backend = 'dsh'
        with self.assertRaisesRegex(ValueError, 'Pi'):
            self.g.task_routing.validate(self.g.requests[row['id']])

    def test_intake_and_management_are_only_user_actions(self):
        for method in ('submitTask','stopTaskRoute','leaveTaskMode'):
            with self.assertRaisesRegex(ValueError,'管理仅允许'):
                self.g.handle(method,{},agent=True)
        row = self.submit()
        for operation in ('agent_bus.dispatch','agent_bus.set_connection'):
            with self.assertRaisesRegex(ValueError,'任务协调模式'):
                self.g.execute(operation,{},self.caller)
        self.assertEqual(self.g.execute('agent_bus.routes',{},self.target),{'routes':[]})
        with self.assertRaisesRegex(ValueError,'真实协调者'):
            self.g.execute('agent_bus.route',{'routeId':row['id']},self.target)

    def test_other_coordinator_cannot_decide_or_read_request(self):
        row = self.submit()
        other = self.g.ensure(self.g.handle('create',{'name':'other'})['id'])
        self.assertEqual(self.g.execute('agent_bus.routes',{},other)['routes'],[])
        with self.assertRaisesRegex(ValueError,'真实协调者'):
            self.g.execute('agent_bus.route',{'routeId':row['id']},other)

    def test_explicit_new_and_continue_cannot_be_overruled(self):
        task = self.store.create('original','只读检查',str(self.cwd))
        row = self.submit(requestedTask='new')
        self.assertEqual(self.route(row,decision='continue',taskId=task)['status'],'rejected')
        row = self.submit('existing',requestedTask=task)
        self.assertEqual(self.route(row)['status'],'rejected')
        self.assertFalse(self.g.requests)

    def test_clarification_does_not_create_task_and_user_can_choose_continuation(self):
        row = self.submit()
        self.assertEqual(self.route(row,decision='clarify',reason='新目标还是补充？')['status'],'clarify')
        self.assertFalse(self.store.tasks())
        first = self.route(self.submit('new'))
        second = self.route(self.submit('follow',requestedTask=first['taskId']),decision='continue',taskId=first['taskId'])
        self.assertEqual(first['taskId'],second['taskId'])
        self.assertEqual(len(self.store.tasks()),1)
        self.assertTrue(self.store.running(first['taskId']))

    def test_unknown_directory_connection_session_or_model_never_falls_back(self):
        self.assertEqual(self.submit(cwd='relative')['status'],'rejected')
        self.assertFalse(self.store.tasks())
        self.connect(False)
        self.assertIn('授权',self.submit('disabled')['reason'])
        self.connect()
        row = self.submit('missing')
        self.assertEqual(self.route(row,targetId='session:unknown')['status'],'rejected')
        self.target.model = 'unknown'
        self.assertEqual(self.submit('bad-model')['status'],'rejected')
        self.assertEqual(len(self.g.agents),1)
        self.assertEqual(len(self.b._pool.records),2)

    def test_saved_session_with_missing_history_cannot_be_recreated_as_executor(self):
        self.target.id = 'missing-native'
        self.target.file = str(self.cwd/'absent.jsonl')
        self.connect()
        self.assertEqual(self.submit()['status'],'rejected')
        self.b._command_pi.assert_not_called()

    def test_unauthorized_connection_is_rechecked_after_model_routing(self):
        row = self.submit()
        self.connect(False)
        rejected = self.route(row)
        self.assertEqual(rejected['status'],'rejected')
        self.assertIn('授权',rejected['reason'])
        self.assertFalse(self.store.tasks())

    def test_actual_directory_is_checked_again_immediately_before_delivery(self):
        row = self.route(self.submit())
        other = Path(self.temp.name)/'other'
        other.mkdir()
        self.target.workspace = str(other)
        self.b._command_pi.reset_mock()
        self.g.tick()
        self.b._command_pi.assert_not_called()
        row = self.store.route(row['id'])
        self.assertEqual(row['execution'],'failed')
        self.assertEqual(row['failurePhase'],'delivery')
        self.assertIn('目录',row['result'])

    def test_scope_change_requires_explicit_task_choice_and_stops_only_old_task(self):
        first = self.route(self.submit())
        other = self.route(self.submit('other'))
        ambiguous = self.submit('ambiguous',scope='允许修改测试')
        self.assertEqual(self.route(ambiguous,decision='continue',taskId=first['taskId'])['status'],'clarify')
        new = self.submit('confirmed',requestedTask=first['taskId'],scope='允许修改测试')
        self.assertEqual(self.store.route(first['id'])['execution'],'cancelled')
        self.assertEqual(self.store.route(other['id'])['execution'],'queued')
        self.assertEqual(self.route(new,decision='continue',taskId=first['taskId'])['taskId'],first['taskId'])

    def test_existing_chat_attempt_prevents_scope_update_or_parallel_routing(self):
        task = self.store.create('original','只读检查',str(self.cwd))
        self.store.begin(task,str(self.cwd),'','',[])
        row = self.submit(requestedTask=task)
        self.assertEqual(self.route(row,decision='continue',taskId=task)['status'],'rejected')
        self.assertEqual(self.submit('changed',requestedTask=task,scope='write')['status'],'rejected')

    def test_stop_before_or_after_routing_prevents_replay(self):
        pending = self.submit()
        self.g.handle('stopTaskRoute',{'routeId':pending['id']})
        self.assertEqual(self.route(pending)['status'],'cancelled')
        queued = self.route(self.submit('queued'))
        self.assertFalse(self.store.delete(queued['taskId']))
        self.g.handle('stopTaskRoute',{'routeId':queued['id']})
        self.assertEqual(self.g.requests[queued['id']]['status'],'cancelled')
        self.assertTrue(self.store.delete(queued['taskId']))
        self.assertEqual(self.submit('queued')['execution'],'cancelled')

    def test_two_tasks_two_sessions_keep_results_and_reply_identity_separate(self):
        first = self.route(self.submit())
        cwd = Path(self.temp.name)/'second'
        cwd.mkdir()
        target = SessionState(workspace=str(cwd),model='test')
        self.b._pool.touch(target)
        self.connect(target=target)
        second = self.route(self.submit('second',cwd=str(cwd)),targetId=self.g.identifier(target))
        self.assertNotEqual(first['taskId'],second['taskId'])
        self.g.tick()
        with self.assertRaisesRegex(ValueError,'当前会话'):
            self.g.execute('agent_bus.reply',{'requestId':first['id'],'result':'wrong task'},target)
        self.g.finish(self.g.requests[first['id']],'completed','first')
        self.g.finish(self.g.requests[second['id']],'failed','second')
        self.assertEqual(self.store.routes(task_id=first['taskId'])[0]['result'],'first')
        self.assertEqual(self.store.routes(task_id=second['taskId'])[0]['result'],'second')

    def test_received_is_not_completed_and_foreign_delivery_cannot_advance_it(self):
        row = self.route(self.submit())
        self.g.tick()
        item = next(item for item in self.g.outbox.values() if item['requestId']==row['id'])
        event = {'type':'widget_delivery','id':item['id'],'status':'delivered'}
        self.g.observe(self.caller,event)
        self.assertEqual(self.store.route(row['id'])['execution'],'sending')
        self.g.observe(self.target,event)
        self.assertEqual(self.store.route(row['id'])['execution'],'running')
        self.g.execute('agent_bus.reply',{'requestId':row['id'],'result':'done'},self.target)
        self.assertEqual(self.store.route(row['id'])['execution'],'completed')
        self.assertEqual(item['data']['taskId'],row['taskId'])
        self.assertEqual(item['data']['scope'],'只读检查')

    def test_restart_and_timeout_do_not_reissue_work(self):
        row = self.route(self.submit())
        self.store.recover('应用已重启')
        self.assertEqual(self.submit()['execution'],'interrupted')
        self.assertEqual(self.route(row)['execution'],'interrupted')
        self.g.tick()
        timed = self.route(self.submit('timed'))
        self.g.requests[timed['id']]['deadline'] = 0
        self.g.tick()
        self.assertEqual(self.route(timed)['execution'],'failed')
        self.assertEqual(len(self.store.tasks()),2)

    def test_durable_identity_survives_bus_history_eviction(self):
        row = self.route(self.submit())
        self.g.requests.clear()
        self.g.outbox.clear()
        self.assertEqual(self.submit()['id'],row['id'])
        self.assertEqual(self.route(row)['taskId'],row['taskId'])
        self.assertFalse(self.g.requests)

    def test_full_bus_is_rejected_before_creating_task(self):
        row = self.submit()
        for i in range(4):
            self.g.requests[str(i)] = {'id':str(i),'target':self.g.identifier(self.target),
                'source':'agent:'+self.agent,'created':time.time(),'status':'queued'}
        self.assertEqual(self.route(row)['status'],'rejected')
        self.assertFalse(self.store.tasks())

    def test_task_and_acceptance_roll_back_atomically(self):
        row = self.submit()
        with patch.object(self.store,'_save_route',side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaisesRegex(ValueError,'保存失败'):
                self.route(row)
        self.assertFalse(self.store.tasks())
        self.assertFalse(self.g.requests)

    def test_storage_failures_at_delivery_and_stop_fail_closed(self):
        row = self.route(self.submit())
        self.b._command_pi.reset_mock()
        with patch.object(self.store,'save_route',side_effect=sqlite3.OperationalError('disk full')):
            self.g.tick()
        self.b._command_pi.assert_not_called()
        pending = self.submit('pending')
        with patch.object(self.store,'save_route',side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaisesRegex(ValueError,'保存失败'):
                self.g.handle('stopTaskRoute',{'routeId':pending['id']})
        self.assertEqual(self.route(pending)['status'],'cancelled')

    def test_coordinator_failure_and_user_exit_mode_leave_no_old_dispatch(self):
        row = self.submit()
        self.g.observe(self.caller,{'type':'done'})
        self.assertEqual(self.store.route(row['id'])['status'],'clarify')
        pending = self.submit('pending')
        self.g.handle('leaveTaskMode',{'id':self.agent})
        self.assertEqual(self.route(pending)['status'],'cancelled')
        self.assertFalse(self.g.agents[self.agent]['taskRouter'])

    def test_version_one_and_two_migration_preserve_timeline_values(self):
        for version in (1,2):
            path = Path(self.temp.name)/f'v{version}.sqlite'
            with sqlite3.connect(path) as db:
                db.executescript(SCHEMA+'\nPRAGMA user_version = 1;')
                db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?)',('old','goal','scope',str(self.cwd),'now','now'))
                if version == 2:
                    for statement in ('ALTER TABLE steps ADD COLUMN observed TEXT','ALTER TABLE steps ADD COLUMN updated TEXT','ALTER TABLE files ADD COLUMN observed TEXT'):
                        db.execute(statement)
                    db.execute('PRAGMA user_version = 2')
            migrated = TaskStore(path)
            self.assertEqual(migrated.task('old')['objective'],'goal')
            with migrated.connection() as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],3)
                self.assertIn('observed',[row[1] for row in db.execute('PRAGMA table_info(steps)')])

    def test_snapshot_has_bounded_pages_and_skips_storage_when_unchanged(self):
        self.submit()
        result = self.g.handle('taskRoutes',{})
        with patch.object(self.g.task_routing,'store',side_effect=AssertionError('redundant storage')):
            self.assertEqual(self.g.handle('taskRoutes',{'revision':result['revision']}),{'unchanged':True})
        with self.assertRaisesRegex(ValueError,'页码'):
            self.g.handle('taskRoutes',{'offset':-1})

    def test_routing_and_bus_registry_save_failures_do_not_launch_work(self):
        with patch.object(self.g,'save',return_value=False):
            rejected = self.submit()
        self.assertEqual(rejected['status'],'rejected')
        self.b._command_pi.assert_not_called()
        pending = self.submit('next')
        with patch.object(self.g,'save',return_value=False):
            failed = self.route(pending)
        self.assertEqual(failed['execution'],'failed')
        self.assertFalse(self.g.requests)
        self.assertFalse(self.g.outbox)
        self.assertEqual(self.route(pending)['execution'],'failed')

    def test_history_paging_is_bounded_and_a_new_page_is_not_unchanged(self):
        import uuid
        row = self.submit()
        for i in range(25):
            self.store.save_route({**row,'id':uuid.uuid4().hex,'requestKey':str(i),'status':'clarify'})
        first = self.g.handle('taskRoutes',{})
        self.assertEqual(len(first['routes']),20)
        self.assertTrue(first['hasMore'])
        next_page = self.g.handle('taskRoutes',{'offset':20,'revision':first['revision'],'revisionOffset':0})
        self.assertEqual(len(next_page['routes']),6)
        self.assertFalse(next_page['hasMore'])


if __name__ == '__main__':
    unittest.main()
