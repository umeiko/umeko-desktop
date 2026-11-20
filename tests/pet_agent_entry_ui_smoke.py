"""Synthetic real Qt/Pi explicit target handoff; no external model or credentials."""
import os,sys,tempfile,json,copy
from threading import Event
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
temporary=tempfile.TemporaryDirectory(prefix='pet-agent-entry-');base=Path(temporary.name)
language=os.environ.get('UMEKO_PET_ENTRY_LANGUAGE','zh')
os.environ.update(UMEKO_DATA_DIR=str(base/'profile'),PI_CODING_AGENT_DIR=str(base/'agent'),QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',UMEKO_LANGUAGE=language)
from PySide6.QtCore import QObject,QPointF,Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtWidgets import QSystemTrayIcon
QSystemTrayIcon.show=lambda *a:None
from app.storage import Store
store=Store();store.data['agent']['agentDir']=str(base/'agent');store.save()
from main import create_application
app,engine,b=create_application();main=engine.rootObjects()[0];warnings=[]
engine.warnings.connect(lambda errors:warnings.extend(e.toString() for e in errors))
m=b.desktopPlugins;pet=m.pet;entry=pet.agentEntry;bus=m.global_agents
out=ROOT/'build/pet-agent-entry'/language;out.mkdir(parents=True,exist_ok=True)
def wait(check,label):
    for _ in range(1200):
        QTest.qWait(20)
        if check():return
    raise AssertionError(label+'\n'+'\n'.join(warnings))
def find(window,name):
    stack=[window.contentItem()]
    while stack:
        i=stack.pop()
        if i.objectName()==name:return i
        stack.extend(i.childItems())
    raise AssertionError(name)
def click(window,name):
    i=find(window,name);assert i.isEnabled(),name
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,i.mapToScene(i.boundingRect().center()).toPoint())
    QTest.qWait(30)
