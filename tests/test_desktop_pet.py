"""Lifecycle, no-history activity observation, imports and Widget Agent RPC."""
import copy
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtGui import QImage, QColor

from app.desktop_pet import PetMotion
from app.desktop_plugins import DesktopPlugins
from app.pet_packs import import_pack, read_pack
from tests.test_desktop_plugins import Host


class MotionTests(unittest.TestCase):
    def test_latest_activity_wins_only_after_minimum_and_pause(self):
        now=[0.0]
        motion=PetMotion(lambda:now[0])
        for t,state in [(1,'thinking'),(2,'working'),(2.99,'waiting')]:
            now[0]=t;motion.request(state);self.assertFalse(motion.step())
        now[0]=3;self.assertTrue(motion.step());self.assertEqual(motion.state,'waiting')
        now[0]=4;motion.request('error');self.assertFalse(motion.step())
        now[0]=6;self.assertFalse(motion.step(paused=True))
        now[0]=7;self.assertTrue(motion.step());self.assertEqual(motion.state,'error')

    def test_click_queues_without_cutting_short_current_animation(self):
        now=[0.0];motion=PetMotion(lambda:now[0]);motion.interact('done',3)
        now[0]=2.9;self.assertFalse(motion.step())
        now[0]=3;self.assertTrue(motion.step());self.assertEqual(motion.state,'done')
        now[0]=5.99;self.assertFalse(motion.step())
        now[0]=6;self.assertTrue(motion.step());self.assertEqual(motion.state,'idle')


class PetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QCoreApplication.instance() or QCoreApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name).resolve();self.host=Host(self.path)
        self.manager=DesktopPlugins(self.host);self.addCleanup(self.manager.close)
        self.pet=self.manager.pet
    def wait(self,predicate):
        import time
        until=time.monotonic()+10
        while time.monotonic()<until:
            self.app.processEvents()
            if predicate():return
            time.sleep(.01)
        self.fail('Pet request timed out')
    def image(self,name='sample.png'):
        path=self.path/name;image=QImage(32,48,QImage.Format_ARGB32);image.fill(QColor('transparent'))
        image.setPixelColor(16,24,QColor('blue'));self.assertTrue(image.save(str(path)));return path
    def control(self):
        from app.umeko_control import UmekoControl
        control=UmekoControl.__new__(UmekoControl);QObject.__init__(control)
        control.b=self.host;control.jobs={}
        control.operations=json.loads((self.host.root/'runtime/umeko-operations.json').read_text(encoding='utf-8'))['operations']
        self.host.desktopPlugins=self.manager
        return control
    def rpc(self,control,method,args=None):
        value=control.execute({'operation':'widgets.call','arguments':{'id':'desktop-pet','method':method,'arguments':args or {}}})
        self.assertTrue(value['ok'],value)
        self.wait(lambda:self.manager.bridge.calls[value['requestId']]['status']!='running')
        return control.execute({'operation':'widgets.result','arguments':{'requestId':value['requestId']}})['result']
    def test_default_loaded_hidden_no_process_and_application_lifetime(self):
        self.assertTrue(self.manager.enabled('desktop-pet'));self.assertTrue(self.pet.running);self.assertFalse(self.pet.visible)
        worker=self.manager.workers['desktop-pet'];self.assertNotIn('process',worker)
        self.host._view.key='next';self.host._view.id='second';self.host.viewChanged.emit()
        self.assertIs(self.manager.workers['desktop-pet'],worker)
        self.pet.configure({'visible':True});self.assertTrue(self.pet.visible)
        self.manager.setEnabled('desktop-pet',False);self.assertFalse(self.pet.running);self.assertFalse(self.pet.visible);self.assertFalse(self.pet.timer.isActive())
        self.manager.setEnabled('desktop-pet',True);self.assertTrue(self.pet.visible)
        self.manager.close();self.assertFalse(self.pet.running)
    def test_whale_builtin_has_all_animated_states_and_cannot_be_replaced(self):
        appearances = {row['id']: row for row in self.pet.appearances}
        self.assertTrue(appearances['yanami']['builtin'])
        self.assertTrue(appearances['whale-girl']['builtin'])
        pack = self.host.root/'umeko-plugins/desktop-pet/assets/whale-girl'
        checked = read_pack(pack, check=True)
        self.assertEqual(set(checked['states']), {'idle','thinking','working','waiting','done','error'})
        self.assertTrue(all(row['animated'] for row in checked['images'].values()))
        self.assertLess(sum((pack/name).stat().st_size for name in checked['states'].values()), 24*1024*1024)
        self.pet.configure({'appearance':'whale-girl'})
        for state in checked['states']:
            self.pet.motion.state = state
            self.assertTrue(self.pet.state['source'].endswith('/whale-girl/'+state+'.webp'))
            self.assertTrue(self.pet.state['animated'])
        with self.assertRaises(ValueError):self.pet.handle('removeAppearance', {'id':'whale-girl'})
        forged = self.path/'forged';forged.mkdir()
        (forged/'pet.json').write_text(json.dumps({'format':'umeko-pet','version':1,'id':'whale-girl','name':'forged','states':{'idle':'one.png'}}))
        (forged/'one.png').write_bytes(self.image().read_bytes())
        self.pet.begin_import(str(forged/'pet.json'))
        self.wait(lambda:not self.pet.importing)
        self.assertIn('id', self.pet.last_error)
        self.assertEqual(self.pet._packs['whale-girl']['directory'], pack)
        self.manager.close();second=DesktopPlugins(self.host);self.addCleanup(second.close)
        self.assertEqual(second.pet.config['appearance'],'whale-girl')
    def test_builtin_komari_has_six_valid_animations_and_persists_selection(self):
        packs = {row['id']:row for row in self.pet.appearances}
        self.assertTrue(packs['yanami']['builtin'])
        self.assertTrue(packs['komari']['builtin'])
        pack = read_pack(self.host.root/'umeko-plugins/desktop-pet/assets/komari', check=True)
        self.assertEqual(set(pack['states']), {'idle','thinking','working','waiting','done','error'})
        self.assertTrue(all(image['animated'] and image['frames'] > 1 for image in pack['images'].values()))
        control = self.control()
        self.assertTrue(self.rpc(control,'selectAppearance',{'id':'komari'})['ok'])
        self.assertEqual(self.pet.state['appearance'],'komari')
        self.assertEqual(self.pet.state['name'],'小鞠知花')
        self.assertFalse(self.rpc(control,'removeAppearance',{'id':'komari'})['ok'])
        self.manager.close()
        second = DesktopPlugins(self.host);self.addCleanup(second.close)
        self.assertEqual(second.pet.config['appearance'],'komari')
        self.assertFalse(second.pet.visible)
    def test_imported_pack_cannot_shadow_builtin_komari(self):
        folder = self.path/'shadow';folder.mkdir()
        (folder/'one.png').write_bytes(self.image().read_bytes())
        value = {'format':'umeko-pet','version':1,'id':'komari','name':'Shadow','states':{'idle':'one.png'}}
        (folder/'pet.json').write_text(json.dumps(value))
        with self.assertRaises(ValueError):import_pack(folder/'pet.json',self.pet.pack_directory)
        self.assertFalse((self.pet.pack_directory/'komari').exists())
        forged=self.pet.pack_directory/'komari';forged.mkdir(parents=True)
        (forged/'pet.json').write_text(json.dumps(value));(forged/'one.png').write_bytes(self.image().read_bytes())
        self.pet.load_packs()
        self.assertEqual(next(row['name'] for row in self.pet.appearances if row['id']=='komari'),'小鞠知花')
    def test_activity_observer_only_reads_compact_metadata_and_background_chats(self):
        class NoTranscript:
            def __len__(self):raise AssertionError('Pet read transcript length')
            def __getitem__(self,key):raise AssertionError('Pet read transcript')
        record=self.host._view;record.messages=NoTranscript();record.busy=True;record.pet_activity='working'
        record.subagents={'one':{'status':'running'},'two':{'status':'running'}}
        self.pet.sample();self.assertEqual(self.pet.state['activity'],{'state':'working','activeChats':1,'activeSubagents':2})
        other=copy.copy(record);other.key='other';other.approval={'question':'confirm'}
        self.host._pool.records[other.key]=other
        self.pet.sample();self.assertEqual(self.pet.state['activity']['state'],'waiting')
        other.busy=False;record.busy=False;record.subagents={};other.subagents={}
        self.pet.sample();self.assertEqual(self.pet.state['activity']['state'],'done')
        record.busy=True;self.pet.sample();record.failed=True;record.busy=False;self.pet.sample()
        self.assertEqual(self.pet.state['activity']['state'],'error')
    def test_whale_uses_only_user_dialogue_and_announces_actual_task_outcomes_once(self):
        self.pet.configure({'appearance':'whale-girl'})
        dialogue=self.pet._packs['whale-girl']['dialogue']
        self.assertEqual({line for lines in dialogue.values() for line in lines},
                         {'要米','米','饿，饿','米呢','好了米','有问题了','米？','没问题了米','米！'})
        spoken=[];self.pet.reaction.connect(spoken.append)
        for kind in ('tap','hover','drag'):
            self.pet.interact(kind)
            self.assertIn(spoken[-1],dialogue[kind])
            self.assertNotIn(spoken[-1],dialogue['done']+dialogue['error'])
        spoken.clear();self.pet.sample()
        self.assertEqual(spoken,[],'An interaction must not announce task completion')
        record=self.host._view
        record.busy=True;self.pet.sample()
        record.busy=False;self.pet.sample()
        self.assertEqual(len(spoken),1);self.assertIn(spoken[0],dialogue['done'])
        self.pet.sample();self.assertEqual(len(spoken),1,'Polling repeated the completion line')
        record.busy=True;self.pet.sample()
        record.busy=False;record.failed=True;self.pet.sample()
        self.assertEqual(spoken[-1],'有问题了')
        self.pet.sample();self.assertEqual(len(spoken),2,'Polling repeated the error line')
    def test_agent_import_select_config_and_result_use_existing_widget_channel(self):
        control=self.control();docs=control.execute({'operation':'widgets.docs','arguments':{'id':'desktop-pet'}})
        self.assertIn('importAppearance',docs['methods']);self.assertIn('umeko-pet',docs['document']['text'])
        imported=self.rpc(control,'importAppearance',{'path':str(self.image())})
        self.assertTrue(imported['ok'],imported);identifier=imported['result']['appearance']
        self.assertFalse(self.pet.visible);self.assertEqual(self.pet.config['appearance'],'yanami')
        self.assertTrue(self.rpc(control,'selectAppearance',{'id':identifier})['ok'])
        self.assertTrue(self.rpc(control,'configure',{'visible':True,'sampleIntervalMs':2000,'minimumStateMs':5000})['ok'])
        self.assertEqual(self.pet.timer.interval(),2000);self.assertTrue(self.pet.visible)
        saved=json.loads(self.manager.registry.read_text(encoding='utf-8'))['config']['desktop-pet'];self.assertEqual(saved['appearance'],identifier)
        self.assertFalse(self.rpc(control,'configure',{'minimumStateMs':500})['ok'])
        self.assertFalse(self.rpc(control,'show',{'unexpected':True})['ok'])
        self.assertTrue(self.rpc(control,'removeAppearance',{'id':identifier})['ok']);self.assertEqual(self.pet.config['appearance'],'yanami')
        self.assertFalse(self.rpc(control,'removeAppearance',{'id':'yanami'})['ok'])
    def test_import_pack_fallback_and_zip_path_rejection_leave_existing_art_intact(self):
        image=self.image();folder=self.path/'pack';folder.mkdir()
        value={'format':'umeko-pet','version':1,'id':'fixture','name':'Fixture','states':{'idle':'one.png'},'dialogue':{'tap':['Hello']}}
        (folder/'pet.json').write_text(json.dumps(value));(folder/'one.png').write_bytes(image.read_bytes())
        imported=import_pack(folder/'pet.json',self.pet.pack_directory)
        self.assertFalse(imported['images']['one.png']['animated']);self.pet.load_packs();self.pet.configure({'appearance':'fixture'})
        self.pet.motion.state='error';self.assertTrue(self.pet.state['source'].endswith('/one.png'))
        bad=self.path/'bad.zip'
        with zipfile.ZipFile(bad,'w') as archive:archive.writestr('../escape.png',image.read_bytes())
        with self.assertRaises(ValueError):import_pack(bad,self.pet.pack_directory)
        self.assertEqual(self.pet.config['appearance'],'fixture');self.assertFalse((self.path/'escape.png').exists())
        with self.assertRaises(ValueError):import_pack(folder/'pet.json',self.pet.pack_directory)
    def test_persisted_preferences_and_disabling_survive_new_manager(self):
        self.pet.configure({'visible':True,'paused':True,'size':224});self.manager.setEnabled('desktop-pet',False)
        self.manager.close();second=DesktopPlugins(self.host);self.addCleanup(second.close)
        self.assertFalse(second.pet.running);self.assertFalse(second.pet.visible);self.assertTrue(second.pet.config['visible'])
        second.setEnabled('desktop-pet',True);self.assertTrue(second.pet.visible);self.assertTrue(second.pet.config['paused'])
        self.assertEqual(second.pet.config['size'],224)

    def test_reminder_methods_use_real_widget_rpc_and_host_clock(self):
        from umeko_plugin_sdk.packages import validate
        # Exercise the existing package validator once: reminder methods stay
        # within its supported schema dialect rather than adding nullable types.
        manifest, defaults, schema = validate(self.host.root/'umeko-plugins/desktop-pet')
        self.assertEqual(manifest['id'], 'desktop-pet')
        self.assertTrue(defaults['reminderNotificationsEnabled'])
        now = datetime(2026, 11, 2, 8, tzinfo=timezone.utc)
        self.pet.reminders.clock = lambda: now
        control = self.control()
        docs = control.execute({'operation':'widgets.docs', 'arguments':{'id':'desktop-pet'}})
        for name in ('listItems', 'getItem', 'createItem', 'updateItem', 'completeItem', 'deleteItem'):
            self.assertIn(name, docs['methods'])
        self.assertIn('clearDueAt', docs['document']['text'])
        created = self.rpc(control, 'createItem', {'title':'RPC reminder', 'notes':'plain text',
                          'dueAt':(now + timedelta(minutes=5)).isoformat()})
        self.assertTrue(created['ok'], created)
        item = created['result']['item']
        listed = self.rpc(control, 'listItems')
        self.assertTrue(listed['ok'], listed)
        self.assertEqual(listed['result']['now'], '2026-11-02T08:00:00Z')
        self.assertEqual(listed['result']['items'][0]['id'], item['id'])
        fetched = self.rpc(control, 'getItem', {'id':item['id']})
        self.assertTrue(fetched['ok'], fetched)
        self.assertEqual(fetched['result']['item']['title'], 'RPC reminder')
        cleared = self.rpc(control, 'updateItem', {'id':item['id'], 'clearDueAt':True})
        self.assertTrue(cleared['ok'], cleared)
        self.assertIsNone(cleared['result']['item']['dueAt'])
        completed = self.rpc(control, 'completeItem', {'id':item['id']})
        self.assertTrue(completed['ok'], completed)
        self.assertTrue(completed['result']['item']['completed'])
        deleted = self.rpc(control, 'deleteItem', {'id':item['id']})
        self.assertTrue(deleted['ok'], deleted)
        self.assertEqual(deleted['result']['deletedId'], item['id'])
        self.assertIn('reminders', self.pet.status())
        self.assertEqual(self.pet.status()['reminders']['openCount'], 0)

    def test_reminder_notification_default_and_existing_config_survive_reload(self):
        self.assertTrue(self.pet.config['reminderNotificationsEnabled'])
        self.pet.configure({'visible':True, 'paused':True, 'size':224})
        self.assertTrue(self.pet.config['reminderNotificationsEnabled'])
        control = self.control()
        configured = self.rpc(control, 'configure', {'reminderNotificationsEnabled':False})
        self.assertTrue(configured['ok'], configured)
        self.assertFalse(self.pet.config['reminderNotificationsEnabled'])
        self.assertFalse(self.rpc(control, 'configure', {'reminderNotificationsEnabled':'false'})['ok'])
        # This is an old persisted config: no newly introduced preference key.
        self.manager.settings['config']['desktop-pet'].pop('reminderNotificationsEnabled')
        self.assertTrue(self.manager.save())
        self.manager.close()
        second = DesktopPlugins(self.host)
        self.addCleanup(second.close)
        self.assertTrue(second.pet.config['reminderNotificationsEnabled'])
        self.assertEqual(second.pet.config['size'], 224)
        self.assertTrue(second.pet.config['paused'])

    def test_reminder_card_merges_due_items_while_animation_is_paused(self):
        now = [datetime(2026, 11, 2, 8, tzinfo=timezone.utc)]
        self.pet.reminders.clock = lambda: now[0]
        self.pet.configure({'visible':True, 'paused':True})
        presented = []
        self.pet.reminderPresented.connect(lambda rows: presented.append(copy.deepcopy(rows)))
        first = self.pet.handle('createItem', {'title':'first',
                              'dueAt':(now[0] + timedelta(seconds=2)).isoformat()})['item']
        second = self.pet.handle('createItem', {'title':'second',
                               'dueAt':(now[0] + timedelta(seconds=4)).isoformat()})['item']
        self.assertEqual(self.pet.reminderCard, [])
        now[0] += timedelta(seconds=2)
        self.pet.reminders.check()
        self.assertEqual([row['id'] for row in self.pet.reminderCard], [first['id']])
        now[0] += timedelta(seconds=2)
        self.pet.reminders.check()
        self.assertEqual({row['id'] for row in self.pet.reminderCard}, {first['id'], second['id']})
        self.assertEqual(len(presented), 2)
        self.assertTrue(self.pet.config['paused'])
        self.assertEqual(len(self.pet.reminderItems), 2)
        self.pet.dismissReminders()
        self.assertEqual(self.pet.reminderCard, [])
        self.assertFalse(self.pet.handle('getItem', {'id':first['id']})['item']['completed'])

    def test_reminder_card_filters_mutations_and_rejects_stale_complete_button(self):
        now = datetime(2026, 11, 2, 8, tzinfo=timezone.utc)
        self.pet.reminders.clock = lambda: now
        self.pet.configure({'visible':True})
        first = self.pet.handle('createItem', {'title':'original', 'dueAt':now.isoformat()})['item']
        self.assertEqual(len(self.pet.reminderCard), 1)
        edited = self.pet.handle('updateItem', {'id':first['id'], 'title':'edited'})['item']
        self.assertEqual(self.pet.reminderCard, [])
        self.pet.completeReminder(first['id'], first['revision'])
        self.assertFalse(self.pet.handle('getItem', {'id':first['id']})['item']['completed'])
        self.assertEqual(self.pet.reminderCard, [])
        second = self.pet.handle('createItem', {'title':'complete', 'dueAt':now.isoformat()})['item']
        self.pet.completeReminder(second['id'], second['revision'])
        self.assertTrue(self.pet.handle('getItem', {'id':second['id']})['item']['completed'])
        self.assertEqual(self.pet.reminderCard, [])
        third = self.pet.handle('createItem', {'title':'delete', 'dueAt':now.isoformat()})['item']
        self.assertEqual(self.pet.reminderCard[0]['id'], third['id'])
        self.pet.handle('deleteItem', {'id':third['id']})
        self.assertEqual(self.pet.reminderCard, [])
        self.assertEqual([row['id'] for row in self.pet.reminderItems], [edited['id']])

    def test_reminder_selection_and_current_card_close_on_visibility_or_preference(self):
        now = datetime(2026, 11, 2, 8, tzinfo=timezone.utc)
        self.pet.reminders.clock = lambda: now
        self.pet.configure({'visible':True})
        item = self.pet.handle('createItem', {'title':'show settings', 'dueAt':now.isoformat()})['item']
        self.pet.openReminders(item['id'], False)
        selected = self.pet.reminderSelection
        self.assertEqual(selected['id'], item['id'])
        self.assertFalse(selected['create'])
        self.assertEqual(self.pet.status()['reminderSelection'], selected)
        self.pet.openReminders('', True)
        self.assertTrue(self.pet.reminderSelection['create'])
        self.assertGreater(self.pet.reminderSelection['serial'], selected['serial'])
        self.pet.configure({'visible':False})
        self.assertEqual(self.pet.reminderCard, [])
        self.assertTrue(self.pet.reminders.running)
        self.pet.configure({'visible':True})
        self.assertEqual(self.pet.reminderCard, [])
        next_item = self.pet.handle('createItem', {'title':'disable bubble', 'dueAt':now.isoformat()})['item']
        self.assertEqual(self.pet.reminderCard[0]['id'], next_item['id'])
        self.pet.configure({'reminderNotificationsEnabled':False})
        self.assertEqual(self.pet.reminderCard, [])
        self.pet.configure({'reminderNotificationsEnabled':True})
        self.assertEqual(self.pet.reminderCard, [])

    def test_reminder_lifecycle_stop_and_reenable_recovers_overdue_card(self):
        now = [datetime(2026, 11, 2, 8, tzinfo=timezone.utc)]
        self.pet.reminders.clock = lambda: now[0]
        self.pet.configure({'visible':True})
        item = self.pet.handle('createItem', {'title':'while disabled',
                              'dueAt':(now[0] + timedelta(minutes=2)).isoformat()})['item']
        self.assertTrue(self.pet.reminders.running)
        self.assertIsNotNone(self.pet.reminders._handle)
        old_callback = self.pet.reminders._handle
        self.manager.setEnabled('desktop-pet', False)
        self.assertFalse(self.pet.reminders.running)
        self.assertIsNone(self.pet.reminders._handle)
        self.assertFalse(old_callback.timer.isActive())
        now[0] += timedelta(minutes=3)
        self.pet.reminders.check()
        self.assertEqual(self.pet.reminderCard, [])
        self.manager.setEnabled('desktop-pet', True)
        self.assertTrue(self.pet.reminders.running)
        self.assertEqual([row['id'] for row in self.pet.reminderCard], [item['id']])
        self.manager.close()
        self.assertFalse(self.pet.reminders.running)
        self.assertTrue(self.pet.reminders.closed)
        self.assertEqual(self.pet.reminderCard, [])


if __name__=='__main__':unittest.main()
