"""Actual proxy gear, language, 50–200% fonts and copyable request details."""
import json
import os
from pathlib import Path
import re
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['UMEKO_DATA_DIR']=tempfile.mkdtemp(prefix='umeko-preferences-ui-')
os.environ['UMEKO_LANGUAGE']='zh'
os.environ.setdefault('QT_QPA_PLATFORM','offscreen');os.environ.setdefault('QT_QUICK_BACKEND','software')
from PySide6.QtCore import Qt,QPointF
from PySide6.QtTest import QTest
from main import create_application
app,engine,backend=create_application();window=engine.rootObjects()[0]
warnings=[];engine.warnings.connect(lambda errors:warnings.extend(e.toString() for e in errors))
def find(name):
    stack=[window.contentItem()]
    while stack:
        item=stack.pop()
        if item.objectName()==name:return item
        stack.extend(item.childItems())
    raise AssertionError(name)
def reveal(item):
    scroll=find('settingsScroll').property('contentItem')
    ancestor=item.parentItem()
    while ancestor is not None and ancestor!=scroll:ancestor=ancestor.parentItem()
    if ancestor is None:return
    y=item.mapToItem(scroll,QPointF(0,0)).y()
    target=scroll.property('contentY')+y-scroll.height()/2
    scroll.setProperty('contentY',max(0,min(target,scroll.property('contentHeight')-scroll.height())))
    QTest.qWait(100)
def click(name):
    item=find(name);reveal(item);QTest.qWait(100)
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(item.boundingRect().center()).toPoint());QTest.qWait(150)
try:
    assert backend.saveProvider('','Fixture','openai','http://127.0.0.1:1/v1','fixture-key',json.dumps([{'upstream':'fixture','alias':'fixture'}]))
    identifier=backend.store.data['providers'][0]['id']
    window.setProperty('page','settings');window.setProperty('settingsTab',0);QTest.qWait(200)
    click('editProvider_'+identifier)
    assert find('settingsPage').property('editingProvider')
    assert find('editProvider_'+identifier).property('glyph')=='chevron-up'
    click('editProvider_'+identifier)
    assert not find('settingsPage').property('editingProvider')
    assert find('editProvider_'+identifier).property('glyph')=='edit'
    click('providerProxy_'+identifier)
    assert find('providerNetworkTitle').property('text')=='网络设置'
    out=ROOT/'artifacts/screenshots';out.mkdir(parents=True,exist_ok=True)
    window.grabWindow().save(str(out/'network-settings-v033.png'))
    mode=find('providerProxyMode');mode.setProperty('currentIndex',2)
    find('providerProxyAddress').setProperty('text','http://127.0.0.1:7890')
    click('saveProviderProxy')
    assert backend.store.data['providers'][0]['proxy']['mode']=='custom'
    window.setProperty('page','chat')
    current=backend._view
    current.phase='running';backend.chatChanged.emit()
    backend._handle_pi_event(current,{'type':'generation_metrics','active':True,'estimated':True,'tokensPerSecond':24.5})
    QTest.qWait(200)
    assert find('generationSpeed').isVisible()
    assert find('generationSpeed').property('text')=='≈ 24.5 tok/s'
    window.grabWindow().save(str(out/'generation-speed-v033.png'))
    other=backend._new_view();backend._activate(other);QTest.qWait(100)
    assert not find('generationSpeed').isVisible()
    backend._handle_pi_event(current,{'type':'generation_metrics','active':True,'estimated':False,'tokensPerSecond':42})
    assert not find('generationSpeed').isVisible()
    backend._activate(current);QTest.qWait(100)
    assert find('generationSpeed').property('text')=='42.0 tok/s'
    backend._handle_pi_event(current,{'type':'generation_metrics','active':False,'estimated':False,'tokensPerSecond':42})
    assert not find('generationSpeed').isVisible()
    backend._handle_pi_event(current,{'type':'done'});current.phase='idle'
    window.setProperty('page','settings')
    window.setProperty('settingsTab',5);QTest.qWait(200)
    language=find('interfaceLanguage');reveal(language)
    language.forceActiveFocus();QTest.keyClick(window,Qt.Key_End);QTest.qWait(200)
    assert backend.language=='en','Language control did not apply English'
    assert find('addProviderButton').property('text')=='Add provider'
    slider=find('fontScaleSlider');reveal(slider)
    def drag_slider(x):
        QTest.mousePress(window,Qt.LeftButton,Qt.NoModifier,slider.mapToScene(QPointF(slider.width()/2,slider.height()/2)).toPoint())
        QTest.mouseMove(window,slider.mapToScene(QPointF(x,slider.height()/2)).toPoint(),50)
        QTest.mouseRelease(window,Qt.LeftButton,Qt.NoModifier,slider.mapToScene(QPointF(x,slider.height()/2)).toPoint())
        QTest.qWait(400)
    drag_slider(slider.width()-1)
    assert backend.fontScale==2.,'Slider did not apply 200%'
    assert find('promptInput').property('font').pixelSize()==26
    assert find('sendGlyph').width()==34
    assert find('attachFilesButton').width()==62
    drag_slider(0)
    assert backend.fontScale==.5 and find('promptInput').property('font').pixelSize()==7
    assert find('sendGlyph').width()==9 and find('attachFilesButton').width()==31
    backend.setFontScale(2);QTest.qWait(300)
    out=ROOT/'artifacts/screenshots';out.mkdir(parents=True,exist_ok=True)
    window.grabWindow().save(str(out/'appearance-english-200.png'))
    failure=backend.gateway.diagnostics.failure({'name':'Fixture','key':'fixture-key'}, {'model':'fixture','messages':[{'role':'user','content':'complete request'}]}, {'status':429,'body':'long diagnostic response'}, 'fixture failure')
    backend._view.messages=[{'role':'assistant','text':str(failure),'error':True}];backend.chatChanged.emit()
    window.setProperty('page','chat');QTest.qWait(350)
    click('requestDetails_0');assert find('requestDetailsText').isVisible()
    click('copyRequestDetails')
    report=json.loads(app.clipboard().text());assert report['response']['status']==429 and report['request']['messages'][0]['content']=='complete request'
    assert 'fixture-key' not in app.clipboard().text()
    assert not warnings,'\n'.join(warnings)
    saved=json.loads(backend.store.path.read_text(encoding='utf-8'))
    assert saved['ui']['fontScale']==2 and saved['ui']['language']=='en'
    print('PREFERENCES_UI_OK: editor toggle, network settings, per-chat live tok/s, fonts/language, error details and persistence')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
