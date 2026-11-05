"""The main character checkbox drives the existing artwork and dialogue components."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
profile = tempfile.TemporaryDirectory(prefix='umeko-system-character-', ignore_cleanup_errors=True)
os.environ.update(UMEKO_DATA_DIR=profile.name, UMEKO_LANGUAGE='zh')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QObject, QMetaObject, Qt, QUrl
from PySide6.QtQml import QQmlComponent
from PySide6.QtTest import QTest
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
shots = ROOT/'artifacts/screenshots'
shots.mkdir(parents=True, exist_ok=True)


def find(name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name:
            return item
        stack.extend(item.childItems())
    return window.findChild(QObject, name)


def click(name):
    item = find(name)
    assert item and item.isVisible() and item.isEnabled(), name
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier,
                     item.mapToScene(item.boundingRect().center()).toPoint())
    QTest.qWait(250)


def source(name):
    return find(name).property('source').toString()


widget = component = None
try:
    window.resize(1700, 920)
    QTest.qWait(300)
    assert backend.selectCharacter('doubao')
    window.setProperty('page', 'settings')
    window.setProperty('settingsTab', 5)
    QTest.qWait(300)
    click('chooseCharacterButton')
    assert not find('disableCharacter').property('checked')
    click('disableCharacter')
    assert backend.characterStyle['id'] == 'system'
    assert find('disableCharacter').property('checked')
    assert not find('subagentCharacterTab').isEnabled()
    assert find('character_system') and not find('character_doubao')
    assert window.grabWindow().save(str(shots/'system-character-picker.png'))
    click('disableCharacter')
    assert backend.characterStyle['id'] == 'doubao'
    assert find('subagentCharacterTab').isEnabled()
    click('disableCharacter')
    click('closeCharacterDialog')
    for tab, artwork, filename in ((3, 'umekoDesktopSettingsArtwork', 'desktop-settings'),
                                   (6, 'aboutApplicationArtwork', 'about')):
        window.setProperty('settingsTab', tab)
        QTest.qWait(200)
        assert find(artwork).isVisible()
        assert '/system/robot.png' in source(artwork)
        assert window.grabWindow().save(str(shots/f'system-character-{filename}.png'))
    window.setProperty('page', 'chat')
    QTest.qWait(300)
    assert find('welcomeMascot').property('loaded')
    assert not find('welcomeMascot').isEnabled()
    assert find('welcomeGreeting').property('text') == '请输入任务或问题'
    tray = backend._system_tray
    assert not tray.personality_enabled and not tray.tray.icon().isNull()
    assert tray.tray.icon().pixmap(32, 32).toImage() == window.icon().pixmap(32, 32).toImage()
    notices = []
    tray.notificationRequested.connect(notices.append)
    with patch.object(tray, 'tray_available', return_value=False):
        tray.minimize_to_tray()
    assert notices[-1] == '系统托盘不可用，已最小化到任务栏。任务仍在运行。'
    tray.restore()
    QTest.qWait(100)
    QMetaObject.invokeMethod(find('welcomeMascot'), 'tap')
    assert not find('welcomeMascot').property('reactionText')
    assert window.grabWindow().save(str(shots/'system-character-welcome.png'))
    backend.setLanguage('en')
    QTest.qWait(100)
    assert find('welcomeGreeting').property('text') == 'Enter a task or question'
    backend.setLanguage('zh')
    for side in ('Left', 'Right'):
        button = find('expandChat'+side)
        art = find('expandChat'+side+'Mascot')
        assert '/system/push.png' in source(art.objectName())
        assert art.property('mirror') == (side == 'Left')
        # Existing controls and layout behavior are reused for both arrow directions.
        QMetaObject.invokeMethod(button, 'clicked')
        QTest.qWait(250)
        assert '/system/pull.png' in source(art.objectName())
        assert find('chatWidthControls').property('expanded'+side)
        QMetaObject.invokeMethod(button, 'clicked')
    backend._view.messages = [
        {'role': 'user', 'text': '检查当前任务状态。'},
        {'role': 'assistant', 'text': '任务已完成。可以继续输入新任务。'},
    ]
    backend.chatChanged.emit()
    QTest.qWait(500)
    QTest.mouseMove(window, find('expandChatLeft').mapToScene(find('expandChatLeft').boundingRect().center()).toPoint())
    QTest.qWait(300)
    assert window.grabWindow().save(str(shots/'system-character-chat.png'))
    for theme in ('dark', 'yanami'):
        backend.setTheme(theme)
        QTest.qWait(150)
        assert window.grabWindow().save(str(shots/f'system-character-{theme}.png'))
    backend.setTheme('light')
    overlay = find('chatLoadingOverlay')
    QMetaObject.invokeMethod(overlay, 'begin')
    QTest.qWait(250)
    assert '/system/robot.png' in source('loadingPortrait')
    assert find('chatLoadingTip').property('text') == '正在读取消息记录，请稍候。'
    assert window.grabWindow().save(str(shots/'system-character-loading.png'))
    QMetaObject.invokeMethod(overlay, 'cancel')
    # Widgets may supply their own portrait, but still respect disabled characters.
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(ROOT/'app/qml/WidgetChatMessage.qml')), engine)
    widget = component.create()
    assert widget, component.errorString()
    widget.setParentItem(window.contentItem())
    widget.setParent(window.contentItem())
    widget.setWidth(400)
    widget.setProperty('messageIndex', 91)
    widget.setProperty('portrait', QUrl.fromLocalFile(str(ROOT/'app/icons/avatars/smile.webp')))
    widget.setProperty('message', {'role': 'assistant', 'text': 'Widget response'})
    widget.setProperty('last', True)
    QTest.qWait(200)
    assert '/system/robot.png' in source('widgetAssistantAvatar_91')
    assert '/system/robot.png' in find('widgetReplyMascot_91').property('portraitSource').toString()
    assert not find('widgetReplyMascot_91').isEnabled()
    assert backend.setCharacterEnabled(True)
    QTest.qWait(200)
    assert backend.characterStyle['id'] == 'doubao'
    assert tray.personality_enabled
    assert find('welcomeMascot').isEnabled()
    assert source('widgetAssistantAvatar_91').endswith('/avatars/smile.webp')
    window.setProperty('page', 'settings')
    for tab, artwork, original in ((3, 'umekoDesktopSettingsArtwork', 'app.png'),
                                   (6, 'aboutApplicationArtwork', 'app.png')):
        window.setProperty('settingsTab', tab)
        QTest.qWait(100)
        assert source(artwork).endswith('/'+original)
    assert not warnings, '\n'.join(warnings)
    print('System character: checkbox, restore, plain text, arrows, themes, loading and Widget artwork passed')
finally:
    backend.close()
    window.close()
    import shiboken6
    shiboken6.delete(engine)
    profile.cleanup()
