"""Exercise the real pet popup, native focus and bound task route offscreen."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
temporary = tempfile.TemporaryDirectory(prefix='umeko-pet-task-ui-')
os.environ.update(UMEKO_DATA_DIR=str(Path(temporary.name) / 'profile'),
                  PI_CODING_AGENT_DIR=str(Path(temporary.name) / 'agent'),
                  QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software', UMEKO_LANGUAGE='zh')
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QInputMethodEvent
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QSystemTrayIcon
from shiboken6 import isValid
QSystemTrayIcon.show = lambda *args: None
from main import create_application

app, engine, backend = create_application()
backend.store.data.setdefault('agent', {})['agentDir'] = str(Path(temporary.name) / 'agent')
main = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda values: warnings.extend(value.toString() for value in values))
pet = backend.desktopPlugins.pet
out = Path(os.environ.get('UMEKO_PET_TASK_UI_OUTPUT', str(ROOT / 'build/pet-task-ui')))
out.mkdir(parents=True, exist_ok=True)


def wait(predicate, message):
    for _ in range(400):
        QTest.qWait(20)
        if predicate():
            return
    raise AssertionError(message + '\n' + '\n'.join(warnings))


def evaluate(obj, expression):
    query = QQmlExpression(QQmlEngine.contextForObject(obj), obj, expression)
    result = query.evaluate()[0]
    assert not query.hasError(), query.error().toString()
    return result


try:
    pet.ui('show', {})
    wait(lambda: main.findChild(QObject, 'desktopPetWindow') is not None, 'Pet did not load')
    window = main.findChild(QObject, 'desktopPetWindow')
    wait(lambda: window.mask().boundingRect().height() > 50, 'Pet silhouette did not load')
    point = window.mask().boundingRect().center()
    composer = window.findChild(QObject, 'desktopPetTaskComposer')
    field = composer.findChild(QObject, 'desktopPetTaskInput')
    send = composer.findChild(QObject, 'desktopPetTaskSend')
    backend.desktopPlugins.setEnabled('global-agents', False)
    QTest.mouseDClick(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(100)
    assert not composer.property('visible'), 'Unbound double click opened a popup'
    backend.desktopPlugins.setEnabled('global-agents', True)
    wait(lambda: pet.assistantStatus.get('bound'), 'Pet did not bind')
    identifier = pet.assistantStatus['id']
    bus = backend.desktopPlugins.global_agents
    record = bus.ensure(identifier)
    before_view = backend._view
    selected = bus.selected_conversation
    command = Mock(return_value=True)
    native_command = backend._command_pi
    backend._command_pi = command

    def open_composer(verify_motion=False):
        QTest.mouseDClick(window, Qt.LeftButton, Qt.NoModifier, point)
        if verify_motion:
            wait(lambda: 0 < composer.property('animationProgress') < 1, 'PID opening did not render intermediate frames')
        wait(lambda: composer.property('opened'), 'Double click did not open the composer')
        wait(lambda: field.property('activeFocus'), 'Text input did not receive focus')
        wait(lambda: not composer.property('animating'), 'PID opening did not settle')
        native = evaluate(composer, 'contentItem.Window.window')
        assert native is not window, 'Task input is clipped to the pet input mask'
        wait(lambda: QGuiApplication.focusWindow() is native, 'Native focus absent')
        assert QGuiApplication.focusObject() is field
        assert bool(QGuiApplication.inputMethod().queryFocusObject(Qt.ImEnabled, None))
        wait(lambda: native.width() >= 350, 'Task popup was constrained to the tiny pet window: '
             + str((native.metaObject().className(), native.width(), native.height(),
                    composer.property('width'), evaluate(composer, 'contentItem.width'))))
        assert abs(send.x() + send.width() / 2 - (native.width() - native.height() / 2)) < .5
        assert abs(send.y() + send.height() / 2 - native.height() / 2) < .5
        assert send.width() == send.height()
        assert evaluate(composer, 'background.radius') == composer.property('height') / 2
        return native

    native = open_composer(verify_motion=True)
    assert field.property('placeholderText') == ''
    assert not send.property('enabled'), 'Empty input can be sent'
    first = window.findChild(QObject, 'desktopPetAnimation').property('currentFrame')
    wait(lambda: window.findChild(QObject, 'desktopPetAnimation').property('currentFrame') != first,
         'Opening task input stopped the animation')
    field.setProperty('text', '检查项目状态')
    assert native.grabWindow().save(str(out / 'composer-zh.png'))
    QTest.keyClick(native, Qt.Key_Return)
    wait(lambda: not composer.property('visible'), 'Enter did not close the successful input')
    assert field.property('text') == ''
    command.assert_called_once_with('prompt', record, text='检查项目状态')
    assert backend._view is before_view and bus.selected_conversation == selected

    command.reset_mock()
    native = open_composer()
    field.setProperty('text', '发送按钮验证')
    click_point = send.mapToScene(QPointF(send.width() / 2, send.height() / 2)).toPoint()
    QTest.mouseClick(native, Qt.LeftButton, Qt.NoModifier, click_point)
    wait(lambda: not composer.property('visible'), 'Send button did not submit')
    command.assert_called_once_with('prompt', record, text='发送按钮验证')

    command.reset_mock()
    native = open_composer()
    QGuiApplication.sendEvent(native, QInputMethodEvent('中文预编辑', []))
    wait(lambda: field.property('inputMethodComposing'), 'IME preedit did not reach the field')
    QTest.keyClick(native, Qt.Key_Return)
    assert not command.called, 'IME confirmation was sent as a task'
    committed = QInputMethodEvent(); committed.setCommitString('中文任务')
    QGuiApplication.sendEvent(native, committed)
    wait(lambda: not field.property('inputMethodComposing'), 'IME commit did not finish')
    QTest.keyClick(native, Qt.Key_Return)
    wait(lambda: not composer.property('visible'), 'Committed Chinese task was not sent')
    command.assert_called_once_with('prompt', record, text='中文任务')

    command.reset_mock()
    native = open_composer()
    field.setProperty('text', '取消候选时保留正文')
    QGuiApplication.sendEvent(native, QInputMethodEvent('候选', []))
    wait(lambda: field.property('inputMethodComposing'), 'Preedit absent')
    QTest.keyClick(native, Qt.Key_Escape)
    assert composer.property('desiredOpen'), 'IME Escape closed the capsule'
    assert not command.called, 'IME Escape dispatched a task'
    # Offscreen has no OS input context. Simulate the platform cancellation
    # response; reset() alone cannot clear an artificially injected preedit.
    QGuiApplication.sendEvent(native, QInputMethodEvent('', []))
    wait(lambda: not field.property('inputMethodComposing'), 'Cancellation response not applied')
    assert field.property('text') == '取消候选时保留正文'
    QTest.keyClick(native, Qt.Key_Escape)
    wait(lambda: not composer.property('visible'), 'Second Escape did not close')

    command.reset_mock(); command.return_value = False
    native = open_composer()
    field.setProperty('text', '失败时保留这段输入')
    QTest.keyClick(native, Qt.Key_Return)
    wait(lambda: bool(composer.property('error')), 'Failure was not shown')
    assert composer.property('visible') and field.property('text') == '失败时保留这段输入'
    assert native.grabWindow().save(str(out / 'composer-error.png'))
    QTest.keyClick(native, Qt.Key_Escape)
    assert not composer.property('desiredOpen') and composer.property('visible'), 'Closing skipped the PID transition'
    wait(lambda: not composer.property('visible'), 'Escape did not dismiss')
    native = open_composer()
    assert field.property('text') == '失败时保留这段输入', 'Dismissal discarded the draft'
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    assert composer.property('desiredOpen'), 'Clicking pet dismissed input'
    main.show(); main.requestActivate()
    wait(lambda: not composer.property('visible'), 'Switching outside pet/input did not dismiss')

    native = open_composer()
    backend.desktopPlugins.setEnabled('global-agents', False)
    wait(lambda: not composer.property('visible'), 'Unbinding left a sendable input open')
    calls = command.call_count
    assert not pet.sendTask('迟到的提交', identifier)['ok']
    assert command.call_count == calls, 'An unbound task was routed'
    backend.desktopPlugins.setEnabled('global-agents', True)
    wait(lambda: pet.assistantStatus.get('bound'), 'Pet did not rebind')
    backend.setLanguage('en')
    native = open_composer()
    field.setProperty('text', '')
    assert field.property('placeholderText') == ''
    assert native.grabWindow().save(str(out / 'composer-en.png'))
    QTest.keyClick(native, Qt.Key_Escape)
    backend.setTheme('dark')
    native = open_composer()
    assert native.grabWindow().save(str(out / 'composer-dark.png'))
    QTest.keyClick(native, Qt.Key_Escape)
    backend.setTheme('white'); backend.setLanguage('zh')
    area = pet.screenBounds(window.x(), window.y())
    for x, y in ((area['x'], area['y']),
                 (area['x'] + area['width'] - window.width(), area['y']),
                 (area['x'], area['y'] + area['height'] - window.height()),
                 (area['x'] + area['width'] - window.width(), area['y'] + area['height'] - window.height())):
        window.setPosition(x, y)
        native = open_composer()
        assert native.x() >= area['x'] and native.y() >= area['y']
        assert native.x() + native.width() <= area['x'] + area['width']
        assert native.y() + native.height() <= area['y'] + area['height']
        QTest.keyClick(native, Qt.Key_Escape)
    backend.store.data['ui']['fontScale'] = 1.6; backend.appearanceChanged.emit()
    native = open_composer()
    assert field.property('font').pixelSize() >= 20
    assert native.grabWindow().save(str(out / 'composer-large-font.png'))
    QTest.keyClick(native, Qt.Key_Escape)
    backend.store.data['ui']['fontScale'] = 1.; backend.appearanceChanged.emit()

    # Complete one real native Pi turn through the normal private gateway and
    # its bound send_to_user tool. Only the paid upstream model is a fixture.
    from app.integration import Completion
    class Fixture:
        ready = True
        def complete(self, model, messages, tools, max_tokens):
            if messages[-1]['role'] == 'tool':
                return Completion('验收链路已完成。')
            return Completion(tool_calls=[{'id':'pet-task-receipt', 'name':'send_to_user',
                'arguments':{'text':'收到，派活链路已接通。'}}])
    backend.store.data.update(selectedProvider='internal', selectedModel='pet-fixture', providers=[{
        'id':'internal', 'name':'Local fixture', 'api':'internal', 'baseUrl':'', 'key':'',
        'models':[{'upstream':'pet-fixture', 'alias':'pet-fixture'}]}])
    backend.adapter = backend.gateway.adapter = Fixture()
    backend._command_pi = native_command
    record = bus.ensure(pet.assistantStatus['id'])
    record.model = bus.agents[record.global_agent]['model'] = 'pet-fixture'
    speech = []; pet.assistantSpeech.connect(speech.append)
    native = open_composer()
    field.setProperty('text', '验证真实派发链路')
    QTest.keyClick(native, Qt.Key_Return)
    wait(lambda: '收到，派活链路已接通。' in speech, 'Native Pi did not deliver the bound assistant reply')
    wait(lambda: not record.busy, 'Native Pi turn did not complete')
    assert record.file and Path(record.file).is_file(), 'No independent agent transcript was persisted'
    assert backend._view is before_view
    native = open_composer()
    pet.ui('hide', {})
    wait(lambda: not isValid(composer) or not composer.property('visible'), 'Hiding pet left a floating input')
    relevant = [value for value in warnings if any(name in value for name in
                ('DesktopPetWindow', 'ReferenceError', 'TypeError'))]
    assert not relevant, '\n'.join(relevant)
    (out / 'result.json').write_text(json.dumps({'boundDoubleClick': True, 'unboundNoPopup': True,
        'nativePopupFocus': True, 'enterAndButtonSend': True, 'unchangedVisibleConversation': True,
        'failedDraftPreserved': True, 'escapeAndOutsideClose': True, 'bindingLossCloses': True,
        'animationContinues': True, 'bilingual': True, 'nativePiRoundTrip': True,
        'concentricSendCircle': True, 'syntheticImeCommit': True, 'osImeManuallyVerified': False, 'screenEdges': True,
        'largeFont': True, 'pidOpenAndClose': True, 'warnings': relevant}, indent=2))
    print('Pet task input UI passed')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
    app.processEvents()
    temporary.cleanup()
