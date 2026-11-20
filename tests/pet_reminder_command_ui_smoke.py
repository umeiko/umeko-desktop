"""Real Qt reminder shortcut on an isolated profile; no model or agent dispatch."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = tempfile.TemporaryDirectory(prefix='pet-reminder-command-')
language = os.environ.get('UMEKO_PET_COMMAND_LANGUAGE', 'zh')
assert language in ('zh', 'en')
os.environ.update(UMEKO_DATA_DIR=tmp.name+'/profile', PI_CODING_AGENT_DIR=tmp.name+'/agent',
                  QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software', UMEKO_LANGUAGE=language)
from PySide6.QtCore import QObject, Qt
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QSystemTrayIcon
import shiboken6

QSystemTrayIcon.show = lambda *args: None
from main import create_application
app, engine, backend = create_application()
main = engine.rootObjects()[0]
pet = backend.desktopPlugins.pet
out = ROOT / 'build/pet-reminder-command'
out.mkdir(parents=True, exist_ok=True)


def js(obj, code):
    expression = QQmlExpression(QQmlEngine.contextForObject(obj), obj, code)
    result = expression.evaluate()[0]
    assert not expression.hasError(), expression.error().toString()
    return result


def wait(check, message):
    for _ in range(250):
        if check():
            return
        QTest.qWait(20)
    raise AssertionError(message)


def click(item):
    window = js(item, 'Window.window')
    center = js(item, 'mapToItem(null, width/2, height/2)').toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, center)


def reminder_rows():
    return pet.ui('listItems', {'status': 'all'})['result']['items']


try:
    backend._command_pi = Mock(side_effect=AssertionError('No Pi dispatch allowed'))
    backend.desktopPlugins.call_for = Mock(side_effect=AssertionError('No agent Widget call allowed'))
    original = backend._view
    original.draft = 'Fixture main draft'
    before = reminder_rows()
    pet.ui('show', {})
    wait(lambda: pet.assistantStatus.get('bound'), 'No pet binding')
    window = main.findChild(QObject, 'desktopPetWindow')
    composer = window.findChild(QObject, 'desktopPetTaskComposer')
    field = composer.findChild(QObject, 'desktopPetTaskInput')
    menu = composer.findChild(QObject, 'desktopPetCommandMenu')
    opener = composer.findChild(QObject, 'desktopPetCommands')
    submit = composer.findChild(QObject, 'desktopPetTaskSend')
    js(window, 'openTaskComposer()')
    wait(lambda: composer.property('opened'), 'No task capsule')
    body = '取快递' if language == 'zh' else 'Pick up the parcel'
    field.setProperty('text', body)
    assert not main.findChild(QObject, 'desktopPetReminderWindow')
    click(opener)
    wait(lambda: menu.property('visible'), 'Menu failed to open')
    choice = js(menu, '(function(){for(let i=0;i<count;i++){let a=itemAt(i);if(a && a.objectName==="desktopPetCommand_reminder")return a;}return null;})()')
    assert choice.property('text') == ('Reminder' if language == 'en' else '/提醒')
    QTest.qWait(200)
    assert js(menu, 'contentItem.Window.window').grabWindow().save(str(out/f'menu-{language}.png'))
    click(choice)
    original_text = '/提醒 ' + body
    wait(lambda: field.property('text') == original_text, 'Selection changed body')
    assert not main.findChild(QObject, 'desktopPetReminderWindow')
    assert reminder_rows() == before
    click(submit)
    wait(lambda: main.findChild(QObject, 'desktopPetReminderWindow') is not None, 'Form did not appear')
    form = main.findChild(QObject, 'desktopPetReminderWindow')
    wait(form.isVisible, 'Form is hidden')
    title = form.findChild(QObject, 'desktopPetReminderTitle')
    notes = form.findChild(QObject, 'desktopPetReminderNotes')
    save = form.findChild(QObject, 'desktopPetReminderSave')
    cancel = form.findChild(QObject, 'desktopPetReminderCancel')
    wait(lambda: title.property('text') == body, 'Body was not prefilled')
    assert reminder_rows() == before
    assert field.property('text') == original_text
    assert form.grabWindow().save(str(out/f'form-{language}.png'))

    # Re-submission while editing must not replace this form's unsaved title.
    title.setProperty('text', 'Keep existing form draft')
    assert pet.openReminderDraft(pet.assistantStatus['id'], 'Incoming draft')['ok']
    assert title.property('text') == 'Keep existing form draft'
    assert reminder_rows() == before
    click(cancel)
    QTest.qWait(100)
    assert reminder_rows() == before
    form.close()

    js(window, 'openTaskComposer()')
    wait(lambda: composer.property('opened'), 'Capsule failed to reopen')
    assert field.property('text') == original_text
    selection = pet.reminderSelection
    oversized = '/提醒 ' + 'x' * 2001
    # Validate directly to avoid offscreen geometry/focus for a 2,001-char text.
    denied = pet.openReminderDraft(pet.assistantStatus['id'], oversized[4:])
    assert not denied['ok'] and '2000' in denied['error']
    assert pet.reminderSelection == selection
    assert not pet.openReminderDraft('stale-binding', body)['ok']
    assert pet.reminderSelection == selection
    assert reminder_rows() == before

    multiline = '/提醒 ' + body + '\nTake the receipt'
    field.setProperty('text', multiline)
    click(submit)
    wait(form.isVisible, 'Multiline form did not open')
    assert title.property('text') == ''
    assert notes.property('text') == body + '\nTake the receipt'
    assert field.property('text') == multiline and reminder_rows() == before
    title.setProperty('text', body)
    click(save)
    wait(lambda: len(reminder_rows()) == len(before) + 1, 'Explicit Save did not create one reminder')
    for _ in range(2):
        if save.isVisible():
            click(save)
    item = next(row for row in reminder_rows() if row['title'] == body)
    assert len(reminder_rows()) == len(before) + 1 and item['notes'] == body + '\nTake the receipt'
    assert backend._view is original and original.draft == 'Fixture main draft'
    backend._command_pi.assert_not_called()
    backend.desktopPlugins.call_for.assert_not_called()
    print('PASS real Qt reminder command:', language, 'prepare only, local form, draft preserved, one explicit Save, no Pi')
finally:
    backend.close()
    shiboken6.delete(engine)
    app.processEvents()
    tmp.cleanup()
