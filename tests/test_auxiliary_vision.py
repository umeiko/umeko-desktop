import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QSignalSpy
from app.controller import Controller
from app.auxiliary_vision import normalize

ROOT=Path(__file__).resolve().parents[1]

class AuxiliaryVisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QCoreApplication.instance() or QCoreApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.env=patch.dict(os.environ,UMEKO_DATA_DIR=str(Path(self.temp.name)/'profile'));self.env.start();self.addCleanup(self.env.stop)
        self.b=Controller(ROOT);self.addCleanup(self.b.close)
        self.b.store.data['providers']=[{'id':'p','name':'Fixture','api':'internal','models':[
            {'alias':'text','upstream':'text','vision':False,'visionAuto':False},
            {'alias':'eyes','upstream':'vision-upstream-model','vision':True,'visionAuto':False}]}]
    def test_selection_and_independent_switches_persist(self):
        self.assertEqual([row['model'] for row in self.b.auxiliaryVisionModels],['eyes'])
        self.assertTrue(self.b.saveAuxiliaryVision(json.dumps({'providerId':'p','model':'eyes'})))
        self.assertEqual(self.b._auxiliary_vision()['modelName'],'vision-upstream-model')
        self.assertEqual(self.b._auxiliary_vision()['providerName'],'Fixture')
        self.assertTrue(self.b._can_analyze_attachments('text','p'))
        self.assertFalse(self.b._can_analyze_attachments('eyes','p'))
        self.assertTrue(self.b.saveAuxiliaryVision('{"autoAnalyze":false}'))
        self.assertFalse(self.b._can_analyze_attachments('text','p'))
        self.assertTrue(self.b.store.data['auxiliaryVision']['toolEnabled'])
        from app.storage import Store
        self.assertEqual(Store().data['auxiliaryVision'],self.b.store.data['auxiliaryVision'])
    def test_invalid_target_and_types_leave_configuration_intact(self):
        before=dict(self.b.store.data['auxiliaryVision'])
        self.assertFalse(self.b.saveAuxiliaryVision('{"providerId":"p","model":"text"}'))
        self.assertFalse(self.b.saveAuxiliaryVision('{"autoAnalyze":1}'))
        self.assertEqual(self.b.store.data['auxiliaryVision'],before)
        with self.assertRaises(ValueError):normalize({'unrecognized':True})
    def test_missing_configuration_follows_original_path(self):
        self.assertFalse(self.b._can_analyze_attachments('text','p'))

    def test_switch_save_is_scoped_and_noop_does_not_invalidate_pi(self):
        changed = QSignalSpy(self.b.changed)
        vision = QSignalSpy(self.b.auxiliaryVisionSettingsChanged)
        with patch.object(self.b, '_restart_pi') as restart:
            self.assertTrue(self.b.saveAuxiliaryVision('{"autoAnalyze":false}'))
            self.assertFalse(self.b.auxiliaryVisionSettings['autoAnalyze'])
            self.assertEqual(changed.count(), 0)
            self.assertEqual(vision.count(), 1)
            restart.assert_called_once()
            self.assertTrue(self.b.saveAuxiliaryVision('{"autoAnalyze":false}'))
            self.assertEqual(vision.count(), 1)
            restart.assert_called_once()

    def test_failed_save_preserves_switch_and_running_kernel(self):
        before = self.b.auxiliaryVisionSettings
        vision = QSignalSpy(self.b.auxiliaryVisionSettingsChanged)
        with patch.object(self.b.store, 'save', side_effect=OSError('fixture write failure')), patch.object(self.b, '_restart_pi') as restart:
            self.assertFalse(self.b.saveAuxiliaryVision('{"autoAnalyze":false}'))
            self.assertEqual(self.b.auxiliaryVisionSettings, before)
            self.assertEqual(vision.count(), 0)
            restart.assert_not_called()
