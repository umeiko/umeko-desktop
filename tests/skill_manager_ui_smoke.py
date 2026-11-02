"""Real pointer/keyboard interaction with the two-root Skill folder Widget."""
import copy
import json
import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
from PySide6.QtCore import QObject, Property, QPointF, QTimer, Qt, QUrl, Signal, Slot, QMimeData, QMetaObject, Q_ARG
from PySide6.QtGui import QGuiApplication, QFont, QFontDatabase, QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQml import QQmlExpression
from PySide6.QtTest import QTest
import shiboken6

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

class FakeSdk(QObject):
    hostResponse=Signal(str,'QVariantMap')
    activeChanged=Signal()
    appearanceChanged=Signal()
    languageChanged=Signal()
    def __init__(self):
        super().__init__()
        self._language='en';self._scale=1.;self.counter=0;self.requests=[];self.jobs={};self.page_size=100
        self.fail=False;self.import_error=''
        self.rows=[dict(id=f'skill-{i:02d}',name=f'document-{i:02d}',folderName=f'document-{i:02d}',
            scope='project' if i<20 else 'global',directory=f'/fixture/skills/{i:02d}',kind='folder',
            path=f'/fixture/skills/{i:02d}/SKILL.md',enabled=True,canToggle=True,description=f'Notes for topic {i:02d}') for i in range(40)]
        self.rows[23]['descriptions']={'en':'Notes for topic 23','zh':'整理主题 23 的相关文档与说明，按需阅读技能指引。'}
        self.operations={key:True for key in ['skills.browse','skills.preview','skills.open','skills.copy','skills.paste',
            'skills.attach','skills.insert','skills.rename','skills.delete','skills.job','skills.importPreview','skills.import','skills.importLocal']}
    @Property(bool,notify=activeChanged)
    def active(self):return True
    @Property(float,notify=appearanceChanged)
    def scale(self):return self._scale
    @Property(float,notify=appearanceChanged)
    def fontScale(self):return self._scale
    @Property('QVariantMap',notify=appearanceChanged)
    def config(self):return {'fontFamily':'DejaVu Sans'}
    @Property('QVariantMap',constant=True)
    def themeStyle(self):return {'base':'dark'}
    @Property(str,constant=True)
    def lineSpacing(self):return 'standard'
    @Property(str,notify=languageChanged)
    def language(self):return self._language
    @Property('QVariantMap',constant=True)
    def colors(self):return dict(surface='#202521',bg='#181d19',ink='#e4e9e3',muted='#929e94',accent='#9cc69f',accentBg='#334636',hover='#29362b',line='#465148',danger='#f0a4a0')
    @Property('QVariantMap',constant=True)
    def hostCapabilities(self):return {'operations':self.operations}
    @Slot(str,'QVariantMap',result=str)
    def requestHost(self,operation,args):
        assert operation in self.operations,operation
        self.counter+=1;identifier=f'request-{self.counter}';self.requests.append((operation,args))
        def reply(value):QTimer.singleShot(0,lambda:self.hostResponse.emit(identifier,value))
        if self.fail and operation not in ('skills.preview','skills.job'):
            self.fail=False;reply({'ok':False,'error':'Fixture failure'});return identifier
        if operation=='skills.job':
            result=copy.deepcopy(self.jobs[args['id']])
            field='skills' if 'skills' in result else 'preview.skills'
            container=result if field=='skills' else result.get('preview',{})
            if 'skills' in container:
                values=container['skills'];start=args.get('offset',0);end=min(start+self.page_size,len(values))
                container['skills']=values[start:end]
                result['skillsPage']=dict(field=field,offset=start,total=len(values),nextOffset=end if end<len(values) else None)
            reply({'ok':True,'jobs':[dict(id=args['id'],status='completed',result=result)]});return identifier
        result={'ok':True}
        if operation=='skills.browse':result.update(skills=copy.deepcopy(self.rows),roots={'project':'/fixture/workspace/.pi/skills','global':'/fixture/agent/skills'})
        elif operation=='skills.preview':result['details']={'id':args['id'],'markdown':'---\nname: fixture\n---\n# Skill instructions\n\nRead these instructions before working.','truncated':False}
        elif operation in ('skills.paste','skills.importLocal'):
            result.update(imported=['copied-skill'],skipped=[],errors=[])
            if self.import_error:result.update(ok=False,error=self.import_error,imported=[],errors=[dict(name='copied-skill',error=self.import_error)])
        elif operation=='skills.attach':next(row for row in self.rows if row['id']==args['id']).update(enabled=args['enabled'])
        elif operation=='skills.rename':next(row for row in self.rows if row['id']==args['id']).update(name=args['name'],folderName=args['name'])
        elif operation=='skills.delete':self.rows=[row for row in self.rows if row['id']!=args['id']]
        elif operation=='skills.importPreview':result['preview']=dict(id='preview-local',project=args['project'],errors=[],skills=[
            dict(name='notes-helper',conflict=False,replaceable=False),dict(name='existing',conflict=True,replaceable=True),
            dict(name='blocked',conflict=True,replaceable=False,error='Cannot replace this source')])
        elif operation=='skills.import':result.update(imported=['notes-helper'],skipped=['existing','blocked'],errors=[])
        job=f'job-{self.counter}';self.jobs[job]=result;reply(dict(ok=True,accepted=True,jobId=job));return identifier

