"""Real composer / native Skill catalog; no provider or paid requests."""
import json, os, sys, tempfile, time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
# A disposable HOME must not retain Qt's mapped disk-cache files on Windows.
os.environ['QML_DISABLE_DISK_CACHE']='1'
os.environ['UMEKO_LANGUAGE']='zh'
from PySide6.QtCore import Qt
from PySide6.QtQml import QQmlExpression
from PySide6.QtTest import QTest
import shiboken6
from app.storage import Store
from main import create_application

def wait(predicate,label):
    end=time.monotonic()+30
    while time.monotonic()<end:
        QTest.qWait(20)
        if predicate():return
    raise AssertionError(label)

def main():
    with tempfile.TemporaryDirectory(prefix='slash-actual-ui-') as temporary:
        base=Path(temporary).resolve();agent=base/'agent';workspace=base/'workspace'
        workspace.mkdir();(workspace/'.git').mkdir();(base/'home').mkdir()
        folder=agent/'skills/文档整理';folder.mkdir(parents=True)
        (folder/'SKILL.md').write_text('---\nname: documents\ndescription: Visible document skill.\n---\nGuide.\n',encoding='utf-8')
        for index in range(40):
            guide=agent/'skills'/('guide-'+str(index).zfill(2));guide.mkdir(parents=True)
            (guide/'SKILL.md').write_text(f'---\nname: guide-{index:02}\ndescription: Guide fixture.\n---\nInstructions.\n',encoding='utf-8')
        os.environ.update(UMEKO_DATA_DIR=str(base/'profile'),HOME=str(base/'home'),USERPROFILE=str(base/'home'),PI_CODING_AGENT_DIR=str(agent))
        store=Store();store.data['agent']['agentDir']=str(agent);store.data['workspace']=str(workspace);store.save()
        app,engine,b=create_application();window=engine.rootObjects()[0];window.resize(1280,900)
        warnings=[];engine.warnings.connect(lambda errors:warnings.extend(e.toString() for e in errors))
        def find(name):
            stack=[window.contentItem()]
            while stack:
                item=stack.pop()
                if item.objectName()==name:return item
                stack.extend(item.childItems())
        def js(obj,source):
            e=QQmlExpression(engine.rootContext(),obj,source);v=e.evaluate()
            assert not e.hasError(),e.error().toString()
            v=v[0] if isinstance(v,tuple) else v
            return v.toVariant() if hasattr(v,'toVariant') else v
        prompt=find('promptInput');menu=find('compactCommandMenu');composer=find('composer')
        def query(text):
            prompt.setProperty('text',text);prompt.forceActiveFocus();QTest.qWait(30)
            assert menu.isVisible(),text
            return js(menu,'matches.map(e=>e.title)')
        try:
            wait(lambda:prompt.isEnabled(),'Composer disabled')
            assert '/compact' in query('/')
            assert abs(menu.width()-find('composer').width())<1,'Menu must keep the compact composer width'
            assert menu.height()>=180,'Menu kept the initial minimum height after composer layout'
            assert js(menu,'rowHeight')<40,'Menu rows lost the compact layout'
            wait(lambda:'文档整理' in query('/w'),'Native Skill catalog did not arrive')
            # A delayed catalog update must preserve an already scrolled menu,
            # including when newly discovered items are inserted above it.
            commands=b.slashCommands
            native=[dict(id=row['id'], name=row['title'], path=row['path'], attached=True,
                description=row['description'], descriptions=row.get('descriptions',{}), scope=row['scopeKey']) for row in commands._skills]
            prompt.setProperty('text','');QTest.qWait(20)
            commands._loaded_at=0
            with patch.object(b,'_job') as jobs:
                query('/')
                assert jobs.call_count==1
                listing=find('compactCommandList')
                js(menu,'selectedIndex=matches.length-4; revealSelection()');QTest.qWait(20)
                before=listing.property('contentY')
                selected=js(menu,'matches[selectedIndex].id')
                top=js(listing,'indexAt(1,contentY+1)')
                anchor=js(menu,f'rowKey(rows[{top}])')
                offset=js(listing,'itemAtIndex(indexAt(1,contentY+1)).y-contentY')
                extra=dict(native[0], id='added-guide', name='added-guide', path=str(agent/'skills/added-guide/SKILL.md'))
                commands.finished('slash-skills',{'ok':True,'value':{'skills':[extra]+native}})
                QTest.qWait(30)
                assert js(menu,'matches[selectedIndex].id')==selected,(selected,js(menu,'matches[selectedIndex].id'),js(menu,'selectedIndex'),before,listing.property('contentY'))
                top=js(listing,'indexAt(1,contentY+1)')
                assert js(menu,f'rowKey(rows[{top}])')==anchor
                assert abs(js(listing,'itemAtIndex(indexAt(1,contentY+1)).y-contentY')-offset)<1
                after=listing.property('contentY')
                commands.refresh();b.desktopPlugins.changed.emit();QTest.qWait(20)
                assert jobs.call_count==1 and abs(listing.property('contentY')-after)<1
            query('/guide-03');assert listing.property('contentY')<1
            for prefix in ('w','wd','wendang','文档'):
                assert '文档整理' in query('/'+prefix),prefix
            for prefix in ('s','sk','ski','skil','skill','skills'):
                titles=query('/'+prefix)
                assert '文档整理' in titles and 'Skill 管理' in titles,(prefix,titles)
            assert query('/skill wd')==['文档整理']
            assert query('/s w')==['文档整理']
            query('/wd');QTest.keyClick(window,Qt.Key_Tab)
            wait(lambda:prompt.property('text')=='','Skill selection did not clear query')
            assert len(b._view.attachments)==1 and Path(b._view.attachments[0]['path']).resolve()==folder.resolve(),b._view.attachments
            assert b._view.attachments[0]['kind']=='folder'
            assert not b._view.messages and not b._view.skill_modes
            query('/w');QTest.keyClick(window,Qt.Key_Escape);wait(lambda:not menu.isVisible(),'Escape did not dismiss menu')
            prompt.setProperty('text','/wd');QTest.qWait(30);assert menu.isVisible()
            query('/zzzz');QTest.keyClick(window,Qt.Key_Return)
            assert prompt.property('text')=='/zzzz' and not b._view.messages
            query('/re');QTest.keyClick(window,Qt.Key_Return)
            assert prompt.property('text').strip()=='/reload' and not menu.isVisible()
            with patch.object(b,'_command_pi',return_value=True) as command:
                QTest.keyClick(window,Qt.Key_Return);command.assert_called_once_with('reload')
            b.desktopPlugins.setSessionEnabled('skill-manager',False)
            titles=query('/s');assert '文档整理' not in titles and 'Skill 管理' not in titles
            b.desktopPlugins.setSessionEnabled('skill-manager',True)
            # No hidden aliases/description-only matches.
            assert query('/Visible')==[]
            query('/')
            Path('build/ci-smoke').mkdir(parents=True,exist_ok=True)
            window.grabWindow().save('build/ci-smoke/slash-commands.png')
            assert not [w for w in warnings if 'CompactCommandMenu' in w or 'Composer.qml' in w],warnings
            print('SLASH_COMMANDS_UI_OK: /, shared Skill prefixes, visible-name pinyin, attachment without send, Escape/edit, unknown slash, native reload, disabled Widget fence')
        finally:
            shiboken6.delete(engine);b.close();app.processEvents()
if __name__=='__main__':main()
