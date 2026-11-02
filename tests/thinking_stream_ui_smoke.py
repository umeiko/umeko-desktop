"""Real chat + local SSE reasoning stream; no accounts, windows or native notices."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QUICK_BACKEND'] = 'software'
os.environ['UMEKO_LANGUAGE'] = 'en'

from PySide6.QtCore import QEventLoop, QObject, QMetaObject, QPointF, Qt, QTimer, Signal, Slot
from PySide6.QtTest import QTest
from app.storage import Store
from main import create_application
from reasoning_stream_fixture import ReasoningStream


class QuietTray(QObject):
    quitRequested = Signal()
    notificationRequested = Signal(str)

    def __init__(self, window, icon, parent):
        super().__init__(parent)
        self.tray = None

    def set_language(self, language):
        pass

    def restore(self):
        pass


class QuietNotifications(QObject):
    activated = Signal(str)

    def __init__(self, window, tray, root, parent):
        super().__init__(parent)

    @Slot(str, str, bool, bool)
    def task_finished(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--record', type=Path)
    args = parser.parse_args()
    samples = []
    engine = backend = timer = None
    with tempfile.TemporaryDirectory(prefix='umeko-thinking-stream-') as sandbox, ExitStack() as mocks:
        server = mocks.enter_context(ReasoningStream())
        sent, requests = server.sent, server.requests
        os.environ['UMEKO_DATA_DIR'] = str(Path(sandbox) / 'profile')
        seed = Store()
        seed.data['agent']['agentDir'] = str(Path(sandbox) / 'agent')
        seed.data['agent']['safeMode'] = True
        seed.data['providers'] = [{'id': 'test-provider', 'name': 'Test provider', 'api': 'openai',
            'baseUrl': f'http://127.0.0.1:{server.server_port}/v1', 'key': 'test-key',
            'proxy': {'mode': 'direct'}, 'models': [{'alias': 'test-model', 'upstream': 'test-model'}]}]
        seed.data['selectedProvider'] = 'test-provider'
        seed.data['selectedModel'] = 'test-model'
        seed.save()
        mocks.enter_context(patch('app.tray.TrayController', QuietTray))
        mocks.enter_context(patch('app.notifications.TaskNotifications', QuietNotifications))
        mocks.enter_context(patch('app.controller.Controller.loadNativeIndex', lambda self: None))
        mocks.enter_context(patch('app.desktop_plugins.DesktopPlugins.start', lambda *args: None))
        try:
            app, engine, backend = create_application()
            window = engine.rootObjects()[0]
            window.setWidth(1000)
            window.setHeight(700)
            window.setProperty('page', 'chat')

            def find(prefix):
                pending = [window.contentItem()]
                while pending:
                    item = pending.pop()
                    if item.objectName().startswith(prefix) and item.isVisible():
                        return item
                    pending.extend(item.childItems())
                return None

            event_loop = QEventLoop()

            def until(predicate, timeout=25):
                deadline = time.monotonic() + timeout
                while not predicate():
                    server.poll()
                    assert not server.errors, server.errors
                    assert time.monotonic() < deadline, ('Timed out', sent.value, requests, backend._view.messages)
                    # Use a real Qt event loop, as app.exec() does, so the
                    # loopback gateway's Python threads also get to run.
                    QTimer.singleShot(10, event_loop.quit)
                    event_loop.exec()
                server.poll()

            assert backend.send('Run the local reasoning stream test.')
            until(lambda: find('toggleThinking_') is not None)
            QTest.qWait(600)
            toggle = find('toggleThinking_')
            thinking_root = toggle.parentItem().parentItem()
            thinking_root.property('expansionState').setProperty('expanded', True)
            assert thinking_root.setProperty('expanded', True)
            QTest.qWait(100)
            view = find('conversation')
            status = find('turnStatus')
            phase = 'tail'
            started = time.monotonic()
            attached = set()
            connections = []
            cached = {}

            def sample(event='tick'):
                import shiboken6
                thinking = cached.get('thinking')
                if thinking is None or not shiboken6.isValid(thinking) or not thinking.isVisible():
                    thinking = find('thinkingText_')
                if thinking is None:
                    return
                cached['thinking'] = thinking
                row = cached.get('row')
                if row is None or not shiboken6.isValid(row):
                    row = find('messageBubble_1').parentItem()
                    cached['row'] = row
                quick = thinking.property('textDocument')
                document = quick.textDocument()
                identity = shiboken6.getCppPointer(document)[0]
                if identity not in attached:
                    attached.add(identity)
                    for signal, label in ((document.contentsChanged, 'document'), (thinking.implicitHeightChanged, 'text-height'), (row.heightChanged, 'delegate-height')):
                        callback = lambda label=label: sample(label)
                        signal.connect(callback)
                        connections.append((document if label=='document' else thinking if label=='text-height' else row, signal, callback))
                block = document.begin()
                layout = block.layout()
                line = layout.lineAt(0) if layout.lineCount() else None
                fmt = block.blockFormat()
                samples.append({'event': event, 'ms': round((time.monotonic()-started)*1000, 2),
                    'tokens': sent.value, 'phase': phase, 'length': len(thinking.property('text')),
                    'contentY': view.property('contentY'), 'contentHeight': view.property('contentHeight'),
                    'originY': view.property('originY'), 'atYEnd': view.property('atYEnd'),
                    'footerBottom': status.parentItem().mapToItem(view, QPointF(0, status.parentItem().height())).y(),
                    'viewHeight': view.height(), 'followTail': view.property('followTail'),
                    'delegateHeight': row.height(), 'thinkingHeight': thinking.parentItem().parentItem().height(),
                    'textHeight': thinking.height(), 'fontSize': thinking.property('font').pixelSize(),
                    'lineHeight': fmt.lineHeight(), 'lineHeightType': fmt.lineHeightType(),
                    'glyphHeight': line.height() if line else 0,
                    'secondLineY': document.documentLayout().blockBoundingRect(block.next()).y() if block.next().isValid() else 0,
                    'statusHeight': status.height(), 'statusVisible': status.isVisible(),
                    'statusState': status.property('state'), 'statusText': status.property('text'),
                    'firstLineViewportY': thinking.mapToItem(view, QPointF(0, 0)).y()})

            scroll_sample = lambda: sample('scroll')
            frame_sample = lambda: sample('frame')
            view.contentYChanged.connect(scroll_sample)
            window.frameSwapped.connect(frame_sample)
            timer = QTimer()
            timer.timeout.connect(sample)
            timer.start(4)
            sample('start')
            server.release.set()
            until(lambda: sent.value >= 410)
            # Use the existing QML scroll hook, with no input injection.
            phase = 'browse-transition'
            from PySide6.QtCore import Q_ARG
            assert QMetaObject.invokeMethod(view, 'scrollBy', Qt.DirectConnection, Q_ARG('QVariant', -250))
            QTest.qWait(100)
            phase = 'browse'
            until(lambda: sent.value >= 560)
            phase = 'finish'
            until(lambda: not backend.busy)
            QTest.qWait(150)
            timer.stop()
            sample('done')
            # The thinking delegate can be rebuilt when the final answer adds an activity.
            final_status = status.property('state')
            final_label = status.property('text')
            assert not server.errors, server.errors
            assert sent.value == 600 and requests == [('/v1/chat/completions', 'test-model')], requests
            assert not backend._view.failed, backend._view.messages
            assert 'The local streaming test is complete.' in str(backend._view.messages)
            active = [s for s in samples if s['phase'] == 'tail' and s['tokens'] > 5]
            browse = [s for s in samples if s['phase'] == 'browse']
            streamed = active + browse
            frames = [s for s in active if s['event'] == 'frame' and s['contentY'] > 1]
            backwards = [b['contentY']-a['contentY'] for a,b in zip(active,active[1:]) if b['contentY'] < a['contentY']-1]
            summary = {'tokens': sent.value, 'updates': len(samples), 'frames': sum(s['event']=='frame' for s in active),
                'fontSizes': sorted(set(s['fontSize'] for s in streamed)),
                'lineHeights': sorted(set(s['lineHeight'] for s in streamed)),
                'secondLineY': [min(s['secondLineY'] for s in streamed), max(s['secondLineY'] for s in streamed)],
                'largestTailGap': round(max(abs(s['footerBottom']-s['viewHeight']) for s in frames),3),
                'tailScrollAdvance': round(active[-1]['contentY']-active[0]['contentY'],3),
                'backwardJumps': len(backwards), 'largestBackwardJump': round(-min(backwards,default=0),3),
                'browseDrift': round(max(s['contentY'] for s in browse)-min(s['contentY'] for s in browse),3),
                'browseLineDrift': round(max(s['firstLineViewportY'] for s in browse)-min(s['firstLineViewportY'] for s in browse),3),
                'statusHeights': sorted(set(s['statusHeight'] for s in active)),
                'statusStates': sorted(set(s['statusState'] for s in samples) | {final_status})}
            print(json.dumps(summary, sort_keys=True), flush=True)
            if args.record:
                args.record.write_text(json.dumps({'summary': summary, 'samples': samples}), encoding='utf-8')
            assert len(active) >= 200 and len(browse) >= 50, (len(active), len(browse))
            assert any(s['statusVisible'] and s['statusState']=='running' and 'Running' in s['statusText'] for s in active)
            assert status.isVisible() and final_status == 'finished' and 'Done' in final_label
            assert summary['fontSizes'] == [13], summary
            assert summary['lineHeights'] == [120], summary
            assert summary['secondLineY'][1]-summary['secondLineY'][0] <= 1, summary
            assert not backwards, summary
            assert summary['browseDrift'] <= 1, summary
            assert summary['browseLineDrift'] <= 1, summary
            assert len(frames) >= 20 and summary['tailScrollAdvance'] > view.height(), summary
            # A frame may precede the zero-delay tail timer by one newly added line.
            assert summary['largestTailGap'] <= summary['secondLineY'][1] + 1, summary
            print('THINKING_STREAM_UI_OK', flush=True)
        finally:
            server.stop.set()
            server.release.set()
            if timer:
                timer.stop()
            if 'sample' in locals():
                import shiboken6
                for owner, signal, callback in connections:
                    if shiboken6.isValid(owner):
                        signal.disconnect(callback)
                view.contentYChanged.disconnect(scroll_sample)
                window.frameSwapped.disconnect(frame_sample)
            if backend:
                backend.close()
            if engine:
                import shiboken6
                shiboken6.delete(engine)
                app.processEvents()


if __name__ == '__main__':
    main()