first_release = Event()
try:
    from app.integration import Completion
    class Fixture:
        ready=True
        block_next = False
        entered = Event()
        def complete(self,model,messages,tools,max_tokens):
            if self.block_next:
                self.block_next = False
                self.entered.set()
                assert first_release.wait(12), 'Fixture run gate timed out'
            return Completion('目标独立回执：检查完成。')
    b.store.data.update(selectedProvider='internal',selectedModel='pet-fixture',providers=[{'id':'internal','name':'Local fixture','api':'internal','baseUrl':'','key':'','models':[{'upstream':'pet-fixture','alias':'pet-fixture'}]}])
    b.adapter=b.gateway.adapter=Fixture()
    pet.ui('show',{});wait(lambda:main.findChild(QObject,'desktopPetWindow') is not None,'pet load')
    pet_window=main.findChild(QObject,'desktopPetWindow')
    default_id=pet.assistantStatus['id']
    # Fixture creation is explicit test setup, never done by entry selection.
    target_id=bus.handle('create',{'name':'合成测试：构建助手','model':'pet-fixture','character':'yanami','tools':[],'skills':[]})['id']
    record=bus.ensure(target_id)
    before=b._view;before.draft='主窗口保留草稿';before.attachments=[{'name':'synthetic.txt','path':str(base/'synthetic.txt')}]
    speech=[];pet.assistantSpeech.connect(speech.append)
    snapshot=copy.deepcopy(bus.agents);bridges=copy.deepcopy(bus.bridges)
    # Trigger the actual production menu action, not a new model/Widget API.
    action=pet_window.findChild(QObject,'desktopPetAgentEntry')
    assert action is not None
    action.triggered.emit()
    window=pet_window.findChild(QObject,'petAgentEntryWindow')
    wait(lambda:window is not None and window.isVisible(),'entry window')
    assert entry.state['selected']==''
    click(window,'petAgentTargets')
    QTest.keyClick(window,Qt.Key_Down)
    QTest.keyClick(window,Qt.Key_Return)
    wait(lambda:entry.state['selected']==target_id,'real target selector')
    field=find(window,'petAgentDraft');field.setProperty('text','检查本次构建，不连接任何新项目。')
    wait(lambda:entry.body=='检查本次构建，不连接任何新项目。','draft bind')
    assert bus.agents==snapshot and bus.bridges==bridges and not record.busy
    # Existing target composer draft must survive a separate pet handoff.
    assert entry.openDesktop()
    wait(lambda:bus.selected_conversation==target_id,'initial target page')
    QTest.qWait(900)
    target_input=find(main,'globalAgentInput')
    target_input.setProperty('text','目标原会话未发草稿')
    # Real multiline/IME events cannot submit. Escape cancels and retains text.
    window.requestActivate();QTest.qWait(60)
    click(window,'petAgentDraft')
    field.forceActiveFocus()
    QTest.keyClick(window,Qt.Key_End)
    QTest.keyClick(window,Qt.Key_Return)
    assert entry.body.endswith('\n') and not entry.preview and not record.busy
    field.setProperty('text','检查本次构建，不连接任何新项目。')
    app.sendEvent(field,QInputMethodEvent('候选',[]))
    assert field.property('inputMethodComposing')
    assert not find(window,'petAgentSubmit').isEnabled()
    app.sendEvent(field,QInputMethodEvent('',[]))
    QTest.keyClick(window,Qt.Key_Escape)
    assert not entry.opened and entry.body=='检查本次构建，不连接任何新项目。'
    entry.open();QTest.qWait(40)
    window.grabWindow().save(str(out/f'cancel-restored-{language}.png'))
    click(window,'petAgentSubmit');assert entry.preview
    assert window.grabWindow().save(str(out/f'preview-{language}.png'))
    # Busy-at-confirm race must not append or interrupt, and must keep text.
    record.busy=True
    with patch.object(b,'_command_pi') as dispatch:
        click(window,'petAgentSubmit');dispatch.assert_not_called()
    record.busy=False
    assert entry.body=='检查本次构建，不连接任何新项目。' and not entry.attempted
    assert window.grabWindow().save(str(out/f'busy-preserved-{language}.png'))
    record.approval={'id':'synthetic-approval'}
    click(window,'petAgentSubmit')
    assert not entry.preview and record.approval=={'id':'synthetic-approval'}
    window.grabWindow().save(str(out/f'approval-preserved-{language}.png'))
    record.approval=None
    removed=bus.agents.pop(target_id)
    click(window,'petAgentSubmit')
    assert not entry.preview and entry.body
    window.grabWindow().save(str(out/f'removed-preserved-{language}.png'))
    bus.agents[target_id]=removed
    click(window,'petAgentSubmit')
    with patch.object(b,'_command_pi',return_value=False) as dispatch:
        click(window,'petAgentSubmit')
        assert dispatch.call_count==1 and entry.body and entry.attempted
        entry.confirm();assert dispatch.call_count==1
    window.grabWindow().save(str(out/f'failed-preserved-{language}.png'))
    entry.select(target_id) # Deliberate new selection, not an automatic retry.
    click(window,'petAgentSubmit');assert entry.preview
    click(window,'petAgentSubmit');assert entry.attempted
    wait(lambda:not record.busy and any('目标独立回执' in x.get('text','') for x in record.messages),'native Pi reply')
    assert record.file and Path(record.file).is_file()
    assert not speech,'non-default response leaked into companion speech'
    assert b._view is before and before.draft=='主窗口保留草稿' and before.attachments[0]['name']=='synthetic.txt'
    assert pet.assistantStatus['id']==default_id and bus.bridges==bridges
    assert window.grabWindow().save(str(out/f'submitted-{language}.png'))
    click(window,'petAgentOpenDesktop')
    wait(lambda:bus.selected_conversation==target_id,'exact Global Agents conversation')
    assert m.page['id']=='global-agents'
    assert find(main,'globalAgentInput').property('text')=='目标原会话未发草稿'
    QTest.qWait(1200) # Let the existing drawer animation and message refresh settle.
    main.grabWindow().save(str(out/f'target-conversation-{language}.png'))
    # Existing native run sets bridge-issued identity; fixture holds its network
    # response until the exact queue receipt arrives, without an actual service.
    b.gateway.adapter.block_next = True
    assert b._command_pi('prompt', record=record, text='原任务保持运行')
    wait(lambda:b.gateway.adapter.entered.is_set() and record.pet_follow_up_run,
         'first request did not enter the native target run')
    entry.select(target_id)
    field.setProperty('text','原任务结束后追加检查')
    click(window,'petAgentSubmit')
    assert entry.preview and entry.state['followUp']
    assert window.grabWindow().save(str(out/f'follow-up-preview-{language}.png'))
    click(window,'petAgentSubmit')
    wait(lambda:'后续消息已进入' in entry.notice, 'exact queue receipt not obtained')
    assert record.busy and not record.cancelled and record.queue[0]['mode']=='followUp'
    assert window.grabWindow().save(str(out/f'follow-up-queued-{language}.png'))
    first_release.set()
    wait(lambda:not record.busy and any('原任务结束后追加检查' in row.get('text','')
        for row in record.messages), 'queued input did not reach its own target')
    assert before.draft=='主窗口保留草稿' and bus.bridges==bridges
    # Explicit close/reopen never replays the accepted task.
    entry.close();entry.open();assert entry.attempted and not entry.body
    relevant=[x for x in warnings if any(n in x for n in ('PetAgentEntry','ReferenceError','TypeError','binding loop'))]
    assert not relevant,relevant
    print('PET_AGENT_ENTRY_UI_OK: explicit preview, busy rejection, real Pi target reply and exact busy follow-up, original conversation navigation, companion/main isolation')
finally:
    first_release.set()
    b.close()
    import shiboken6
    shiboken6.delete(engine);app.processEvents();temporary.cleanup()
