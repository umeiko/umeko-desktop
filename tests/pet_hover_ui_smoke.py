"""Real Qt hover hint: no focus, draft, session or dispatch side effects."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = tempfile.TemporaryDirectory(prefix='pet-hover-150-')
language = os.environ.get('UMEKO_PET_HOVER_LANGUAGE', 'zh')
assert language in ('zh', 'en')
os.environ.update(UMEKO_DATA_DIR=tmp.name+'/profile', PI_CODING_AGENT_DIR=tmp.name+'/agent',
                  QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software', UMEKO_LANGUAGE=language)
from PySide6.QtCore import QObject, QPoint, Qt
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QSystemTrayIcon
QSystemTrayIcon.show = lambda *args: None
from main import create_application
import shiboken6
app, engine, backend = create_application()
main = engine.rootObjects()[0]
pet = backend.desktopPlugins.pet
out = ROOT / 'build/pet-hover-150'
out.mkdir(parents=True, exist_ok=True)

def js(obj, code):
    exp = QQmlExpression(QQmlEngine.contextForObject(obj), obj, code)
    result = exp.evaluate()[0]
    assert not exp.hasError(), exp.error().toString()
    return result

def wait(test, message):
    for _ in range(250):
        if test(): return
        QTest.qWait(20)
    raise AssertionError(message)


try:
    backend._command_pi = Mock(side_effect=AssertionError('unexpected native command'))
    backend.desktopPlugins.call_for = Mock(side_effect=AssertionError('unexpected widget call'))
    original = backend._view
    original.draft = '主窗口合成草稿'
    original.attachments.append({'path': 'fixture.png'})
    pet.ui('show', {})
    wait(lambda: pet.assistantStatus.get('bound'), 'No pet binding')
    window = main.findChild(QObject, 'desktopPetWindow')
    pointer = window.findChild(QObject, 'desktopPetPointer')
    preview = window.findChild(QObject, 'desktopPetHoverPreview')
    label = preview.findChild(QObject, 'desktopPetHoverPreviewLabel')
    composer = window.findChild(QObject, 'desktopPetTaskComposer')
    field = composer.findChild(QObject, 'desktopPetTaskInput')
    input_window = window.findChild(QObject, 'desktopPetTaskWindow')
    main.requestActivate()
    wait(lambda: main.isActive(), 'Main did not gain focus for the test')
    focused = main.activeFocusItem()
    point = js(pointer, 'mapToItem(null, width/2, height/2)').toPoint()
    away = QPoint(2, 2)
    QTest.mouseMove(window, away)
    QTest.qWait(25)
    js(window, 'caption = ""')
    session_keys = tuple(backend._pool.records)
    sessions = tuple(row['id'] for row in backend._sessions)
    state = (original.draft, list(original.attachments), original.model, original.provider,
             composer.property('targetId'), field.property('text'),
             dict(pet.projectEntry.state), dict(pet.taskSchedule.state))
    QTest.mouseMove(window, point)
    wait(lambda: pointer.property('containsMouse'), 'Mouse did not arrive')
    QTest.qWait(170)
    assert not preview.property('visible'), 'Preview ignored hover delay'
    wait(lambda: preview.property('visible'), 'Preview did not appear')
    assert label.property('text') == ('双击桌宠打开聊天' if language == 'zh' else 'Double-click the pet to chat')
    assert main.isActive() and main.activeFocusItem() is focused
    assert not input_window.isActive() and not composer.property('visible')
    assert tuple(backend._pool.records) == session_keys
    assert tuple(row['id'] for row in backend._sessions) == sessions
    assert backend._view is original
    assert state == (original.draft, list(original.attachments), original.model, original.provider,
                     composer.property('targetId'), field.property('text'),
                     dict(pet.projectEntry.state), dict(pet.taskSchedule.state))
    assert window.grabWindow().save(str(out/f'hover-{language}.png'))

    # Moving off before the deadline, pressing/dragging, and context-menu entry
    # must not rearm a delayed hint without a fresh hover.
    QTest.mouseMove(window, away)
    wait(lambda: not preview.property('visible'), 'Preview did not dismiss')
    QTest.mouseMove(window, point)
    QTest.qWait(100)
    QTest.mouseMove(window, away)
    QTest.qWait(460)
    assert not preview.property('visible')
    QTest.mouseMove(window, point)
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(460)
    assert not preview.property('visible')
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(460)
    assert not preview.property('visible')
    QTest.mouseClick(window, Qt.RightButton, Qt.NoModifier, point)
    context = window.findChild(QObject, 'desktopPetContextMenu')
    wait(lambda: context.property('visible'), 'Context menu did not open')
    assert not preview.property('visible')
    js(context, 'close()')

    # The existing explicit double-click still opens and focuses the editor.
    QTest.mouseDClick(window, Qt.LeftButton, Qt.NoModifier, point)
    wait(lambda: composer.property('opened'), 'Explicit editor no longer opens')
    assert not preview.property('visible')
    field.setProperty('text', '桌宠合成草稿')
    QTest.keyClick(input_window, Qt.Key_Escape)
    wait(lambda: not composer.property('visible'), 'Escape no longer closes the editor')
    QTest.mouseMove(window, away)
    QTest.mouseMove(window, point)
    wait(lambda: preview.property('visible'), 'No repeat hover hint')
    assert field.property('text') == '桌宠合成草稿'
    pet.assistantSpeech.emit('合成重要回复')
    wait(lambda: not preview.property('visible'), 'Important response did not hide preview')
    assert window.findChild(QObject, 'desktopPetSpeechBubble').property('visible')
    pet.assistantSpeech.emit('')
    wait(lambda: preview.property('visible'), 'No hover preview after synthetic response cleared')
    assert pet.ui('hide', {})['ok']
    wait(lambda: not shiboken6.isValid(window) or (not window.isVisible() and not preview.property('visible')), 'Hide left preview visible')
    assert original.draft == '主窗口合成草稿'
    backend._command_pi.assert_not_called()
    backend.desktopPlugins.call_for.assert_not_called()
    print('PET_HOVER_150_OK: delay, passive focus, session/draft isolation, press/menu, double-click, Escape, hide')
finally:
    backend.close()
    shiboken6.delete(engine)
    app.processEvents()
    tmp.cleanup()
