import importlib.util
import json
import re
import unittest
from pathlib import Path

from app.umeko_control import redacted

ROOT = Path(__file__).resolve().parents[1]


class UmekoControlTests(unittest.TestCase):
    def test_redaction_preserves_settings_and_metadata(self):
        values = {'maxTokens': 32768, 'hasKey': True, 'secret': True, 'key': 'fixture-key',
                  'credentials': {'custom': 'private'}, 'headers': {'Authorization': 'Bearer fixture'},
                  'env': {'EXAMPLE_API_KEY': 'private'}, 'models': [{'id': 'model', 'contextWindow': 128000}]}
        output = redacted(values)
        self.assertEqual(output['maxTokens'], 32768)
        self.assertIs(output['secret'], True)
        self.assertIs(output['hasKey'], True)
        self.assertEqual(output['credentials'], '[redacted]')
        self.assertEqual(output['headers']['Authorization'], '[redacted]')
        self.assertEqual(output['env']['EXAMPLE_API_KEY'], '[redacted]')
        self.assertEqual(output['models'], values['models'])
        self.assertEqual(values['key'], 'fixture-key')

    def test_reference_and_document_links_match_the_bundled_api(self):
        spec = importlib.util.spec_from_file_location('umeko_docs', ROOT/'scripts/build-umeko-docs.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        docs = ROOT/'runtime/umeko-docs'
        self.assertEqual((docs/'operations.md').read_text(encoding='utf-8'), module.generate())
        for file in docs.glob('*.md'):
            for name in re.findall(r'\]\(([^)#]+\.md)\)', file.read_text(encoding='utf-8')):
                self.assertTrue((file.parent/name).is_file(), (file, name))
        operations = json.loads((ROOT/'runtime/umeko-operations.json').read_text())['operations']
        self.assertGreater(len(operations), 50)
        for name, entry in operations.items():
            self.assertLessEqual(len(entry['args']), 6, name)
            self.assertEqual(len({arg[0] for arg in entry['args']}), len(entry['args']))


if __name__ == '__main__': unittest.main()
