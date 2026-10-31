"""Offscreen Qt rendering and input regression; never controls a user desktop."""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
temp=tempfile.TemporaryDirectory(prefix='umeko-pet-ui-')
os.environ.update(UMEKO_DATA_DIR=str(Path(temp.name)/'profile'),PI_CODING_AGENT_DIR=str(Path(temp.name)/'agent'),UMEKO_LANGUAGE='zh',QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software')
from PySide6.QtCore import QObject, QPoint, QPointF, Qt, QMetaObject, Q_ARG
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QSystemTrayIcon
# Stub native and fallback notification routes before application construction.
notification_calls=[]
class SilentNativeCenter:
    def __init__(self,*args):pass
    def send(self,*args):notification_calls.append(('native',args));return 1
    def poll(self):return None
    def close(self):pass
import app.notifications as notifications
notifications.NativeCenter=SilentNativeCenter
notifications.TaskNotifications.task_finished=lambda *args:notification_calls.append(('task',args[1:]))
QSystemTrayIcon.showMessage=lambda *args:notification_calls.append(('tray',args[1:]))
QSystemTrayIcon.show=lambda *args:None
from main import create_application

app,engine,backend=create_application()
main=engine.rootObjects()[0]
warnings=[]
engine.warnings.connect(lambda values:warnings.extend(e.toString() for e in values))
pet=backend.desktopPlugins.pet
window=None
assert app.platformName()=='offscreen'
out=Path(os.environ.get('UMEKO_PET_UI_OUTPUT',str(ROOT/'build/desktop-pet-ui')));out.mkdir(parents=True,exist_ok=True)

def find(name):
    stack=[main.contentItem()]
    while stack:
        item=stack.pop()
        if item.objectName()==name:return item
        stack.extend(item.childItems())
    return main.findChild(QObject,name)

def wait(predicate,description):
    for _ in range(400):
        QTest.qWait(20)
        if predicate():return
    raise AssertionError(description+'\n'+'\n'.join(warnings))

def menu_object(menu, expression):
    query=QQmlExpression(QQmlEngine.contextForObject(menu),menu,expression)
    value=query.evaluate()[0]
    assert not query.hasError(),query.error().toString()
    return value

def activate_menu_item(menu,index):
    assert menu_object(menu,'contentItem.Window.window !== parent.Window.window && contentItem.Window.window.transientParent === parent.Window.window'),'Menu lost its transient parent'
    menu_object(menu,'itemAt('+str(index)+').click()')
    wait(lambda:not menu.property('visible'),'Menu did not close after activation')

def open_pet_menu():
    QTest.mouseClick(window,Qt.RightButton,Qt.NoModifier,point)
    wait(lambda:menu.property('opened'),'Context menu did not reopen')
    assert menu_object(menu,'contentItem.Window.window.flags & Qt.WindowStaysOnTopHint'),'Pet menu lost its explicit stay-on-top flag'
def variant(value):
    return value.toVariant() if hasattr(value,'toVariant') else value

def invoke(obj,method,*args):
    assert QMetaObject.invokeMethod(obj,method,*[Q_ARG('QVariant',arg) for arg in args]),method

def click(name):
    invoke(find(name),'clicked')

def all_items():
    return pet.handle('listItems',{'status':'all'})['items']

def edit_item(item=None):
    invoke(find('desktopPetSettings'),'beginEdit',item)

def fill_item(title,notes='',due=None):
    find('desktopPetReminderTitle').setProperty('text',title)
    find('desktopPetReminderNotes').setProperty('text',notes)
    find('desktopPetReminderTimed').setProperty('checked',due is not None)
    if due:
        find('desktopPetReminderDate').setProperty('text',due.strftime('%Y-%m-%d'))
        find('desktopPetReminderTime').setProperty('text',due.strftime('%H:%M'))

def reminder_settings_smoke():
    settings=find('desktopPetSettings')
    click('desktopPetNewReminder')
    fill_item('  离线待办 <b>纯文本</b>  ','带取件码')
    click('desktopPetReminderSave')
    wait(lambda:len(all_items())==1,'QML create did not persist')
    item=all_items()[0]
    assert item['title']=='离线待办 <b>纯文本</b>' and item['dueAt'] is None
    edit_item(item);fill_item('未来提醒','编辑备注',datetime.now()+timedelta(days=3))
    click('desktopPetReminderSave')
    wait(lambda:all_items()[0]['title']=='未来提醒' and all_items()[0]['dueAt'] is not None,'QML update did not persist')
    item=all_items()[0]
    edit_item(item);find('desktopPetReminderDate').setProperty('text','2026-02-30')
    click('desktopPetReminderSave')
    assert settings.property('formError') and all_items()[0]['revision']==item['revision']
    assert find('desktopPetReminderDate').property('text')=='2026-02-30'
    edit_item(item);invoke(settings,'resolveLocalTime')
    candidates=variant(settings.property('localCandidates'))
    assert candidates and all(isinstance(row['epoch'],(int,float)) for row in candidates)
    for language in ('zh','en'):
        backend.setLanguage(language);QTest.qWait(80)
        # Use the existing settings scroll area to show the list and editor,
        # then capture the real window, including its opaque theme background.
        viewport=settings.parentItem()
        while viewport is not None:
            if viewport.metaObject().indexOfProperty('contentY')>=0:
                title=find('desktopPetReminderTitle')
                target=viewport.property('contentY')+title.mapToItem(viewport,QPointF()).y()-viewport.height()*.35
                maximum=max(0,viewport.property('contentHeight')-viewport.height())
                viewport.setProperty('contentY',max(0,min(maximum,target)))
                QTest.qWait(50)
                break
            viewport=viewport.parentItem()
        assert main.grabWindow().save(str(out/('reminder-settings-'+language+'.png')))
    backend.setLanguage('zh')
    main.setProperty('page','chat');pet.openReminders(item['id'],False)
    wait(lambda:main.property('page')=='settings' and (current:=find('desktopPetSettings')) is not None and current.property('editId')==item['id'],'Reminder navigation did not select the item')
    pet.openReminders('',True)
    wait(lambda:(current:=find('desktopPetSettings')) is not None and current.property('editing') and current.property('editId')=='','New-item navigation did not open the form')
    settings=find('desktopPetSettings')
    invoke(settings,'call','completeItem',{'id':item['id']})
    wait(lambda:all_items()[0]['completed'],'QML complete did not persist')
    click('desktopPetCompletedFilter')
    wait(lambda:len(variant(settings.property('items')))==1 and variant(settings.property('items'))[0]['completed'],'Completed filter did not refresh')
    settings.setProperty('deleteId',item['id']);dialog=find('desktopPetDeleteReminderDialog');invoke(dialog,'open');invoke(dialog,'accepted')
    wait(lambda:not all_items(),'Confirmed deletion did not persist')
    invoke(dialog,'close');click('desktopPetOpenFilter')

def reminder_card_smoke():
    clock=[datetime.now(timezone.utc).replace(second=0,microsecond=0)]
    pet.reminders.clock=lambda:clock[0]
    pet.ui('configure',{'paused':True})
    due=(clock[0]+timedelta(minutes=2)).isoformat()
    item=pet.handle('createItem',{'title':'提醒 <b>纯文本</b>','dueAt':due})['item']
    clock[0]+=timedelta(minutes=2);pet.reminders.check()
    card=window.findChild(QObject,'desktopPetReminderCard')
    wait(lambda:card.isVisible(),'Paused animation suppressed reminder card')
    assert not window.property('caption')
    pet.reaction.emit('不应补播的旧台词');assert not window.property('caption')
    for language in ('zh','en'):
        backend.setLanguage(language)
        rendered={}
        def capture_rendered_pet():
            animation=window.findChild(QObject,'desktopPetAnimation')
            if animation is None or not animation.property('ready') or animation.property('paintedHeight')<=0:
                return False
            # grabWindow renders the actual scene. Ready alone does not establish
            # that the asynchronously decoded pet has reached the screenshot.
            window.requestUpdate()
            image=window.grabWindow()
            if image.isNull() or not card.isVisible():return False
            scale=image.height()/window.height()
            below_card=int((card.y()+card.height()+2)*scale)
            pixels=sum(image.pixelColor(x,y).alpha()>0
                       for y in range(max(0,below_card),image.height(),2)
                       for x in range(0,image.width(),2))
            if not pixels:return False
            rendered.update(image=image,petPixels=pixels)
            return True
        wait(capture_rendered_pet,'Reminder '+language+' screenshot has no rendered pet below the card')
        assert rendered['image'].save(str(out/('reminder-card-'+language+'.png')))
        print('Reminder card screenshot '+language+': '+str(rendered['petPixels'])+' nontransparent pet samples below card')
    backend.setLanguage('zh')
    stale=item['revision']
    pet.handle('updateItem',{'id':item['id'],'title':'更新后的标题'})
    pet.completeReminder(item['id'],stale)
    assert not pet.handle('getItem',{'id':item['id']})['item']['completed']
    pet.handle('deleteItem',{'id':item['id']})
    wait(lambda:not card.isVisible(),'Deleted item remained in reminder card')
    due=(clock[0]+timedelta(minutes=2)).isoformat()
    ids=[pet.handle('createItem',{'title':title,'dueAt':due})['item']['id'] for title in ('合并提醒一','合并提醒二')]
    clock[0]+=timedelta(minutes=2);pet.reminders.check()
    wait(lambda:len(pet.reminderCard)==2 and card.isVisible(),'Due items did not merge into one card')
    invoke(window.findChild(QObject,'desktopPetReminderView'),'clicked')
    wait(lambda:not card.isVisible() and main.property('page')=='settings','View card did not navigate and dismiss')
    pet.reminders.check();assert not card.isVisible(),'Processed reminders replayed'
    for identifier in ids:pet.handle('deleteItem',{'id':identifier})
    pet.reminders.clock=lambda:datetime.now(timezone.utc)
    pet.ui('configure',{'paused':False})

try:
    window_loader=main.findChild(QObject,'desktopPetWindowLoader')
    assert pet.running and window_loader.property('item') is None
    # Select the real Widget settings page, not a test-only control surface.
    main.setProperty('settingsTab',3);main.setProperty('page','settings');QTest.qWait(100)
    page=find('desktopPluginsPage');page.setProperty('selectedId','desktop-pet')
    agent=page.parentItem().parentItem();agent.setProperty('pluginsOpen',True)
    wait(lambda:find('desktopPetSettings') is not None,'Pet settings did not load')
    wait(lambda:find('desktopPetAppearancePicker').property('count')==len(pet.appearances),'Appearance list did not load')
    assert {'yanami','komari','whale-girl'} <= {row['id'] for row in pet.appearances}
    assert all(row['builtin'] for row in pet.appearances)
    pet.ui('selectAppearance',{'id':'whale-girl'})
    main.grabWindow().save(str(out/'settings.png'))
    reminder_settings_smoke()
    page=find('desktopPluginsPage')
    settings_loader=find('desktopPluginSettingsLoader')
    for identifier in ('git-viewer','file-tree','desktop-pet','git-viewer','desktop-pet'):
        page.setProperty('selectedId',identifier);QTest.qWait(50)
        if identifier=='desktop-pet':
            wait(lambda:find('desktopPetSettings') is not None,'Pet settings did not reload')
            assert settings_loader.isVisible() and settings_loader.height()>0
        else:
            assert not settings_loader.isVisible() and settings_loader.property('item') is None,'Inactive settings reserved a blank area'
            divider=find('desktopPluginSettingsDivider');heading=find('desktopPluginReadmeHeading')
            assert 0<=heading.y()-divider.y()-divider.height()<30,'Widget description was pushed down by an empty settings container'
    pet.ui('show',{})
    wait(lambda:main.findChild(QObject,'desktopPetWindow') is not None,'Pet window did not load')
    window=main.findChild(QObject,'desktopPetWindow')
    loader=window.findChild(QObject,'desktopPetAnimationLoader')
    wait(lambda:window.isVisible() and window.findChild(QObject,'desktopPetAnimation') is not None,'Pet did not show')
    animation=window.findChild(QObject,'desktopPetAnimation')
    wait(lambda:animation.property('ready'),'Animation did not decode')
    assert animation.property('frameCount')>1 and not animation.property('cache')
    reminder_card_smoke()
    first=animation.property('currentFrame');QTest.qWait(180)
    assert animation.property('currentFrame')!=first,'Animation is static'
    pet.ui('selectAppearance',{'id':'komari'})
    wait(lambda:pet.state['appearance']=='komari' and 'assets/komari/' in str(animation.property('source')),'Komari did not replace the active animation')
    wait(lambda:animation.property('ready') and animation.property('frameCount')>1,'Komari animation did not decode')
    first=animation.property('currentFrame')
    wait(lambda:animation.property('currentFrame')!=first,'Komari animation is static')
    pet.ui('selectAppearance',{'id':'whale-girl'})
    wait(lambda:animation.property('ready') and 'assets/whale-girl/' in str(animation.property('source')),'Whale did not replace Komari')
    assert '/whale-girl/idle.webp' in str(animation.property('source'))
    pet.ui('configure',{'paused':True})
    for state in ('idle','thinking','working','waiting','done','error'):
        pet.motion.state=state;pet.changed.emit()
        wait(lambda:animation.property('source').toString().endswith('/'+state+'.webp') and animation.property('ready'),'Whale state did not decode: '+state)
        assert animation.property('frameCount')>1
        window.grabWindow().save(str(out/('whale-'+state+'.png')))
    pet.ui('configure',{'paused':False})
    window.grabWindow().save(str(out/'pet.png'))
    pet.ui('configure',{'paused':True});QTest.qWait(100)
    frame=animation.property('currentFrame');QTest.qWait(200)
    assert animation.property('currentFrame')==frame,'Pause did not stop playback'
    pet.ui('configure',{'paused':False})
    pointer=window.findChild(QObject,'desktopPetPointer')
    point=pointer.mapToScene(pointer.boundingRect().center()).toPoint()
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,point)
    wait(lambda:bool(window.property('caption')),'Click interaction did not respond')
    bubble=window.findChild(QObject,'desktopPetSpeechBubble')
    assert bubble is not None
    for size in (96,192,320):
        pet.ui('configure',{'size':size});QTest.qWait(60)
        picture_top=loader.y()+loader.height()-animation.property('paintedHeight')*(1-pet.state['contentTop'])
        bottom=bubble.y()+bubble.height()
        assert 0<=picture_top-bottom<=24,'Speech bubble detached from the painted pet'
    window.grabWindow().save(str(out/'whale-speech.png'))
    original=(window.x(),window.y())
    QTest.mousePress(window,Qt.LeftButton,Qt.NoModifier,point)
    QTest.mouseMove(window,point+QPoint(-25,-15),30)
    QTest.mouseRelease(window,Qt.LeftButton,Qt.NoModifier,point)
    assert (window.x(),window.y())!=original,'Drag did not move window'
    QTest.mouseClick(window,Qt.RightButton,Qt.NoModifier,point)
    menu=window.findChild(QObject,'desktopPetContextMenu')
    wait(lambda:menu.property('opened'),'Context menu did not open')
    menu.close()
    wait(lambda:not menu.property('visible'),'Context menu did not close')
    restored=[]
    pet.restoreRequested.connect(lambda:restored.append(True))
    for toggle in range(50):
        open_pet_menu()
        pinned=pet.config['alwaysOnTop']
        activate_menu_item(menu,6)
        assert pet.config['alwaysOnTop'] is not pinned,'Pin menu action did not toggle the pet'
        open_pet_menu()
        # The first row used to be covered by the pet on Windows.
        activate_menu_item(menu,0)
        assert len(restored)==toggle+1,'Top menu row did not activate'
    open_pet_menu()
    paused=pet.config['paused']
    activate_menu_item(menu,5)
    assert pet.config['paused'] is not paused,'Pause menu action did not respond'
    open_pet_menu()
    appearance_menu=menu_object(menu,'menuAt(4)')
    menu_object(menu,'itemAt(4).click()')
    wait(lambda:appearance_menu.property('opened'),'Appearance submenu did not open')
    assert menu_object(appearance_menu,'contentItem.Window.window.flags & Qt.WindowStaysOnTopHint'),'Appearance submenu lost its explicit stay-on-top flag'
    activate_menu_item(appearance_menu,0)
    wait(lambda:not menu.property('visible'),'Appearance selection did not dismiss the menu')
    assert pet.config['appearance']==pet.appearances[0]['id'],'Appearance submenu selection did not respond'
    open_pet_menu()
    reminder_menu=window.findChild(QObject,'desktopPetReminderMenu')
    menu_object(menu,'itemAt(1).click()')
    wait(lambda:reminder_menu.property('opened'),'Reminder submenu did not open')
    assert menu_object(reminder_menu,'contentItem.Window.window.flags & Qt.WindowStaysOnTopHint'),'Reminder submenu lost its explicit stay-on-top flag'
    invoke(reminder_menu.findChild(QObject,'desktopPetReminderNewMenu'),'clicked')
    wait(lambda:not menu.property('visible'),'New reminder did not dismiss the menu')
    wait(lambda:(current:=find('desktopPetSettings')) is not None and current.property('editing') and current.property('editId')=='','Reminder submenu did not open the new-item form')
    pet.ui('hide',{})
    wait(lambda:window_loader.property('item') is None,'Hidden pet retained decoder')
    assert pet.running and pet.timer.isActive()
    backend.desktopPlugins.setEnabled('desktop-pet',False)
    wait(lambda:not pet.running,'Disabled pet is still observing')
    assert find('desktopPluginSettingsLoader').property('item') is None
    relevant=[w for w in warnings if any(s in w for s in ('DesktopPet','desktop-pet','DesktopPlugin','ReferenceError','TypeError'))]
    assert not relevant,'\n'.join(relevant)
    assert not notification_calls,'Reminder UI used a task/native/tray notification sender'
    (out/'result.json').write_text(json.dumps({'settings':'passed','reminderCrud':'passed','localDateValidation':'passed','reminderNavigation':'passed','reminderCardStaleAndRemove':'passed','reminderBilingualScreenshots':'passed','notificationCalls':len(notification_calls),'animation':'passed','click':'passed','drag':'passed','contextMenu':'passed','pinToggles':50,'menuActionsAfterPinToggles':len(restored),'appearanceSubmenu':'passed','reminderSubmenu':'passed','hiddenDecoderReleased':True,'warnings':relevant},indent=2),encoding='utf-8')
    print('Desktop pet offscreen Qt acceptance passed')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
    app.processEvents();temp.cleanup()
