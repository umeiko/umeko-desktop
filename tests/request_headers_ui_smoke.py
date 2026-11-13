"""Real Qt editor interactions and responsive layout, with a disposable profile."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
temporary=tempfile.TemporaryDirectory(prefix='umeko-request-headers-')
os.environ.update(UMEKO_DATA_DIR=temporary.name,PI_CODING_AGENT_DIR=temporary.name+'/agent',UMEKO_LANGUAGE='zh',QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software')
from PySide6.QtCore import Qt,QPointF
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from app.storage import Store
from main import create_application

app,engine,backend=create_application();window=engine.rootObjects()[0];window.resize(1200,900)
warnings=[];engine.warnings.connect(lambda values:warnings.extend(v.toString() for v in values))
output=ROOT/'build/request-headers-ui';output.mkdir(parents=True,exist_ok=True)
def find(name):
    pending=[window.contentItem()]
    while pending:
        item=pending.pop()
        if item.objectName()==name:return item
        pending.extend(item.childItems())
def wait(predicate,message):
    until=time.monotonic()+10
    while time.monotonic()<until:
        QTest.qWait(20)
        if predicate():return
    raise AssertionError(message+'\n'+'\n'.join(warnings))
def click(name):
    wait(lambda:find(name) is not None and find(name).isVisible(),name)
    item=find(name)
    parent=item.parentItem()
    while parent:
        if parent.property('contentY') is not None:
            y=parent.property('contentY')+item.mapToItem(parent,QPointF(0,0)).y()-parent.height()/2
            parent.setProperty('contentY',max(0,min(y,parent.property('contentHeight')-parent.height())))
        parent=parent.parentItem()
    QTest.qWait(50)
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(item.boundingRect().center()).toPoint())
    QTest.qWait(50)
def edit(name,value):
    field=find(name);assert field is not None;field.forceActiveFocus()
    QTest.keyClick(window,Qt.Key_A,Qt.ControlModifier)
    event=QInputMethodEvent();event.setCommitString(value);app.sendEvent(field,event)
    QTest.keyClick(window,Qt.Key_Tab);QTest.qWait(30)
try:
    window.setProperty('page','settings');window.setProperty('settingsTab',3);QTest.qWait(100)
    click('openUmekoDesktopSettingsButton')
    editor=find('requestHeadersSettings');assert not editor.isVisible()
    assert find('desktopChatWidthHints').isVisible() and find('openRequestHeaders').isVisible()
    window.grabWindow().save(str(output/'desktop-menu.png'))
    click('openRequestHeaders')
    assert editor.isVisible() and find('customRequestsPage').isVisible()
    assert not find('desktopChatWidthHints').isVisible() and not find('openRequestHeaders').isVisible()
    window.grabWindow().save(str(output/'headers-page.png'))
    stable=find('requestHeaderValue_user-agent');stable.forceActiveFocus();backend.changed.emit();QTest.qWait(30)
    assert find('requestHeaderValue_user-agent') is stable and stable.hasActiveFocus()
    edit('requestHeaderValue_user-agent','My-Client/1.0')
    click('backFromRequestHeaders')
    assert not editor.isVisible() and find('desktopChatWidthHints').isVisible()
    assert editor.property('dirty')
    click('openRequestHeaders')
    assert find('requestHeaderValue_user-agent').property('text')=='My-Client/1.0'
    click('addRequestHeader');QTest.qWait(50)
    fields=[];pending=[editor]
    while pending:
        item=pending.pop()
        if item.objectName().startswith('requestHeaderName_custom-'):fields.append(item.objectName())
        pending.extend(item.childItems())
    assert len(fields)==1
    identifier=fields[0].removeprefix('requestHeaderName_')
    edit(fields[0],'X-Project');edit('requestHeaderValue_'+identifier,'local-fixture')
    click('requestHeaderEnabled_'+identifier);click('saveRequestHeaders')
    assert backend.requestHeaders[-1]['enabled'] is False
    assert backend.requestHeaders[-1]['value']=='local-fixture'
    assert Store(backend.store.directory).data['requestHeaders']==backend.requestHeaders
    for language,width,scale in [('zh',1200,1),('en',900,1.6)]:
        backend.setLanguage(language);backend.setFontScale(scale);window.resize(width,900);QTest.qWait(150)
        for name in ('requestHeaderName_user-agent','requestHeaderValue_user-agent','requestHeaderEnabled_authorization','saveRequestHeaders'):
            item=find(name);assert item.isVisible();bounds=item.mapRectToItem(editor,item.boundingRect())
            assert bounds.left()>=0 and bounds.right()<=editor.width()+1,(name,bounds,editor.width())
        window.grabWindow().save(str(output/(language+'.png')))
    backend.setFontScale(1);backend.setLanguage('zh');window.resize(1200,900)
    edit('requestHeaderName_'+identifier,'Bad Header');click('saveRequestHeaders')
    assert editor.property('dirty') and backend.requestHeaders[-1]['name']=='X-Project'
    click('discardRequestHeaderChanges');assert not editor.property('dirty')
    click('deleteRequestHeader_'+identifier);click('saveRequestHeaders');assert len(backend.requestHeaders)==5
    click('restoreRequestHeaders');assert backend.requestHeaders[1]['value']=='Umeko-Desktop'
    click('backFromRequestHeaders');click('backFromUmekoDesktopButton');click('openUmekoDesktopSettingsButton')
    assert find('openRequestHeaders').isVisible() and not editor.isVisible()
    assert not warnings,'\n'.join(warnings)
    print('REQUEST_HEADERS_UI_OK: secondary page navigation and draft preservation, edit/add/omit/delete/save/reload/reset/invalid rollback, bilingual responsive fields')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine);app.processEvents();temporary.cleanup()
