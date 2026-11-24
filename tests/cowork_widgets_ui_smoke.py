"""Verify Cowork role resources through the same Widgets and Pi used by chats."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')

from PySide6.QtTest import QTest
from app.pi_management import resource_command
from app.storage import Store
from main import create_application


def test():
    with tempfile.TemporaryDirectory(prefix='umeko-cowork-widgets-') as temporary:
        base = Path(temporary).resolve()
        workspace = base / 'workspace'
        agent = base / 'agent'
        standard = agent / 'skills' / 'standard-guide'
        standard.mkdir(parents=True)
        workspace.mkdir()
        (standard / 'SKILL.md').write_text('---\nname: standard-guide\ndescription: Ordinary fixture.\n---\nNormal only.\n')
        source = base / 'private-guide'
        source.mkdir()
        (source / 'SKILL.md').write_text('---\nname: private-guide\ndescription: Cowork fixture.\n---\nCowork only.\n')
        os.environ.update(UMEKO_DATA_DIR=str(base / 'profile'), PI_CODING_AGENT_DIR=str(agent), UMEKO_LANGUAGE='zh')
        previous = workspace / '.pi/skills/legacy-guide/SKILL.md'
        previous.parent.mkdir(parents=True)
        previous.write_text('---\nname: legacy-guide\ndescription: Earlier preview fixture.\n---\nLegacy skill.\n')
        registry = base / 'profile/cowork/roles.json'
        registry.parent.mkdir(parents=True)
        dormant = registry.parent / 'type-skills/study/dormant-guide/SKILL.md'
        dormant.parent.mkdir(parents=True)
        dormant.write_text('---\nname: dormant-guide\ndescription: Previously uploaded but unchecked.\n---\nSaved.\n')
        registry.write_text(json.dumps({'roles': [{
            'id': 'papers', 'name': 'Paper translator', 'description': '', 'workspace': str(workspace),
            'context': 'files', 'prompt': 'Translate papers.', 'tools': ['read'], 'skills': [str(previous), 'pdf'],
        }]}))
        store = Store()
        store.data['workspace'] = str(workspace)
        store.data['agent']['agentDir'] = str(agent)
        store.save()

        app, engine, backend = create_application()
        window = engine.rootObjects()[0]
        window.resize(1320, 860)
        if sys.platform == 'darwin':
            # PyInstaller exposes runtime under Contents/Frameworks while
            # Node resolves the entry modules into Contents/Resources.
            bundled = base / 'Frameworks'
            bundled.mkdir()
            (bundled / 'runtime').symlink_to(backend._release.parent.parent, target_is_directory=True)
            backend._release = bundled / 'runtime/releases' / backend._release.name
        manager = backend.desktopPlugins
        cowork = backend.cowork
        replies = {}
        manager.hostResponse.connect(lambda _, identifier, response: replies.__setitem__(identifier, response))

        def find(name):
            pending = [window.contentItem()]
            while pending:
                item = pending.pop()
                if item.objectName() == name:
                    return item
                pending.extend(item.childItems())

        def wait(condition, message):
            deadline = time.monotonic() + 18
            while time.monotonic() < deadline:
                QTest.qWait(30)
                if condition():
                    return
            raise AssertionError((message, [(v.get('operation'), v.get('error')) for v in list(replies.values())[-12:]]))

        def prop(name, key):
            value = find(name).property(key)
            return value.toVariant() if hasattr(value, 'toVariant') else value

        def open_widget(identifier, object_name, data):
            assert manager.openPage(identifier)
            wait(lambda: find(object_name) and not prop(object_name, 'working') and prop(object_name, data), identifier)
            assert not prop(object_name, 'notice'), prop(object_name, 'notice')

        def request(operation, args):
            identifier = manager.requestHost(operation, json.dumps(args))
            assert identifier
            wait(lambda: identifier in replies, operation)
            assert replies[identifier]['ok'], replies[identifier]
            return replies[identifier]

        skills_widget = 'skillManagerWidget'
        tools_widget = 'piManagerWidget'
        try:
            QTest.qWait(450)
            assert not backend.desktopSettings['coworkEnabled']
            assert not find('openCoworkButton').isVisible()
            migrated = base / 'profile/cowork/skill-library/migrated/papers/legacy-guide/SKILL.md'
            wait(lambda: str(migrated) in cowork.roleDetails('papers')['skills'], 'Legacy role Skill migration')
            assert previous.read_bytes() == migrated.read_bytes()
            assert (registry.parent / 'skill-library/migrated/study/dormant-guide/SKILL.md').read_bytes() == dormant.read_bytes()
            assert 'pdf-paper-reading' in cowork.roleDetails('papers')['skills']
            assert backend.saveDesktopSettings('{"coworkEnabled":true}')
            assert not cowork.saveInstance('', 'study', 'Study Buddy', str(workspace))

            # Both widgets work before a provider or model has been selected.
            open_widget('pi-manager', tools_widget, 'rows')
            assert prop(tools_widget, 'readOnly')
            assert not find('piCapabilityPresets').isVisible()
            for group in prop(tools_widget, 'rows'):
                result = request('pi.tools', {'id': group['id']})['result']
                assert all(not item['editable'] for item in result['tools'])
                assert group['enabledToolCount'] == sum(item['visible'] for item in result['tools'])
            tools = backend.piManagement.capability_extensions()
            selected = {tool['name'] for group in tools for tool in group['tools'] if tool['visible']}
            assert selected == set(cowork.role['tools'])

            open_widget('skill-manager', skills_widget, 'skills')
            visible = {row['name']: row for row in prop(skills_widget, 'skills')}
            assert visible['evidence-citations']['enabled']
            assert 'standard-guide' not in visible
            assert set(prop(skills_widget, 'roots')) == {'builtin', 'bundled', 'project'}
            bundled = {row['name'] for row in json.loads((ROOT / 'bundled-skills/sources.json').read_text())}
            assert bundled <= visible.keys()
            citation = visible['evidence-citations']
            request('skills.attach', {'id': citation['id'], 'enabled': False})
            wait(lambda: 'evidence-citations' not in cowork.role['skills'], 'Skill toggle did not update role')
            wait(lambda: not prop(skills_widget, 'working') and not any(
                row['enabled'] for row in prop(skills_widget, 'skills') if row['name'] == 'evidence-citations'),
                'Widget did not refresh role selection')

            cowork.importSkill('study', '', str(source))
            wait(lambda: not cowork.importingSkill, 'Skill import')
            assert not cowork.resourceError, cowork.resourceError
            copied = base / 'profile/cowork/skill-library/private-guide/SKILL.md'
            assert copied.is_file()
            assert not (workspace / '.pi/skills/private-guide').exists()
            values = {**cowork.typeDetails('study'), 'skills': [str(copied)]}
            assert cowork.saveType(json.dumps(values)) == 'study'
            wait(lambda: any(row['name'] == 'private-guide' and row['enabled']
                            for row in prop(skills_widget, 'skills')), 'Widget did not reflect editor changes')
            assert cowork.skill_paths(backend._view) == [str(copied)]
            assert any(row['id'] == 'bundled:pdf' for row in cowork.skillOptions)

            backend.store.data['providers'] = [{
                'id': 'fixture', 'name': 'Fixture', 'api': 'openai', 'baseUrl': 'http://127.0.0.1:1/v1',
                'key': 'fixture', 'models': [{'upstream': 'fixture', 'alias': 'fixture'}],
            }]
            record = backend._view
            record.provider = record.model = 'fixture'
            assert backend._command_pi('inspect', record)
            wait(lambda: not record.busy and record.resources.get('allTools'), 'Pi resource inventory')
            assert {skill['name'] for skill in record.resources['skills']} == {'private-guide'}
            assert set(record.resources['tools']) == set(cowork.role['tools'])
            assert {tool['name'] for group in backend.piManagement.capability_extensions()
                    for tool in group['tools'] if tool['visible']} == set(record.resources['tools'])

            library = next(row for row in cowork.skillOptions if row['id'] == str(copied))
            assert library['group'] == 'library'
            office = cowork.typeDetails('office')
            office['skills'] = office['skills'] + [str(copied)]
            assert cowork.saveType(json.dumps(office)) == 'office'
            cowork.deleteSkill('study', str(copied))
            wait(lambda: not cowork.importingSkill, 'Delete shared library Skill')
            assert not cowork.resourceError and not copied.exists()
            assert source.joinpath('SKILL.md').is_file()
            assert str(copied) not in cowork.typeDetails('study')['skills'] + cowork.typeDetails('office')['skills']
            assert not cowork.saveInstance('', 'office', 'Office', str(workspace))
            open_widget('skill-manager', skills_widget, 'skills')
            assert 'private-guide' not in {row['name'] for row in prop(skills_widget, 'skills')}
            assert {row['name'] for row in prop(skills_widget, 'skills') if row['enabled']} == {'office-artifacts'}

            cowork.leave()
            open_widget('skill-manager', skills_widget, 'skills')
            names = {row['name'] for row in prop(skills_widget, 'skills')}
            assert 'standard-guide' in names and 'private-guide' not in names
            assert not names.intersection({'evidence-citations', 'office-artifacts', 'pdf-paper-reading', 'document-to-action-items'})
            assert resource_command(backend._release, workspace, agent, {}, action='scan')
            print('COWORK_WIDGETS_UI_OK: offline tool inventory, role Skill toggle/import, editor sync and ordinary-chat isolation')
        finally:
            window.hide()
            app.quit()
            backend.close()


if __name__ == '__main__':
    test()
