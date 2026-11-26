"""Verify category settings, instance actions and Cowork conversations."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')

from PySide6.QtCore import QObject, QMetaObject, Q_ARG, Qt
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest
from app.pi_runtime import node_executable
from main import create_application


def test():
    with tempfile.TemporaryDirectory(prefix='umeko-cowork-creation-') as temporary:
        base = Path(temporary).resolve()
        workspace = base / 'folder-a'
        second = base / 'folder-b'
        third = base / 'folder-c'
        for folder in (workspace, second, third):
            folder.mkdir()
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
            hidden = None
            while stack:
                item = stack.pop()
                if item.objectName() == name:
                    if item.isVisible():
                        return item
                    hidden = item
                stack.extend(item.childItems())
            return hidden

        def click(name):
            wait(lambda: find(name) and find(name).isVisible() and find(name).isEnabled(), name)
            item = find(name)
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())
            QTest.qWait(140)

        def expression(source, object_name='coworkEditor'):
            editor = window.findChild(QObject, object_name)
            value = QQmlExpression(QQmlEngine.contextForObject(editor), editor, source)
            value.evaluate()
            assert not value.hasError(), value.error().toString()

        def context(identifier, action):
            row = find('sidebarRow_' + identifier)
            assert row and row.isVisible()
            point = row.mapToScene(row.boundingRect().center()).toPoint()
            QTest.mouseClick(window, Qt.RightButton, Qt.NoModifier, point)
            click(action)

        def choose_folder(folder):
            expression(f'chooseFolder({json.dumps(folder.as_uri())})', 'coworkSessionDialog')

        def choose_template(template, folder):
            menu = find('coworkTemplateChoice')
            index = next(index for index, row in enumerate(cowork.templates) if row['id'] == template)
            menu.setProperty('currentIndex', index)
            assert QMetaObject.invokeMethod(menu, 'activated', Qt.DirectConnection, Q_ARG(int, index))
            default_workspace = str((base / 'profile/workspace').resolve())
            assert find('coworkInstanceWorkspace').property('text') == default_workspace
            assert find('coworkInstanceConfirm').isEnabled()
            choose_folder(folder)
            wait(lambda: find('coworkInstanceConfirm').isEnabled(), 'required workspace')

        try:
            QTest.qWait(450)
            assert not find('openCoworkButton').isVisible()
            assert backend.saveDesktopSettings('{"coworkEnabled":true}')
            click('settingsButton')
            click('settingsTab_3')
            click('openUmekoDesktopSettingsButton')
            click('openCoworkWebNetwork')
            assert find('coworkWebProxyMode').property('currentIndex') == 0
            click('coworkWebProxyDns')
            find('coworkWebProxyMode').setProperty('currentIndex', 2)
            find('coworkWebProbeUrl').setProperty('text', 'https://127.0.0.1')
            click('coworkWebProbeRun')
            wait(lambda: cowork.webNetwork.result.get('code') == 'ADDRESS_DENIED', 'web access diagnostic')
            assert find('coworkWebProbeResult').isVisible()
            click('coworkWebSave')
            assert cowork.webNetwork.settings['mode'] == 'direct'
            assert cowork.webNetwork.settings['proxyDns'] is True
            click('settingsButton')
            ordinary = backend._view
            ordinary.resources['toolCatalog'] = [
                {'name': name, 'owner': f'builtin:{name}',
                 'description': f'Short summary for {name}.\n\n' + ('Long tool documentation ' * 40)}
                for name in ('codemode', 'tool_search')
            ]
            click('openCoworkButton')
            assert cowork.active and not cowork.activeRole and cowork.rows == []
            assert find('coworkEmptyState').isVisible()
            assert find('coworkEmptyCreate').isVisible() and find('coworkEmptyCreate').isEnabled()
            assert find('coworkCard_study').isVisible() and find('coworkCard_office').isVisible()
            assert find('coworkCardNewType').isVisible()
            click('coworkCard_office')
            default_workspace = str((base / 'profile/workspace').resolve())
            assert find('coworkInstanceTitle').property('text') == '文档生成'
            assert find('coworkInstanceWorkspace').property('text') == default_workspace
            assert find('coworkInstanceConfirm').isEnabled()
            click('coworkInstanceCancel')
            click('newChatButton')
            choose_template('study', workspace)
            assert find('coworkInstanceTitle').property('text') == 'Study Buddy'
            click('coworkInstanceConfirm')
            identifier = cowork.activeRole
            assert identifier.startswith('custom-')
            assert [row['id'] for row in cowork.rows] == ['cowork-type:study', identifier]
            assert cowork.role['workspace'] == str(workspace)
            assert cowork.rows[0]['title'] == cowork.rows[1]['title'] == 'Study Buddy'
            assert 'path' not in cowork.rows[0] and cowork.rows[1]['displayTitle'] == 'folder-a @ Study Buddy'
            assert cowork.rows[1]['kind'] == 'coworkDraft'
            assert not find('newProjectSession_' + identifier).isVisible()
            assert not find('openWorkspacePickerButton').isVisible() and not find('createCoworkerButton')
            assert find('editCoworkType_study').property('glyph') == 'settings'
            click('editCoworkType_study')
            assert find('coworkNameField').property('text') == 'Study Buddy'
            assert not find('coworkWebTab')
            click('coworkToolsTab')
            assert find('coworkToolsTab').property('text').startswith('Tools')
            assert find('coworkToolGroup_bundled').isVisible()
            search = find('coworkCapabilityFilter_tools')
            for scale in (1.0, 1.7):
                backend.setFontScale(scale)
                for name in ('codemode', 'tool_search'):
                    search.setProperty('text', name)
                    wait(lambda: find('coworkOption_' + name) is not None, 'filtered tool row')
                    QTest.qWait(80)
                    option = find('coworkOption_' + name)
                    body = option.property('contentItem')
                    details = next(item for item in body.childItems() if item.objectName() == 'coworkOptionDescription')
                    assert details.property('lineCount') == 2 and details.property('truncated')
                    assert details.property('contentWidth') <= details.width() + 1
                    assert details.mapToItem(option, details.boundingRect().topRight()).x() <= option.property('indicator').x()
            backend.setFontScale(1.0)
            search.setProperty('text', '')
            click('coworkToolGroup_mcp')
            click('coworkAddMcp')
            find('coworkMcpJson').setProperty('text', '{"mcpServers":')
            click('coworkConfirmMcp')
            wait(lambda: not cowork.mcpBusy and bool(cowork.mcpError), 'invalid MCP JSON')
            assert not (cowork.root / 'mcp/study/mcp.json').exists()
            server = {'command': node_executable(), 'args': [str(ROOT / 'tests/fixtures/cowork-mcp-server.mjs')]}
            find('coworkMcpJson').setProperty('text', json.dumps({'mcpServers': {'notes': server}}))
            click('coworkConfirmMcp')
            wait(lambda: not cowork.mcpBusy and any(row['state'] == 'connected' for row in cowork.mcpServers), 'MCP discovery')
            assert not (base / 'agent/mcp.json').exists()
            mcp_option = next(row['id'] for row in cowork.toolOptions if row['label'] == 'parent-note')
            click('coworkOption_' + mcp_option)
            click('coworkToolGroup_bundled')
            search.setProperty('text', '管理 Umeko')
            assert not find('coworkOption_umeko_desktop').property('checked')
            click('coworkOption_umeko_desktop')
            click('coworkSubagentsTab')
            click('coworkSubagentEnabled_researcher')
            click('coworkSubagentEdit_reviewer')
            assert '副本' not in find('coworkSubagentName').property('text')
            find('coworkSubagentName').setProperty('text', '文献复核')
            click('coworkSaveSubagent')
            assert not find('coworkSubagentEnabled_reviewer').property('checked')
            backend.store.data['providers'] = [{
                'id':'fixture', 'name':'Fixture', 'api':'openai', 'key':'',
                'baseUrl':'http://127.0.0.1:1/v1', 'models':[{'alias':'child-model','upstream':'child-model'}],
            }]
            click('coworkSubagentClone_reviewer')
            assert find('coworkSubagentName').property('text') == '文献复核 副本'
            find('coworkSubagentName').setProperty('text', '本地复核')
            find('coworkSubagentPrompt').setProperty('text', 'Review paper citations.')
            click('coworkSubagentTab_1')
            option = find('coworkOption_grep')
            assert option.property('indicator').objectName() == 'umekoCheckIndicator'
            assert option.property('checked')
            click('coworkOption_grep')
            click('coworkToolGroup_mcp')
            child_mcp_option = next(row['id'] for row in cowork.subagentToolOptions if row['label'] == 'child-note')
            click('coworkOption_' + child_mcp_option)
            click('coworkSubagentTab_3')
            find('coworkSubagentModel').setProperty('currentIndex', 1)
            click('coworkSubagentTab_4')
            pack_index = next(i for i, row in enumerate([pack for pack in backend.subagentCharacterPacks if pack['id'] != 'system'], 1)
                              if row['id'] == 'komari')
            find('coworkSubagentCharacter').setProperty('currentIndex', pack_index)
            click('coworkSaveSubagent')
            click('coworkSubagentDelete_planner')
            assert not find('coworkSubagentEdit_planner')
            click('coworkSaveRole')
            assert 'umeko_desktop' in cowork.role['tools']
            assert 'umeko_desktop' not in {row['id'] for row in cowork.subagentToolOptions}
            expected = ['researcher', 'reviewer', 'child-']
            assert all(row['id'].startswith(prefix) for row, prefix in zip(cowork.role['subagents'], expected))
            assert cowork.role['hiddenSubagents'] == ['planner']
            assert not cowork.role['subagents'][1]['enabled']
            child = cowork.role['subagents'][2]
            assert child['name'] == '本地复核' and child['enabled']
            assert 'grep' not in child['tools']
            assert child['prompt'] == 'Review paper citations.'
            assert child['skills'] == ['evidence-citations']
            assert child['model'] == 'child-model' and child['character'] == 'komari'
            assert cowork.role['toolOwners'][mcp_option] == child['toolOwners'][child_mcp_option] == 'cowork:mcp:notes'
            click('newCoworkInstance_study')
            assert not find('coworkTemplateChoice').isVisible()
            assert find('coworkInstanceTitle').property('text') == 'Study Buddy'
            choose_folder(second)
            click('coworkInstanceConfirm')
            other = cowork.activeRole
            assert other != identifier and cowork.role['name'] == 'Study Buddy'
            assert [row['id'] for row in cowork.rows] == ['cowork-type:study', identifier, other]
            assert cowork.role['subagents'] == cowork.roleDetails(identifier)['subagents']
            click('toggleCoworkType_study')
            assert [row['id'] for row in cowork.rows] == ['cowork-type:study']
            click('toggleCoworkType_study')
            current = backend._view
            backend.setDraft('Keep this draft')
            context(identifier, 'coworkContextNewSession')
            assert backend._view is current
            assert find('coworkSessionTitle').property('text') == '新会话'
            assert find('coworkSessionWorkspace').property('text') == str(workspace)
            click('coworkSessionCancel')
            assert backend._view is current and current.draft == 'Keep this draft'
            context(identifier, 'coworkContextNewSession')
            choose_folder(second)
            find('coworkSessionTitle').setProperty('text', '资料复核')
            click('coworkSessionConfirm')
            assert backend._view is not current and cowork.activeRole == identifier
            assert backend._view.workspace == str(second) and cowork.role['workspace'] == str(workspace)
            assert backend.sessionTitle == '资料复核'
            backend._view.id = 'preview-task'
            backend._index_record(backend._view)
            cowork.refresh_rows()
            assert [row['displayTitle'] for row in cowork.rows if row['kind'] == 'session'] == ['folder-b @ 资料复核']
            assert not any(row['id'] == identifier for row in cowork.rows)
            context('preview-task', 'coworkContextClone')
            assert find('coworkInstanceTitle').property('text') == 'Study Buddy 副本'
            assert find('coworkInstanceWorkspace').property('text') == str(workspace)
            click('coworkInstanceConfirm')
            clone = cowork.activeRole
            assert clone not in (identifier, other)
            assert [row['kind'] for row in cowork.rows if row.get('instanceId') == clone] == ['coworkDraft']
            assert cowork.role['subagents'] == cowork.roleDetails(identifier)['subagents']
            context(clone, 'coworkContextRename')
            find('renameInput').setProperty('text', '读书笔记')
            click('confirmRenameButton')
            assert cowork.roleName == '读书笔记'
            context(clone, 'coworkContextFolder')
            choose_folder(third)
            click('coworkInstanceConfirm')
            assert backend._view.workspace == str(third)
            assert cowork.profiles[clone]['workspace'] == str(third)
            assert cowork.profiles[identifier]['workspace'] == str(workspace)
            assert [row['displayTitle'] for row in cowork.rows if row['kind'] == 'session'] == ['folder-b @ 资料复核']

            source = third / 'source.txt'
            source.write_text('keep')
            history = cowork.session_directory(clone) / 'archived.jsonl'
            history.parent.mkdir(parents=True)
            chat_id = str(uuid.uuid4())
            history.write_text(json.dumps({'type': 'session', 'id': chat_id, 'cwd': str(third)}) + '\n')
            backend._sessions.insert(0, {'id': chat_id, 'cowork': clone, 'workspace': str(third),
                                         'title': 'Archived test fixture', 'file': str(history)})
            backend.store.data['sessionMeta'][chat_id] = {'archived': True}
            context(clone, 'coworkContextDelete')
            click('confirmDeleteProjectButton')
            wait(lambda: clone not in cowork.profiles and not backend.sessionFiles.busy, 'delete instance')
            assert not history.exists() and source.read_text() == 'keep'
            assert any(row['id'] == 'cowork-type:study' for row in cowork.rows)

            click('newChatButton')
            click('coworkCreateType')
            find('coworkNameField').setProperty('text', '资料归纳')
            click('coworkSaveRole')
            assert find('coworkInstanceTitle').property('text') == '资料归纳'
            assert not any(row['title'] == '资料归纳' for row in cowork.rows)
            click('coworkInstanceCancel')
            assert any(row['label'] == '资料归纳' for row in cowork.templates)
            click('coworkHeaderOverview')
            wait(lambda: find('coworkEmptyState') and find('coworkEmptyState').isVisible(), 'return to cowork overview')
            assert find('coworkInstanceCard_' + identifier).isVisible()
            assert find('coworkCard_' + cowork.templates[-1]['id']).isVisible()
            click('coworkInstanceCard_' + identifier)
            wait(lambda: cowork.activeRole == identifier, 'open instance from overview')
            click('openCoworkButton')
            assert backend._view is ordinary
            assert not [warning for warning in notices if 'CoworkEditor.qml' in warning or 'CoworkSessionDialog.qml' in warning or 'CoworkOverview.qml' in warning], notices[-15:]
            print('COWORK_CREATION_UI_OK: flat categories, shared subagent preferences, instance actions and configured conversations')
        finally:
            window.hide()
            app.quit()
            backend.close()


if __name__ == '__main__':
    test()
