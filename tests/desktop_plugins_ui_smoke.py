"""Actual QML plugin management, lazy tree, Git diff and pane exclusion."""
import os,sys,json,tempfile,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
work=tempfile.TemporaryDirectory(prefix='umeko-plugins-ui-');base=Path(work.name);workspace=base/'workspace';workspace.mkdir()
(workspace/'hello.md').write_text('# Plugin preview\n');(workspace/'example.py').write_text('print("hello")\n');(workspace/'folder').mkdir();(workspace/'delete-me.txt').write_text('temporary')
subprocess.run(['git','init','-q',str(workspace)],check=True)
(workspace/'baseline.py').write_text('print("initial")\n')
subprocess.run(['git','-C',str(workspace),'add','baseline.py'],check=True)
subprocess.run(['git','-C',str(workspace),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-q','-m','Initial fixture'],check=True)
os.environ.update(UMEKO_DATA_DIR=str(base/'profile'),PI_CODING_AGENT_DIR=str(base/'agent'),UMEKO_LANGUAGE='zh',QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software')
from PySide6.QtCore import QUrl,Qt,QObject,QCoreApplication,QEvent
from PySide6.QtGui import QKeyEvent
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
def click(name,button=Qt.LeftButton):
    item=find(name);assert item is not None,name
    window.grabWindow();QTest.mouseClick(window,button,Qt.NoModifier,item.mapToScene(item.boundingRect().center()).toPoint());QTest.qWait(120)
def clickable(item):
    if item is None or not item.isVisible() or not item.isEnabled() or item.width()<=0 or item.height()<=0:return False
    point=item.mapToScene(item.boundingRect().center())
    if not (0<point.x()<window.width() and 0<point.y()<window.height()):return False
    ancestor=item.parentItem()
    while ancestor is not None:
        if ancestor.property('clip'):
            local=ancestor.mapFromScene(point)
            if not (0<=local.x()<ancestor.width() and 0<=local.y()<ancestor.height()):return False
        ancestor=ancestor.parentItem()
    return True
def check_launcher_boundary():
    launcher=find('desktopPluginLauncher');chat=find('chatPage');composer=find('composer')
    corner=launcher.mapToScene(launcher.boundingRect().bottomRight());edge=chat.mapToScene(chat.boundingRect().bottomRight())
    assert edge.x()-corner.x()>=11 and abs(edge.y()-corner.y()-12)<2
    assert launcher.mapToScene(launcher.boundingRect().topLeft()).y()-composer.mapToScene(composer.boundingRect().bottomRight()).y()>=9
    if not launcher.property('docking'):
        target=composer.mapToScene(composer.boundingRect().bottomRight()).x() if launcher.property('docked') else edge.x()-12
        assert abs(target-corner.x())<2
out=ROOT/'build/desktop-plugins-ui';out.mkdir(parents=True,exist_ok=True)
try:
    window.resize(1560,1000);backend.setWorkspace(QUrl.fromLocalFile(str(workspace)).toString());QTest.qWait(250)
    window.setProperty('settingsTab',3);window.setProperty('page','settings');QTest.qWait(250)
    assert find('settingsTab_7') is None
    assert find('openDesktopPluginsButton').isVisible();assert not find('desktopPluginsPage').isVisible()
    wait(lambda:find('pluginManagerArtwork').property('progress')==1 and find('pluginManagerArtwork').property('implicitWidth')>0,'Plugin illustration did not load')
    window.grabWindow().save(str(out/'agent-plugin-entry.png'))
    click('openDesktopPluginsButton')
    assert find('desktopPluginsPage').isVisible();assert find('desktopPluginInstalledList').property('count')==3
    search=find('desktopPluginSearch');search.setProperty('text','Git');QTest.qWait(50);assert find('desktopPluginInstalledList').property('count')==1
    search.setProperty('text','');QTest.qWait(50);window.grabWindow().save(str(out/'manager.png'))
    manager=backend.desktopPlugins
    window.setProperty('page','chat');QTest.qWait(100)
    launcher=find('desktopPluginLauncher');assert launcher.isVisible()
    check_launcher_boundary()
    click('desktopPluginMenuButton')
    wait(lambda:find('desktopPluginSessionMenu').property('desiredOpen') and not find('desktopPluginSessionMenu').property('animating'),'Plugin menu did not open')
    assert find('desktopPluginQuickList').property('count')==2
    window.grabWindow().save(str(out/'quick-menu.png'))
    click('desktopPluginMenuButton')
    wait(lambda:not find('desktopPluginSessionMenu').property('visible'),'Second click did not close menu')
    click('desktopPluginRecentButton',Qt.RightButton)
    wait(lambda:find('desktopPluginSessionMenu').property('desiredOpen') and not find('desktopPluginSessionMenu').property('animating'),'Right click did not open menu')
    click('desktopPluginSettingsButton')
    wait(lambda:window.property('settingsTab')==3 and find('desktopPluginsPage').isVisible(),'Menu settings did not open Agent plugin management')
    click('backFromDesktopPluginsButton');assert find('openDesktopPluginsButton').isVisible()
    window.setProperty('page','chat');QTest.qWait(100)
    manager.setSessionEnabled('git-viewer',False)
    click('desktopPluginMenuButton')
    wait(lambda:not find('desktopPluginSessionMenu').property('animating'),'Filtered menu did not settle')
    assert find('desktopPluginQuickList').property('count')==1
    click('openDesktopPlugin_file-tree')
    wait(lambda:find('fileTreeEntries') is not None and find('fileTreeEntries').property('count')>=3,'Tree did not load')
    assert window.property('page')=='chat';assert find('webPane').property('mode')=='plugin'
    wait(lambda:not find('webPane').property('moving'),'Pane animation did not settle');window.grabWindow().save(str(out/'file-tree.png'))
    check_launcher_boundary()
    assert launcher.mapToScene(launcher.boundingRect().bottomRight()).x()<find('webPane').mapToScene(find('webPane').boundingRect().topLeft()).x()
    click('desktopPluginRecentButton')
    assert not manager.page
    for _ in range(12):QTest.qWait(20);check_launcher_boundary()
    wait(lambda:not find('webPane').property('opened') and not find('webPane').property('moving'),'Second click did not close widget')
    click('desktopPluginRecentButton')
    for _ in range(12):QTest.qWait(20);check_launcher_boundary()
    wait(lambda:find('fileTreeEntries') is not None and find('fileTreeEntries').property('count')>=3 and not find('webPane').property('moving'),'Widget did not reopen')
    window.resize(1420,920);QTest.qWait(150);check_launcher_boundary()
    backend.setFontScale(1.5)
    wait(lambda:not launcher.property('docking'),'Launcher docking did not settle')
    assert launcher.property('docked');check_launcher_boundary()
    window.grabWindow().save(str(out/'docked-launcher.png'))
    backend.setFontScale(1.0);QTest.qWait(100)
    window.grabWindow().save(str(out/'chat-boundary-launcher.png'))
    attachments_before=len(backend._view.attachments)
    click('fileTreeRow_hello.md')
    assert len(backend._view.attachments)==attachments_before,'Single click attached a file'
    file_row=find('fileTreeRow_hello.md')
    QTest.mouseDClick(window,Qt.LeftButton,Qt.NoModifier,file_row.mapToScene(file_row.boundingRect().center()).toPoint())
    wait(lambda:any(row.get('name')=='hello.md' for row in backend._view.attachments),'Double click did not attach file')
    assert manager.page.get('id')=='file-tree' and find('webPane').property('mode')=='plugin'
    click('fileTreeRow_hello.md',Qt.RightButton)
    wait(lambda:find('fileManagerContextMenu').property('visible'),'File manager menu did not open')
    window.grabWindow().save(str(out/'file-manager-context-menu.png'))
    click('fileManagerCopy')
    wait(lambda:bool(app.clipboard().mimeData().urls()) and Path(app.clipboard().mimeData().urls()[0].toLocalFile()).resolve()==(workspace/'hello.md').resolve(),'Copy did not put a file on the clipboard')
    click('fileTreeRow_hello.md',Qt.RightButton);click('fileManagerRename')
    wait(lambda:find('fileManagerRenameField') is not None and find('fileManagerRenameField').property('activeFocus'),'Inline rename did not activate')
    assert find('fileManagerRenameDialog') is None
    assert find('fileManagerRenameField').property('selectedText')=='hello'
    QTest.keyClick(window,Qt.Key_Escape)
    wait(lambda:(workspace/'hello.md').exists() and find('fileManagerRenameField') is None,'Escape did not cancel inline rename')
    click('fileTreeRow_hello.md',Qt.RightButton);click('fileManagerRename')
    wait(lambda:find('fileManagerRenameField') is not None and find('fileManagerRenameField').property('activeFocus'),'Inline rename did not reopen')
    QTest.keyClick(window,Qt.Key_A,Qt.ControlModifier)
    for character in 'renamed.md':QTest.keyClick(window,Qt.Key(ord(character.upper())))
    QTest.keyClick(window,Qt.Key_Return)
    wait(lambda:(workspace/'renamed.md').exists() and find('fileTreeRow_renamed.md') is not None,'File was not renamed')
    click('fileTreeRow_delete-me.txt',Qt.RightButton);click('fileManagerDelete')
    wait(lambda:find('fileManagerDeleteDialog').property('visible'),'Delete confirmation did not open')
    assert (workspace/'delete-me.txt').exists()
    click('fileManagerDeleteConfirm');wait(lambda:not (workspace/'delete-me.txt').exists(),'Confirmed file was not deleted')
    click('fileTreeRow_renamed.md',Qt.RightButton);click('fileManagerPreview')
    wait(lambda:find('webPane').property('mode')=='document','File did not open in document preview')
    assert not manager.page and set(manager.workers)=={'desktop-pet'}
    click('desktopPluginRecentButton')
    wait(lambda:manager.page.get('id')=='file-tree' and find('fileTreeEntries') is not None,'Left click did not reopen recent widget')
    manager.setSessionEnabled('git-viewer',True)
    assert manager.openPage('git-viewer')
    wait(lambda:find('gitChangesList') is not None and find('gitChangesList').property('count')>=3,'Git changes did not load')
    wait(lambda:find('gitHistoryList') is not None and find('gitHistoryList').property('count')==1,'Real commit graph did not load')
    wait(lambda:not find('webPane').property('moving'),'Git pane animation did not settle');window.grabWindow().save(str(out/'git-viewer.png'))
    click('gitGraphToggle');QTest.qWait(100)
    assert abs(find('gitGraphSection').height()-22)<2
    assert find('gitChangesSection').height()>find('gitViewerPluginPage').height()*.8
    click('gitChangesToggle');QTest.qWait(100)
    assert abs(find('gitChangesSection').height()-22)<2 and abs(find('gitGraphSection').height()-22)<2
    assert find('gitGraphSection').y()-find('gitChangesSection').y()<28
    window.grabWindow().save(str(out/'both-sections-collapsed.png'))
    click('gitGraphToggle');QTest.qWait(100)
    assert find('gitGraphSection').height()>find('gitViewerPluginPage').height()*.8
    click('gitChangesToggle');QTest.qWait(100)
    click('gitBranchButton')
    wait(lambda:find('gitBranchPicker').property('visible') and find('gitBranchList').property('count')>=4,'Branch picker did not populate')
    pickerLeft=find('gitBranchSearch').mapToScene(find('gitBranchSearch').boundingRect().topLeft()).x()
    widgetLeft=find('gitViewerPluginPage').mapToScene(find('gitViewerPluginPage').boundingRect().topLeft()).x()
    assert pickerLeft>=widgetLeft and find('gitBranchPicker').property('width')<=find('gitViewerPluginPage').width()
    window.grabWindow().save(str(out/'branch-picker.png'))
    click('gitBranchAction_create')
    wait(lambda:find('gitCreateBranchDialog').property('visible'),'Create branch prompt did not open')
    find('gitNewBranchName').setProperty('text','ui-preview-branch');click('gitCreateBranchConfirm')
    wait(lambda:find('gitViewerPluginPage').property('branch')=='ui-preview-branch','Branch was not created and checked out')
    click('gitChange_untracked_example.py',Qt.RightButton)
    wait(lambda:find('gitFileContextMenu').property('visible'),'File context menu did not open')
    window.grabWindow().save(str(out/'git-file-context-menu.png'))
    click('gitContextAttach');wait(lambda:any(row.get('name')=='example.py' for row in backend._view.attachments),'File was not attached to chat')
    click('gitChange_untracked_example.py',Qt.RightButton);click('gitContextExplorer')
    wait(lambda:find('fileTreePluginPage') is not None and find('fileTreePluginPage').property('selectedPath')=='example.py','Explorer did not select requested file')
    assert manager.openPage('git-viewer')
    wait(lambda:find('gitChangesList') is not None and find('gitChangesList').property('count')>=3,'Git changes did not reload')
    wait(lambda:clickable(find('gitChange_untracked_example.py')),'Git example.py row did not become clickable')
    click('gitChange_untracked_example.py')
    wait(lambda:find('gitDiffText') is not None and 'hello' in find('gitDiffText').property('text'),'Git diff did not open')
    window.grabWindow().save(str(out/'git-diff.png'))
    window.setProperty('page','settings');QTest.qWait(200);assert not manager.page;assert not find('webPane').property('opened')
    window.setProperty('page','chat');assert manager.openPage('file-tree');QTest.qWait(200);backend.newSession();QTest.qWait(250);assert not manager.page and set(manager.workers)=={'desktop-pet'}
    manager.setSessionEnabled('file-tree',False);manager.setSessionEnabled('git-viewer',False)
    click('desktopPluginMenuButton')
    wait(lambda:find('desktopPluginSessionMenu').property('desiredOpen') and not find('desktopPluginSessionMenu').property('animating'),'Empty plugin menu did not open')
    assert find('desktopPluginQuickList').property('count')==0
    click('desktopPluginSettingsButton')
    wait(lambda:find('desktopPluginsPage').isVisible(),'Empty menu lost the settings entry')
    assert not warnings,warnings
    print('DESKTOP_PLUGINS_UI_OK: Agent subpage, chat-boundary launcher, toggle, file attach/copy/rename/delete, branch picker/create, exact section collapse, Git context actions and explorer selection, session cleanup',flush=True)
finally:
    app.clipboard().clear()
    backend.close();window.hide()
    import shiboken6;shiboken6.delete(engine)
    work.cleanup()
