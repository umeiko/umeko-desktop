"""Actual Main.qml, Widget host confirmation and native local skill operations.

All profiles and packages are disposable. No provider, model or public server
is configured. UI actions use QML signals rather than mouse/keyboard injection.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
os.environ.setdefault('QT_QUICK_CONTROLS_STYLE', 'Basic')
os.environ['UMEKO_LANGUAGE'] = 'en'

from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
import shiboken6

from app.storage import Store
from main import create_application


def wait_for(predicate, message, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QTest.qWait(20)
        time.sleep(.005)  # Allow native worker threads to run between Qt events.
        if predicate():
            return
    raise AssertionError(message() if callable(message) else message)


def markdown(name):
    return f'---\nname: {name}\ndescription: Local fixture for skill management.\n---\n\nUse this local fixture.\n'


def main():
    with tempfile.TemporaryDirectory(prefix='skill-host-ui-') as directory:
        base = Path(directory)
        profile, agent, workspace = base / 'profile', base / 'agent', base / 'workspace'
        for path in (profile, agent, workspace, base / 'home'):
            path.mkdir()
        os.environ.update(UMEKO_DATA_DIR=str(profile), PI_CODING_AGENT_DIR=str(agent),
                          HOME=str(base / 'home'), USERPROFILE=str(base / 'home'))
        store = Store(profile)
        store.data['workspace'] = str(workspace)
        store.data['agent']['agentDir'] = str(agent)
        store.save()

        package = base / 'fixture-package'
        (package / 'skills/packaged-fixture').mkdir(parents=True)
        (package / 'package.json').write_text(json.dumps({'name': 'fixture-local-skills',
            'version': '1.0.0', 'pi': {'skills': ['skills']}}), encoding='utf-8')
        (package / 'skills/packaged-fixture/SKILL.md').write_text(markdown('packaged-fixture'), encoding='utf-8')

        app, engine, backend = create_application()
        app.setQuitOnLastWindowClosed(False)
        manager, warnings, replies = backend.desktopPlugins, [], {}
        engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
        manager.hostResponse.connect(lambda widget, identifier, value: replies.__setitem__(identifier, value))
        window = engine.rootObjects()[0]
        window.resize(1180, 850)
        host = manager.hostServices

        def find(name):
            stack = [window.contentItem()]
            while stack:
                item = stack.pop()
                if item.objectName() == name:
                    return item
                stack.extend(item.childItems())
            return window.findChild(QQuickItem, name)

        def idle():
            widget = find('skillManagerWidget')
            return (not backend.busy and not backend.kernelBusy and not backend.piManagement.busy
                and not host.panelApproval and widget is not None and not widget.property('working')
                and (host._skills is None or not any(row['status'] == 'running' for row in host._skills.jobs.values())))

        def assert_font_family(container, family):
            pending, count = [container], 0
            while pending:
                item = pending.pop()
                pending.extend(item.childItems())
                if item.isVisible() and item.property('text') and item.property('font') is not None:
                    assert item.property('font').family() == family, (item.objectName(), item.property('font').family(), family)
                    count += 1
            assert count >= 4, count

        def request(operation, args, *, confirm=False):
            wait_for(idle, 'The skill panel did not become idle')
            identifier = manager.requestHost(operation, json.dumps(args))
            assert identifier, operation
            if confirm:
                wait_for(lambda: bool(host.panelApproval) or identifier in replies,
                         'Host confirmation did not appear')
                assert identifier not in replies, replies.get(identifier)
                assert host.panelApproval['id'] == identifier
                assert host.pendingApproval == {}, 'Skill action opened the global confirmation'
                confirmation = find('widgetPanelConfirmation')
                allow = find('widgetPanelAllow')
                assert confirmation is not None and confirmation.isVisible()
                assert allow is not None and allow.isVisible() and allow.isEnabled()
                assert_font_family(confirmation, 'serif')
                return identifier, allow
            wait_for(lambda: identifier in replies, 'Host response missing: ' + operation)
            assert replies[identifier]['ok'], replies[identifier]
            return replies[identifier]

        def approved(identifier, allow):
            allow.clicked.emit()
            wait_for(lambda: identifier in replies, 'Confirmed host response missing')
            assert replies[identifier]['ok'], replies[identifier]
            assert not host.panelApproval
            return replies[identifier]

        def skill_result(reply):
            job = reply['jobId']
            wait_for(lambda: host._skills.jobs[job]['status'] != 'running', 'Native skill job did not finish')
            identifier = manager.requestHost('skills.job', json.dumps({'id': job}))
            wait_for(lambda: identifier in replies, 'Skill job poll did not return')
            row = replies[identifier]['jobs'][0]
            assert row['status'] == 'completed', row
            assert row['result']['ok'], row
            return row['result']

        def catalog():
            return skill_result(request('skills.list', {}))['skills']

        try:
            assert not backend.store.data['providers'], 'Fixture configured a provider'
            assert backend.public_server is None, 'Fixture started a public server'
            assert manager.openPage('skill-manager'), 'Built-in skill panel did not open'
            wait_for(lambda: bool(manager.page.get('error')) or manager.workers.get('skill-manager', {}).get('ready') and idle(),
                     lambda: 'Actual skill widget did not initialize: ' + repr({
                         'page': manager.page,
                         'ready': manager.workers.get('skill-manager', {}).get('ready'),
                         'backendBusy': backend.busy, 'kernelBusy': backend.kernelBusy,
                         'managementBusy': backend.piManagement.busy,
                         'widgetWorking': find('skillManagerWidget').property('working') if find('skillManagerWidget') else None,
                     }))
            assert not manager.page.get('error'), manager.page
            backend.setFontFamily('serif')
            backend.setFontScale(1.17)
            QTest.qWait(100)
            widget = find('skillManagerWidget')
            assert_font_family(widget, 'serif')
            assert find('skillManagerSearch').property('font').pixelSize() == 14
            settings = agent / 'settings.json'
            before = settings.read_bytes() if settings.exists() else None
            identifier, allow = request('pi.install', {'source': str(package), 'project': False}, confirm=True)
            assert (settings.read_bytes() if settings.exists() else None) == before, 'Package installed before confirmation'
            reply = approved(identifier, allow)
            job = reply['jobId']
            wait_for(lambda: backend._umeko_control.jobs[job]['status'] != 'running', 'Native local package install did not finish')
            poll = manager.requestHost('pi.job', json.dumps({'id': job}))
            wait_for(lambda: poll in replies, 'Package job poll did not return')
            assert replies[poll]['jobs'][0]['status'] == 'done', replies[poll]
            rows = catalog()
            packaged = next(row for row in rows if row['name'] == 'packaged-fixture')
            assert packaged['source'] == 'package' and packaged['removable']

            imported = []
            for project in (False, True):
                name = 'project-import-fixture' if project else 'global-import-fixture'
                source = base / (name + '.zip') if not project else base / name
                if project:
                    source.mkdir()
                    (source / 'SKILL.md').write_text(markdown(name), encoding='utf-8')
                else:
                    with zipfile.ZipFile(source, 'w') as archive:
                        archive.writestr(name + '/SKILL.md', markdown(name))
                        archive.writestr(name + '/references/local.txt', 'Inert local reference.')
                destination = (workspace / '.pi/skills' if project else agent / 'skills') / name
                preview = skill_result(request('skills.importPreview', {'source': str(source), 'project': project}))['preview']
                assert preview['project'] == project and preview['errors'] == [], preview
                assert [row['name'] for row in preview['skills']] == [name], preview
                assert not destination.exists(), 'Preview wrote a skill directory'
                identifier, allow = request('skills.import', {'id': preview['id'], 'decisions': {}}, confirm=True)
                assert not destination.exists(), 'Skill imported before host confirmation'
                result = skill_result(approved(identifier, allow))
                assert result['imported'] == [name] and result['errors'] == [], result
                assert (destination / 'SKILL.md').read_text(encoding='utf-8') == markdown(name)
                row = next(row for row in catalog() if row['name'] == name)
                assert row['scope'] == ('project' if project else 'global'), row
                imported.append(name)

            relevant_warnings = [warning for warning in warnings if 'skill-manager' in warning
                                 or 'DesktopPluginSurface' in warning]
            assert not relevant_warnings, relevant_warnings
            print('SKILL_MANAGER_HOST_UI_OK: actual App/QML confirmation and live font propagation, native local package, '
                  'ZIP/global and folder/project imports, native catalog; model calls=0')
        finally:
            backend.close()
            shiboken6.delete(engine)
            app.processEvents()


if __name__ == '__main__':
    main()
