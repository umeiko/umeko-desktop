"""Hover-only question navigation through virtualized, uneven message heights."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-question-navigation-')
os.environ['UMEKO_LANGUAGE'] = 'zh'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QPoint, QPointF, Qt, QMetaObject, Q_ARG, QUrl
from PySide6.QtQml import QQmlComponent
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))

def find(name):
    pending = [window.contentItem()]
    while pending:
        item = pending.pop()
        if item.objectName() == name: return item
        pending.extend(item.childItems())
    raise AssertionError(name)

def point(item, x=5, y=5):
    return item.mapToScene(QPointF(x,y)).toPoint()

def invoke(item, method, value):
    assert QMetaObject.invokeMethod(item, method, Qt.DirectConnection, Q_ARG('QVariant', value))

def wheel(item):
    local = point(item, item.width()/2, item.height()/2)
    event = QWheelEvent(QPointF(local), QPointF(window.mapToGlobal(local)), QPoint(), QPoint(0,240), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    app.sendEvent(window, event)

try:
    backend.setTheme('yanami')
    backend.setFontScale(1.49)
    messages = []
    for i in range(60):
        messages.append({'role':'user','text':f'问题 {i+1}：question_marker_{i}，这是一个上下文定位测试','error':False})
        if i % 5 == 0:
            messages.append({'role':'assistant','text':'Checking files','tools':[{'id':f'tool_{i}','name':'read','state':'done'}]})
        messages.append({'role':'assistant','text':f'Answer {i}\n\n' + ('Variable-height answer paragraph.\n\n' * (90 if i == 0 else i%8 + 2)), 'error':False})
    backend._view.messages = messages
    backend.chatChanged.emit()
    QTest.qWait(550)
    view = find('conversation')
    nav = find('questionNavigator')
    rail = find('questionNavigatorRail')
    avatar_component = QQmlComponent(engine, QUrl.fromLocalFile(str(ROOT/'app/qml/AssistantAvatar.qml')))
    assert not avatar_component.isError(), avatar_component.errorString()
    avatar = avatar_component.create(engine.rootContext())
    variants = set()
    for i in range(60):
        avatar.setProperty('messageKey', f'test-session/{i}')
        variants.add(avatar.property('variant'))
        QTest.qWait(2)
        assert avatar.property('loaded'), avatar.property('source')
    assert variants == {0,1,2}, variants
    avatar.deleteLater()
    first_source = None
    QTest.mouseMove(window, point(view, view.width()/2, view.height()/2))
    QTest.qWait(350)
    assert not nav.property('expanded') and rail.property('opacity') == 0
    assert not find('conversationScrollBar').property('visible')
    QTest.mouseMove(window, point(nav, 12, nav.height()/2))
    QTest.qWait(250)
    assert nav.property('expanded'), 'Right edge did not reveal the navigator'
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point(nav, 12, nav.height()/2))
    QTest.qWait(100)
    assert nav.property('expanded'), 'Clicking the navigation edge closed it'
    listing = find('questionNavigationList')
    QTest.mouseMove(window, point(listing, listing.width()/2, listing.height()/2))
    QTest.qWait(250)
    assert nav.property('expanded'), 'Crossing from the edge into the panel closed it'
    before = listing.property('contentY')
    wheel(listing)
    QTest.qWait(150)
    assert listing.property('contentY') < before, 'Long question list did not scroll'
    # Position the menu, then use a real click; navigation itself must resolve
    # virtualized message rows and their actual (uneven) sizes.
    for index in (27, 0, 59, 0, 59):
        QMetaObject.invokeMethod(listing, 'positionViewAtIndex', Qt.DirectConnection, Q_ARG(int,index), Q_ARG(int,0))
        QTest.qWait(100)
        option = find('questionNavigationItem_'+str(index))
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point(option, option.width()/2, option.height()/2))
        QTest.qWait(350)
        assert nav.property('activeQuestion') == index, (index, nav.property('activeQuestion'))
        assert not view.property('followTail'), 'Question jump enabled automatic tail following'
        row = backend.messageModel.questions[index]['row']
        QMetaObject.invokeMethod(view, 'forceLayout')
        # The question's delegate must be at the viewport start, rather than
        # merely setting an estimated percentage of the complete transcript.
        bubble = find('messageBubble_'+str(row))
        y = bubble.mapToItem(view, QPointF()).y()
        assert -2 <= y <= 4 or view.property('atYEnd') and 0 <= y < view.height(), (index, row, y)
        if index == 0:
            header = find('assistantAvatar_1')
            assert header.property('loaded')
            source = header.property('source')
            assert first_source is None or first_source == source, 'Recreated message delegate changed its avatar'
            first_source = source
            backend._view.id = 'assigned-native-session-id'
            backend.chatChanged.emit()
            QTest.qWait(20)
            assert header.property('source') == source, 'Native session initialization changed the avatar'
            offset = view.property('contentY')
            updates = []
            def question_update(): updates.append(1)
            backend.messageModel.questionsChanged.connect(question_update)
            for chunk in range(20): backend._handle_pi_event(backend._view, {'type':'delta','text':' streamed'})
            QTest.qWait(80)
            assert not updates and abs(view.property('contentY') - offset) < 2, 'Streaming rebuilt navigation or pulled history to the bottom'
            assert header.property('source') == source, 'Streaming changed the avatar'
            backend.messageModel.questionsChanged.disconnect(question_update)
    (ROOT/'artifacts').mkdir(exist_ok=True)
    window.grabWindow().save(str(ROOT/'artifacts/question-navigation-yanami.png'))
    backend.setTheme('dark')
    QTest.qWait(120)
    window.grabWindow().save(str(ROOT/'artifacts/question-navigation-dark.png'))
    QTest.mouseMove(window, point(view, 40, 40))
    QTest.qWait(350)
    assert not nav.property('expanded')
    QTest.mouseMove(window, point(nav, 12, nav.height()/2))
    QTest.qWait(200)
    assert nav.property('expanded')
    backend.newSession()
    QTest.qWait(200)
    assert not nav.isVisible() and not nav.property('expanded') and backend.messageModel.questions == []
    assert not warnings, '\n'.join(warnings)
    print('QUESTION_NAVIGATION_UI_OK', flush=True)
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
