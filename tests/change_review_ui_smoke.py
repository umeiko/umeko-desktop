"""Render and use the opt-in review Widget against real temporary snapshots."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
temporary=tempfile.TemporaryDirectory(prefix='umeko-review-ui-')
base=Path(temporary.name);workspace=base/'workspace';(workspace/'src').mkdir(parents=True)
file=workspace/'src'/'example.py';file.write_text('before = 1\n',encoding='utf-8')
os.environ.update(UMEKO_DATA_DIR=str(base/'profile'),PI_CODING_AGENT_DIR=str(base/'agent'),UMEKO_LANGUAGE='zh',QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software')
from PySide6.QtCore import QObject,QUrl,Qt
from PySide6.QtTest import QTest
from main import create_application

app,engine,backend=create_application();window=engine.rootObjects()[0]
warnings=[]
engine.warnings.connect(lambda values:warnings.extend(v.toString() for v in values))
manager=backend.desktopPlugins;responses={}
manager.response.connect(lambda request,value:responses.__setitem__(request,value))
out=ROOT/'build/change-review-ui';out.mkdir(parents=True,exist_ok=True)

def find(name):
    stack=[window.contentItem()]
    while stack:
        item=stack.pop()
        if item.objectName()==name:return item
        stack.extend(item.childItems())
    return window.findChild(QObject,name)

def wait(predicate,label):
    for _ in range(500):
        QTest.qWait(20)
        if predicate():return
    window.grabWindow().save(str(out/'failure.png'))
    raise AssertionError(label+'\n'+'\n'.join(warnings))

def call(method,arguments):
    request=manager.call_for('change-review',method,json.dumps(arguments),session=manager.bridge.snapshot(backend._view))
    assert request,method
    wait(lambda:request in responses,method+' did not finish')
    assert responses[request]['ok'],responses[request]
    return responses[request]['result']

def click(name,button=Qt.LeftButton):
    wait(lambda:find(name) is not None,'Missing control '+name)
    window.grabWindow();item=find(name)
    QTest.mouseClick(window,button,Qt.NoModifier,item.mapToScene(item.boundingRect().center()).toPoint())
    QTest.qWait(80)

try:
    window.resize(1440,960);backend.setWorkspace(QUrl.fromLocalFile(str(workspace)).toString());QTest.qWait(100)
    assert not manager.enabled('change-review')
    manager.setEnabled('change-review',True)
    assert call('begin',{'loopId':'fixture'})['captured']
    file.write_text('after = 2\n',encoding='utf-8');(workspace/'added.txt').write_text('new file\n',encoding='utf-8')
    result=call('finish',{'loopId':'fixture','reason':'cancelled'})
    assert result['files']==2 and not result['error']
    wait(lambda:manager.page.get('id')=='change-review' and find('changeReviewWidget') is not None,'Finishing did not open the review page')
    wait(lambda:find('changeReviewRow_src') is not None,'Review tree did not populate')
    wait(lambda:not find('webPane').property('moving'),'Review pane did not settle')
    window.grabWindow().save(str(out/'tree.png'))
    click('changeReviewRow_src')
    click('changeReviewRow_src/example.py')
    wait(lambda:'+after = 2' in find('changeReviewWidget').property('diff'),'Diff did not show updated content')
    assert '-before = 1' in find('changeReviewWidget').property('diff')
    assert find('changeReviewDiff').isVisible()
    window.grabWindow().save(str(out/'diff.png'))
    click('changeReviewCopy');assert '+after = 2' in app.clipboard().text()
    click('changeReviewBack')
    assert find('changeReviewFiles').isVisible()
    click('changeReviewRow_src/example.py',Qt.RightButton)
    menu=find('gitFileContextMenu')
    wait(lambda:menu.property('visible'),'Read-only menu did not open')
    assert menu.property('readOnly') and not find('gitContextDiscard').isVisible() and not find('gitContextIgnore').isVisible()
    menu.close();manager.closePage()
    assert 'change-review' in manager.workers,'Closing the page stopped the application service'
    window.setProperty('settingsTab',3);window.setProperty('page','settings');QTest.qWait(100)
    page=find('desktopPluginsPage');page.setProperty('selectedId','change-review')
    page.parentItem().parentItem().setProperty('pluginsOpen',True)
    wait(lambda:find('changeReviewAutoOpenSwitch') is not None,'Review setting did not load')
    toggle=find('changeReviewAutoOpenSwitch');assert toggle.property('checked')
    worker=manager.workers['change-review']
    click('changeReviewAutoOpenSwitch')
    wait(lambda:manager.settings.get('config',{}).get('change-review',{}).get('autoOpen') is False and not manager.busy,'Setting did not save')
    assert manager.workers['change-review'] is worker,'Setting restarted snapshot service'
    assert call('status',{})['total']==2,'Setting discarded the completed review'
    window.grabWindow().save(str(out/'settings.png'))
    for selected in ('desktop-pet','change-review'):
        page.setProperty('selectedId',selected);QTest.qWait(60)
    wait(lambda:find('changeReviewAutoOpenSwitch') is not None,'Review setting did not reload')
    assert not find('changeReviewAutoOpenSwitch').property('checked'),'Setting was not restored'
    window.setProperty('page','chat');QTest.qWait(150)
    call('begin',{'loopId':'manual-open'});file.write_text('manual = 3\n',encoding='utf-8')
    call('finish',{'loopId':'manual-open'})
    assert not manager.page,'Disabled auto-open still opened a pane'
    assert manager.openPage('change-review')
    wait(lambda:find('changeReviewRow_src') is not None,'Manual review did not populate')
    manager.setEnabled('change-review',False)
    wait(lambda:not any((manager.root/'state'/'change-review').rglob('review-*')),'Stopping retained temporary snapshots')
    assert file.read_text(encoding='utf-8')=='manual = 3\n'
    assert not (workspace/'.git').exists(),'Review created a repository in the project'
    assert not warnings,'\n'.join(warnings)
    print('CHANGE_REVIEW_UI_OK: automatic/manual pane, live persistent setting, retained snapshot, tree/diff/back/copy, read-only menu and cleanup')
finally:
    app.clipboard().clear();backend.close()
    import shiboken6
    shiboken6.delete(engine)
    app.processEvents();temporary.cleanup()
