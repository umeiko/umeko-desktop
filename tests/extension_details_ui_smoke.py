"""Real QML metadata, registered tools, links and targeted update-check results."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
os.environ['UMEKO_LANGUAGE']='zh'
os.environ['UMEKO_DATA_DIR']=tempfile.mkdtemp(prefix='umeko-extension-details-')
from PySide6.QtCore import QObject, Slot, QUrl, QPointF, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QTest
from app.storage import Store
from main import create_application

store=Store()
agent,workspace,pkg=(store.directory/name for name in ['agent','workspace','fixture'])
for directory in [agent,workspace,pkg]: directory.mkdir()
(pkg/'package.json').write_text(json.dumps({'name':'@fixture/extension-details','version':'1.2.3','homepage':'https://example.com/extensions','repository':{'url':'git+https://github.com/example/extensions.git'},'description':'Fixture extension description','pi':{'extensions':['index.mjs']}}))
(pkg/'index.mjs').write_text('''export default pi=>pi.registerTool({name:'detail_fixture',label:'Fixture',description:'Reads fixture data and reports the result.',parameters:{type:'object',properties:{}},execute:async()=>({content:[{type:'text',text:'fixture'}]})});''')
(agent/'settings.json').write_text(json.dumps({'packages':[str(pkg)]}))
store.data['agent']['agentDir']=str(agent)
store.data['workspace']=str(workspace)
store.data.update(providers=[{'id':'fixture','name':'Fixture','api':'openai','baseUrl':'http://127.0.0.1:9/v1','key':'fixture','models':[{'alias':'fixture','upstream':'fixture'}]}],selectedProvider='fixture',selectedModel='fixture')
store.save()
app,engine,backend=create_application()
window=engine.rootObjects()[0]
window.setWidth(1500);window.setHeight(1000)
warnings=[]
engine.warnings.connect(lambda items:warnings.extend(item.toString() for item in items))
class Links(QObject):
    def __init__(self): super().__init__();self.urls=[]
    @Slot(QUrl)
    def open(self,url): self.urls.append(url.toString())
links=Links()
QDesktopServices.setUrlHandler('https',links,'open')
def find(name):
    pending=[window.contentItem()]
    while pending:
        item=pending.pop()
        if item.objectName()==name:return item
        pending.extend(item.childItems())
    raise AssertionError(name)
def wait(predicate):
    for _ in range(1500):
        QTest.qWait(10)
        if predicate():return
    raise AssertionError((backend.piManagement.status,warnings))
def click(name):
    item=find(name)
    flick=find('settingsScroll').property('contentItem')
    parent=item.parentItem()
    while parent is not None and parent!=flick:parent=parent.parentItem()
    if parent is not None:
        y=item.mapToItem(flick,QPointF()).y()+flick.property('contentY')-flick.height()/2
        flick.setProperty('contentY',max(0,y));QTest.qWait(100)
    assert item.isVisible() and item.isEnabled(),name
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(item.boundingRect().center()).toPoint())
    QTest.qWait(80)
try:
    window.setProperty('page','settings');window.setProperty('settingsTab',3);QTest.qWait(200)
    click('openPiSettingsButton')
    find('piFold_kernel').setProperty('expanded',False)
    find('piFold_extensions').setProperty('expanded',True)
    find('piFold_packages').setProperty('expanded',True)
    wait(lambda:not backend.piManagement.busy and bool(backend.piManagement.extensions))
    fixture=next(row for row in backend.piManagement.extensions if row['name']=='@fixture/extension-details')
    click('agentExtensionsDetails_'+fixture['id'])
    wait(lambda:any(tool['name']=='detail_fixture' for tool in backend.agentResources.get('allTools',[])))
    wait(lambda:find('extensionDetailsToolList').property('count')==1)
    assert find('extensionDetailsName').property('text')=='@fixture/extension-details'
    assert find('extensionDetailsToolList').height()>100
    click('extensionHomepageButton');click('extensionRepositoryButton')
    assert links.urls==['https://example.com/extensions','https://github.com/example/extensions'],links.urls
    click('closeExtensionDetailsButton')
    child=next(row for row in backend.piManagement.extensions if row['path']=='builtin:subagents')
    assert child['info']['package']=='@gotgenes/pi-subagents' and child['info']['origin']=='community'
    click('agentExtensionsDetails_'+child['id'])
    assert find('extensionDetailsToolList').property('count')>=3
    with patch('app.pi_management.resource_command',return_value={'id':child['id'],'status':'available','current':'25.0.5','latest':'25.0.6','message':'发现新版本'}) as check:
        click('checkExtensionUpdateButton')
        wait(lambda:backend.piManagement.extensionUpdate.get('latest')=='25.0.6')
        assert check.call_args.kwargs=={'action':'check-update','id':child['id']}
    assert '25.0.6' in find('extensionUpdateResult').property('text')
    output=ROOT/'artifacts/screenshots/extension-details.png';output.parent.mkdir(parents=True,exist_ok=True)
    window.grabWindow().save(str(output))
    assert not warnings,warnings
    print('EXTENSION_DETAILS_UI_OK: real package metadata and registered tool descriptions, community subagents, web/repository links and scoped update results')
finally:
    QDesktopServices.unsetUrlHandler('https')
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
