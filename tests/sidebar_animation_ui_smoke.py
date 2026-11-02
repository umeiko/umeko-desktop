"""Sidebar motion must not repeatedly reflow long, even folded, thinking."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ.setdefault('QT_QUICK_BACKEND', 'software')

from PySide6.QtCore import QObject, QMetaObject, Qt, Signal
from PySide6.QtQuick import QQuickItem
from PySide6.QtQml import QQmlExpression, qmlContext
from PySide6.QtTest import QTest
from app.storage import Store
from main import create_application


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

    def task_finished(self, *args):
        pass


with tempfile.TemporaryDirectory(prefix='umeko-sidebar-animation-') as directory:
    os.environ['UMEKO_DATA_DIR'] = directory
    store = Store()
    store.data['agent']['agentDir'] = str(Path(directory) / 'agent')
    store.save()
    with patch('app.tray.TrayController', QuietTray), patch('app.notifications.TaskNotifications', QuietNotifications):
        app, engine, backend = create_application()
    window = engine.rootObjects()[0]
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))

    def items():
        stack = [window.contentItem()]
        while stack:
            item = stack.pop()
            yield item
            stack.extend(item.childItems())

    def find(name):
        for item in items():
            if item.objectName() == name:
                return item
        raise AssertionError(name)

    def invoke(item, method):
        assert QMetaObject.invokeMethod(item, method, Qt.DirectConnection), method

    def settle():
        deadline = time.monotonic() + 15
        while motion.property('moving'):
            assert time.monotonic() < deadline, 'Sidebar did not settle'
            QTest.qWait(1)
        QTest.qWait(100)

    try:
        window.resize(1060, 860)
        QTest.qWait(150)
        motion = find('sidebarWidthMotion')
        settle()
        thinking = ('Compare the constraints and each possible result before deciding.\n' * 400)[:20000]
        backend._view.messages = [
            {'role': 'assistant', 'thinking': thinking, 'text': f'Result {i}.'}
            for i in range(8)
        ]
        backend.chatChanged.emit()
        QTest.qWait(250)
        conversation = find('conversation')
        widths, frames = [], []
        conversation.widthChanged.connect(lambda: widths.append(conversation.width()))
        window.frameSwapped.connect(lambda: frames.append(time.perf_counter()))

        def animate(label, reverse=False):
            widths.clear()
            frames.clear()
            initial = conversation.width()
            invoke(window, 'toggleSidebar')  # Same handler as the button and Ctrl+B.
            assert motion.property('moving')
            if reverse:
                QTest.qWait(60)
                invoke(window, 'toggleSidebar')
            settle()
            # This count is independent of rendering speed. On the old binding
            # each PID step invalidates every instantiated TextEdit's layout.
            assert len(widths) <= 2, (label, 'full conversation reflows', len(widths))
            assert len(frames) > 2, (label, 'No animated frames')
            controls = find('chatWidthControls')
            expected = find('chatPage').width() - controls.property('conversationLeft') - controls.property('conversationRight')
            assert abs(conversation.width() - expected) < .1, (label, 'Final wrap width')
            if not reverse:
                assert abs(conversation.width() - initial) > 60, (label, 'Width did not change')
            intervals = sorted((b-a)*1000 for a,b in zip(frames, frames[1:]))
            print(json.dumps({'case': label, 'conversation_reflows': len(widths),
                              'frames': len(frames), 'p95_ms': round(intervals[int(len(intervals)*.95)], 2)}), flush=True)

        animate('folded collapse')
        animate('folded expand')
        # Reveal a real long thinking block through its existing click signal.
        toggle = max((item for item in items()
                      if item.objectName().startswith('toggleThinking_') and item.isVisible()),
                     key=lambda item: tuple(map(int, item.objectName().split('_')[1:])))
        suffix = toggle.objectName().removeprefix('toggleThinking_')
        click = QQmlExpression(qmlContext(toggle), toggle, 'clicked(null)')
        click.evaluate()
        assert not click.hasError(), click.error().toString()
        QTest.qWait(150)
        text = find(f'thinkingText_{suffix}')
        assert text.isVisible() and len(text.property('text')) == len(thinking), (suffix, text.isVisible(), len(text.property('text')))
        changes = []
        text.widthChanged.connect(lambda: changes.append(text.width()))
        animate('expanded collapse')
        animate('expanded expand')
        animate('rapid reversal', reverse=True)
        assert len(changes) <= 6, ('Expanded thinking repeatedly reflowed', len(changes))
        assert len(text.property('text')) == len(thinking)
        assert text.property('contentHeight') > 100
        # A real window resize outside the animation must still update wrapping.
        previous = conversation.width()
        window.resize(1120, 860)
        QTest.qWait(40)
        settle()
        assert conversation.width() > previous + 40
        assert not warnings, '\n'.join(warnings)
        print('SIDEBAR_ANIMATION_UI_OK', flush=True)
    finally:
        backend.close()
        import shiboken6
        shiboken6.delete(engine)
