import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QSignalSpy
from app.desktop_preferences import DEFAULTS, configure_graphics, normalize, startup_settings, validate_patch
from app.storage import Store
from app.controller import Controller

ROOT = Path(__file__).resolve().parents[1]
APP = QCoreApplication.instance() or QCoreApplication([])


class DesktopPreferencesTests(unittest.TestCase):
    def test_width_hint_change_notifies_chat_without_refreshing_all_settings_or_pi(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'UMEKO_DATA_DIR':temp}):
            controller = Controller(ROOT)
            try:
                all_settings = QSignalSpy(controller.changed)
                desktop = QSignalSpy(controller.desktopSettingsChanged)
                with patch.object(controller._pool, 'write') as write, patch.object(controller.documentPreview, 'refreshWebPolicy') as preview:
                    self.assertTrue(controller.saveDesktopSettings('{"chatWidthHints":false}'))
                    self.assertFalse(controller.desktopSettings['chatWidthHints'])
                    self.assertFalse(Store(Path(temp)).data['desktop']['chatWidthHints'])
                    self.assertEqual(all_settings.count(), 0)
                    self.assertEqual(desktop.count(), 1)
                    write.assert_not_called()
                    preview.assert_not_called()
                    self.assertTrue(controller.saveDesktopSettings('{"chatWidthHints":false}'))
                    self.assertEqual(desktop.count(), 1)
            finally:
                controller.close()

    def test_external_desktop_edits_refresh_scoped_bindings(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'UMEKO_DATA_DIR':temp}):
            controller = Controller(ROOT)
            try:
                desktop = QSignalSpy(controller.desktopSettingsChanged)
                vision = QSignalSpy(controller.auxiliaryVisionSettingsChanged)
                data = json.loads(controller.store.path.read_text())
                data['desktop']['chatWidthHints'] = False
                data['auxiliaryVision']['autoAnalyze'] = False
                controller.store.path.write_text(json.dumps(data))
                controller.store.save()
                self.assertFalse(controller.desktopSettings['chatWidthHints'])
                self.assertFalse(controller.auxiliaryVisionSettings['autoAnalyze'])
                self.assertEqual(desktop.count(), 1)
                self.assertEqual(vision.count(), 1)
            finally:
                controller.close()

    def test_qml_config_does_not_copy_internal_session_metadata(self):
        class BackendOnlyHistory(dict):
            def __deepcopy__(self, memo):
                raise AssertionError('Session metadata must stay out of the QML view')
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'UMEKO_DATA_DIR':temp}):
            controller = Controller(ROOT)
            try:
                original = controller.store.data['sessionMeta']
                controller.store.data['sessionMeta'] = BackendOnlyHistory(original)
                config = controller.config
                self.assertNotIn('sessionMeta', config)
                self.assertEqual(config['desktop'], controller.desktopSettings)
                config['desktop']['chatWidthHints'] = False
                self.assertTrue(controller.store.data['desktop']['chatWidthHints'])
                controller.store.data['sessionMeta'] = original
            finally:
                controller.store.data['sessionMeta'] = original
                controller.close()

    def test_defaults_normalization_and_pre_application_read(self):
        self.assertEqual(normalize(None), DEFAULTS)
        self.assertEqual(normalize({'autoOpenSubmissions':1,'webDisplay':[],'chatWidthHints':0,
                                    'disableDxgiVblankThread':'true'}), DEFAULTS)
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'UMEKO_DATA_DIR':temp}):
            self.assertEqual(startup_settings(), DEFAULTS)
            store = Store(Path(temp))
            self.assertEqual(store.data['desktop'], DEFAULTS)
            store.data['desktop'] = {'autoOpenSubmissions':False,'webDisplay':'external'}; store.save()
            expected = {**DEFAULTS, **store.data['desktop']}
            self.assertEqual(startup_settings(), expected)
            self.assertEqual(Store(Path(temp)).data['desktop'], expected)
        for value in ([], {'unknown':True}, {'autoOpenSubmissions':'false'}, {'webDisplay':'unsafe'},
                      {'chatWidthHints':'false'}, {'chatWidthHints':0}, {'disableDxgiVblankThread':1}):
            with self.subTest(value=value), self.assertRaises(ValueError): validate_patch(value)

    def test_graphics_compatibility_applies_from_saved_settings_on_windows_startup(self):
        variable = 'QT_D3D_NO_VBLANK_THREAD'
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'UMEKO_DATA_DIR': temp}):
            os.environ.pop(variable, None)
            controller = Controller(ROOT)
            try:
                self.assertFalse(controller.desktopSettings['disableDxgiVblankThread'])
                result = controller._umeko_control.execute(
                    {'operation': 'desktop.configure', 'arguments': {'config': {'disableDxgiVblankThread': True}}})
                self.assertFalse(result['ok'])
                self.assertFalse(controller.desktopSettings['disableDxgiVblankThread'])
                self.assertTrue(controller.saveDesktopSettings('{"disableDxgiVblankThread":true}'))
                self.assertNotIn(variable, os.environ)
                with patch('app.desktop_preferences.sys.platform', 'linux'):
                    configure_graphics(startup_settings())
                    self.assertNotIn(variable, os.environ)
                with patch('app.desktop_preferences.sys.platform', 'win32'):
                    configure_graphics(startup_settings())
                    self.assertEqual(os.environ.pop(variable), '1')
                self.assertTrue(controller.saveDesktopSettings('{"disableDxgiVblankThread":false}'))
                with patch('app.desktop_preferences.sys.platform', 'win32'):
                    configure_graphics(startup_settings())
                    self.assertNotIn(variable, os.environ)
                    os.environ[variable] = '1'
                    configure_graphics(startup_settings())
                    self.assertEqual(os.environ[variable], '1')
            finally:
                controller.close()

    def test_partial_settings_hot_update_without_retiring_running_session(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'UMEKO_DATA_DIR':temp}):
            controller = Controller(ROOT); record = controller._view
            try:
                record.process = Mock(); record.phase = 'running'
                with patch.object(controller._pool,'write') as write, patch.object(controller._pool,'retire') as retire:
                    self.assertTrue(controller.saveDesktopSettings(json.dumps({'webDisplay':'external'})))
                    self.assertTrue(record.busy)
                    self.assertFalse(controller.webviewAvailable)
                    self.assertEqual(write.call_args.args[1]['type'],'desktop_settings')
                    self.assertEqual(write.call_args.args[1]['webview']['display'],'external')
                    retire.assert_not_called()
                    self.assertTrue(controller.saveDesktopSettings(json.dumps({'autoOpenSubmissions':False})))
                    self.assertTrue(controller.saveDesktopSettings(json.dumps({'chatWidthHints':False})))
                    self.assertEqual(controller.config['desktop'], {**DEFAULTS, 'autoOpenSubmissions':False,
                                                                   'webDisplay':'external', 'chatWidthHints':False})
                    self.assertEqual(Store(Path(temp)).data['desktop'], controller.config['desktop'])
                    self.assertEqual(startup_settings(), controller.config['desktop'])
                    self.assertTrue(record.busy)
                    retire.assert_not_called()
                record.process = None
                result = controller._umeko_control.execute({'operation':'desktop.configure','arguments':{'config':{'webDisplay':'embedded','chatWidthHints':True}}})
                self.assertTrue(result['ok'], result)
                self.assertFalse(controller.config['desktop']['autoOpenSubmissions'])
                self.assertTrue(controller.config['desktop']['chatWidthHints'])
                bad = controller._umeko_control.execute({'operation':'desktop.configure','arguments':{'config':{'webDisplay':'unknown'}}})
                self.assertFalse(bad['ok'])
            finally:
                record.process = None; record.phase = 'idle'; controller.close()

    def test_team_switch_disables_saved_roles_without_discarding_them(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'UMEKO_DATA_DIR': temp}):
            controller = Controller(ROOT)
            try:
                view = controller._view
                view.draft_model_roles = {'planningModel': 'planned-before-upgrade'}
                self.assertEqual(controller.sessionModelRoles, {})
                self.assertFalse(controller.selectRoleModel('planningModel', ''))
                board = controller.desktopPlugins.global_agents.team_board
                with self.assertRaisesRegex(ValueError, '开启团队协作'):
                    board.execute('team_members', {})
                self.assertTrue(controller.saveDesktopSettings('{"teamCollaborationEnabled":true}'))
                self.assertEqual(controller.sessionModelRoles, view.draft_model_roles)
                bus = controller.desktopPlugins.global_agents
                member = {'id': 'fixture-member', 'name': 'Reviewer', 'model': 'prior'}
                bus.agents[member['id']] = member
                routes = [{'id': 'replacement', 'providerID': 'fixture'}]
                with patch.object(controller.gateway, 'models', return_value=routes):
                    self.assertTrue(controller.selectRoleModel('executionModel', 'replacement'))
                    self.assertTrue(controller.selectTeamMemberModel(member['id'], 'replacement'))
                    self.assertEqual(controller.teamMemberModels, [{'id': member['id'], 'name': member['name'], 'model': 'replacement'}])
                self.assertTrue(controller.saveDesktopSettings('{"teamCollaborationEnabled":false}'))
                self.assertEqual(controller.sessionModelRoles, {})
                self.assertEqual(view.draft_model_roles,
                                 {'planningModel': 'planned-before-upgrade', 'executionModel': 'replacement'})
            finally:
                controller.close()

    def test_auto_delivery_policy_does_not_remove_cards_or_affect_manual_actions(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'UMEKO_DATA_DIR':temp}):
            controller = Controller(ROOT)
            note = Path(temp)/'note.md'; note.write_text('# Notes')
            html = Path(temp)/'page.html'; html.write_text('<h1>Local page</h1>')
            documents=[]; webs=[]
            controller.documentRequested.connect(lambda *args:documents.append(args))
            controller.webRequested.connect(lambda *args:webs.append(args))
            media=[{'kind':'web','path':'http://127.0.0.1:8000/preview','url':'http://127.0.0.1:8000/preview','presentation':'webview'},
                   {'kind':'markdown','path':str(note)}, {'kind':'code','path':str(html)}]
            def submit(record):
                controller._handle_pi_event(record,{'type':'tool','id':'delivery','name':'submit_to_chatbox','state':'done','media':media})
            try:
                controller.saveDesktopSettings(json.dumps({'autoOpenSubmissions':False,'webDisplay':'external'}))
                with patch('app.preferences.QDesktopServices.openUrl',return_value=True) as browser:
                    submit(controller._view)
                    self.assertFalse(documents); self.assertFalse(webs); browser.assert_not_called()
                    self.assertEqual(controller._view.messages[-1]['tools'][-1]['media'],media)
                    self.assertTrue(controller.openWebPreview(media[0]['url'],'Preview'))
                    self.assertEqual(browser.call_count,1)
                    self.assertTrue(controller.openExternalHtml(str(html)))
                    self.assertEqual(Path(browser.call_args.args[0].toLocalFile()), html)
                    self.assertFalse(controller.openWebPreview('file:///tmp/unsafe',''))
                    self.assertFalse(controller.openWebPreview('https://user:secret@example.invalid/',''))
                    controller.saveDesktopSettings(json.dumps({'autoOpenSubmissions':True}))
                    submit(controller._view)
                    self.assertEqual(browser.call_count,4)
                    self.assertEqual(len(documents),1); self.assertEqual(documents[0][0],str(note))
                    self.assertFalse(webs)
                    background = controller._new_view('')
                    submit(background)
                    self.assertEqual(browser.call_count,4)
            finally: controller.close()

    def test_embedded_delivery_keeps_legacy_routing_and_save_failure_rolls_back(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'UMEKO_DATA_DIR':temp}):
            controller = Controller(ROOT)
            try:
                events=[];controller.webRequested.connect(lambda *args:events.append(args))
                with patch('app.webview._configuration',{'available':True}), patch('app.preferences.QDesktopServices.openUrl') as browser:
                    self.assertTrue(controller.openWebPreview('http://127.0.0.1:8000/preview','Preview'))
                    self.assertEqual(events,[('http://127.0.0.1:8000/preview','Preview')]);browser.assert_not_called()
                with patch.object(controller.store,'save',side_effect=OSError('fixture write failure')):
                    self.assertFalse(controller.saveDesktopSettings(json.dumps({'webDisplay':'external'})))
                self.assertEqual(controller.config['desktop'],DEFAULTS)
            finally:controller.close()
