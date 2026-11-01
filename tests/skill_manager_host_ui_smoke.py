"""Actual App/QML, native folder discovery and scoped clipboard/filesystem jobs.

Disposable profile only. No provider, model request or public server is used.
"""
from __future__ import annotations
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
os.environ.setdefault('QT_QUICK_CONTROLS_STYLE','Basic')
os.environ['UMEKO_LANGUAGE']='en'
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem
from PySide6.QtQml import QQmlExpression
from PySide6.QtTest import QTest
import shiboken6
from app.storage import Store
from main import create_application

def wait_for(predicate,message,seconds=45):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        QTest.qWait(15);time.sleep(.003)
        if predicate():return
    raise AssertionError(message() if callable(message) else message)

def markdown(name):return f'---\nname: {name}\ndescription: Local folder fixture.\n---\n\n# Skill guide\n\nPreserve this content.\n'
def variant(value):return value.toVariant() if hasattr(value,'toVariant') else value

def main():
    with tempfile.TemporaryDirectory(prefix='skill-folder-ui-') as temporary:
        base=Path(temporary).resolve();profile=base/'profile';agent=base/'agent';workspace=base/'workspace'
        for folder in (profile,agent,workspace,base/'home'):folder.mkdir()
        os.environ.update(UMEKO_DATA_DIR=str(profile),PI_CODING_AGENT_DIR=str(agent),HOME=str(base/'home'),USERPROFILE=str(base/'home'))
        store=Store(profile);store.data['workspace']=str(workspace);store.data['agent']['agentDir']=str(agent);store.data['character']='komari';store.save()
        global_folder=agent/'skills/global-guide';global_folder.mkdir(parents=True)
        (global_folder/'SKILL.md').write_text(markdown('global-guide'),encoding='utf-8')
        (global_folder/'references').mkdir();(global_folder/'references/note.txt').write_text('Packaged reference.',encoding='utf-8')
        project_folder=workspace/'.pi/skills/project-guide';project_folder.mkdir(parents=True)
        (project_folder/'SKILL.md').write_text(markdown('project-guide'),encoding='utf-8')
        archive=base/'import.skill'
        with zipfile.ZipFile(archive,'w') as stream:
            stream.writestr('zip-guide/SKILL.md',markdown('zip-guide'))
            stream.writestr('zip-guide/reference.txt','ZIP reference.')
        app,engine,backend=create_application();app.setQuitOnLastWindowClosed(False)
        manager=backend.desktopPlugins;host=manager.hostServices;window=engine.rootObjects()[0];window.resize(1180,850)
        warnings=[];replies={}
        engine.warnings.connect(lambda errors:warnings.extend(e.toString() for e in errors))
        manager.hostResponse.connect(lambda widget,identifier,value:replies.__setitem__(identifier,value))
        def find(name):
            stack=[window.contentItem()]
            while stack:
                item=stack.pop()
                if item.objectName()==name:return item
                stack.extend(item.childItems())
            return None
        def idle():
            widget=find('skillManagerWidget')
            return widget is not None and not widget.property('working') and not host.panelApproval and not backend.piManagement.busy
        def request(operation,args):
            wait_for(idle,'Widget remained busy before '+operation)
            identifier=manager.requestHost(operation,json.dumps(args));assert identifier
            wait_for(lambda:identifier in replies,'No reply: '+operation)
            assert replies[identifier]['ok'],replies[identifier]
            return replies[identifier]
        def result(reply):
            job=reply['jobId'];wait_for(lambda:host._skills.jobs[job]['status']!='running','Native Skill job did not finish')
            identifier=manager.requestHost('skills.job',json.dumps({'id':job}))
            wait_for(lambda:identifier in replies,'Job reply missing')
            row=replies[identifier]['jobs'][0];assert row['status']=='completed',row
            return row['result']
        def js(source):
            expression=QQmlExpression(engine.rootContext(),find('skillManagerWidget'),source);value=expression.evaluate()
            assert not expression.hasError(),expression.error().toString()
            return value[0] if isinstance(value,tuple) else value
        def confirm(operation):
            wait_for(lambda:bool(host.panelApproval),'Missing panel confirmation: '+operation)
            assert host.panelApproval['operation']==operation,host.panelApproval
            assert host.pendingApproval=={} and find('widgetPanelConfirmation').isVisible()
            find('widgetPanelAllow').clicked.emit();wait_for(idle,'Confirmed operation did not finish: '+operation)
        try:
            assert not backend.store.data['providers'] and backend.public_server is None
            assert manager.openPage('skill-manager')
            wait_for(lambda:idle() and bool(variant(find('skillManagerWidget').property('roots')).get('global')),
                     lambda:'Widget did not initialize: '+repr(manager.page))
            widget=find('skillManagerWidget')
            actual=variant(widget.property('skills'))
            assert {(r['name'],r['scope']) for r in actual}=={('global-guide','global'),('project-guide','project')},{'rows':actual,'notice':widget.property('notice'),'roots':variant(widget.property('roots')),'jobs':[(r['operation'],r['status'],str(r['result'])[:300]) for r in host._skills.jobs.values()] if host._skills else []}
            assert find('skillManagerScope_global') and find('skillManagerScope_project')
            global_row=next(row for row in actual if row['scope']=='global')

            # Attach a whole global folder, preserving the existing draft and
            # without sending, changing availability or writing Pi settings.
            backend.setDraft('Existing draft')
            before=(agent/'settings.json').read_bytes() if (agent/'settings.json').exists() else None
            result(request('skills.insert',{'id':global_row['id']}))
            assert backend._view.draft=='Existing draft'
            assert any(row['path']==str(global_folder) and row['kind']=='folder' for row in backend._view.attachments)
            assert not backend._view.skill_modes
            assert ((agent/'settings.json').read_bytes() if (agent/'settings.json').exists() else None)==before

            # Paste directly into the selected workspace, without navigating,
            # confirming or treating the global source as a local conflict.
            result(request('skills.copy',{'id':global_row['id'],'kind':'folder'}))
            assert QGuiApplication.clipboard().mimeData().urls()[0].toLocalFile()==str(global_folder)
            widget.setProperty('selectedScope','project');js('action("paste")')
            wait_for(idle,'Clipboard import did not finish')
            assert widget.property('route')=='main' and not host.panelApproval
            assert not widget.property('importFailure') and not widget.property('notice'),widget.property('importFailure')
            target=workspace/'.pi/skills/global-guide'
            assert (target/'references/note.txt').read_text()=='Packaged reference.'
            assert (target/'SKILL.md').read_text()==markdown('global-guide')
            # A repeated paste fails in-place and never modifies the original.
            original=(target/'SKILL.md').read_bytes();js('action("paste")')
            wait_for(idle,'Repeated paste did not settle')
            assert widget.property('route')=='main' and widget.property('importFailure')
            assert find('skillManagerImportError').isVisible() and not host.panelApproval
            assert (target/'SKILL.md').read_bytes()==original
            find('skillManagerImportErrorClose').clicked.emit()

            # Renaming changes only the directory. Denied deletion keeps it.
            actual=variant(widget.property('skills'));row=next(row for row in actual if row['name']=='global-guide' and row['scope']=='project')
            widget.setProperty('contextRow',row);js('action("rename")')
            find('skillManagerRenameName').setProperty('text','renamed-guide');find('skillManagerRenameSave').clicked.emit()
            wait_for(lambda:bool(host.panelApproval),'Rename confirmation missing');assert target.exists()
            confirm('skills.rename')
            renamed=target.with_name('renamed-guide');assert (renamed/'SKILL.md').read_text()==markdown('global-guide')
            row=next(row for row in variant(widget.property('skills')) if row['name']=='renamed-guide')
            widget.setProperty('contextRow',row);js('action("delete")');wait_for(lambda:bool(host.panelApproval),'Delete confirmation missing')
            find('widgetPanelDeny').clicked.emit();wait_for(idle,'Denied deletion did not settle');assert renamed.exists()
            js('action("delete")');confirm('skills.delete');assert not renamed.exists()

            # ZIP drop imports into the pointer's scope, regardless of the
            # previously selected workspace. Native archive checks still run.
            widget.setProperty('selectedScope','project')
            assert js('dropLocalUrls('+json.dumps([QUrl.fromLocalFile(str(archive)).toString()])+',"global")')
            wait_for(idle,'ZIP import did not finish')
            assert widget.property('route')=='main' and not widget.property('importFailure')
            assert not host.panelApproval
            assert (agent/'skills/zip-guide/reference.txt').read_text()=='ZIP reference.'
            assert not (workspace/'.pi/skills/zip-guide').exists()

            # A bad archive reports an in-pane failure without changing route.
            invalid=base/'broken.zip';invalid.write_bytes(b'Not a zip')
            assert js('dropLocalUrls('+json.dumps([QUrl.fromLocalFile(str(invalid)).toString()])+',"project")')
            wait_for(idle,'Broken ZIP import did not settle')
            assert widget.property('importFailure') and widget.property('route')=='main'
            find('skillManagerImportErrorClose').clicked.emit()

            # Long descriptions exercise the real host byte budget and QML's
            # final-page cursor handling, with no partial catalog published.
            for index in range(210):
                name=f'paged-{index:03d}';folder=agent/'skills'/name;folder.mkdir()
                (folder/'SKILL.md').write_text(f'---\nname: {name}\ndescription: '+'技能说明'*256+'\n---\nLocal fixture.\n',encoding='utf-8')
            find('skillManagerRefresh').clicked.emit();wait_for(lambda:bool(widget.property('job')),'Large browse did not begin')
            wait_for(idle,'Large native folder catalog failed to page')
            actual=variant(widget.property('skills'));assert len(actual)==213,len(actual)
            assert len({row['id'] for row in actual})==213
            assert len(json.dumps(actual,ensure_ascii=False).encode())>262144
            assert not [warning for warning in warnings if 'skill-manager' in warning or 'DesktopPluginSurface' in warning],warnings
            print('SKILL_FOLDER_HOST_UI_OK: configured global/workspace roots, whole-folder attachment, direct clipboard paste and ZIP drop, no navigation or import confirmations, failure-only pane popup and conflict preservation, directory rename/delete confirmations, 213-record UTF-8 paging; model calls=0')
        finally:
            # Offscreen Qt owns the Python-created file MIME object. Release it
            # while QApplication is alive, before its platform is destroyed.
            QGuiApplication.clipboard().clear()
            backend.close();shiboken6.delete(engine);app.processEvents()

if __name__=='__main__':main()
