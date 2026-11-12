"""Withheld Widgets must not leak through app staging or SDK examples."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('desktop_resource_builder', ROOT/'scripts/build-desktop-plugin-resources.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class DesktopResourceTests(unittest.TestCase):
    def test_actual_resources_exclude_task_records_and_remove_previous_staging(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            staged = base/'builtin-widgets'
            stale = staged/'task-records/manifest.json'
            stale.parent.mkdir(parents=True)
            stale.write_text('stale previous build', encoding='utf-8')
            archive = builder.build_resources(ROOT, base/'sdk', staged)
            self.assertFalse((staged/'task-records').exists())
            self.assertTrue((ROOT/'umeko-plugins/task-records/manifest.json').is_file())
            self.assertEqual((staged/'scheduled-tasks/qml/Main.qml').read_bytes(),
                             (ROOT/'umeko-plugins/scheduled-tasks/qml/Main.qml').read_bytes())
            self.assertEqual(json.loads((staged/'scheduled-tasks/manifest.json').read_text(encoding='utf-8'))['icon'], 'clock')
            with zipfile.ZipFile(archive) as stream:
                self.assertFalse(any(name.startswith('examples/task-records/') for name in stream.namelist()))
                self.assertTrue(stream.read('examples/scheduled-tasks/qml/ScheduleLabel.qml'))
                self.assertIn('clock', {row['id'] for row in json.loads(stream.read('umeko_plugin_sdk/icons.json'))})


if __name__ == '__main__':
    unittest.main()
