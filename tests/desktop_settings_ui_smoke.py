"""Actual settings/navigation and browser dispatch, without opening a browser or loading WebView."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
temporary=tempfile.TemporaryDirectory(prefix='umeko-desktop-settings-');base=Path(temporary.name)
os.environ.update(UMEKO_DATA_DIR=str(base/'profile'),PI_CODING_AGENT_DIR=str(base/'agent'),UMEKO_LANGUAGE='zh',QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software')
from PySide6.QtCore import Qt
from PySide6.QtQml import QQmlExpression
from PySide6.QtTest import QTest
from app.storage import Store
from app import webview
from main import create_application

store=Store();store.data['desktop']={'autoOpenSubmissions':False,'webDisplay':'external'};store.save()
app,engine,backend=create_application();window=engine.rootObjects()[0];window.resize(1200,900)
warnings=[];engine.warnings.connect(lambda values:warnings.extend(v.toString() for v in values))
output=ROOT/'build/desktop-settings-ui';output.mkdir(parents=True,exist_ok=True)

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
    wait(lambda:find(name) is not None and find(name).isVisible(),name+' did not appear')
    window.grabWindow();item=find(name)
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(item.boundingRect().center()).toPoint());QTest.qWait(100)

def js(source):
    expression=QQmlExpression(engine.rootContext(),window,source);expression.evaluate()
    assert not expression.hasError(),expression.error().toString()

serial=0
def submit(media):
    global serial
    serial+=1
    backend._handle_pi_event(backend._view,{'type':'tool','id':'delivery-'+str(serial),'name':'submit_to_chatbox','state':'done','media':media})

try:
    assert webview.configuration().get('disabled') and not webview._libraries
    assert not backend.webviewAvailable
    window.setProperty('settingsTab',3);window.setProperty('page','settings');QTest.qWait(100)
    assert find('openPiSettingsButton').isVisible() and find('openDesktopPluginsButton').isVisible()
    click('openUmekoDesktopSettingsButton')
    assert not find('openPiSettingsButton').isVisible()
    assert not find('desktopAutoOpenSubmissions').property('checked')
    assert find('desktopChatWidthHints').property('checked')
    assert find('desktopWebDisplay').property('currentIndex')==1
    for language,scale in [('zh',1.0),('en',2.0)]:
        backend.setLanguage(language);backend.setFontScale(scale);QTest.qWait(150)
        combo=find('desktopWebDisplay');settings=find('umekoDesktopSettings')
        assert combo.property('currentIndex')==1 and combo.property('displayText')==('系统默认浏览器' if language=='zh' else 'System default browser')
        assert combo.width()>120 and combo.mapToItem(settings,combo.boundingRect().bottomRight()).x()<=settings.width()+1
        hints=find('desktopChatWidthHints')
        assert hints.isVisible() and hints.mapToItem(settings,hints.boundingRect().bottomRight()).x()<=settings.width()+1
        window.grabWindow().save(str(output/('settings-'+language+'.png')))
    backend.setLanguage('zh');backend.setFontScale(1.0);QTest.qWait(100)
    click('desktopWebDisplay');QTest.keyClick(window,Qt.Key_Home);QTest.keyClick(window,Qt.Key_Return);QTest.qWait(100)
    assert backend.config['desktop']['webDisplay']=='embedded' and find('desktopWebDisplay').property('currentIndex')==0
    assert not backend.webviewAvailable  # Re-enabling native initialization needs a restart.
    backend.saveDesktopSettings(json.dumps({'webDisplay':'external'}));QTest.qWait(50)
    assert find('desktopWebDisplay').property('currentIndex')==1
    click('desktopAutoOpenSubmissions')
    assert backend.config['desktop']['autoOpenSubmissions']
    click('desktopAutoOpenSubmissions')
    click('desktopChatWidthHints')
    assert not backend.config['desktop']['chatWidthHints']
    assert not Store(store.directory).data['desktop']['chatWidthHints']
    assert not find('chatWidthControls').property('hintsEnabled')
    click('desktopChatWidthHints')
    assert backend.config['desktop']['chatWidthHints'] and find('chatWidthControls').property('hintsEnabled')
    click('backFromUmekoDesktopButton')
    assert find('openPiSettingsButton').isVisible() and find('openDesktopPluginsButton').isVisible()
    window.setProperty('page','chat');QTest.qWait(100)
    pane=find('webPane');url='http://127.0.0.1:9876/preview'
    html=base/'page.html';html.write_text('<h1>Local page</h1>')
    note=base/'notes.md';note.write_text('# Notes')
    media=[{'kind':'web','url':url,'path':url,'title':'Web','presentation':'external'}, {'kind':'code','path':str(html)}, {'kind':'markdown','path':str(note)}]
    with patch('app.preferences.QDesktopServices.openUrl',return_value=True) as browser:
        submit(media);QTest.qWait(150)
        assert not pane.property('opened');browser.assert_not_called()
        js('previewChatWeb('+json.dumps({'url':url,'title':'Web'})+')')
        assert browser.call_count==1 and not pane.property('opened')
        js('previewChatDocument('+json.dumps({'path':str(html),'kind':'code'})+')')
        assert browser.call_count==2 and not pane.property('opened')
        backend.webRequested.emit(url,'Direct web delivery')
        assert browser.call_count==3 and not pane.property('opened')
        assert find('webSurfaceLoader').property('item') is None
        backend.saveDesktopSettings(json.dumps({'autoOpenSubmissions':True}))
        submit(media[:2]);QTest.qWait(100)
        assert browser.call_count==5 and not pane.property('opened')
        submit(media[2:]);wait(lambda:pane.property('opened') and pane.property('mode')=='document','Markdown did not open in native preview')
        wait(lambda:not backend.documentPreview.state.get('busy'),'Markdown did not finish loading')
        assert find('webSurfaceLoader').property('item') is None
    assert not warnings,'\n'.join(warnings)
    print('DESKTOP_SETTINGS_UI_OK: persisted policy, Agent navigation, bilingual scaled settings, manual/automatic browser routing, local HTML and no embedded WebView')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine);app.processEvents();temporary.cleanup()
