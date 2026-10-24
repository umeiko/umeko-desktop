import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication
from app.controller import Controller

APP = QCoreApplication.instance() or QCoreApplication([])
ROOT = Path(__file__).resolve().parents[1]


class CommonProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {'UMEKO_DATA_DIR': self.temp.name})
        self.environment.start()
        self.controller = Controller(ROOT)

    def tearDown(self):
        self.controller.close()
        self.environment.stop()
        self.temp.cleanup()

    def test_six_presets_are_ready_and_repeated_accounts_have_unique_routes(self):
        self.assertEqual({p['id'] for p in self.controller.commonProviders},
                         {'claude', 'codex', 'kimi', 'deepseek', 'glm', 'minimax'})
        for preset in self.controller.commonProviders:
            self.assertTrue(self.controller.addCommonProvider(preset['id'], 'fixture-key', ''))
            self.assertTrue(self.controller.addCommonProvider(preset['id'], 'fixture-key-2', ''))
            rows = [p for p in self.controller.store.data['providers'] if p.get('presetId') == preset['id']]
            self.assertEqual([p['name'] for p in rows], [preset['name'], preset['name']+'(2)'])
            self.assertEqual([m['upstream'] for m in rows[1]['models']], [m['upstream'] for m in preset['models']])
            self.assertEqual(rows[1]['baseUrl'], preset['baseUrl'])
            self.assertEqual(self.controller.config['selectedProvider'], rows[1]['id'])
            self.assertNotIn('key', next(p for p in self.controller.config['providers'] if p['id'] == rows[1]['id']))
        aliases = [m['alias'] for p in self.controller.store.data['providers'] for m in p['models']]
        self.assertEqual(len(aliases), len(set(aliases)))

    def test_subscription_presets_keep_regions_separate_and_current_models(self):
        presets = {p['id']: p for p in self.controller.commonProviders}
        glm, minimax = presets['glm'], presets['minimax']
        zai = glm['international']
        self.assertTrue(glm['subscription'] and minimax['subscription'])
        self.assertEqual(glm['baseUrl'], 'https://open.bigmodel.cn/api/coding/paas/v4')
        self.assertEqual(glm['keyUrl'], 'https://bigmodel.cn/coding-plan/personal/overview')
        self.assertEqual([(m['upstream'], m['vision']) for m in glm['models']],
                         [('glm-5.3', False), ('glm-5.3-flash', True)])
        self.assertEqual(zai['baseUrl'], 'https://api.z.ai/api/coding/paas/v4')
        self.assertEqual(zai['keyUrl'], 'https://z.ai/manage-apikey/apikey-list')
        self.assertEqual(zai['models'], glm['models'])
        self.assertEqual(minimax['baseUrl'], 'https://api.minimax.cn/v1')
        self.assertEqual(minimax['keyUrl'], 'https://platform.minimax.cn/console/plan')
        self.assertEqual(minimax['models'][0]['upstream'], 'MiniMax-M3.1-Flash')
        self.assertEqual(minimax['international']['baseUrl'], 'https://api.minimax.io/v1')
        self.assertEqual(minimax['international']['keyUrl'], 'https://platform.minimax.io/console/plan')
        for preset in (glm, minimax):
            self.assertTrue(self.controller.addCommonProvider(preset['id'], 'fixture-subscription-key', '工作号'))
            provider = self.controller.store.data['providers'][-1]
            self.assertEqual(provider['name'], preset['name'] + '(工作号)')
            self.assertEqual(provider['api'], 'openai')
            self.assertEqual(provider['presetId'], preset['id'])
            self.assertNotIn('fixture-subscription-key', self.controller.store.path.read_text())

    def test_region_accounts_keep_credentials_names_and_aliases_separate(self):
        c = self.controller
        for preset_id, domestic_name, global_name in [('glm', 'GLM', 'Z.ai'), ('minimax', 'MiniMax', 'MiniMax(2)')]:
            self.assertTrue(c.addCommonProvider(preset_id, 'fixture-domestic', ''))
            domestic = c.store.data['providers'][-1]
            self.assertTrue(c.addCommonProvider(preset_id, 'fixture-international', '', 'international'))
            international = c.store.data['providers'][-1]
            self.assertEqual((domestic['name'], international['name']), (domestic_name, global_name))
            self.assertEqual((domestic['presetRegion'], international['presetRegion']), ('cn', 'international'))
            self.assertNotEqual(domestic['baseUrl'], international['baseUrl'])
            self.assertEqual([m['upstream'] for m in domestic['models']], [m['upstream'] for m in international['models']])
            self.assertTrue({m['alias'] for m in domestic['models']}.isdisjoint(m['alias'] for m in international['models']))
            self.assertTrue(c.saveProvider(international['id'], international['name'] + '(Work)', international['api'],
                                           international['baseUrl'], '', json.dumps(international['models'])))
            saved = c.gateway.provider(international['id'])
            self.assertEqual((saved['presetId'], saved['presetRegion'], saved['key']),
                             (preset_id, 'international', 'fixture-international'))
            self.assertEqual(c.gateway.provider(domestic['id'])['key'], 'fixture-domestic')
        self.assertTrue(c.addCommonProvider('glm', 'fixture-international-2', '', 'international'))
        self.assertEqual(c.store.data['providers'][-1]['name'], 'Z.ai(2)')
        before = len(c.store.data['providers'])
        self.assertFalse(c.addCommonProvider('kimi', 'fixture', '', 'international'))
        self.assertFalse(c.addCommonProvider('glm', 'fixture', '', 'unknown-region'))
        self.assertEqual(len(c.store.data['providers']), before)

    def test_custom_names_numbering_and_deleted_account_collisions(self):
        c = self.controller
        self.assertTrue(c.addCommonProvider('kimi', 'fixture', ' Work '))
        self.assertTrue(c.addCommonProvider('kimi', 'fixture', ''))
        self.assertTrue(c.addCommonProvider('kimi', 'fixture', ''))
        rows = c.store.data['providers']
        self.assertEqual([p['name'] for p in rows], ['Kimi(Work)', 'Kimi(2)', 'Kimi(3)'])
        c.removeProvider(rows[1]['id'])
        self.assertTrue(c.addCommonProvider('kimi', 'fixture', ''))
        self.assertEqual(c.store.data['providers'][-1]['name'], 'Kimi(4)')
        before = len(c.store.data['providers'])
        for preset, key, alias in [('kimi', '', ''), ('missing', 'fixture', ''), ('kimi', 'fixture', 'Work'), ('kimi', 'fixture', 'bad\nname')]:
            self.assertFalse(c.addCommonProvider(preset, key, alias))
            self.assertEqual(len(c.store.data['providers']), before)

    def test_edit_keeps_responses_transport_and_credentials(self):
        c = self.controller
        self.assertTrue(c.addCommonProvider('codex', 'fixture', 'Work'))
        provider = c.store.data['providers'][-1]
        self.assertTrue(c.saveProvider(provider['id'], 'Codex(Updated)', 'openai', provider['baseUrl'], '', json.dumps(provider['models'])))
        saved = c.gateway.provider(provider['id'])
        self.assertEqual((saved['wireApi'], saved['presetId'], saved['key']), ('responses', 'codex', 'fixture'))
