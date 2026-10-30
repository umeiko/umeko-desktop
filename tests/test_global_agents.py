import os, tempfile, unittest, uuid, json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
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
    def __init__(self,b):super().__init__();self.b=b
class GlobalAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QCoreApplication.instance() or QCoreApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.b=Backend(self.temp.name);self.m=Manager(self.b);self.g=GlobalAgents(self.m);self.g.start()
        self.id=self.g.handle('create',{'name':'协调员'})['id'];self.source=self.g.ensure(self.id)
    def tearDown(self):self.g.close();self.temp.cleanup()
    def dispatch(self):return self.g.execute('agent_bus.dispatch',{'targetId':self.g.identifier(self.b._view),'text':'检查测试'},self.source)
    def enable(self):self.g.handle('setBridge',{'id':self.g.identifier(self.b._view),'enabled':True})
    def test_appearance_defaults_existing_candidates_and_persists(self):
        self.assertEqual(self.g.agents[self.id]['character'],'komari')
        other=self.g.handle('create',{'name':'八奈见','character':'yanami'})['id'];self.assertEqual(self.g.agents[other]['character'],'yanami')
        with self.assertRaises(ValueError):self.g.handle('create',{'name':'bad','character':'missing'})
        self.g.save();loaded=GlobalAgents(self.m);self.assertEqual(loaded.agents[self.id]['character'],'komari');loaded.close()
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
        self.enable();request=self.dispatch()['requestId'];self.b._view.id='native-id';self.g.observe(self.b._view,{'type':'ready'})
        self.assertEqual(self.g.requests[request]['target'],'session:native-id');self.assertTrue(self.g.allowed(self.b._view))
        self.g.execute('agent_bus.reply',{'requestId':request,'result':'done'},self.b._view)
    def test_revocation_cancels_queued_work_and_late_reply(self):
        self.enable();request=self.dispatch()['requestId'];self.g.handle('setBridge',{'id':self.g.identifier(self.b._view),'enabled':False})
        self.assertEqual(self.g.requests[request]['status'],'cancelled');self.assertFalse(any(x['target']==self.g.identifier(self.b._view) for x in self.g.outbox.values()))
        with self.assertRaises(ValueError):self.g.execute('agent_bus.reply',{'requestId':request,'result':'late'},self.b._view)
    def test_restart_does_not_replay_pending_requests(self):
        self.enable();request=self.dispatch()['requestId'];self.g.save();loaded=GlobalAgents(self.m)
        self.assertEqual(loaded.requests[request]['status'],'interrupted');self.assertFalse(loaded.outbox);loaded.close()
    def test_only_global_can_dispatch_and_agent_cannot_administer(self):
        self.enable()
        with self.assertRaises(ValueError):self.g.execute('agent_bus.dispatch',{'targetId':'agent:'+self.id,'text':'test'},self.b._view)
        with self.assertRaises(ValueError):self.g.handle('create',{'name':'forged'},agent=True)
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
