"""Exercise the workspace group with real QML and Pi against a loopback model."""
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import sqlite3
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PREVIEW = '--preview' in sys.argv
if not PREVIEW:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ.setdefault('QT_QUICK_BACKEND', 'software')
os.environ['UMEKO_LANGUAGE'] = 'zh'

from PySide6.QtCore import QObject, QTimer, Qt, QUrl
from PySide6.QtTest import QTest
from app.storage import Store
from main import create_application


def run(folder):
    os.environ['UMEKO_DATA_DIR'] = str(folder / 'profile')
    first, second, third = [f'018faaaa-0000-7000-8000-{i:012d}' for i in (1, 2, 3)]
    workspace = folder / '产品资料'
    workspace.mkdir()
    engineering = folder / '工程文件'
    engineering.mkdir()
    artifact = workspace / '整理报告.md'
    artifact.write_text('# 进度汇报\n\n文档已完成。\n', encoding='utf-8')
    (engineering / artifact.name).write_text(artifact.read_text(encoding='utf-8'), encoding='utf-8')
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            names = {tool.get('function', {}).get('name') for tool in body.get('tools', [])}
            requests.append((names, body.get('messages', [])))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()

            def emit(delta, finish=None):
                data = {'id': 'group-fixture', 'object': 'chat.completion.chunk', 'created': 1,
                        'model': 'fixture', 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
                self.wfile.write(('data: ' + json.dumps(data) + '\n\n').encode())

            emit({'role': 'assistant'})
            if 'submit_to_chatgroup' in names and body['messages'][-1]['role'] != 'tool':
                emit({'tool_calls': [{'index': 0, 'id': f'call-group-{len(requests)}', 'type': 'function',
                     'function': {'name': 'submit_to_chatgroup', 'arguments': json.dumps({
                         'text': '整理报告已完成，可以预览。', 'items': [{'path': artifact.name}]})}}]})
                emit({}, 'tool_calls')
            else:
                emit({'content': '测试会话工作完成。'})
                emit({}, 'stop')
            self.wfile.write(b'data: [DONE]\n\n')

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    store = Store()
    store.data['agent']['agentDir'] = str(folder / 'agent')
    store.data['agent']['safeMode'] = True
    store.data['workspace'] = str(workspace)
    store.data['projects'] = [
        {'id': 'group-smoke', 'name': '产品资料', 'path': str(workspace)},
        {'id': 'group-smoke-engineering', 'name': '工程文件', 'path': str(engineering)},
    ]
    store.data['providers'] = [{'id': 'local', 'name': '本地预览模型', 'api': 'openai',
        'baseUrl': f'http://127.0.0.1:{server.server_port}/v1', 'key': 'fixture-key',
        'proxy': {'mode': 'direct'}, 'models': [{'upstream': 'fixture', 'alias': 'fixture'}]}]
    store.data['selectedProvider'], store.data['selectedModel'] = 'local', 'fixture'
    store.save()
    sessions = []
    directory = store.directory / 'pi/sessions'
    directory.mkdir(parents=True, exist_ok=True)
    examples = [(first, '文档整理', workspace, {}), (second, '代码复核', engineering, {}),
                (third, '其他工作', workspace, {'cowork': 'example'})]
    if PREVIEW:
        examples.extend([
            ('018faaaa-0000-7000-8000-000000000004', '会议纪要', workspace, {}),
            ('018faaaa-0000-7000-8000-000000000005', '接口检查', engineering, {}),
        ])
    for identifier, title, cwd, extra in examples:
        path = directory / f'2026-11-27T00-00-00Z_{identifier}.jsonl'
        timestamp = '2026-11-27T00:00:00Z'
        entries = [
            {'type': 'session', 'id': identifier, 'version': 3, 'timestamp': timestamp, 'cwd': str(cwd)},
            {'type': 'session_info', 'id': '1a2b3c4d', 'parentId': None, 'timestamp': timestamp, 'name': title},
        ]
        path.write_text(''.join(json.dumps(entry) + '\n' for entry in entries), encoding='utf-8')
        sessions.append({'id': identifier, 'file': str(path), 'workspace': str(cwd), 'title': title,
                         'model': 'fixture', 'provider': 'local', **extra})
    store.save_sessions(sessions)
    app, engine, backend = create_application()
    window = engine.rootObjects()[0]
    window.setTitle('Umeko · 会话群聊预览')
    group = backend.sessionGroup

    def find(name):
        stack = [window.contentItem()]
        while stack:
            item = stack.pop()
            if item.objectName() == name:
                return item
            stack.extend(reversed(item.childItems()))
        return window.findChild(QObject, name)

    def wait(check, description, seconds=12):
        for _ in range(seconds * 40):
            if check():
                return
            QTest.qWait(25)
        if os.environ.get('UMEKO_GROUP_UI_DIAGNOSTICS'):
            window.grabWindow().save(os.environ['UMEKO_GROUP_UI_DIAGNOSTICS'])
            for state in ('groupChatDetails', 'groupChatMemberPicker', 'groupChatMemberActions'):
                item = find(state)
                print(state, item.property('opened') if item else None, flush=True)
            print('members', group.memberRows, flush=True)
        raise AssertionError(description)

    def click(name, button=Qt.LeftButton):
        wait(lambda: find(name) is not None and find(name).isVisible(), name)
        item = find(name)
        point = item.mapToScene(item.boundingRect().center()).toPoint()
        QTest.mouseClick(window, button, Qt.NoModifier, point)
        QTest.qWait(90)

    def messages():
        return group.chat.history(group.storage(), 0, 0)['messages']

    try:
        click('workspaceGroupChatButton')
        wait(lambda: find('workspaceGroupChat') is not None, 'Group page did not load')
        assert window.property('page') == 'sessionGroup'
        assert not find('chatPage').isVisible()
        candidate_ids = {row['id'] for row in group.candidates}
        if PREVIEW:
            assert {first, second} <= candidate_ids and third not in candidate_ids
        else:
            assert candidate_ids == {first, second}
        click('groupChatDetailsButton')
        click('groupChatAddMember')
        search = find('groupChatMemberFilter')
        search.setProperty('text', '没有这个会话')
        wait(lambda: find('groupChatMemberCandidate_' + first) is None, 'Search did not filter conversations')
        search.setProperty('text', '')
        workspace_choice = find('groupChatMemberWorkspace')
        workspaces = sorted((str(workspace), str(engineering)))
        workspace_choice.setProperty('currentIndex', workspaces.index(str(engineering)) + 1)
        assert find('groupChatMemberPicker').property('selectedWorkspace') == str(engineering)
        wait(lambda: find('groupChatMemberCandidate_' + first) is None, 'Workspace filter did not apply')
        workspace_choice.setProperty('currentIndex', 0)
        click('groupChatMemberCandidate_' + first)
        wait(lambda: len(group.memberRows) == 1, 'Add conversation did not persist')
        assert group.memberRows[0]['id'] == first
        details = find('groupChatDetails')
        wait(lambda: details.property('opened') and find('groupChatMember_agent:' + first),
             'Adding a member did not return to the member panel')
        assert details.property('highlightedMember') == 'agent:' + first
        click('groupChatAddMember')
        click('groupChatMemberCandidate_' + second)
        wait(lambda: len(group.memberRows) == 2 and details.property('opened'),
             'Adding a second member did not return to the member panel')
        assert details.property('highlightedMember') == 'agent:' + second
        click('groupChatMember_agent:' + first, Qt.RightButton)
        click('groupChatRenameMember')
        find('groupChatRenameInput').setProperty('text', '资料员')
        click('groupChatSaveNickname')
        wait(lambda: group.memberRows[0]['name'] == '资料员', 'Nickname did not persist')
        composer = find('groupChatComposer')
        composer.setProperty('text', '请更新进度')
        # Direct a single turn at the first session. The member row carries
        # the same stable ID used by the visible mention picker.
        find('workspaceGroupChat').setProperty('recipient', 'agent:' + first)
        # The release runs on the GUI thread. A blocking SQLite busy wait
        # would prevent the timer from running and discard this send.
        with closing(sqlite3.connect(group.database)) as writer:
            writer.execute('BEGIN IMMEDIATE')
            QTimer.singleShot(250, window, writer.rollback)
            click('groupChatSend')
            wait(lambda: not writer.in_transaction, 'The GUI did not release the database lock')
        wait(lambda: any(row['author'] == 'agent:' + first for row in messages()), 'Pi did not report to the group', 25)
        assert any('submit_to_chatgroup' in names and '(from group chat)' in json.dumps(rows)
                   for names, rows in requests)
        reported = next(row for row in messages() if row['author'] == 'agent:' + first)
        assert reported['recipient'] == 'user' and reported['files'][0]['name'] == artifact.name
        click(f"groupChatFile_{reported['id']}_0")
        wait(lambda: backend.documentPreview.state.get('path') == reported['files'][0]['path'],
             'Artifact did not open in the document pane')
        assert window.property('page') == 'sessionGroup' and not find('chatPage').isVisible()
        click('groupChatAvatar_agent:' + first)
        wait(lambda: window.property('page') == 'chat', 'Opening the member did not exit the group')
        wait(lambda: backend.activeSession == first, 'Previous conversation was not active')
        prompt = find('promptInput')
        prompt.setProperty('text', '返回前的草稿')
        click('workspaceGroupChatButton')
        wait(lambda: window.property('page') == 'sessionGroup', 'Group entry did not reopen')
        click('workspaceGroupChatButton')
        wait(lambda: window.property('page') == 'chat' and backend.activeSession == first,
             'Toggling the group did not return to the previous conversation')
        assert find('promptInput').property('text') == '返回前的草稿'
        prompt.setProperty('text', '')
        if PREVIEW:
            window.showSessionGroup()
            picker = find('groupChatMemberPicker')
            picker.begin()
            wait(lambda: picker.property('opened'), 'Group member picker did not open in preview')
            print('Workspace group preview ready', flush=True)
            app.exec()
        else:
            wait(lambda: not backend._pool.find(first).busy, 'Group turn did not settle')
            previous = reported['id']
            backend.send('在这个会话里继续整理。')
            wait(lambda: any(row['id'] > previous and row['author'] == 'agent:' + first for row in messages()),
                 'An ordinary conversation turn did not report progress', 25)
            wait(lambda: not backend._pool.find(first).busy, 'Ordinary turn did not settle')
            click('workspaceGroupChatButton')
            previous = messages()[-1]['id']
            composer = find('groupChatComposer')
            composer.setProperty('text', 'Broadcast dispatch')
            note = workspace / 'acceptance-note.txt'
            note.write_text('Attachment sent with SQLite contention.\n', encoding='utf-8')
            assert find('workspaceGroupChat').acceptChatFiles([QUrl.fromLocalFile(str(note)).toString()])
            with (
                closing(sqlite3.connect(group.database)) as writer,
                patch.object(group.timer, 'start'),
                patch.object(group.chat, 'copy_files', wraps=group.chat.copy_files) as archive,
            ):
                writer.execute('BEGIN IMMEDIATE')
                QTimer.singleShot(250, window, writer.rollback)
                click('groupChatSend')
                wait(lambda: len(group.outbox) == 2, 'Broadcast did not queue both members')
                assert not writer.in_transaction
                archive.assert_called_once()
            sent = [row for row in messages() if row['id'] > previous and row['author'] == 'user']
            assert len(sent) == 1 and Path(sent[0]['files'][0]['path']).read_bytes() == note.read_bytes()
            group.drain()
            assert len(group.outbox) == 1, 'One dispatch tick started both idle members'
            group.drain()
            assert not group.outbox, 'The next dispatch tick did not start the other member'
            wait(lambda: {row['author'] for row in messages() if row['id'] > previous}
                 >= {'agent:' + first, 'agent:' + second}, 'Broadcast lost a member report', 25)
            wait(lambda: all(not backend._pool.find(sid).busy for sid in (first, second)),
                 'Broadcast turns did not settle')
            click('groupChatDetailsButton')
            click('groupChatClearHistory')
            with closing(sqlite3.connect(group.database)) as reader:
                reader.execute('BEGIN')
                assert reader.execute('SELECT COUNT(*) FROM global_chat_messages').fetchone()[0] > 0
                QTimer.singleShot(250, window, reader.rollback)
                click('groupChatConfirmClear')
                wait(lambda: not reader.in_transaction, 'The GUI did not release the read lock')
            wait(lambda: not messages() and find('groupChatMessages').property('count') == 0,
                 'Clear did not recover after the lock')
            assert first in group.aliases and second in group.aliases
            click('groupChatDetailsButton')
            click('groupChatMember_agent:' + first, Qt.RightButton)
            click('groupChatRemoveMember')
            wait(lambda: first not in group.aliases, 'Removal did not persist')
            click('sidebarRow_' + first)
            wait(lambda: window.property('page') == 'chat' and backend.activeSession == first,
                 'Selecting another conversation did not close the group')
            count = len(requests)
            backend.send('移出群聊后，在普通会话里继续。')
            wait(lambda: len(requests) > count, 'Pi did not start after removing the member', 25)
            assert 'submit_to_chatgroup' not in requests[count][0]
            print('Workspace group: entry, member management, Pi reporting, side preview and navigation verified.')
    finally:
        backend.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


if __name__ == '__main__':
    with TemporaryDirectory(prefix='umeko-workspace-group-') as folder, patch(
            'app.storage.protect', side_effect=lambda value, *_, **__: value):
        run(Path(folder).resolve())
