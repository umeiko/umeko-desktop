"""Actual offscreen capsule -> inline questions -> existing timer worker (local session fixtures)."""
import json, os, sys, tempfile
from pathlib import Path
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
tmp=tempfile.TemporaryDirectory(prefix='umeko-pet-timer-ui-')
os.environ.update(UMEKO_DATA_DIR=tmp.name+'/profile',PI_CODING_AGENT_DIR=tmp.name+'/agent',QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',UMEKO_LANGUAGE='zh')
from PySide6.QtCore import QObject, Qt
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QSystemTrayIcon
QSystemTrayIcon.show=lambda *args:None
from main import create_application
from app.pi_sessions import SessionState
app,engine,b=create_application();main=engine.rootObjects()[0];m=b.desktopPlugins;pet=m.pet
# Native project payload reads the app setting, not only the environment variable.
b.store.data.setdefault('agent',{})['agentDir']=tmp.name+'/agent'
out=ROOT/'build/pet-timer-ui';out.mkdir(parents=True,exist_ok=True)
warnings=[];engine.warnings.connect(lambda rows:warnings.extend(r.toString() for r in rows))
def wait(fn,message):
    for _ in range(500):
        QTest.qWait(20)
        if fn():return
    raise AssertionError(message+'\n'+'\n'.join(warnings))
def js(obj,code):
    q=QQmlExpression(QQmlEngine.contextForObject(obj),obj,code);r=q.evaluate()[0]
    assert not q.hasError(),q.error().toString()
    return r

def shot(name):
    QTest.qWait(150);assert main.grabWindow().save(str(out/name))
try:
    pet.ui('show',{});wait(lambda:pet.assistantStatus.get('bound'),'No binding')
    window=main.findChild(QObject,'desktopPetWindow');wait(lambda:window.mask().boundingRect().height()>50,'No silhouette')
    composer=window.findChild(QObject,'desktopPetTaskComposer');field=composer.findChild(QObject,'desktopPetTaskInput')
    prompt=window.findChild(QObject,'petTimerPrompt');assert prompt
    assert main.findChild(QObject,'petTimerDialog') is None
    restores=[];pet.restoreRequested.connect(lambda:restores.append(True))
    native_command=b._command_pi;b._command_pi=Mock(return_value=True)
    visible=b._view;visible.draft='主窗口草稿不变';original_binding=pet.assistantStatus['id']
    def command(text):
        QTest.mouseDClick(window,Qt.LeftButton,Qt.NoModifier,window.mask().boundingRect().center())
        wait(lambda:composer.property('opened'),'Capsule did not open')
        field.setProperty('text',text)
        native=js(composer,'contentItem.Window.window')
        QTest.keyClick(native,Qt.Key_Return)
        wait(lambda:pet.taskSchedule.opened,'Timer form did not open')
        assert composer.property('visible'),'Capsule unexpectedly closed'
        assert composer.property('timerDraft')==text,'Command body was lost'
        assert not restores,'Timer navigated to Desktop'
        assert b._view is visible and visible.draft=='主窗口草稿不变'
        b._command_pi.assert_not_called()
    command('/定时任务 帮我检查构建')
    t=pet.taskSchedule
    assert not t.owner and not t.owners
    assert t.state['question']['key']=='owner'
    def promptshot(name):
        QTest.qWait(150)
        assert prompt.width() == composer.property('width'), 'Question card must align with the capsule'
        assert js(prompt, 'contentItem.Window.window').grabWindow().save(str(out/name))
    promptshot('01-no-owner.png')
    # Existing ordinary persisted-session fixtures; no model or session creation API is called.
    for key,title in [('ordinary-a','通用会话 [演示 / Demo]'),('ordinary-b','Build check [演示 / Demo]')]:
        file=Path(tmp.name)/(key+'.jsonl')
        file.write_text(json.dumps({'type':'session','version':3,'id':key,'timestamp':'2026-11-15T00:00:00Z','cwd':str(b.store.directory/'workspace')})+'\n')
        r=SessionState(id=key,file=str(file),title=title,workspace='')
        b._pool.touch(r);b._sessions.append({'id':key,'file':str(file),'title':title,'workspace':''})
    (b.store.directory/'workspace').mkdir(exist_ok=True)
    t.refresh()
    def answer(text):
        field.setProperty('text',text)
        js(composer,'submit()')
        assert not t.error,t.error
        assert not field.property('text')
        assert not restores
    picker=prompt.findChild(QObject,'petTimerChoices')
    wait(lambda:js(picker,'count')==2,'Owner choices missing')
    wait(lambda:js(picker,'itemAtIndex(1)') is not None, 'Owner delegate not materialized')
    QTest.qWait(100)
    choice=js(picker,'itemAtIndex(1)')
    point=js(choice,'mapToItem(null,width/2,height/2)')
    QTest.mouseClick(js(prompt,'contentItem.Window.window'),Qt.LeftButton,Qt.NoModifier,point.toPoint())
    wait(lambda:t.owner=='ordinary-b','Actual owner choice click failed')
    assert composer.property('desiredOpen'),'Clicking question card dismissed capsule'
    assert t.owner=='ordinary-b'
    assert t.state['question']['key']=='name'
    prompt.requestActivate(); QTest.qWait(350)
    assert composer.property('desiredOpen'), 'Question-window interaction closed capsule'
    edits=prompt.findChild(QObject,'petTimerEdits')
    js(edits,'open()'); QTest.qWait(350)
    assert composer.property('desiredOpen'), 'Edit-menu interaction closed capsule'
    js(edits,'close()'); js(composer,'focusTimerInput()'); QTest.qWait(350)
    assert field.property('activeFocus') and composer.property('desiredOpen')
    assert not js(prompt,'placement.blocked')
    assert js(prompt,'y + height <= transientParent.y || y >= transientParent.y + transientParent.height')
    promptshot('02-missing-fields.png')
    from chat_input_keys import check_newline_and_ime
    check_newline_and_ime(js(composer,'contentItem.Window.window'), field)
    assert t.opened and t.state['question']['key'] == 'name'
    field.setProperty('text','尚未发出的任务名');js(field,'textEdited()')
    QTest.keyClick(js(composer,'contentItem.Window.window'),Qt.Key_Escape)
    wait(lambda:not t.opened,'Escape should dismiss wizard and retain draft')
    assert composer.property('desiredOpen')
    js(composer,'close()')
    command('/定时任务 检查构建');t.answer('ordinary-b')
    assert t.state['answer']=='尚未发出的任务名'
    field.setProperty('text',t.state['answer'])
    answer('构建检查')
    assert t.state['question']['key']=='target','Already supplied instruction should be skipped'
    answer('main');answer('once');answer('2035-01-02');answer('09:30')
    assert t.preview,t.error
    t.editStep('zone');answer('Asia/Shanghai')
    assert not t.request and not t.draft().get('outcome')
    promptshot('03-confirm.png')
    responses={};m.response.connect(lambda key,value:responses.__setitem__(key,value))
    confirm=prompt.findChild(QObject,'petTimerConfirm')
    QTest.mouseClick(js(prompt,'contentItem.Window.window'),Qt.LeftButton,Qt.NoModifier,js(confirm,'mapToItem(null,width/2,height/2)').toPoint())
    t.confirm() # repeat while pending must not duplicate
    wait(lambda:not t.request,'Worker save timed out')
    assert t.draft()['outcome'].startswith('已创建'),(t.error,t.state)
    source=m.bridge.snapshot(b._pool.find('ordinary-b'))
    request=m.call_for('scheduled-tasks','list','{}',session=source)
    wait(lambda:request in responses,'List timed out')
    result=responses[request];assert result['ok'],result
    assert len(result['result']['tasks'])==1,result
    assert result['result']['tasks'][0]['message']=='帮我检查构建'
    assert pet.assistantStatus['id']==original_binding
    assert b._view is visible and visible.draft=='主窗口草稿不变'
    promptshot('04-created.png')
    t.close();js(composer,'close()');command('/定时任务 新输入仍保留')
    t.selectOwner('ordinary-b');assert '新输入未替换' in t.notice
    assert t.draft()['message']=='帮我检查构建'
    promptshot('05-restored-draft.png')
    t.close();js(composer,'close()')
    project_dir=Path(tmp.name)/'demo-project';project_dir.mkdir()
    project_record=b._pool.find('ordinary-b');project_record.workspace=str(project_dir)
    header=json.loads(Path(project_record.file).read_text());header['cwd']=str(project_dir)
    Path(project_record.file).write_text(json.dumps(header)+'\n')
    next(r for r in b._sessions if r['id']=='ordinary-b')['workspace']=str(project_dir)
    b.store.data['projects']=[{'id':'demo-project','name':'构建项目 [演示 / Demo]','path':str(project_dir)}]
    QTest.mouseDClick(window,Qt.LeftButton,Qt.NoModifier,window.mask().boundingRect().center())
    wait(lambda:composer.property('opened'),'Project capsule did not open')
    field.setProperty('text','/项目')
    QTest.keyClick(js(composer,'contentItem.Window.window'),Qt.Key_Return)
    project=pet.projectEntry
    project_menu=window.findChild(QObject,'desktopPetProjectMenu')
    wait(lambda:project_menu.property('opened'),'Compact project menu did not open')
    assert composer.property('desiredOpen') and b._view is visible
    assert main.findChild(QObject,'petProjectDialog') is None,'Large project dialog remains'
    native=js(composer,'contentItem.Window.window')
    QTest.qWait(150)
    assert js(project_menu,'contentItem.Window.window').grabWindow().save(str(out/'06-project-menu.png'))
    QTest.keyClick(js(project_menu,'contentItem.Window.window'),Qt.Key_Escape)
    wait(lambda:not project_menu.property('visible'),'Escape did not dismiss menu')
    assert composer.property('desiredOpen') and field.property('text')=='/项目'
    js(composer,"projectChoices('/项目')")
    wait(lambda:project_menu.property('opened'),'Menu did not reopen')
    action=js(project_menu,"Array.from({length: count}, (_, i)=>itemAt(i)).find(item=>item.objectName==='desktopPetProject_ordinary-b')")
    assert action
    project_menu.setProperty('currentIndex',0)
    QTest.keyClick(js(project_menu,'contentItem.Window.window'),Qt.Key_Down)
    QTest.keyClick(js(project_menu,'contentItem.Window.window'),Qt.Key_Return)
    wait(lambda:not project_menu.property('visible') and field.property('activeFocus'),'Menu selection did not restore input focus')
    QTest.qWait(350)
    assert composer.property('desiredOpen') and js(composer,'contentItem.Window.window.active')
    assert project.selected=='ordinary-b' and composer.property('projectMode')
    field.setProperty('text','帮我检查构建');js(field,'textEdited()')
    assert project.body=='帮我检查构建'
    js(composer,"projectChoices('/项目')")
    wait(lambda:project_menu.property('opened'),'Target button menu failed')
    js(composer,'useDefaultTarget()')
    assert not composer.property('projectMode') and field.property('text')=='/项目'
    assert not project.selected and project.drafts['ordinary-b']=='帮我检查构建'
    field.setProperty('text','/项目 新正文');js(field,'textEdited()')
    js(composer,'submit()');wait(lambda:project_menu.property('opened'),'Conflict menu did not open')
    js(action,'triggered()')
    assert not composer.property('projectMode') and not project.selected
    assert field.property('text')=='/项目 新正文' and project.drafts['ordinary-b']=='帮我检查构建'
    assert '未覆盖' in composer.property('error')
    js(project_menu,'close()')
    field.setProperty('text','助手独立草稿');js(field,'textEdited()')
    js(composer,"projectChoices('/项目')")
    wait(lambda:project_menu.property('opened'),'Switch-back menu failed')
    js(action,'triggered()')
    wait(lambda:not project_menu.property('visible'),'Switch-back menu remains')
    assert field.property('text')=='帮我检查构建' and composer.property('globalDraft')=='助手独立草稿'
    field.setProperty('text','/项目 保留正文');js(field,'textEdited()')
    js(composer,'submit()');wait(lambda:project_menu.property('opened'),'Same-target command menu failed')
    js(action,'triggered()');wait(lambda:not project_menu.property('visible'),'Same-target menu remains')
    assert field.property('text')=='保留正文'
    field.setProperty('text','帮我检查构建');js(field,'textEdited()')
    target=composer.findChild(QObject,'desktopPetProjectTarget')
    assert target.property('text')==project.state['label']
    assert js(target,'background.color.a')==0,'Project target must not use a native grey button background'
    assert js(target,'width')<=110
    assert js(field, 'x + leftPadding') > js(target, 'x + width'),'Target overlaps editable text'
    js(target,'clicked()')
    wait(lambda:project_menu.property('opened'),'Inline target no longer opens the project picker')
    QTest.keyClick(js(project_menu,'contentItem.Window.window'),Qt.Key_Escape)
    wait(lambda:not project_menu.property('visible'),'Inline target picker cannot be dismissed')
    field.setProperty('focus',True)
    QTest.qWait(150)
    assert native.grabWindow().save(str(out/'07-project-capsule.png'))
    from chat_input_keys import check_newline_and_ime
    # Real Qt key events; native model bridge deliberately not exercised here.
    check_newline_and_ime(native, field)
    field.setProperty('text', '项目第一行\n项目第二行'); js(field, 'textEdited()')
    assert project.body == '项目第一行\n项目第二行'
    QTest.qWait(150)
    assert native.grabWindow().save(str(out/'10-merged-project-multiline.png'))
    assert composer.property('height') > 40
    b._command_pi.assert_not_called()
    # Explicitly mocked project dispatch, preserving real routing and session identity.
    QTest.keyClick(native, Qt.Key_Return)
    wait(lambda:not composer.property('visible'), 'Mock project send did not close')
    assert b._command_pi.call_args.kwargs['record'] is project_record
    assert b._command_pi.call_args.kwargs['text'] == '项目第一行\n项目第二行'
    assert b._view is visible and visible.draft == '主窗口草稿不变'
    relevant=[r for r in warnings if any(s in r for s in ('PetTimerPrompt','DesktopPetWindow','ReferenceError','TypeError'))]
    assert not relevant,relevant
    print('Merged Qt-only checks passed: timer confirmation/draft/Escape, project routing, multiline and synthetic IME; native bridge NOT tested')
finally:
    b.close()
    import shiboken6
    shiboken6.delete(engine);app.processEvents();tmp.cleanup()
