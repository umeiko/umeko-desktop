import os, tempfile, unittest, uuid, json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QObject, QCoreApplication
from app.global_agents import GlobalAgents
from app.pi_sessions import SessionState, PiSessionPool

class Backend(QObject):
    def __init__(self,directory):
        super().__init__();self.store=SimpleNamespace(directory=Path(directory),data={'selectedModel':'test'})
        self.characterPacks=[{'id':v,'portrait':v+'.png','name':v} for v in ('yanami','komari','kaju')]
        self.characterStyle={'id':'komari'};self.gateway=SimpleNamespace(models=lambda:[{'id':'test'}]);self._sessions=[]
        self._pool=PiSessionPool(self);self._view=SessionState(workspace='/work/one');self._pool.touch(self._view)
        self._command_pi=Mock(return_value=True)
class Manager(QObject):
    def __init__(self,b):
        super().__init__();self.b=b;self.openPage=Mock(return_value=True);self.bridge=SimpleNamespace(notify=Mock())
class GlobalAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QCoreApplication.instance() or QCoreApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.b=Backend(self.temp.name);self.m=Manager(self.b);self.g=GlobalAgents(self.m);self.g.start()
        self.id=self.g.handle('create',{'name':'协调员'})['id'];self.source=self.g.ensure(self.id)
    def tearDown(self):self.g.close();self.temp.cleanup()
    def dispatch(self):return self.g.execute('agent_bus.dispatch',{'targetId':self.g.identifier(self.b._view),'text':'检查测试'},self.source)
    def enable(self):self.g.handle('setBridge',{'id':self.g.identifier(self.b._view),'agentId':self.id,'enabled':True})
    def create_request(self,key='first',**fields):
        return self.g.execute('agent_bus.create',{'requestKey':key,**fields},self.b._view)
    def creation_status(self,row,caller=None):
        return self.g.execute('agent_bus.creation_status',{'requestId':row['requestId']},caller or self.b._view)
    def test_model_creation_requires_user_confirmation_and_randomizes_once(self):
        with patch('app.global_agents.secrets.choice',return_value=self.b.characterPacks[2]) as choose:
            result=self.create_request(name='helper',instructions='test')
            self.assertEqual(result['status'],'awaiting_approval');self.assertEqual(result['character'],'kaju')
            self.assertEqual(len(self.g.agents),1);self.assertFalse(self.g.allowed(self.b._view));self.m.openPage.assert_called_with('global-agents')
            retry=self.create_request(name='changed',character='yanami')
            self.assertEqual(result,retry);choose.assert_called_once()
        draft=self.g.snapshot()['creationDraft'];self.assertEqual(draft['requestId'],result['requestId'])
        created=self.g.handle('confirmCreation',{'requestId':result['requestId'],'name':'user-edited'})
        self.assertEqual(created['status'],'created');self.assertEqual(created['character'],'kaju')
        self.assertEqual(created['name'],'user-edited');self.assertEqual(len(self.g.agents),2)
        self.assertEqual(self.g.handle('confirmCreation',{'requestId':result['requestId']}),created)
        self.assertEqual(self.creation_status(result),created);self.assertEqual(self.create_request(),created)
        notification=self.m.bridge.notify.call_args.args[1]
        self.assertEqual(notification['session']['token'],self.b._view.key);self.assertFalse(notification['wake'])
        self.assertTrue(created['sourceBridge']['enabled']);self.assertEqual(created['sourceBridge']['scope'],'pair')
        self.assertTrue(self.g.allowed(self.b._view,created['targetId']));self.assertFalse(self.g.allowed(self.b._view,'agent:'+self.id));self.b._command_pi.assert_not_called()
    def test_user_auto_creation_switch_is_persistent_and_cannot_be_changed_by_model(self):
        self.assertFalse(self.g.allow_automatic_creation)
        for method,args in [('setAutomaticCreation',{'enabled':True}),('confirmCreation',{'requestId':'forged'})]:
            with self.assertRaises(ValueError):self.g.handle(method,args,agent=True)
        with self.assertRaises(ValueError):self.create_request(enabled=True)
        self.g.handle('setAutomaticCreation',{'enabled':True})
        with patch('app.global_agents.secrets.choice',return_value=self.b.characterPacks[0]):
            result=self.create_request()
        self.assertEqual(result['status'],'created');self.assertEqual(result['character'],'yanami');self.assertEqual(result['name'],'yanami')
        self.assertEqual(self.create_request(),result);self.assertEqual(len(self.g.agents),2);self.m.openPage.assert_not_called()
        explicit=self.create_request('second',character='komari');self.assertEqual(explicit['character'],'komari')
        self.g.save();loaded=GlobalAgents(self.m);loaded.start()
        self.assertTrue(loaded.allow_automatic_creation);self.assertEqual(loaded.execute('agent_bus.creation_status',{'requestId':result['requestId']},self.b._view)['id'],result['id']);loaded.close()
        self.g.handle('setAutomaticCreation',{'enabled':False});self.assertEqual(self.create_request('third')['status'],'awaiting_approval')
    def test_creation_is_bound_to_native_caller_and_survives_draft_id_change(self):
        source=self.b._view;source.title='original';result=self.create_request()
        other=SessionState(workspace='/work/other');self.b._pool.touch(other);self.b._view=other
        with self.assertRaises(ValueError):self.creation_status(result,other)
        source.id='native-session';self.g.observe(source,{'type':'ready'})
        self.g.handle('confirmCreation',{'requestId':result['requestId']})
        self.assertEqual(self.creation_status(result,source)['status'],'created')
        notification=self.m.bridge.notify.call_args.args[1]
        self.assertEqual(notification['session']['token'],source.key);self.assertEqual(notification['session']['id'],source.id)
        created=self.creation_status(result,source);self.assertTrue(self.g.allowed(source,created['targetId']));self.assertFalse(self.g.allowed(other,created['targetId']))
        same_key_other=self.create_request();self.assertNotEqual(same_key_other['requestId'],result['requestId'])
    def test_created_agent_has_scoped_return_bus_with_revocation_and_persistence(self):
        proposal=self.create_request();created=self.g.handle('confirmCreation',{'requestId':proposal['requestId']})
        child=self.g.ensure(created['id']);target=self.g.identifier(self.b._view)
        self.assertTrue(self.g.execute('agent_bus.overview',{},child)['targets'][0]['canDispatch'])
        dispatched=self.g.execute('agent_bus.dispatch',{'targetId':target,'text':'test'},child)
        with self.assertRaises(ValueError):self.dispatch()
        other=SessionState(workspace='/work/other');self.b._pool.touch(other)
        with self.assertRaises(ValueError):self.g.execute('agent_bus.dispatch',{'targetId':self.g.identifier(other),'text':'test'},child)
        self.b._view.id='native-created-source';self.g.observe(self.b._view,{'type':'ready'})
        self.assertTrue(self.g.allowed(self.b._view,created['targetId']));self.assertFalse(self.g.allowed(self.b._view,'agent:'+self.id))
        self.g.save();loaded=GlobalAgents(self.m);loaded.start()
        self.assertTrue(loaded.allowed(self.b._view,created['targetId']));self.assertFalse(loaded.allowed(self.b._view,'agent:'+self.id));loaded.close()
        self.g.handle('setBridge',{'id':self.g.identifier(self.b._view),'agentId':created['id'],'enabled':False})
        self.assertEqual(self.g.requests[dispatched['requestId']]['status'],'cancelled')
        self.assertFalse(self.create_request()['sourceBridge']['enabled'],'Retry must not restore a user-revoked grant')
        self.assertFalse(self.g.allowed(self.b._view,created['targetId']))
        self.g.handle('setBridge',{'id':self.g.identifier(self.b._view),'agentId':self.id,'enabled':True})
        self.assertTrue(self.g.allowed(self.b._view,'agent:'+self.id),'An explicit user grant applies only to the selected global')
    def test_creation_deletion_removes_only_its_own_source_bus_grant(self):
        self.g.handle('setAutomaticCreation',{'enabled':True})
        first=self.create_request('first');second=self.create_request('second')
        self.g.handle('delete',{'id':first['id']})
        self.assertFalse(self.g.allowed(self.b._view,first['targetId']));self.assertTrue(self.g.allowed(self.b._view,second['targetId']))
        self.g.handle('delete',{'id':second['id']});self.assertFalse(self.g.allowed(self.b._view))
    def test_creation_errors_include_repairable_tool_documentation(self):
        for fields in ({'role':'test'},{'title':'test'}):
            with self.assertRaisesRegex(ValueError,'instructions.*role/title'):self.create_request(**fields)
        with self.assertRaisesRegex(ValueError,'requestKey.*示例'):self.g.execute('agent_bus.create',{'name':'test'},self.b._view)
        self.assertEqual(len(self.g.agents),1);self.assertFalse(self.g.allowed(self.b._view))
    def test_cancel_expire_and_restart_never_create_pending_requests(self):
        cancelled=self.create_request('cancel');self.g.handle('cancelCreation',{'requestId':cancelled['requestId']})
        with self.assertRaises(ValueError):self.g.handle('confirmCreation',{'requestId':cancelled['requestId']})
        self.assertEqual(self.create_request('cancel')['status'],'cancelled')
        expired=self.create_request('expire');self.g.creation_requests[expired['requestId']]['deadline']=0;self.g.tick()
        self.assertEqual(self.creation_status(expired)['status'],'expired')
        with self.assertRaises(ValueError):self.g.handle('confirmCreation',{'requestId':expired['requestId']})
        pending=self.create_request('restart');self.g.save();loaded=GlobalAgents(self.m);loaded.start()
        self.assertEqual(loaded.execute('agent_bus.creation_status',{'requestId':pending['requestId']},self.b._view)['status'],'interrupted')
        self.assertEqual(len(loaded.agents),1);self.assertFalse(loaded.snapshot()['creationDraft']);self.assertFalse(loaded.allowed(self.b._view));loaded.close()
    def test_creation_validation_pending_limit_and_record_bound(self):
        for fields in ({'character':'missing'},{'model':'missing'},{'requestKey':''},{'name':'x'*61},{'instructions':'x'*8001},{'allowAutomaticCreation':True}):
            with self.assertRaises(ValueError):self.create_request(**fields)
        for index in range(8):self.create_request(str(index))
        with self.assertRaises(ValueError):self.create_request('full')
        self.g.handle('setAutomaticCreation',{'enabled':True})
        self.assertEqual(self.create_request('auto')['status'],'created')
        # Model requests cannot grow the retained history without bound.
        self.g.handle('setAutomaticCreation',{'enabled':False})
        for row in self.g.creation_requests.values():
            if row['status']=='awaiting_approval':self.g.handle('cancelCreation',{'requestId':row['id']})
        for index in range(40):
            row=self.create_request('bounded-'+str(index));self.g.handle('cancelCreation',{'requestId':row['requestId']})
        self.assertEqual(len(self.g.creation_requests),32)
        self.m.openPage.return_value=False
        with self.assertRaises(ValueError):self.create_request('cannot-open')
        self.assertFalse(any(row['requestKey']=='cannot-open' for row in self.g.creation_requests.values()))
    def test_global_can_manage_only_own_pair_and_ordinary_discovery_is_filtered(self):
        target=self.g.identifier(self.b._view)
        self.assertFalse([row for row in self.g.overview(self.b._view)['targets'] if row['kind']=='global'])
        self.g.execute('agent_bus.set_connection',{'sessionId':target,'enabled':True},self.source)
        visible=[row for row in self.g.overview(self.b._view)['targets'] if row['kind']=='global']
        self.assertEqual([row['id'] for row in visible],['agent:'+self.id]);self.assertTrue(visible[0]['canDispatch']);self.assertEqual(visible[0]['activity'],'idle')
        other=self.g.handle('create',{'name':'hidden'})['id'];self.assertNotIn('agent:'+other,[row['id'] for row in self.g.overview(self.b._view)['targets']])
        with self.assertRaises(ValueError):self.g.execute('agent_bus.set_connection',{'sessionId':target,'enabled':True,'agentId':other},self.source)
        connections=self.g.execute('agent_bus.connections',{},self.source);self.assertTrue(connections['canManage']);self.assertTrue(connections['connections'][0]['bridge'])
        self.source.busy=True;self.source.prompt_started=__import__('time').monotonic()-73
        state=self.g.overview(self.b._view)['targets'][-1];self.assertEqual(state['activity'],'busy: 1min13s')
        self.g.execute('agent_bus.set_connection',{'sessionId':target,'enabled':False},self.source)
        self.assertFalse([row for row in self.g.overview(self.b._view)['targets'] if row['kind']=='global'])
    def test_serial_queue_priority_cancellation_and_result_back_to_ordinary_sender(self):
        self.enable();caller=self.b._view;destination='agent:'+self.id
        def send(text):return self.g.execute('agent_bus.dispatch',{'targetId':destination,'text':text},caller)['requestId']
        first=send('first');second=send('second');third=send('third')
        self.source.busy=True;self.g.tick();self.b._command_pi.assert_not_called()
        self.assertEqual([row['id'] for row in self.g.snapshot(self.id)['queue']],[first,second,third])
        self.g.handle('prioritizeRequest',{'id':third});self.g.handle('cancelRequest',{'id':second})
        self.source.busy=False;self.g.tick();self.assertEqual(self.g.requests[third]['status'],'sending');self.assertEqual(self.g.requests[first]['status'],'queued')
        self.assertEqual(self.b._command_pi.call_count,2) # cancellation receipt and one task
        with self.assertRaises(ValueError):self.g.execute('agent_bus.reply',{'requestId':first,'result':'too early'},self.source)
        self.g.execute('agent_bus.reply',{'requestId':third,'result':'hello'},self.source)
        self.assertTrue(any(row['target']==self.g.identifier(caller) and row['data']['result']=='hello' and row['wake'] for row in self.g.outbox.values()))
        self.g.tick();self.assertEqual(self.g.requests[first]['status'],'sending');self.assertEqual(self.g.requests[second]['status'],'cancelled')
        self.g.handle('setBridge',{'id':self.g.identifier(caller),'agentId':self.id,'enabled':False})
        self.assertEqual(self.g.requests[first]['status'],'cancelled');self.assertFalse(self.g.outbox)
    def test_results_to_busy_global_use_the_same_queue_without_changing_completed_work(self):
        self.enable();request=self.dispatch()['requestId'];self.g.tick()
        self.source.busy=True;self.g.execute('agent_bus.reply',{'requestId':request,'result':'finished'},self.b._view)
        self.b._command_pi.reset_mock();self.g.tick();self.b._command_pi.assert_not_called()
        queued=self.g.snapshot(self.id)['queue'];self.assertEqual(len(queued),1);self.assertTrue(queued[0]['id'].startswith('message:'))
        self.assertIn('finished',queued[0]['text'])
        self.g.handle('prioritizeRequest',{'id':queued[0]['id']});self.g.handle('cancelRequest',{'id':queued[0]['id']})
        self.assertFalse(self.g.pending_queue(self.id));self.assertEqual(self.g.requests[request]['status'],'completed')
    def test_legacy_grants_expand_only_to_existing_globals_and_survive_restart(self):
        state=__import__('json').loads(self.g.registry.read_text());state['bridges']={self.b._view.id or 'draft:'+self.b._view.key:True}
        self.g.registry.write_text(__import__('json').dumps(state));loaded=GlobalAgents(self.m);loaded.start()
        extra=loaded.handle('create',{'name':'new'})['id']
        self.assertTrue(loaded.allowed(self.b._view,'agent:'+self.id));self.assertFalse(loaded.allowed(self.b._view,'agent:'+extra));loaded.close()
    def test_appearance_defaults_existing_candidates_and_persists(self):
        self.assertEqual(self.g.agents[self.id]['character'],'komari')
        other=self.g.handle('create',{'name':'八奈见','character':'yanami'})['id'];self.assertEqual(self.g.agents[other]['character'],'yanami')
        with self.assertRaises(ValueError):self.g.handle('create',{'name':'bad','character':'missing'})
        self.g.save();loaded=GlobalAgents(self.m);self.assertEqual(loaded.agents[self.id]['character'],'komari');loaded.close()
    def test_optional_names_number_only_automatic_names_and_survive_edits(self):
        first=self.g.handle('create',{'name':'   ','character':'yanami'})['id']
        self.assertEqual(self.g.agents[first]['name'],'yanami')
        second=self.g.handle('create',{'character':'yanami'})['id']
        self.assertEqual([self.g.agents[k]['name'] for k in (first,second)],['yanami-1','yanami-2'])
        self.g.handle('update',{'id':first,'name':'','character':'yanami'})
        self.assertEqual(self.g.agents[first]['name'],'yanami-1')
        custom=self.g.handle('create',{'name':'custom','character':'yanami'})['id']
        third=self.g.handle('create',{'character':'yanami'})['id']
        self.assertEqual(self.g.agents[third]['name'],'yanami-3');self.assertEqual(self.g.agents[custom]['name'],'custom')
        self.g.save();loaded=GlobalAgents(self.m)
        self.assertTrue(loaded.agents[first]['autoName']);self.assertEqual(loaded.agents[second]['name'],'yanami-2');loaded.close()
    def test_native_caller_is_explicit_even_when_another_chat_is_visible(self):
        other=self.g.handle('create',{'name':'另一个'})['id'];second=self.g.ensure(other)
        result=self.g.execute('agent_bus.overview',{},second)
        self.assertEqual(result['self']['id'],'agent:'+other)
        self.assertEqual(result['self']['name'],'另一个')
        self.assertEqual([row['id'] for row in result['targets'] if row['isSelf']],['agent:'+other])
        disabled=next(row for row in result['targets'] if row['id']==self.g.identifier(self.b._view))
        self.assertFalse(disabled['canDispatch'])
        self.assertIn('"id": "agent:'+other+'"',self.g.prompt(second))
        self.assertIn('"name": "另一个"',self.g.prompt(second))
    def test_send_marks_the_native_echo_and_failed_start_rolls_it_back(self):
        self.g.handle('send',{'id':self.id,'text':'pending'})
        self.assertTrue(self.source.optimistic_user)
        self.source.optimistic_user=False;self.source.messages=[]
        self.b._command_pi.return_value=False
        with self.assertRaises(ValueError):self.g.handle('send',{'id':self.id,'text':'failed'})
        self.assertFalse(self.source.optimistic_user);self.assertFalse(self.source.messages)
    def test_rich_projection_keeps_tool_arguments_and_merges_assistant_steps(self):
        self.source.messages=[{'role':'user','text':'test'},{'role':'assistant','thinking':'reason','text':'','tools':[{'id':'test','name':'umeko_desktop','state':'done','arguments':{'operation':'agent_bus.overview'},'result':'members'}]},{'role':'assistant','text':'```python\nprint(1)\n```'}]
        rows=self.g.snapshot(self.id)['messages']
        self.assertEqual(len(rows),2)
        self.assertEqual([step['kind'] for step in rows[-1]['activity']],['thinking','tools','text'])
        self.assertEqual(rows[-1]['tools'][0]['arguments']['operation'],'agent_bus.overview')
        self.g.save();loaded=GlobalAgents(self.m);self.assertEqual(loaded.snapshot(self.id)['messages'][-1]['tools'][0]['result'],'members');loaded.close()
        legacy=self.g.messages([{'role':'assistant','toolsText':'saved summary'}])
        self.assertEqual(legacy[0]['tools'][0]['result'],'saved summary')
    def test_opt_in_and_native_identity_and_explicit_completion(self):
        with self.assertRaises(ValueError):self.dispatch()
        self.enable();reply=self.dispatch();request=reply['requestId'];self.assertEqual(reply['status'],'accepted')
        self.g.tick();self.assertTrue(self.b._command_pi.called);sent=self.b._command_pi.call_args.kwargs['notification'];self.assertIn(request,sent['message'])
        impostor=SessionState()
        with self.assertRaises(ValueError):self.g.execute('agent_bus.reply',{'requestId':request,'result':'forged'},impostor)
        self.g.observe(self.b._view,{'type':'widget_delivery','id':sent['id'],'status':'delivered'})
        self.assertEqual(self.g.requests[request]['status'],'running')
        self.g.execute('agent_bus.reply',{'requestId':request,'result':'通过'},self.b._view)
        self.assertEqual(self.g.requests[request]['status'],'completed')
        self.assertTrue(any(v['target']=='agent:'+self.id and v['wake'] for v in self.g.outbox.values()))
        with self.assertRaises(ValueError):self.g.execute('agent_bus.reply',{'requestId':request,'result':'again'},self.b._view)
    def test_draft_to_native_id_keeps_routing(self):
        self.enable();request=self.dispatch()['requestId'];self.g.tick();self.b._view.id='native-id';self.g.observe(self.b._view,{'type':'ready'})
        self.assertEqual(self.g.requests[request]['target'],'session:native-id');self.assertTrue(self.g.allowed(self.b._view))
        self.g.execute('agent_bus.reply',{'requestId':request,'result':'done'},self.b._view)
    def test_revocation_cancels_queued_work_and_late_reply(self):
        self.enable();request=self.dispatch()['requestId'];self.g.handle('setBridge',{'id':self.g.identifier(self.b._view),'agentId':self.id,'enabled':False})
        self.assertEqual(self.g.requests[request]['status'],'cancelled');self.assertFalse(any(x['target']==self.g.identifier(self.b._view) for x in self.g.outbox.values()))
        with self.assertRaises(ValueError):self.g.execute('agent_bus.reply',{'requestId':request,'result':'late'},self.b._view)
    def test_restart_does_not_replay_pending_requests(self):
        self.enable();request=self.dispatch()['requestId'];self.g.save();loaded=GlobalAgents(self.m)
        self.assertEqual(loaded.requests[request]['status'],'interrupted');self.assertFalse(loaded.outbox);loaded.close()
    def test_connected_ordinary_can_dispatch_without_administering_other_links(self):
        self.enable()
        result=self.g.execute('agent_bus.dispatch',{'targetId':'agent:'+self.id,'text':'hello'},self.b._view)
        self.assertEqual(result['status'],'accepted')
        other=SessionState();self.b._pool.touch(other)
        with self.assertRaises(ValueError):self.g.execute('agent_bus.dispatch',{'targetId':self.g.identifier(other),'text':'test'},self.b._view)
        with self.assertRaises(ValueError):self.g.handle('create',{'name':'forged'},agent=True)
        with self.assertRaises(ValueError):self.g.execute('agent_bus.set_connection',{'sessionId':self.g.identifier(other),'enabled':True},self.b._view)
    def test_queue_bounds_and_transcript_budget(self):
        self.enable()
        for _ in range(4):self.dispatch()
        with self.assertRaises(ValueError):self.dispatch()
        rows=self.g.messages([{'role':'assistant','text':'x'*10000,'thinking':'y'*10000}]*100)
        self.assertLessEqual(len(rows),64);self.assertLessEqual(sum(len(v['text'])+len(v['thinking']) for v in rows),96000)
    def test_target_crash_is_reported_without_waiting_for_timeout(self):
        self.enable();request=self.dispatch()['requestId']
        self.b._view.failed=True;self.g.observe(self.b._view,{'type':'exit'})
        self.assertEqual(self.g.requests[request]['status'],'failed')
        self.assertTrue(any(v['target']=='agent:'+self.id for v in self.g.outbox.values()))
    def test_confirmation_is_bound_to_the_selected_native_instance(self):
        self.source.approval={'id':'confirm-one','method':'confirm'}
        self.b._pool.write=Mock()
        with self.assertRaises(ValueError):self.g.handle('respond',{'id':self.id,'requestId':'stale','value':True})
        self.g.handle('respond',{'id':self.id,'requestId':'confirm-one','value':False})
        self.b._pool.write.assert_called_once_with(self.source,{'type':'ui_response','id':'confirm-one','value':False})
        self.assertFalse(self.source.approval)
    def test_own_context_only(self):
        other=self.g.handle('create',{'name':'other'})['id'];self.g.agents[other]['sessionFile']=str(Path(self.temp.name)/'someone-else.jsonl')
        Path(self.g.agents[other]['sessionFile']).write_text('{}')
        with self.assertRaises(ValueError):self.g.ensure(other)
    def test_delete_stops_only_owned_session(self):
        normal=self.b._view;self.g.handle('delete',{'id':self.id});self.assertNotIn(self.id,self.g.agents);self.assertIn(normal.key,self.b._pool.records)
if __name__=='__main__':unittest.main()
