"""Real offscreen app: a read-file tool row opens the shared file preview.

The row must not fold out the file text. A missing file keeps the existing
"moved or missing" toast, a failed read still expands to its error, and other
tools keep their inline details. No provider, Pi process or desktop input is
used; Qt mouse events are delivered to the offscreen window only.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class ReadToolPreviewTests(unittest.TestCase):
    def test_read_row_opens_preview_instead_of_expanding(self):
        # Screenshots can set a short neutral temp root so the preview path shown
        # in the header does not include a local user directory.
        temporary_root = os.environ.get('UMEKO_READ_PREVIEW_TEMP_ROOT')
        with tempfile.TemporaryDirectory(prefix='umeko-read-preview-', dir=temporary_root) as directory:
            command = [sys.executable, str(Path(__file__).resolve()), '--child', directory]
            if os.environ.get('UMEKO_READ_PREVIEW_SCREENSHOTS'):
                command.extend(['--screenshots', os.environ['UMEKO_READ_PREVIEW_SCREENSHOTS']])
            result = subprocess.run(command, cwd=ROOT,
                env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                         QT_QUICK_CONTROLS_STYLE='Basic', PYTHONUTF8='1',
                         UMEKO_DATA_DIR=str(Path(directory) / 'profile'),
                         UMEKO_WEBVIEW_COMPONENT_DIR=str(Path(directory) / 'missing-components'),
                         PI_CODING_AGENT_DIR=str(Path(directory) / 'agent')),
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(summary['previewPath'], summary['expectedPath'])


def run_child(base, screenshots=None):
    from PySide6.QtCore import QObject, Qt, Signal
    from PySide6.QtTest import QTest
    import shiboken6
    from main import create_application

    class QuietNotifications(QObject):
        activated = Signal(str)

        def __init__(self, *args):
            super().__init__()

        def task_finished(self, *args):
            pass

        def close(self):
            pass

    workspace = base / 'workspace'
    workspace.mkdir()
    notes = workspace / 'notes.md'
    notes.write_text('# Release notes\n\n- Read rows open this preview.\n- Other tools still expand.\n', encoding='utf-8')
    missing = workspace / 'deleted.py'
    profile = base / 'profile'
    profile.mkdir()
    (profile / 'settings.json').write_text(json.dumps({
        'agent': {'agentDir': str(base / 'agent')}, 'workspace': str(workspace)}), encoding='utf-8')
    with patch('app.controller.Controller.loadNativeIndex', lambda self: None), \
         patch('app.tray.TrayController.tray_available', lambda self: False), \
         patch('app.notifications.TaskNotifications', QuietNotifications), \
         patch('app.webview.configure'):
        app, engine, backend = create_application()
    # Match the compaction fixture: offscreen delegates have no continuous
    # rendered-frame incubation budget. Keep model work asynchronous.
    engine.setIncubationController(None)
    window = engine.rootObjects()[0]
    window.resize(1400, 900)
    warnings, toasts = [], []
    engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    backend.toast.connect(toasts.append)
    backend.store.data.update(providers=[{'id': 'test-provider', 'name': 'Test provider', 'api': 'openai',
        'baseUrl': '', 'key': '', 'models': [{'upstream': 'test-model', 'alias': 'test-model'}]}],
        selectedProvider='test-provider', selectedModel='test-model')

    def items(root):
        todo = [root]
        while todo:
            item = todo.pop()
            yield item
            if item.objectName() != 'webSurfaceLoader':
                todo.extend(item.childItems())

    def find(name, prefix=False):
        return next((item for item in items(window.contentItem())
                     if (item.objectName().startswith(name) if prefix else item.objectName() == name)), None)

    def wait(check, label):
        # A bounded wait for asynchronous Qt work; nothing measures elapsed time.
        for _ in range(400):
            QTest.qWait(25)
            if check():
                return
        raise AssertionError('Timed out waiting for ' + label + ': ' + '\n'.join(warnings[:5]))

    def click(item):
        name = item.objectName()
        wait(lambda: (target := find(name)) is not None and target.isVisible()
             and target.width() > 0 and target.height() > 0, 'click target ' + name)
        window.grabWindow()  # Finish virtual-list layout before mapping input.
        item = find(name)
        point = item.mapToScene(item.boundingRect().center()).toPoint()
        # Populate the selection overlay's passive hover target before pressing,
        # as a real pointer does. Some offscreen platforms omit this implicit move.
        QTest.mouseMove(window, point)
        QTest.qWait(25)
        # Hover processes queued model/layout work; remap the current delegate.
        window.grabWindow()
        item = find(name)
        assert item is not None, name
        point = item.mapToScene(item.boundingRect().center()).toPoint()
        assert window.contentItem().contains(point), (name, point)
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(80)

    def shot(name):
        if screenshots:
            Path(screenshots).mkdir(parents=True, exist_ok=True)
            assert window.grabWindow().save(str(Path(screenshots) / name)), name

    def tool(identifier, name, args, state='done', result=''):
        backend._handle_pi_event(backend._view, {'type': 'tool', 'id': identifier, 'name': name,
                                                 'state': state, 'args': args, 'result': result})

    try:
        backend._view.messages.append({'role': 'user', 'text': 'Summarize the release notes.'})
        tool('read-ok', 'read', {'path': 'notes.md'}, result=notes.read_text(encoding='utf-8'))
        tool('read-missing', 'read', {'path': 'deleted.py'}, result='print("gone")')
        tool('read-failed', 'read', {'path': 'locked.txt'}, state='error', result='EACCES: permission denied')
        tool('bash-1', 'bash', {'command': 'git status --short'}, result=' M notes.md')
        backend._view.messages[-1]['text'] = 'The notes describe the new read preview.'
        backend.chatChanged.emit(); backend.transcriptChanged.emit(); backend.viewChanged.emit()
        wait(lambda: find('toggleTools_', prefix=True) is not None, 'tool history header')
        click(find('toggleTools_', prefix=True))
        wait(lambda: find('toggleToolDetail_read-ok') is not None and find('toggleToolDetail_read-ok').isVisible(), 'tool rows')

        # The read row advertises a preview, not a fold-out chevron.
        assert find('toolRowAffordance_read-ok').property('name') == 'eye'
        assert find('toolRowAffordance_read-missing').property('name') == 'eye'
        assert find('toolRowAffordance_read-failed').property('name') == 'chevron-right'
        assert find('toolRowAffordance_bash-1').property('name') == 'chevron-right'
        shot('01-tool-rows.png')

        # Clicking the read row opens the shared document preview for that file.
        pane = find('webPane')
        click(find('toggleToolDetail_read-ok'))
        wait(lambda: backend.documentPreview.state.get('html') and not pane.property('moving'), 'document preview')
        assert pane.property('mode') == 'document', pane.property('mode')
        preview_path = backend.documentPreview.state.get('path')
        assert os.path.normcase(preview_path) == os.path.normcase(str(notes.resolve())), preview_path
        assert 'Release notes' in find('documentPreviewText').property('text')
        detail = find('toolDetail_read-ok')
        assert detail is None or not detail.isVisible(), 'read row expanded inline'
        assert not find('toggleToolDetail_read-ok').parentItem().parentItem().property('details')
        shot('02-read-preview-open.png')

        # A missing file keeps the existing error toast and opens no preview.
        click(find('closeWebPaneButton'))
        wait(lambda: not pane.property('opened') and not pane.property('moving'), 'preview closed')
        toasts.clear()
        click(find('toggleToolDetail_read-missing'))
        wait(lambda: toasts, 'missing-file toast')
        assert toasts == ['文件已移动或不存在'], toasts
        assert not pane.property('opened'), 'missing file opened a preview'
        detail = find('toolDetail_read-missing')
        assert detail is None or not detail.isVisible()
        shot('03-read-missing-toast.png')

        # A failed read still folds out its error, and other tools keep details.
        click(find('toggleToolDetail_read-failed'))
        wait(lambda: find('toolDetail_read-failed') is not None and find('toolDetail_read-failed').isVisible(), 'failed read detail')
        assert 'EACCES' in find('toolDetail_read-failed').property('text')
        click(find('toggleToolDetail_bash-1'))
        wait(lambda: find('toolDetail_bash-1') is not None and find('toolDetail_bash-1').isVisible(), 'bash detail')
        assert 'git status' in find('toolDetail_bash-1').property('text')
        assert not pane.property('opened')
        shot('04-other-tools-expand.png')

        if screenshots:
            click(find('closeWebPaneButton'))
            wait(lambda: not pane.property('opened') and not pane.property('moving'), 'preview closed')
            backend.store.data['ui']['language'] = 'zh' if backend.language == 'en' else 'en'
            backend.appearanceChanged.emit()
            QTest.qWait(150)
            click(find('toggleToolDetail_read-ok'))
            wait(lambda: backend.documentPreview.state.get('html') and not pane.property('moving'), 'second-language preview')
            shot('05-read-preview-open-' + backend.language + '.png')
        assert not warnings, warnings[:10]
        print(json.dumps({'previewPath': os.path.normcase(preview_path),
                          'expectedPath': os.path.normcase(str(notes.resolve()))}), flush=True)
    finally:
        backend.close()
        window.hide()
        shiboken6.delete(engine)


if __name__ == '__main__':
    if '--child' in sys.argv:
        shots = sys.argv[sys.argv.index('--screenshots') + 1] if '--screenshots' in sys.argv else None
        run_child(Path(sys.argv[sys.argv.index('--child') + 1]), shots)
    else:
        unittest.main()
