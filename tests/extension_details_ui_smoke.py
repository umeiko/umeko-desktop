"""Actual closeable Pi Widget: local docs, scrolling, installation and chat modes."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
os.environ['UMEKO_LANGUAGE']='zh'
os.environ['UMEKO_DATA_DIR']=tempfile.mkdtemp(prefix='umeko-pi-widget-')
from PySide6.QtCore import QObject, Slot, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QTest
from app.storage import Store
from main import create_application

store=Store()
agent,workspace,pkg=(store.directory/name for name in ['agent','workspace','fixture'])
for directory in [agent,workspace,pkg]: directory.mkdir()
(pkg/'package.json').write_text(json.dumps({'name':'@fixture/extension-details','version':'1.2.3','homepage':'https://example.com/extensions','repository':{'url':'git+https://github.com/example/extensions.git'},'description':'Fixture extension description','pi':{'extensions':['index.mjs']}}))
(pkg/'index.mjs').write_text("export default () => {};\n")
(pkg/'README.md').write_text('# Fixture extension\n\n'+('## A long local document\n\nA paragraph inside the scroll viewport.\n\n'*150))
(agent/'settings.json').write_text(json.dumps({'packages':[str(pkg)]}))
store.data['agent']['agentDir']=str(agent)
store.data['workspace']=str(workspace)
store.save()
app,engine,backend=create_application()
window=engine.rootObjects()[0]
window.setWidth(1120);window.setHeight(720)
manager=backend.desktopPlugins
warnings=[]
engine.warnings.connect(lambda items:warnings.extend(item.toString() for item in items))
class Links(QObject):
    def __init__(self): super().__init__();self.urls=[]
    @Slot(QUrl)
    def open(self,url): self.urls.append(url.toString())
links=Links()
QDesktopServices.setUrlHandler('https',links,'open')
def find(name,required=True):
    pending=[window.contentItem()]
    while pending:
        item=pending.pop()
        if item.objectName()==name:return item
        pending.extend(item.childItems())
    if required:raise AssertionError(name)
def wait(predicate):
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        QTest.qWait(10);time.sleep(.001)
        if predicate():return
    widget=find('piManagerWidget',False)
    raise AssertionError((backend.piManagement.status, manager.status, {key:widget.property(key) for key in ('job','working','notice','pending','rows')} if widget else 'no widget',warnings))
def click(name):
    item=find(name)
    QTest.qWait(100)
    assert item.isVisible() and item.isEnabled(),name
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(item.boundingRect().center()).toPoint())
    QTest.qWait(100)
def snapshot(name):
    target=ROOT/'artifacts/screenshots'/name;target.parent.mkdir(parents=True,exist_ok=True)
    assert window.grabWindow().save(str(target))
try:
    assert 'pi-manager' in manager.entries
    assert 'pi-manager' not in manager.workers, 'Widget should start lazily'
    window.setProperty('page','settings');window.setProperty('settingsTab',3);QTest.qWait(100)
    click('openPiSettingsButton')
    assert find('piFold_packages',False) is None
    window.setProperty('page','chat')
    assert manager.openPage('pi-manager')
    wait(lambda:find('piManagerWidget',False) is not None)
    widget=find('piManagerWidget')
    wait(lambda:find('piManagerList').property('count')>=8 and not widget.property('working'))
    snapshot('pi-widget-installed.png')
    find('piManagerSearch').setProperty('text','extension-details')
    wait(lambda:find('piManagerList').property('count')==1 and not widget.property('working'))
    fixture=next(row for row in backend.piManagement.extensions if row['name']=='@fixture/extension-details')
    click('piManagerEntry_'+fixture['id'])
    wait(lambda:'Fixture extension' in find('piManagerReadme').property('text') and not widget.property('working'))
    scroll=find('piManagerDetailScroll')
    snapshot('pi-widget-detail-debug.png')
    wait(lambda:scroll.property('contentHeight')>scroll.height()*2)
    assert scroll.property('clip')
    assert find('piManagerReadme').width()<=scroll.width()
    assert scroll.mapToItem(widget,scroll.boundingRect().bottomRight()).y()<=widget.height()+1
    snapshot('pi-widget-detail-scroll.png')
    click('piManagerHomepage');click('piManagerRepository')
    assert links.urls==['https://example.com/extensions','https://github.com/example/extensions']
    # Select the conversation-only override and accept the actual native popup.
    click('piManagerActivation');QTest.keyClick(window,Qt.Key_Home);QTest.keyClick(window,Qt.Key_Down);QTest.keyClick(window,Qt.Key_Return)
    wait(lambda:bool(manager.hostServices.pendingApproval))
    click('widgetHost_allowToolButton')
    wait(lambda:backend._view.extension_modes.get(fixture['path'])=='session' and not widget.property('working'))
    assert json.loads((agent/'settings.json').read_text())=={'packages':[str(pkg)]}
    first=backend._view
    click('piManagerBack')
    click('piManagerInstall')
    click('piManagerCatalog');assert links.urls[-1]=='https://pi.dev/packages'
    command=find('piManagerInstallCommand')
    command.setProperty('text','pi install npm:fixture && whoami')
    click('piManagerInstallConfirm')
    assert not manager.hostServices.pendingApproval and not backend.piManagement.busy
    local=store.directory/'a local package'
    (local/'extensions').mkdir(parents=True)
    (local/'extensions/local.ts').write_text('export default () => {};\n')
    command.setProperty('text','pi install "'+str(local)+'" --local')
    assert find('piManagerInstallScope').property('currentIndex')==1
    assert not find('piManagerInstallScope').isEnabled()
    click('piManagerInstallConfirm')
    wait(lambda:bool(manager.hostServices.pendingApproval))
    click('widgetHost_allowToolButton')
    wait(lambda:backend.piManagement.installState=='succeeded' and not widget.property('working'))
    assert local.resolve() in {(workspace/'.pi'/path).resolve() for path in json.loads((workspace/'.pi/settings.json').read_text())['packages']}
    # Closing and globally disabling both stop the session-scoped worker.
    assert 'pi-manager' in manager.workers
    click('closeWebPaneButton')
    wait(lambda:'pi-manager' not in manager.workers)
    assert manager.openPage('pi-manager')
    wait(lambda:'pi-manager' in manager.workers and manager.workers['pi-manager']['ready'])
    manager.setEnabled('pi-manager',False)
    wait(lambda:'pi-manager' not in manager.workers and not manager.page)
    assert not manager.openPage('pi-manager')
    manager.setEnabled('pi-manager',True)
    backend.newSession()
    assert backend._view is not first and not backend._view.extension_modes
    assert first.extension_modes[fixture['path']]=='session'
    assert not warnings,warnings
    print('PI_WIDGET_UI_OK: actual Widget, bounded scroll, local search, metadata links, native confirmation, literal local install, scoped activation, close and disable lifecycle')
finally:
    QDesktopServices.unsetUrlHandler('https')
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
