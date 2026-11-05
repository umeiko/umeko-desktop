"""Real offscreen paging: mixed rich histories must cover the settled viewport."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from collections import Counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class DynamicMessageLoadingTests(unittest.TestCase):
    def test_mixed_history_fast_scroll_and_retained_controls(self):
        with tempfile.TemporaryDirectory(prefix='umeko-dynamic-loading-') as directory:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--child', directory],
                cwd=ROOT, env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                                   QT_QUICK_CONTROLS_STYLE='Basic', UMEKO_DATA_DIR=str(Path(directory) / 'profile')),
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())


def run_history(base):
    from PySide6.QtCore import QObject, Signal, QMetaObject, Q_ARG, Qt
    from PySide6.QtTest import QTest
    import shiboken6
    from app.message_attachments import attachment_prompt
    from main import create_application

    class QuietNotifications(QObject):
        activated = Signal(str)

        def __init__(self, *args):
            super().__init__()

        def task_finished(self, *args):
            pass

        def close(self):
            pass

    profile = base / 'profile'
    profile.mkdir()
    (profile / 'settings.json').write_text(json.dumps({
        'agent': {'agentDir': str(base / 'agent')}, 'workspace': str(base)}), encoding='utf-8')
    with patch('app.controller.Controller.loadNativeIndex', lambda self: None), \
         patch('app.tray.TrayController.tray_available', lambda self: False), \
         patch('app.notifications.TaskNotifications', QuietNotifications):
        app, engine, backend = create_application()
    window = engine.rootObjects()[0]
    window.resize(1400, 1000)
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    backend.store.data.update(providers=[{'id': 'test-provider', 'name': 'Test provider', 'api': 'openai',
        'baseUrl': '', 'key': '', 'models': [{'upstream': 'test-model', 'alias': 'test-model'}]}],
        selectedProvider='test-provider', selectedModel='test-model')
    counts, tracked = Counter(), set()

    def items(root):
        todo = [root]
        while todo:
            item = todo.pop()
            yield item
            todo.extend(item.childItems())

    def find(name):
        return next((item for item in items(window.contentItem()) if item.objectName() == name), None)

    def observe(view, name):
        def scan():
            for item in view.property('contentItem').childItems():
                if item.property('messageSlot') is not True:
                    continue
                pointer = shiboken6.getCppPointer(item)[0]
                if pointer in tracked:
                    continue
                tracked.add(pointer)
                item.destroyed.connect(lambda _, pointer=pointer: tracked.discard(pointer))

                def changed(item=item):
                    if shiboken6.isValid(item) and item.property('bodyReady'):
                        counts[name, item.property('index')] += 1

                item.bodyReadyChanged.connect(changed)
                changed()
        view.property('contentItem').childrenChanged.connect(scan)
        scan()

    def invoke(view, method, *args):
        assert QMetaObject.invokeMethod(view, method, Qt.DirectConnection,
                                       *[Q_ARG('QVariant', arg) for arg in args])

    def visible(view):
        top = view.property('contentY')
        return sorted([(item.property('index'), item.property('bodyReady'), item.y() - top, item.height())
            for item in view.property('contentItem').childItems() if item.property('messageSlot') is True
            and item.y() + item.height() > top + 2 and item.y() < top + view.height() - 2], key=lambda row: row[2])

    def covered(view):
        assert QMetaObject.invokeMethod(view, 'forceLayout', Qt.DirectConnection)
        controller = engine.incubationController()
        if backend.messageModel._job is not None or (controller and controller.incubatingObjectCount()):
            return False
        rows = visible(view)
        if not rows or not all(row[1] for row in rows) or view.property('restoring'):
            return False
        edge, gap = 0, view.property('spacing') + 2
        for _, _, y, height in rows:
            if y - edge > gap:
                return False
            edge = max(edge, y + height)
        return edge >= view.height() - gap

    def wait(check, seconds=15):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            QTest.qWait(10)
            time.sleep(.001)  # Let the Python paging worker run alongside Qt.
            if check():
                return True
        return False

    def open_session(name, token):
        backend.sessionPreview.prepare(name, token)
        assert wait(lambda: backend.sessionPreview.prepared is not None), ('prepare', name, warnings)
        assert backend.sessionPreview.activate(token)
        view = find('conversation')
        observe(view, name)
        assert wait(lambda: covered(view)), ('open', name, visible(view), warnings)
        return view

    def make_history(name, mixed):
        entries = []

        def add(role, content, **values):
            entries.append({'type': 'message', 'id': f'{name}-{len(entries)}',
                'parentId': entries[-1]['id'] if entries else None,
                'message': {'role': role, 'content': content, 'provider': 'test-provider',
                            'model': 'test-model', **values}})

        attachment = base / 'attachment.txt'
        attachment.write_text('A local test attachment.', encoding='utf-8')
        for turn in range(200):
            prompt = f'Question {turn}'
            if mixed and turn % 3 == 0:
                prompt = attachment_prompt(prompt, [{'kind': 'file', 'path': str(attachment)}])
            add('user', prompt)
            if not mixed:
                add('assistant', 'A normal reply for control-creation comparison.', stopReason='stop')
                continue
            text = f'Reply {turn}\n\n```python\n' + ''.join(
                f'print({line})\n' for line in range((4, 220, 12)[turn % 3])) + '```\n\n'
            text += '| Step | Value |\n| --- | --- |\n' + ''.join(
                f'| {line} | result {line} |\n' for line in range(12))
            call = f'command-{turn}'
            add('assistant', [{'type': 'thinking', 'thinking': 'Collapsed reasoning line.\n' * (2000, 180, 35)[turn % 3]},
                {'type': 'text', 'text': text}, {'type': 'toolCall', 'id': call, 'name': 'bash',
                                               'arguments': {'command': 'printf fixture'}}])
            add('toolResult', [{'type': 'text', 'text': 'command output\n' * (900 if turn % 2 else 2)}], toolCallId=call)
            if turn % 4 == 0:
                entries.append({'type': 'custom', 'id': f'delivery-{turn}', 'parentId': entries[-1]['id'],
                    'customType': 'umeko-chatbox', 'data': {'version': 1, 'toolCallId': call + '/delivery',
                        'items': [{'kind': 'file', 'path': str(attachment), 'title': 'Fixture report'}]}})
            add('assistant', [{'type': 'text', 'text': f'Command {turn} finished.'}], stopReason='stop')
        source = base / f'{name}.jsonl'
        source.write_text('\n'.join(json.dumps(entry) for entry in entries) + '\n', encoding='utf-8')
        backend._sessions.append({'id': name, 'file': str(source), 'title': name, 'workspace': str(base)})

    try:
        backend._sessions = []
        make_history('normal', False)
        make_history('mixed', True)
        backend.chatChanged.emit()
        normal = open_session('normal', 1)
        normal_model = backend.messageModel
        normal_bubble = find('messageBubble_399')
        identity = shiboken6.getCppPointer(normal_bubble)[0]
        normal_creations = sum(counts.values())
        view = open_session('mixed', 2)
        results, expanded, details = [], set(), set()
        for target in (backend.messageModel.rowCount() - 20, 450, 310, 240, 170, 100, 30, 3, 5):
            invoke(view, 'jumpToMessage', target)
            assert wait(lambda: covered(view)), ('jump', target, visible(view))
            # Invoke QML actions without injecting desktop input. Leave some
            # tools folded and open others, including short and long output.
            for item in list(items(view)):
                name = item.objectName()
                if name.startswith('toggleTools_') and item.isVisible() and (target in (3, 5) or int(name.split('_')[1]) % 4 == 1):
                    root = item.parentItem().parentItem()
                    root.property('expansionState').setProperty('expanded', True)
                    assert root.setProperty('expanded', True)
                    expanded.add(name)
            QTest.qWait(30)
            for item in list(items(view)):
                name = item.objectName()
                if name.startswith('toggleToolDetail_') and item.isVisible():
                    assert item.parentItem().parentItem().setProperty('details', True)
                    details.add(name)
            for delta in (-4500, -12000, 3200, -18000, 900, -6000, 2400, -8000):
                invoke(view, 'scrollBy', delta)
                QTest.qWait(2)
            settled = wait(lambda: covered(view), 5)
            results.append({'target': target, 'covered': settled, 'visible': visible(view)})
        assert all(result['covered'] for result in results), results
        assert {'toggleToolDetail_command-0', 'toggleToolDetail_command-1'} <= details, details
        # Prepared rows stay within the requested groups, never the whole history.
        model = backend.messageModel
        assert len(model._prepared) <= max(16, len(model._wanted)) <= model.rowCount() // 2, (len(model._prepared), len(model._wanted))
        warm = open_session('normal', 3)
        assert warm is normal and backend.messageModel is normal_model
        assert shiboken6.getCppPointer(find('messageBubble_399'))[0] == identity
        assert sum(value for (name, _), value in counts.items() if name == 'normal') == normal_creations
        # The screen's groups and one group on each side, not 400 bodies.
        assert normal_creations < 60, counts
        assert not warnings, warnings[:10]
        print(json.dumps({'normal_controls': normal_creations, 'sequences': len(results),
                          'empty': sum(not result['covered'] for result in results),
                          'expanded_tools': len(expanded), 'expanded_outputs': len(details),
                          'retained_view': True}), flush=True)
    finally:
        backend.close()
        window.hide()
        shiboken6.delete(engine)


if __name__ == '__main__':
    if '--child' in sys.argv:
        run_history(Path(sys.argv[-1]))
    else:
        unittest.main()
