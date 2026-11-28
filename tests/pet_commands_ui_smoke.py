"""Real Qt menu, isolated synthetic drafts; no model calls or OS IME claim."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = tempfile.TemporaryDirectory(prefix='pet-menu-151-')
language = os.environ.get('UMEKO_PET_COMMAND_LANGUAGE', 'zh')
assert language in ('zh', 'en')
os.environ.update(UMEKO_DATA_DIR=tmp.name+'/profile', PI_CODING_AGENT_DIR=tmp.name+'/agent',
                  QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software', UMEKO_LANGUAGE=language)
from PySide6.QtCore import QObject, Qt
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QSystemTrayIcon
QSystemTrayIcon.show = lambda *args: None
from main import create_application
import shiboken6
app, engine, backend = create_application()
main = engine.rootObjects()[0]
pet = backend.desktopPlugins.pet
out = ROOT / 'build/pet-command-menu'
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

def click(item):
    native = js(item, 'Window.window')
    point = js(item, 'mapToItem(null, width/2, height/2)').toPoint()
    QTest.mouseClick(native, Qt.LeftButton, Qt.NoModifier, point)

try:
    backend._command_pi = Mock(return_value=True)
    backend.desktopPlugins.call_for = Mock()
    original = backend._view
    original.draft = '主窗口演示草稿保持不变'
    pet.ui('show', {})
    wait(lambda: pet.assistantStatus.get('bound'), 'No pet binding')
    window = main.findChild(QObject, 'desktopPetWindow')
    composer = window.findChild(QObject, 'desktopPetTaskComposer')
    field = composer.findChild(QObject, 'desktopPetTaskInput')
    button = composer.findChild(QObject, 'desktopPetCommands')
    menu = composer.findChild(QObject, 'desktopPetCommandMenu')
    js(window, 'openTaskComposer()')
    wait(lambda: composer.property('opened'), 'No capsule')
    field.setProperty('text', '中文演示正文')
    click(button)
    wait(lambda: menu.property('visible'), 'Command button did not open menu')
    QTest.qWait(200)
    assert js(menu, 'contentItem.Window.window').grabWindow().save(str(out/f'menu-{language}.png'))
    choice = js(menu, '(function(){for(let i=0;i<count;i++){let a=itemAt(i);if(a && a.objectName === "desktopPetCommand_timer")return a;} return null;})()')
    assert choice is not None
    english = language == 'en'
    assert backend.language == language
    assert js(button, 'Accessible.name') == (
        'Choose a pet command without running it' if english else '选择桌宠入口（仅准备，不执行）')
    assert js(menu, '(function(){for(let i=0;i<count;i++){let a=itemAt(i);if(a && a.objectName === "desktopPetCommandHeader")return a.text;} return null;})()') == (
        'Choose a command to insert, not run' if english else '选择入口，只填入命令，不执行')
    assert choice.property('text') == ('Scheduled task' if english else '/定时任务')
    assert js(menu, '(function(){for(let i=0;i<count;i++){let a=itemAt(i);if(a && a.objectName === "desktopPetCommand_project")return a.text;} return null;})()') == (
        'Project session' if english else '/项目')
    print('CHOICE', choice.property('objectName'), choice.property('text'), choice.property('enabled'), js(choice, 'mapToItem(null,width/2,height/2)'))
    click(choice)
    QTest.qWait(300)
    print('AFTER', field.property('text'), composer.property('error'), menu.property('visible'))
    wait(lambda: field.property('text') == '/定时任务 中文演示正文', 'Choice lost draft')
    assert not pet.taskSchedule.opened, 'Selecting command executed the wizard'
    assert composer.property('desiredOpen')
    backend._command_pi.assert_not_called()
    backend.desktopPlugins.call_for.assert_not_called()
    # Escape dismisses only the menu, preserving the capsule and body.
    click(button)
    wait(lambda: menu.property('visible'), 'Menu did not reopen')
    QTest.keyClick(js(menu, 'contentItem.Window.window'), Qt.Key_Escape)
    wait(lambda: not menu.property('visible'), 'Escape did not dismiss menu')
    assert composer.property('desiredOpen')
    assert field.property('text') == '/定时任务 中文演示正文'
    # An unknown slash/path remains literal body even after explicit choice.
    field.setProperty('text', '/tmp/demo 保留路径正文')
    click(button)
    wait(lambda: menu.property('visible'), 'Path menu did not open')
    choice = js(menu, '(function(){for(let i=0;i<count;i++){let a=itemAt(i);if(a && a.objectName === "desktopPetCommand_timer")return a;} return null;})()')
    click(choice)
    wait(lambda: field.property('text') == '/定时任务 /tmp/demo 保留路径正文', 'Unknown slash/path was consumed')
    assert not pet.taskSchedule.opened
    backend._command_pi.assert_not_called()
    backend.desktopPlugins.call_for.assert_not_called()
    backend.desktopPlugins.settings.setdefault('enabled', {})['scheduled-tasks'] = False
    click(button)
    wait(lambda: menu.property('visible'), 'Disabled menu did not open')
    wait(lambda: not js(menu, '(function(){for(let i=0;i<count;i++){let a=itemAt(i);if(a && a.objectName === "desktopPetCommand_timer")return a;} return null;})()').property('enabled'), 'Disabled capability still selectable')
    QTest.qWait(200)
    assert js(menu, 'contentItem.Window.window').grabWindow().save(str(out/f'disabled-{language}.png'))
    disabled = js(menu, '(function(){for(let i=0;i<count;i++){let a=itemAt(i);if(a && a.objectName === "desktopPetCommand_timer")return a.text;} return null;})()')
    assert disabled == ('Scheduled task · Enable the Scheduled Tasks Widget' if english else '/定时任务 · 请先启用内置定时任务 Widget')
    # A stale ticket reports a localized error but does not alter the draft.
    before_error = field.property('text')
    js(composer, 'commandQuery = ({ticket: "stale", entries: []}); chooseCommand("timer")')
    assert composer.property('error') == ('Menu expired. Reopen it. Draft kept.' if english else '菜单已过期，请重新打开；草稿保留')
    assert field.property('text') == before_error
    assert backend._view is original and original.draft == '主窗口演示草稿保持不变'
    print('PASS actual QML menu: click selection, draft, no execution, reopen/Escape, disabled capability; Linux offscreen only')
finally:
    backend.close()
    shiboken6.delete(engine)
    app.processEvents()
    tmp.cleanup()
