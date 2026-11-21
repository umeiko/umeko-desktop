"""Default native folders preserve user ownership across launches and upgrades."""
import hashlib, json, shutil, tempfile, unittest
from pathlib import Path
from app.bundled_skills import install_bundled, describe_bundled
ROOT=Path(__file__).resolve().parents[1]

class BundledSkillTests(unittest.TestCase):
    def test_bundled_descriptions_cover_both_languages_and_preserve_custom_skills(self):
        source=ROOT/'bundled-skills'
        translations=json.loads((source/'descriptions.json').read_text(encoding='utf-8'))
        names={row['name'] for row in json.loads((source/'sources.json').read_text())}
        self.assertEqual(set(translations),names)
        for value in translations.values():
            self.assertEqual(set(value),{'zh','en'})
            self.assertTrue(all(value.values()))
        with tempfile.TemporaryDirectory() as temporary:
            agent=Path(temporary)/'agent';folder=agent/'skills/pdf';folder.mkdir(parents=True)
            shutil.copyfile(source/'pdf/SKILL.md',folder/'SKILL.md')
            row={'path':str(folder/'SKILL.md'),'description':'Original instructions'}
            describe_bundled([row],agent)
            self.assertEqual(row['descriptions'],translations['pdf'])
            self.assertEqual(row['description'],'Original instructions')
            (folder/'SKILL.md').write_text('---\nname: pdf\ndescription: User edit\n---\nChanged')
            custom={'path':str(folder/'SKILL.md'),'description':'User edit'}
            describe_bundled([custom],agent)
            self.assertNotIn('descriptions',custom)
            project=Path(temporary)/'project/pdf';project.mkdir(parents=True)
            shutil.copyfile(source/'pdf/SKILL.md',project/'SKILL.md')
            third_party={'path':str(project/'SKILL.md'),'description':'Third-party'}
            describe_bundled([third_party],agent)
            self.assertNotIn('descriptions',third_party)

    def test_default_install_never_overwrites_edits_or_resurrects_deleted_skills(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);source=base/'distribution';source.mkdir()
            rows=[{'name':name,'commit':'version-one'} for name in ('custom','edited','deleted')]
            (source/'sources.json').write_text(json.dumps(rows))
            for row in rows:
                folder=source/row['name'];folder.mkdir();(folder/'SKILL.md').write_text('Distributed content')
            agent=base/'agent';custom=agent/'skills/custom';custom.mkdir(parents=True)
            (custom/'SKILL.md').write_text('User existing content')
            install_bundled(source,agent)
            (agent/'skills/edited/SKILL.md').write_text('User edit')
            shutil.rmtree(agent/'skills/deleted')
            for folder in source.iterdir():
                if folder.is_dir():(folder/'SKILL.md').write_text('Upstream new revision')
            install_bundled(source,agent)
            self.assertEqual((custom/'SKILL.md').read_text(),'User existing content')
            self.assertEqual((agent/'skills/edited/SKILL.md').read_text(),'User edit')
            self.assertFalse((agent/'skills/deleted').exists())
            install_bundled(source,base/'another-agent')
            self.assertTrue((base/'another-agent/skills/deleted/SKILL.md').is_file())

    def test_pinned_distribution_has_licenses_and_matches_its_integrity_manifest(self):
        source=ROOT/'bundled-skills';rows=json.loads((source/'sources.json').read_text())
        self.assertEqual(len({row['name'] for row in rows}),10)
        for row in rows:
            folder=source/row['name']
            self.assertTrue((folder/'SKILL.md').is_file())
            self.assertTrue(any((folder/name).is_file() for name in ('LICENSE','LICENSE.txt','LICENSE.md')))
            self.assertRegex(row['commit'],r'^[a-f0-9]{40}$')
            actual={file.relative_to(folder).as_posix():hashlib.sha256(file.read_bytes()).hexdigest()
                    for file in folder.rglob('*') if file.is_file() and '__pycache__' not in file.parts}
            self.assertEqual(actual,row['files'],row['name'])