QQuickStyle.setStyle('Basic')
app=QGuiApplication([])
from app.syntax_highlight import register_text_types
register_text_types()
for path in ('C:/Windows/Fonts/segoeui.ttf','C:/Windows/Fonts/msyh.ttc'):
    if Path(path).is_file():QFontDatabase.addApplicationFont(path)
app.setFont(QFont('Segoe UI',10))
sdk=FakeSdk();view=QQuickView();warnings=[]
view.engine().rootContext().setContextProperty('backend',sdk)
view.engine().warnings.connect(lambda values:warnings.extend(value.toString() for value in values))
view.setResizeMode(QQuickView.SizeRootObjectToView);view.setInitialProperties({'sdk':sdk})
view.setSource(QUrl.fromLocalFile(str(ROOT/'umeko-plugins/skill-manager/qml/Main.qml')))
assert view.status()==QQuickView.Ready,[e.toString() for e in view.errors()]
view.resize(500,800);view.show();root=view.rootObject()
def variant(value):return value.toVariant() if hasattr(value,'toVariant') else value
def find(name):
    stack=[root]
    while stack:
        item=stack.pop()
        if item.objectName()==name:return item
        stack.extend(item.childItems())
    return None
def wait_for(predicate,message):
    for _ in range(700):
        QTest.qWait(10)
        if predicate():return
    raise AssertionError(message+': '+str(root.property('notice')))
def idle():wait_for(lambda:not root.property('working'),'Widget remained busy')
def click(name,button=Qt.LeftButton,double=False):
    reveal(name)
    QTest.qWait(20);item=find(name);assert item and item.isVisible() and item.isEnabled(),name
    point=item.mapToScene(item.boundingRect().center()).toPoint()
    (QTest.mouseDClick if double else QTest.mouseClick)(view,button,Qt.NoModifier,point)
    QTest.qWait(20)
def js(source):
    expression=QQmlExpression(view.engine().rootContext(),root,source);value=expression.evaluate()
    assert not expression.hasError(),expression.error().toString()
    return value[0] if isinstance(value,tuple) else value
def actions():return [entry for entry in sdk.requests if entry[0] not in ('skills.job','skills.preview')]

def reveal(name):
    name=name.replace('skillManagerEnabled_','skillManagerEntry_')
    entries=variant(root.property('entries'))
    index=next((i for i,row in enumerate(entries) if name==('skillManagerEntry_'+row['skill']['id'] if row['kind']=='skill' else 'skillManagerScope_'+row['scope'] if row['kind']=='scope' else '')),None)
    if index is not None:
        assert QMetaObject.invokeMethod(find('skillManagerList'),'positionViewAtIndex',Q_ARG(int,index),Q_ARG(int,4))
        QTest.qWait(30)
