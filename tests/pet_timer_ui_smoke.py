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
        QTest.qWait(150);assert js(prompt,'width')==360;assert js(prompt,'contentItem.Window.window').grabWindow().save(str(out/name))
    promptshot('01-no-owner.png')
    # Existing ordinary persisted-session fixtures; no model or session creation API is called.
    for key,title in [('ordinary-a','通用工作会话'),('ordinary-b','项目构建检查')]:
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
    choice=js(picker,'itemAtIndex(1)')
    point=js(choice,'mapToItem(null,width/2,height/2)')
    QTest.mouseClick(js(prompt,'contentItem.Window.window'),Qt.LeftButton,Qt.NoModifier,point.toPoint())
    wait(lambda:t.owner=='ordinary-b','Actual owner choice click failed')
    assert composer.property('desiredOpen'),'Clicking question card dismissed capsule'
    assert t.owner=='ordinary-b'
    assert t.state['question']['key']=='name'
    promptshot('02-missing-fields.png')
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
    b.store.data['projects']=[{'id':'demo-project','name':'构建项目','path':str(project_dir)}]
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
    assert js(field,'leftPadding')>js(target,'x+width'),'Target overlaps editable text'
    js(target,'clicked()')
    wait(lambda:project_menu.property('opened'),'Inline target no longer opens the project picker')
    QTest.keyClick(js(project_menu,'contentItem.Window.window'),Qt.Key_Escape)
    wait(lambda:not project_menu.property('visible'),'Inline target picker cannot be dismissed')
    field.setProperty('focus',True)
    QTest.qWait(150)
    assert native.grabWindow().save(str(out/'07-project-capsule.png'))
    from app.integration import Completion
    import time
    class Fixture:
        ready=True
        def complete(self,model,messages,tools,max_tokens):
            time.sleep(.8)
            return Completion('项目后台执行完成。')
    b.store.data.update(selectedProvider='internal',selectedModel='project-fixture',providers=[{'id':'internal','name':'Local fixture','api':'internal','baseUrl':'','key':'','models':[{'upstream':'project-fixture','alias':'project-fixture'}]}])
    b.adapter=b.gateway.adapter=Fixture();b._command_pi=native_command
    project_record.model='project-fixture';project_record.provider='internal'
    project_record.draft='项目原有草稿';project_record.attachments=[{'id':'keep','kind':'file','path':str(project_dir/'not-sent.txt')}]
    QTest.keyClick(native,Qt.Key_Return)
    wait(lambda:not composer.property('visible'),'Project send did not close capsule')
    js(composer,'submit()') # hidden input must not submit again
    wait(lambda:project_record.ready and project_record.phase=='running','Native project process not running: '+project.error)
    assert b._view is visible and visible.draft=='主窗口草稿不变'
    wait(lambda:project.submission.get('acknowledged'),'First native receipt missing')
    QTest.mouseDClick(window,Qt.LeftButton,Qt.NoModifier,window.mask().boundingRect().center())
    wait(lambda:composer.property('opened'),'Reopen project capsule failed')
    field.setProperty('text','第二条后台排队指令');js(field,'textEdited()')
    QTest.keyClick(js(composer,'contentItem.Window.window'),Qt.Key_Return)
    wait(lambda:any(r.get('text')=='第二条后台排队指令' for r in project_record.queue),'Native follow-up queue missing: '+project.error+' captured='+str(project.captured)+' actual='+str((project_record.id,project_record.workspace,project_record.file)))
    assert b._view is visible
    wait(lambda:not project_record.busy and sum(r.get('role')=='user' for r in project_record.messages)>=2,'Project native turns did not finish: '+project.error)
    assert project_record.draft=='项目原有草稿' and len(project_record.attachments)==1
    assert b._view is visible and visible.draft=='主窗口草稿不变'
    assert field.property('text')==''
    assert pet.assistantStatus['id']==original_binding
    transcript=Path(project_record.file).read_text()
    assert '帮我检查构建' in transcript and '第二条后台排队指令' in transcript
    assert 'not-sent.txt' not in transcript,'Existing target attachment was accidentally sent'
    assert project.submission.get('acknowledged')
    project.close()
    relevant=[r for r in warnings if any(s in r for s in ('PetTimerPrompt','DesktopPetWindow','ReferenceError','TypeError'))]
    assert not relevant,relevant
    (out/'result.json').write_text(json.dumps({'noImplicitOwner':True,'capsuleDraftPreserved':True,'requiredFields':True,'explicitConfirmation':True,'realWidgetCreatedExactlyOnce':True,'mainDraftAndBindingUnchanged':True,'oldDraftNotice':True,'nativeProjectPromptAndFollowUp':True,'projectDraftAndAttachmentsPreserved':True,'warnings':relevant},ensure_ascii=False,indent=2))
    print('Pet timer actual UI passed:',out)
finally:
    b.close()
    import shiboken6
    shiboken6.delete(engine);app.processEvents();tmp.cleanup()
