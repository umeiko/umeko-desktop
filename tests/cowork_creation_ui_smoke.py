"""Create workspace-bound coworker instances and configure their own subagent pools."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')

from PySide6.QtCore import QObject, QMetaObject, Q_ARG, Qt
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest
from main import create_application


def test():
    with tempfile.TemporaryDirectory(prefix='umeko-cowork-creation-') as temporary:
        base = Path(temporary).resolve()
        workspace = base / 'folder-a'
        second = base / 'folder-b'
        workspace.mkdir()
        second.mkdir()
        os.environ.update(UMEKO_DATA_DIR=str(base / 'profile'), PI_CODING_AGENT_DIR=str(base / 'agent'), UMEKO_LANGUAGE='zh')
        app, engine, backend = create_application()
        window = engine.rootObjects()[0]
        window.resize(1320, 860)
        cowork = backend.cowork
        notices = []
        engine.warnings.connect(lambda rows: notices.extend(item.toString() for item in rows))

        def wait(condition, detail):
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                QTest.qWait(25)
                if condition():
                    return
            raise AssertionError((detail, notices[-15:]))

        def find(name):
            stack = [window.contentItem()]
            while stack:
                item = stack.pop()
                if item.objectName() == name:
                    return item
                stack.extend(item.childItems())

        def click(name):
            wait(lambda: find(name) and find(name).isVisible() and find(name).isEnabled(), name)
            item = find(name)
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())
            QTest.qWait(140)

        def expression(source):
            editor = window.findChild(QObject, 'coworkEditor')
            value = QQmlExpression(QQmlEngine.contextForObject(editor), editor, source)
            value.evaluate()
            assert not value.hasError(), value.error().toString()

        def choose_template(template, folder):
            menu = find('coworkTemplateChoice')
            index = next(index for index, row in enumerate(cowork.templates) if row['id'] == template)
            menu.setProperty('currentIndex', index)
            assert QMetaObject.invokeMethod(menu, 'activated', Qt.DirectConnection, Q_ARG(int, index))
            assert not find('coworkSaveRole').isEnabled()
            expression(f'chooseWorkspace({json.dumps(folder.as_uri())})')
            wait(lambda: find('coworkSaveRole').isEnabled(), 'required workspace')

        try:
            QTest.qWait(450)
            assert not find('openCoworkButton').isVisible()
            assert backend.saveDesktopSettings('{"coworkEnabled":true}')
            ordinary = backend._view
            click('openCoworkButton')
            assert cowork.active and not cowork.activeRole and cowork.rows == []
            assert find('coworkEmptyState').isVisible()
            click('newChatButton')
            assert find('coworkNameField').property('text')
            choose_template('study', workspace)
            assert find('coworkNameField').property('text') == 'Study Buddy'
            click('coworkSubagentsTab')
            click('coworkSubagentEnabled_researcher')
            click('coworkSubagentEdit_reviewer')
            assert '副本' in find('coworkSubagentName').property('text')
            find('coworkSubagentName').setProperty('text', '本地复核')
            find('coworkSubagentPrompt').setProperty('text', 'Review paper citations.')
            click('coworkSubagentTab_1')
            option = find('coworkOption_grep')
            assert option.property('indicator').objectName() == 'umekoCheckIndicator'
            assert option.property('checked')
            click('coworkOption_grep')
            click('coworkSaveSubagent')
            click('coworkSaveRole')
            identifier = cowork.activeRole
            assert identifier.startswith('custom-')
            assert [row['id'] for row in cowork.rows] == [identifier]
            assert cowork.role['workspace'] == str(workspace)
            assert cowork.rows[0]['displayTitle'].endswith('folder-a')
            expected = ['researcher', 'child-']
            assert all(row['id'].startswith(prefix) for row, prefix in zip(cowork.role['subagents'], expected))
            assert cowork.role['subagents'][1]['name'] == '本地复核'
            assert 'grep' not in cowork.role['subagents'][1]['tools']
            assert cowork.role['subagents'][1]['prompt'] == 'Review paper citations.'
            assert cowork.role['subagents'][1]['skills'] == ['evidence-citations']
            click('newChatButton')
            choose_template('study', second)
            click('coworkSaveRole')
            other = cowork.activeRole
            assert other != identifier and cowork.role['name'] == 'Study Buddy'
            assert {row['id'] for row in cowork.rows} == {identifier, other}
            assert not cowork.role.get('subagents')
            assert {row['path'] for row in cowork.rows} == {str(workspace), str(second)}
            click('openCoworkButton')
            assert backend._view is ordinary
            assert not [warning for warning in notices if 'CoworkEditor.qml' in warning], notices[-15:]
            print('COWORK_CREATION_UI_OK: empty tree, preset chooser, required folder, independent instances, pool selection and configured clone')
        finally:
            window.hide()
            app.quit()
            backend.close()


if __name__ == '__main__':
    test()
