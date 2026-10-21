import copy
import json
import tempfile
import unittest
from pathlib import Path

from app.themes import normalize_theme, read_theme, theme_library


class ThemesTest(unittest.TestCase):
    def setUp(self):
        self.theme = {'format':'umeko-theme','version':1,'id':'moon','name':'月夜','base':'dark','colors':{'bg':'#121122','buttonText':'#FFFFFF'}}

    def test_valid_and_inheritance(self):
        self.assertEqual(normalize_theme(self.theme), self.theme)
        self.theme['colors'] = {}
        self.assertEqual(normalize_theme(self.theme)['colors'], {})

    def test_invalid_input_and_paths(self):
        for key, value in [('format','javascript'),('version',True),('version','1'),('id','../moon'),('id','light/../../x'),('name',''),('base','custom'),('colors',{'unknown':'#112233'}),('colors',{'bg':'url(http://example.invalid)'}),('colors',{'bg':'#11223344'})]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                normalize_theme(dict(self.theme, **{key:value}))

    def test_library_tolerates_invalid_and_duplicate_saved_entries(self):
        self.assertEqual(theme_library([None, {}, self.theme, copy.deepcopy(self.theme)]), [self.theme])
        self.assertEqual(theme_library('bad'), [])
        self.assertEqual(len(theme_library([dict(self.theme,id='theme-'+str(i)) for i in range(40)])), 32)

    def test_size_bom_and_prompt_example(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory)/'theme.json'
            file.write_text(json.dumps(self.theme),encoding='utf-8-sig')
            self.assertEqual(read_theme(file),self.theme)
            file.write_bytes(b' '*65537)
            with self.assertRaises(ValueError): read_theme(file)
        text = (Path(__file__).parents[1]/'app/theme-prompt.txt').read_text(encoding='utf-8')
        example = json.JSONDecoder().raw_decode(text[text.index('{'):])[0]
        self.assertEqual(normalize_theme(example)['base'],'dark')


if __name__ == '__main__': unittest.main()
