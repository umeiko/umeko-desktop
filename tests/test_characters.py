import json
import os
import tempfile
import unittest
import zipfile
import stat
import importlib.util
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QImage, QGuiApplication
from PySide6.QtCore import QUrl
from app.characters import read_character, CONFIG_DEFAULTS
from app.controller import Controller
from app.umeko_control import UmekoControl

ROOT = Path(__file__).resolve().parents[1]
# Two-frame, 1px GIF fixture, with a global palette and looping application block.
GIF = (b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff'
       b'\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00' +
       b''.join(b'\x21\xf9\x04\x00\x0a\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02'+data+b'\x00'
                for data in (b'\x44\x01',b'\x4c\x01')) + b'\x3b')

class CharacterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ,UMEKO_DATA_DIR=str(self.root/'profile'))
        self.env.start()
        self.backend = Controller(ROOT)
        self.folder = self.root/'input'
        self.folder.mkdir()
        (self.folder/'loading.gif').write_bytes(GIF)
        image = QImage(16,16,QImage.Format.Format_ARGB32)
        image.fill(0xffaa4466)
        self.assertTrue(image.save(str(self.folder/'portrait.png')))
        self.manifest = {'format':'umeko-character','version':1,'id':'test-character','name':'Test Character',
                         'assets':{'reply':'portrait.png','loading':'loading.gif'},'lines':{'tap':['Hello']}}
        self.file = self.folder/'manifest.json'
        self.write()

    def tearDown(self):
        self.backend.close()
        self.env.stop()
        self.temp.cleanup()

    def write(self):
        self.file.write_text(json.dumps(self.manifest),encoding='utf-8')

    def test_import_persists_independent_assets_live_and_falls_back(self):
        b = self.backend
        self.assertEqual(b.characterStyle['id'],'yanami')
        control = b._umeko_control
        result = control.execute({'operation':'characters.import','arguments':{'path':str(self.file)}})
        self.assertTrue(result['ok'],result)
        self.assertEqual(b.characterStyle['id'],'test-character')
        self.assertIn('/characters/test-character/',b.characterStyle['assets']['reply'])
        self.assertNotIn('catch',b.characterStyle['assets'])
        self.assertEqual(Path(QUrl(b.characterStyle['assets']['loading']).toLocalFile()).read_bytes(),GIF)
        b.setTheme('dark')
        self.assertEqual(b.characterStyle['id'],'test-character')
        self.assertEqual(json.loads(b.store.path.read_text())['character'],'test-character')
        before = b.characterStyle['assets']['reply']
        self.manifest['lines']['tap'] = ['Updated']
        self.write()
        self.assertTrue(b.importCharacter(str(self.file)))
        self.assertEqual(b.characterStyle['lines']['tap'],['Updated'])
        self.assertNotEqual(before,b.characterStyle['assets']['reply'])
        Path(QUrl(b.characterStyle['assets']['reply']).toLocalFile()).unlink()
        self.assertNotIn('reply',b.characterStyle['assets'])
        self.assertTrue(b.removeCharacter('test-character'))
        self.assertEqual(b.characterStyle['id'],'yanami')
        self.assertFalse(b.removeCharacter('komari'))

    def test_invalid_resources_do_not_replace_current_character(self):
        for value in ('../portrait.png','https://example.com/a.png','/a.png','a\\b.png','missing.png'):
            with self.subTest(value=value):
                self.manifest['assets']['reply'] = value
                self.write()
                self.assertFalse(self.backend.importCharacter(str(self.file)))
                self.assertEqual(self.backend.characterStyle['id'],'yanami')
        self.manifest['assets']['reply'] = 'portrait.png'
        self.manifest['id'] = 'komari'
        self.write()
        self.assertFalse(self.backend.importCharacter(str(self.file)))

    def test_failed_reimport_preserves_installed_manifest_and_settings(self):
        b=self.backend
        self.assertTrue(b.importCharacter(str(self.file)))
        manifest=b.store.directory/'characters/test-character/manifest.json'
        original=manifest.read_bytes()
        source=b.characterStyle['assets']['reply']
        self.manifest['name']='Replacement'
        self.write()
        for target in ('app.characters.write_character_manifest', 'app.storage.Store.save'):
            with self.subTest(target=target), patch(target,side_effect=OSError('Write failed')):
                self.assertFalse(b.importCharacter(str(self.file)))
            self.assertEqual(manifest.read_bytes(),original)
            self.assertEqual(b.characterStyle['assets']['reply'],source)
            self.assertEqual(b.store.data['character'],'test-character')

    def test_wrapped_models_and_hidden_builtin_are_queryable(self):
        b = self.backend
        self.assertTrue(any(row['id']=='komari' and row['builtin'] for row in b.characterPacks))
        self.assertTrue(b.selectCharacter('komari'))
        self.assertEqual(b.characterStyle['id'],'komari')
        b.store.data['providers'] = [{'id':'configured-id','name':'Demo','api':'openai','models':[{'upstream':'upstream-name','alias':'call-alias'}]}]
        result = b._umeko_control.execute({'operation':'models.list'})
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['models'][0]['model'],'umeko/call-alias')
        self.assertEqual(result['models'][0]['id'],'call-alias')
        self.assertNotIn('configured-id',json.dumps(result))

    def test_komari_tips_keep_each_original_tutorial_topic(self):
        tips=read_character(ROOT/'app/icons/characters/komari/manifest.json')['_configuration']['scenes']['loading']['tips']
        self.assertEqual(len(tips),len(CONFIG_DEFAULTS['scenes']['loading']['tips']))
        topics=('外观','Pi 扩展','子代理','OpenClaw','供应商','排查','Token','文件路径','预览','右上角','对话','Ctrl+S','别名','上下文','验收标准','计划','账号','分支')
        self.assertEqual(len(tips),len(topics))
        for tip,topic in zip(tips,topics): self.assertIn(topic,tip)

    def make_zip(self, entries, name='character.zip'):
        target=self.root/name
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
            for path, data in entries: archive.writestr(path,data)
        return target

    def zip_entries(self, prefix=''):
        return [(prefix+path.name,path.read_bytes()) for path in self.folder.iterdir()]

    def test_all_builtin_characters_are_complete_and_protected(self):
        b=self.backend
        self.assertEqual({row['id'] for row in b.characterPacks if row['builtin']},{'yanami','komari','kaju','tiara','whale-girl'})
        for identifier in ('yanami','komari','kaju','tiara','whale-girl'):
            self.assertFalse(b.removeCharacter(identifier))
            self.manifest['id']=identifier;self.write()
            self.assertFalse(b.importCharacter(str(self.make_zip(self.zip_entries()))))
        self.assertTrue(b.selectCharacter('kaju'))
        self.assertEqual(b.characterStyle['name'],'温水佳树')
        self.assertEqual(len(b.characterStyle['assets']),10)
        for value in b.characterStyle['assets'].values(): self.assertTrue(Path(QUrl(value).toLocalFile()).is_file())
        self.assertIn('佳树',b.characterStyle['dialogue']['welcome']['greetings'][0])
        b.setTheme('yanami')
        self.assertEqual(b.characterStyle['id'],'kaju')
        self.assertEqual(json.loads(b.store.path.read_text())['character'],'kaju')
        self.assertTrue(all(row['portrait'].startswith('file:') for row in b.characterPacks))

    def test_whale_girl_main_art_dialogue_and_subagent_are_independent(self):
        b = self.backend
        pack = read_character(ROOT/'app/icons/characters/whale-girl/manifest.json',
                              check_images=True)
        self.assertEqual(len(pack['assets']), 10)
        self.assertTrue(b.selectCharacter('whale-girl'))
        self.assertEqual(b.characterStyle['name'], '鲸鱼娘')
        for text in b.characterStyle['dialogue']['welcome']['greetings']:
            self.assertTrue(text.startswith('人，'))
        self.assertTrue(any('Pi Agent' in text for text in
                            b.characterStyle['dialogue']['loading']['tips']))
        self.assertEqual(b.characterStyle['easterEgg']['line'],
                         '人，你给我吃米，人，日后我会放你一马的')
        self.assertTrue(b.selectSubagentCharacter(3, 'whale-girl'))
        self.assertTrue(b.selectCharacter('tiara'))
        self.assertEqual(b.characterNames[3], '鲸鱼娘')
        self.assertFalse(b.removeCharacter('whale-girl'))

    def test_kazuhiko_is_subagent_only_and_is_protected(self):
        b = self.backend
        self.assertNotIn('kazuhiko', {row['id'] for row in b.characterPacks})
        self.assertIn('kazuhiko', {row['id'] for row in b.subagentCharacterPacks})
        pack = read_character(ROOT/'app/icons/characters/kazuhiko/manifest.json', check_images=True)
        self.assertEqual(set(pack['assets']), {'avatarSmile', 'reply', 'catch'})
        self.assertFalse(b.selectCharacter('kazuhiko'))
        self.assertTrue(b.selectSubagentCharacter(0, 'kazuhiko'))
        self.assertEqual(b.characterNames[0], '温水和彦')
        self.assertFalse(b.removeCharacter('kazuhiko'))
        self.manifest['id'] = 'kazuhiko'
        self.write()
        self.assertFalse(b.importCharacter(str(self.file)))
        self.backend.close()
        self.backend = Controller(ROOT)
        self.assertEqual(self.backend.characterNames[0], '温水和彦')
        self.assertEqual(self.backend.characterStyle['id'], 'yanami')

    def test_tiara_main_and_subagent_selection_are_independent_and_persist(self):
        b=self.backend
        self.assertTrue(b.selectCharacter('tiara'))
        self.assertEqual(b.characterStyle['name'],'马剃天爱星')
        pack=read_character(ROOT/'app/icons/characters/tiara/manifest.json',check_images=True)
        self.assertEqual(len(pack['assets']),10)
        self.assertIn('天爱星',b.characterStyle['dialogue']['welcome']['greetings'][0])
        original=b.characterStyle['subagents']
        self.assertTrue(b.configureCharacter(json.dumps({'scenes':{'welcome':{'tap':['keep my line']}}})))
        self.assertTrue(b.selectSubagentCharacter(2,'tiara'))
        self.assertEqual(b.characterStyle['id'],'tiara')
        roles=b.characterStyle['subagents']
        self.assertEqual(len(roles),4)
        self.assertEqual(roles[2]['name'],'马剃天爱星')
        self.assertEqual(roles[0],original[0])
        for key in ('avatar','catch'):
            self.assertTrue(Path(QUrl(roles[2][key]).toLocalFile()).is_file())
            self.assertIn('/character-assets/',roles[2][key])
        self.assertEqual(b.characterStyle['dialogue']['welcome']['tap'],['keep my line'])
        b._init_characters()
        self.assertEqual(b.characterStyle['subagents'][2],roles[2])
        for slot,identifier in [(-1,'tiara'),(4,'tiara'),(0,'missing')]:
            self.assertFalse(b.selectSubagentCharacter(slot,identifier))
        self.assertEqual(b.characterStyle['subagents'],roles)
        self.assertTrue(b.selectCharacter('komari'))
        self.assertEqual(b.characterStyle['subagents'][2]['name'],'马剃天爱星')
        self.assertTrue(b.selectSubagentCharacter(2,''))
        self.assertEqual(b.characterStyle['subagents'][2],original[2])
        self.assertEqual(b.characterStyle['subagents'][0],original[0])

    def test_subagent_picker_caches_partial_pack_portrait_before_removal(self):
        b=self.backend
        self.assertTrue(b.importCharacter(str(self.file)))
        self.assertTrue(b.selectSubagentCharacter(0,'test-character'))
        portrait=Path(QUrl(b.characterStyle['subagents'][0]['avatar']).toLocalFile())
        self.assertEqual(portrait.read_bytes(),(self.folder/'portrait.png').read_bytes())
        self.assertTrue(b.removeCharacter('test-character'))
        self.assertTrue(portrait.is_file())
        self.assertEqual(b.characterStyle['subagents'][0]['name'],'Test Character')

    def test_zip_import_root_wrapped_reimport_and_cleanup(self):
        b=self.backend
        for prefix in ('','my-character/'):
            package=self.make_zip(self.zip_entries(prefix))
            self.assertTrue(b.importCharacter(QUrl.fromLocalFile(str(package)).toString()))
            self.assertEqual(b.characterStyle['id'],'test-character')
            self.assertEqual(Path(QUrl(b.characterStyle['assets']['loading']).toLocalFile()).read_bytes(),GIF)
        self.assertTrue(b.removeCharacter('test-character'))
        self.assertEqual(b.characterStyle['id'],'yanami')

    def test_invalid_zip_preserves_current_character_and_installed_files(self):
        b=self.backend
        self.assertTrue(b.importCharacter(str(self.file)))
        installed=b.store.directory/'characters/test-character/manifest.json'
        original=installed.read_bytes()
        cases=[
            [('manifest.json',self.file.read_bytes()),('../outside.png',b'bad')],
            [('manifest.json',self.file.read_bytes()),('/absolute.png',b'bad')],
            [('manifest.json',self.file.read_bytes()),('a\\b.png',b'bad')],
            [('manifest.json',self.file.read_bytes()),('portrait.png',b'bad'),('PORTRAIT.PNG',b'bad')],
            [('manifest.json',self.file.read_bytes()),('folder',b'bad'),('folder/a.png',b'bad')],
            [('wrapper/manifest.json',self.file.read_bytes()),('outside.png',b'bad')],
            [('wrapper/deep/manifest.json',self.file.read_bytes())],
            [('a/manifest.json',self.file.read_bytes()),('b/manifest.json',self.file.read_bytes())],
            [('manifest.json',self.file.read_bytes()),('script.py',b'print(1)')],
            [('manifest.json',self.file.read_bytes()),('huge.png',b'x'*(12*1024*1024+1))],
            [('manifest.json',self.file.read_bytes())]+[(f'{i}.png',b'x') for i in range(128)],
        ]
        link=zipfile.ZipInfo('portrait.png');link.create_system=3;link.external_attr=(stat.S_IFLNK|0o777)<<16
        cases.append([('manifest.json',self.file.read_bytes()),(link,b'/tmp/elsewhere')])
        for entries in cases:
            with self.subTest(entries=[str(x[0]) for x in entries[:4]]):
                self.assertFalse(b.importCharacter(str(self.make_zip(entries))))
                self.assertEqual(b.characterStyle['id'],'test-character')
                self.assertEqual(installed.read_bytes(),original)
        self.assertFalse((self.root/'outside.png').exists())
        bad=self.root/'invalid.zip';bad.write_bytes(b'not a zip')
        self.assertFalse(b.importCharacter(str(bad)))

    def test_exported_skill_can_package_an_importable_character(self):
        script=ROOT/'character_dev/skills/create-umeko-character/scripts/package.py'
        spec=importlib.util.spec_from_file_location('package_character',script)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        package=module.package(self.folder,self.root/'made-by-skill.zip')
        self.assertTrue(self.backend.importCharacter(str(package)))
        from runpy import run_path
        run_path(str(ROOT/'scripts/build-provider-resources.py'),run_name='__main__')
        exported=self.root/'skill.zip'
        self.assertTrue(self.backend.exportCharacterSkill(QUrl.fromLocalFile(str(exported)).toString()))
        with zipfile.ZipFile(exported) as archive:
            self.assertIn('create-umeko-character/SKILL.md',archive.namelist())
            self.assertIn('create-umeko-character/scripts/package.py',archive.namelist())
            self.assertFalse(any(name.endswith('.pyc') for name in archive.namelist()))

    def test_scene_text_roles_and_portraits_are_configurable_and_persistent(self):
        b = self.backend
        self.assertTrue(b.selectCharacter('komari'))
        self.assertIn('那、那个',b.characterStyle['dialogue']['reply']['tap'][0])
        hub=b.subagents
        hub.merge(b._view,{'id':'role-fixture','avatarSlot':0,'status':'completed'})
        self.assertEqual(hub.agents[0]['name'],'烧盐柠檬')
        config={'scenes':{'reply':{'tap':['custom reply'],'celebration':'custom finish'},'layout':{'tooNarrow':'custom boundary'}},
                'subagents':[{'name':'Custom Worker','avatar':str(self.folder/'portrait.png'),'catch':str(self.folder/'loading.gif'),
                              'tap':['custom role'],'celebration':'role finished'}]}
        result=b._umeko_control.execute({'operation':'characters.configure','arguments':{'config':config}})
        self.assertTrue(result['ok'],result)
        self.assertEqual(hub.agents[0]['name'],'Custom Worker')
        self.assertEqual(b.characterNames[1],'小鞠知花')
        self.assertEqual(b.characterStyle['dialogue']['reply']['tap'],['custom reply'])
        self.assertEqual(b.characterStyle['subagents'][0]['tap'],['custom role'])
        self.assertIn('/character-assets/',b.characterStyle['subagents'][0]['avatar'])
        saved=json.loads((b.store.directory/'character-config.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['subagents'][0]['name'],'Custom Worker')
        b._init_characters()
        self.assertEqual(b.characterNames[0],'Custom Worker')
        self.assertFalse(b.configureCharacter(json.dumps({'scenes':{'unknown':{}}})))
        self.assertEqual(b.characterNames[0],'Custom Worker')
        self.assertTrue(b.configureCharacter('{}'))
        self.assertEqual(hub.agents[0]['name'],'烧盐柠檬')
        self.assertIn('那、那个',b.characterStyle['dialogue']['reply']['tap'][0])

if __name__=='__main__': unittest.main()
