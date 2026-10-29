"""Actual QML plugin management, lazy tree, Git diff and pane exclusion."""
import os,sys,json,tempfile,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
work=tempfile.TemporaryDirectory(prefix='umeko-plugins-ui-');base=Path(work.name);workspace=base/'workspace';workspace.mkdir()
(workspace/'hello.md').write_text('# Plugin preview\n');(workspace/'example.py').write_text('print("hello")\n');(workspace/'folder').mkdir()
subprocess.run(['git','init','-q',str(workspace)],check=True)
os.environ.update(UMEKO_DATA_DIR=str(base/'profile'),PI_CODING_AGENT_DIR=str(base/'agent'),UMEKO_LANGUAGE='zh',QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software')
from PySide6.QtCore import QUrl,Qt,QObject
from PySide6.QtTest import QTest
from main import create_application
app,engine,backend=create_application();window=engine.rootObjects()[0];warnings=[]
engine.warnings.connect(lambda values:warnings.extend(x.toString() for x in values))
def find(name):
    stack=[window.contentItem()]
    while stack:
        item=stack.pop()
        if item.objectName()==name:return item
        if item.objectName() in ('webSurfaceLoader','htmlPreviewBrowser'):continue
        stack.extend(item.childItems())
    return window.findChild(QObject,name)
def wait(check,message):
    for _ in range(400):
        QTest.qWait(20)
        if check():return
    window.grabWindow().save(str(ROOT/'build/desktop-plugins-ui/failure.png'))
    print({name: ({p:str(find(name).property(p)) for p in ('visible','opened','mode','moving','source','width','height')} if find(name) else None) for name in ('webPane','desktopPluginSurfaceLoader','desktopPluginSurface','desktopPluginPageLoader','fileTreePluginPage')},flush=True)
    raise AssertionError(message+'\n'+str(backend.desktopPlugins.page)+'\n'+'\n'.join(warnings))
def click(name):
    item=find(name);assert item is not None,name
    window.grabWindow();QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(item.boundingRect().center()).toPoint());QTest.qWait(120)
out=ROOT/'build/desktop-plugins-ui';out.mkdir(parents=True,exist_ok=True)
try:
    window.resize(1560,1000);backend.setWorkspace(QUrl.fromLocalFile(str(workspace)).toString());QTest.qWait(250)
    window.setProperty('settingsTab',7);window.setProperty('page','settings');QTest.qWait(250)
    assert find('desktopPluginsPage').isVisible();assert find('desktopPluginInstalledList').property('count')==2
    search=find('desktopPluginSearch');search.setProperty('text','Git');QTest.qWait(50);assert find('desktopPluginInstalledList').property('count')==1
    search.setProperty('text','');QTest.qWait(50);window.grabWindow().save(str(out/'manager.png'))
    manager=backend.desktopPlugins
    assert manager.openPage('file-tree')
    wait(lambda:find('fileTreeEntries') is not None and find('fileTreeEntries').property('count')>=3,'Tree did not load')
    assert window.property('page')=='chat';assert find('webPane').property('mode')=='plugin'
    wait(lambda:not find('webPane').property('moving'),'Pane animation did not settle');window.grabWindow().save(str(out/'file-tree.png'))
    click('fileTreeRow_hello.md')
    wait(lambda:find('webPane').property('mode')=='document','File did not open in document preview')
    assert not manager.page and not manager.workers
    assert manager.openPage('git-viewer')
    wait(lambda:find('gitChangesList') is not None and find('gitChangesList').property('count')>=3,'Git changes did not load')
    wait(lambda:not find('webPane').property('moving'),'Git pane animation did not settle');window.grabWindow().save(str(out/'git-viewer.png'))
    click('gitChange_untracked_example.py')
    wait(lambda:find('gitDiffText') is not None and 'hello' in find('gitDiffText').property('text'),'Git diff did not open')
    window.grabWindow().save(str(out/'git-diff.png'))
    window.setProperty('page','settings');QTest.qWait(200);assert not manager.page;assert not find('webPane').property('opened')
    window.setProperty('page','chat');assert manager.openPage('file-tree');QTest.qWait(200);backend.newSession();QTest.qWait(250);assert not manager.page and not manager.workers
    assert not warnings,warnings
    print('DESKTOP_PLUGINS_UI_OK: searchable settings, lazy tree, Git status/diff, mutual exclusion, settings/session cleanup')
finally:
    backend.close();window.hide()
    import shiboken6;shiboken6.delete(engine)
    work.cleanup()