def drop(name,url='file:///tmp/test.skill',point=None):
    if point is None:reveal(name)
    item=find(name);assert item and item.isVisible(),name
    point=point or item.mapToScene(item.boundingRect().center())
    mime=QMimeData();mime.setUrls([QUrl(url)])
    enter=QDragEnterEvent(point.toPoint(),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
    QGuiApplication.sendEvent(view,enter)
    move=QDragMoveEvent(point.toPoint(),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
    QGuiApplication.sendEvent(view,move)
    event=QDropEvent(point,Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
    QGuiApplication.sendEvent(view,event)
    assert event.isAccepted(),'Drop was not accepted: '+name
    idle()

try:
    idle()
    assert len(variant(root.property('skills')))==40
    assert sum(row['kind']=='scope' for row in variant(root.property('entries')))==2
    assert len(variant(root.property('entries')))==42
    assert find('skillManagerEntry_skill-00').height()==56
    assert not find('skillManagerAttach_skill-00') and not find('skillManagerDetails') and not find('skillManagerInstall')
    click('skillManagerEnabled_skill-00');idle()
    assert ('skills.attach',{'id':'skill-00','enabled':False}) in actions()
    assert not find('skillManagerEnabled_skill-00').property('checked')
    screenshot=ROOT/'artifacts/screenshots/skill-checkboxes-dark.png';screenshot.parent.mkdir(parents=True,exist_ok=True);view.grabWindow().save(str(screenshot))
    click('skillManagerEnabled_skill-00');idle();assert find('skillManagerEnabled_skill-00').property('checked')
    sdk.fail=True;click('skillManagerEnabled_skill-00');idle()
    assert find('skillManagerEnabled_skill-00').property('checked'),'Failed switch did not restore the checkbox'
    click('skillManagerRefresh');idle()
    before=len(actions());click('skillManagerEntry_skill-00');assert len(actions())==before,'Single click performed an action'
    wait_for(lambda:variant(root.property('preview')).get('id')=='skill-00','Inline Markdown preview did not load')
    assert 'Skill instructions' in find('skillManagerPreviewMarkdown').property('text')
    assert find('skillManagerDescription_skill-00').property('text')=='Notes for topic 00'
    handle=find('skillManagerSplitHandle');listing=find('skillManagerList');original=listing.height()
    point=handle.mapToScene(handle.boundingRect().center()).toPoint()
    QTest.mousePress(view,Qt.LeftButton,Qt.NoModifier,point);QTest.mouseMove(view,point+QPointF(0,60).toPoint(),80);QTest.mouseRelease(view,Qt.LeftButton,Qt.NoModifier,point+QPointF(0,60).toPoint())
    QTest.qWait(60);assert listing.height()>original+30,'Preview splitter did not resize the list'
    before_preview=sum(operation=='skills.preview' for operation,args in sdk.requests)
    js('selectedId="skill-01"');wait_for(lambda:variant(root.property('preview')).get('id')=='skill-01','Second preview did not load')
    js('selectedId="skill-00"');wait_for(lambda:variant(root.property('preview')).get('id')=='skill-00','Cached preview did not return')
    assert sum(operation=='skills.preview' for operation,args in sdk.requests)==before_preview+1,'Cached preview was loaded again'
    output=ROOT/'build/skill-manager-ui';output.mkdir(parents=True,exist_ok=True)
    assert view.grabWindow().save(str(output/'skills-en.png'))
    click('skillManagerEntry_skill-00',double=True);idle()
    assert actions()[-1]==('skills.insert',{'id':'skill-00'})
    click('skillManagerScope_project');assert len(variant(root.property('entries')))==22
    click('skillManagerScope_project');assert len(variant(root.property('entries')))==42
    windows=len(app.topLevelWindows())
    for name,expected in [('copy','skills.copy'),('copyPath','skills.copy'),('preview','skills.open'),('edit','skills.open'),('reveal','skills.open')]:
        click('skillManagerEntry_skill-00',Qt.RightButton)
        menu=find('skillManagerContextMenu');assert menu.isVisible() and menu.property('clip')
        assert menu.x()>=0 and menu.y()>=0 and menu.x()+menu.width()<=root.width()+.1 and menu.y()+menu.height()<=root.height()+.1
        assert len(app.topLevelWindows())==windows,'Menu opened a window outside its Widget'
        click('skillManagerMenu_'+name);idle();assert actions()[-1][0]==expected
    click('skillManagerEntry_skill-00',Qt.RightButton);click('skillManagerMenu_rename')
    find('skillManagerRenameName').setProperty('text','renamed-notes');click('skillManagerRenameSave');idle()
    assert sdk.rows[0]['name']=='renamed-notes'
    click('skillManagerEntry_skill-00',Qt.RightButton);click('skillManagerMenu_paste');idle()
    assert root.property('route')=='main' and ('skills.paste',{'project':True}) in actions()
    assert not root.property('notice') and not root.property('importFailure')
    # Explicit Import retains its replacement workflow; paste never opens it.
    click('skillManagerImport');find('skillManagerImportSource').setProperty('text','/fixture/copied-skill')
    click('skillManagerImportPreview');idle()
    assert variant(root.property('importDecisions'))=={'notes-helper':'replace','existing':'skip','blocked':'skip'}
    assert not find('skillManagerImportReplace_blocked').isEnabled()
    click('skillManagerImportSubmit');idle();assert variant(root.property('importResult'))['imported']==['notes-helper']
    click('skillManagerBack');idle()
    click('skillManagerEntry_skill-00',Qt.RightButton);click('skillManagerMenu_delete');idle();assert len(sdk.rows)==39
    assert js('acceptsImportUrls(["file:///tmp/test.skill"])')
    assert not js('acceptsImportUrls(["https://example.com/test.zip"])')
    assert not js('acceptsImportUrls(["file:///one","file:///two"])')
    # Real Qt file drops determine the destination from pointer position, not
    # selectedScope. Collapsed headers, scrolled rows and blank space work too.
    root.setProperty('selectedScope','global')
    drop('skillManagerScope_project')
    assert actions()[-2]==('skills.importLocal',{'source':'file:///tmp/test.skill','project':True}),actions()[-3:]
    click('skillManagerScope_project')
    root.setProperty('selectedScope','global');drop('skillManagerScope_project')
    assert actions()[-2][1]['project'] is True
    root.setProperty('selectedScope','project');drop('skillManagerScope_global')
    assert actions()[-2][1]['project'] is False
    click('skillManagerScope_project')
    scroll=find('skillManagerList');scroll.setProperty('contentY',scroll.property('contentHeight')-scroll.height());QTest.qWait(25)
    root.setProperty('selectedScope','project');drop('skillManagerEntry_skill-39')
    assert actions()[-2][1]['project'] is False
    root.setProperty('collapsedScopes',['project','global']);QTest.qWait(30)
    scroll.setProperty('contentY',0);QTest.qWait(25)
    point=scroll.mapToScene(QPointF(40,scroll.height()-10));root.setProperty('selectedScope','project')
    drop('skillManagerList',point=point);assert actions()[-2][1]['project'] is False
    assert root.property('route')=='main'
    sdk.import_error='A same-name folder already exists.\nOriginal files were preserved.'
    drop('skillManagerScope_project')
    assert root.property('route')=='main' and root.property('importFailure')==sdk.import_error
    assert find('skillManagerImportError').isVisible() and len(app.topLevelWindows())==windows
    click('skillManagerImportErrorClose');sdk.import_error='';assert not root.property('importFailure')
    sdk.fail=True;js('paste("project")');idle()
    assert root.property('importFailure')=='Fixture failure' and root.property('route')=='main'
    click('skillManagerImportErrorClose')
    # Neither footer guidance nor successful-import notice is shown.
    assert not root.property('notice')
    assert not js('dropLocalUrls(["file:///tmp/test.skill"],"")')
    click('skillManagerScope_global')
    find('skillManagerSearch').setProperty('text','topic 23');assert len([e for e in variant(root.property('entries')) if e['kind']=='skill'])==1
    find('skillManagerSearch').setProperty('text','')
    sdk.fail=True;click('skillManagerRefresh');idle();assert root.property('noticeError') and 'Fixture failure' in root.property('notice')
    sdk._language='zh';sdk.languageChanged.emit();sdk._scale=1.3;sdk.appearanceChanged.emit();QTest.qWait(40)
    click('skillManagerRefresh');idle()
    click('skillManagerEntry_skill-23')
    wait_for(lambda:variant(root.property('preview')).get('id')=='skill-23','Localized Skill preview did not load')
    assert '整理主题 23' in find('skillManagerDescription_skill-23').property('text')
    assert view.grabWindow().save(str(output/'skills-zh.png'))
    # Large UTF-8 catalog spans multiple immutable pages; publish it once complete.
    root.setProperty('collapsedScopes',[])
    sdk.rows=[dict(sdk.rows[0],id=f'large-{i}',name=f'large-{i:03d}',description='技能说明'*256) for i in range(250)]
    sdk.page_size=60;before=len(sdk.requests);click('skillManagerRefresh')
    wait_for(lambda:root.property('pageOffset')>0,'Pagination did not begin')
    assert len(variant(root.property('skills')))!=250,'Published a partial catalog'
    idle();actual=variant(root.property('skills'));assert len(actual)==250 and len({row['id'] for row in actual})==250
    assert len(json.dumps(actual,ensure_ascii=False).encode())>262144
    assert [args['offset'] for op,args in sdk.requests[before:] if op=='skills.job' and 'offset' in args]==[0,60,120,180,240]
    view.resize(320,240);QTest.qWait(60)
    click('skillManagerEntry_large-0',Qt.RightButton)
    menu=find('skillManagerContextMenu');assert menu.height()<=root.height()
    viewport=find('skillManagerMenuViewport');viewport.setProperty('contentY',viewport.property('contentHeight')-viewport.height())
    click('skillManagerMenu_delete');idle();assert len(sdk.rows)==249
    assert not any(op in ('skills.default','skills.details') for op,args in sdk.requests)
    assert root.property('clip') and not warnings,'\n'.join(warnings)
    print('SKILL_FOLDER_UI_OK: descriptive rows, resizable vertical split, cached Markdown preview, per-chat checkboxes and save-failure rollback, two roots, attachment, scoped menus, rename/delete, paste/drop, import, i18n/scale, bounded paging and narrow layouts')
finally:
    view.close();shiboken6.delete(view);app.processEvents()
