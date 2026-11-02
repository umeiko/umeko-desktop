import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtCore import QCoreApplication
from app.desktop_preferences import DEFAULTS, normalize, startup_settings, validate_patch
from app.storage import Store
from app.controller import Controller

ROOT = Path(__file__).resolve().parents[1]
APP = QCoreApplication.instance() or QCoreApplication([])


class DesktopPreferencesTests(unittest.TestCase):
    def test_defaults_normalization_and_pre_application_read(self):
        self.assertEqual(normalize(None), DEFAULTS)
        self.assertEqual(normalize({'autoOpenSubmissions':1,'webDisplay':[],'chatWidthHints':0}), DEFAULTS)
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'UMEKO_DATA_DIR':temp}):
            self.assertEqual(startup_settings(), DEFAULTS)
            store = Store(Path(temp))
            self.assertEqual(store.data['desktop'], DEFAULTS)
            store.data['desktop'] = {'autoOpenSubmissions':False,'webDisplay':'external'}; store.save()
            expected = {**DEFAULTS, **store.data['desktop']}
            self.assertEqual(startup_settings(), expected)
            self.assertEqual(Store(Path(temp)).data['desktop'], expected)
        for value in ([], {'unknown':True}, {'autoOpenSubmissions':'false'}, {'webDisplay':'unsafe'}, {'chatWidthHints':'false'}, {'chatWidthHints':0}):
            with self.subTest(value=value), self.assertRaises(ValueError): validate_patch(value)

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
                    self.assertEqual(controller.config['desktop'], {'autoOpenSubmissions':False,'webDisplay':'external','chatWidthHints':False})
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
