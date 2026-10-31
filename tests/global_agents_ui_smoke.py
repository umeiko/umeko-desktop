"""Real Widget, native Pi sessions and round-trip delegation; no paid model calls."""
import os,sys,tempfile,json,re,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
work=tempfile.TemporaryDirectory(prefix='umeko-global-ui-');base=Path(work.name)
os.environ.update(UMEKO_DATA_DIR=str(base/'profile'),PI_CODING_AGENT_DIR=str(base/'agent'),UMEKO_LANGUAGE='zh',QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software')
from PySide6.QtCore import QObject,Qt
from PySide6.QtTest import QTest
from app.storage import Store
from app.integration import Completion
from app.pi_runtime import verify_runtime, RELEASE_NAME
verify_runtime(ROOT/"runtime/releases"/RELEASE_NAME, ROOT/"runtime/bridge.mjs")
store=Store(base/'profile');store.data.update(selectedProvider='internal',selectedModel='fixture',providers=[{'id':'internal','name':'Local fixture','api':'internal','baseUrl':'','key':'','models':[{'upstream':'fixture','alias':'fixture'}]}]);store.save()
from main import create_application
app,engine,b=create_application();window=engine.rootObjects()[0];warnings=[]
engine.warnings.connect(lambda values:warnings.extend(x.toString() for x in values))
class Fixture:
    ready=True
    calls=[]
    pause=threading.Event()
    pause_started=threading.Event()
    def complete(self,model,messages,tools,max_tokens):
        self.calls.append((messages,tools));last=messages[-1];content=last.get('content','');content=content if isinstance(content,str) else '\n'.join(block.get('text','') for block in content if block.get('type')=='text')
        if last['role']=='tool':
            if last.get('tool_call_id')=='target-write':
                match=re.search(r'requestId=([a-f0-9]{32})',str(messages))
                return Completion(tool_calls=[{'id':'reply-'+match[1],'name':'umeko_desktop','arguments':{'operation':'agent_bus.reply','arguments':{'requestId':match[1],'status':'completed','result':'桥接测试完成：结果来自真实目标会话。'}}}])
            return Completion('已收到工具结果。')
        if 'Agent Bus result [completed]' in content:return Completion('汇总：目标会话已完成检查，结果已通过智能体总线送回。\n\n```python\nprint("complete")\n```\n\n| 任务 | 状态 |\n| --- | --- |\n| 检查 | 完成 |',thinking='先核对请求 ID 和返回结果。')
        match=re.search(r'requestId=([a-f0-9]{32})',content)
        if match:return Completion(tool_calls=[{'id':'target-write','name':'write','arguments':{'path':'bridge-proof.txt','content':'approved bridge work'}}])
        if content.startswith('coordinate '):
            self.pause_started.set();self.pause.wait(20)
            return Completion(tool_calls=[{'id':'dispatch-fixture','name':'umeko_desktop','arguments':{'operation':'agent_bus.dispatch','arguments':{'targetId':content[11:],'text':'运行桥接验收并回传结果'}}}])
        return Completion('你好，我可以帮你协调任务。')
fixture=Fixture();b.adapter=fixture;b.gateway.adapter=fixture

def find(name):
    stack=[window.contentItem()]
    while stack:
        item=stack.pop()
        if item.objectName()==name:return item
        if item.objectName() in ('webSurfaceLoader','htmlPreviewBrowser'):continue
        stack.extend(item.childItems())
    return window.findChild(QObject,name)
def wait(check,message,ms=20000):
    for _ in range(ms//25):
        QTest.qWait(25)
        if check():return
    raise AssertionError(message+'\n'+str(g.requests)+'\n'+str([(r.phase,r.messages) for r in g.records.values()])+'\n'+str(fixture.calls[-2:])[:8000]+'\n'+'\n'.join(warnings))
def click(name):
    wait(lambda:find(name) is not None,'Missing '+name);item=find(name)
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(item.boundingRect().center()).toPoint());QTest.qWait(80)
out=ROOT/'build/global-agents-ui';out.mkdir(parents=True,exist_ok=True)
try:
    window.resize(1580,1000);b.selectCharacter('komari');b.changed.emit();g=b.desktopPlugins.global_agents
    assert b.desktopPlugins.openPage('global-agents')
    wait(lambda:find('globalAgentsPage') is not None,'Widget did not load')
    page=find('globalAgentsPage');wait(lambda:(page.property('state').toVariant() if hasattr(page.property('state'),'toVariant') else page.property('state')).get('defaultCharacter'),'Snapshot missing')
    QTest.qWait(1000);click('newGlobalAgentButton');assert page.property('chosenCharacter')==b.characterStyle['id']
    assert not find('globalAgentName').property('text')
    find('globalAgentInstructions').setProperty('text','关注所有已开启智能体总线的工作区任务，委派后主动汇总结果。')
    window.grabWindow().save(str(out/'create.png'));click('confirmCreateGlobalAgent')
    wait(lambda:len(g.agents)==1,'Creation failed');identifier=next(iter(g.agents));assert g.agents[identifier]['character']==b.characterStyle['id']
    assert g.agents[identifier]['name']==next(row['name'] for row in b.characterPacks if row['id']==b.characterStyle['id'])
    wait(lambda:page.property('selected')==identifier,'Context not opened')
    # The target is a genuine, separate native Pi session, initially a draft.
    target=g.identifier(b._view);g.handle('setBridge',{'id':target,'agentId':identifier,'enabled':True})
    # Exercise the Widget's own host-dialog binding, then the real target gate.
    coordinator=g.ensure(identifier)
    b._pool.event.emit(coordinator,{'type':'ui_request','id':'fixture-confirm','method':'confirm','title':'确认测试','detail':'这是一个宿主 UI 对话框绑定测试。'})
    wait(lambda:find('confirmGlobalAgentApproval') and find('confirmGlobalAgentApproval').isVisible(),'Widget confirmation missing')
    click('confirmGlobalAgentApproval')
    assert not coordinator.approval
    b.setToolPermissionMode('ask')
    find('globalAgentInput').setProperty('text','coordinate '+target);click('sendGlobalAgentButton')
    wait(lambda:fixture.pause_started.is_set(),'Native model did not reach pending interval')
    assert sum(row['role']=='user' and row['text']=='coordinate '+target for row in coordinator.messages)==1,'Native echo duplicated the user message before reply'
    wait(lambda:sum(row['role']=='user' for row in (page.property('state').toVariant() if hasattr(page.property('state'),'toVariant') else page.property('state'))['messages'])==1,'Pending user message missing from Widget')
    QTest.qWait(750)
    assert sum(row['role']=='user' for row in (page.property('state').toVariant() if hasattr(page.property('state'),'toVariant') else page.property('state'))['messages'])==1,'Pending user message displayed twice'
    window.grabWindow().save(str(out/'pending-single-message.png'));fixture.pause.set()
    wait(lambda:b.pendingApproval,'Target permission prompt was bypassed')
    b.respondApproval(True)
    wait(lambda:any(row['status']=='completed' for row in g.requests.values()),'Bridge did not round trip',40000)
    wait(lambda:'汇总：' in str(g.snapshot(identifier)['messages']),'Coordinator did not wake for final result',30000)
    assert (Path(b._view.workspace)/'bridge-proof.txt').read_text()=='approved bridge work'
    coordinator=g.records[identifier];assert coordinator.file and b._view.file and coordinator.file!=b._view.file
    assert all(row['id']!=coordinator.id for row in b._sessions)
    # Coordinator model sees only its allowlisted host tool; target keeps native tools.
    assert any(len(tools)==1 and tools[0].get('name',tools[0].get('function',{}).get('name'))=='umeko_desktop' for _,tools in fixture.calls)
    wait(lambda:len((page.property('state').toVariant() if hasattr(page.property('state'),'toVariant') else page.property('state'))['messages'])>0,'Transcript not visible')
    QTest.qWait(500);window.grabWindow().save(str(out/'conversation.png'))
    projected=g.snapshot(identifier)['messages'];last_index=len(projected)-1
    wait(lambda:find('widgetAssistantAvatar_'+str(last_index)) is not None,'Shared renderer avatar missing')
    assert find('widgetAssistantAvatar_'+str(last_index)).property('artwork').toString()==g.snapshot(identifier)['agents'][0]['portrait']
    assert find('widgetCopyMessage_'+str(last_index)) is not None
    stack=[find('widgetChatMessage_'+str(last_index))];code=None
    while stack:
        item=stack.pop()
        if item.objectName().startswith('codeBlock_') and 'print("complete")' in (item.property('text') or ''):code=item
        stack.extend(item.childItems())
    assert code is not None,'Shared code renderer missing'
    assert any(step['kind']=='tools' for row in projected for step in row.get('activity',[])),'Structured tool history lost'
    click('widgetCopyMessage_'+str(last_index))
    from PySide6.QtGui import QGuiApplication
    assert 'print("complete")' in QGuiApplication.clipboard().text(),'Widget message copy lost code'
    b.setTheme('dark')
    wait(lambda:code.property('syntaxColors').property('dark'),'Shared syntax theme did not update')
    window.grabWindow().save(str(out/'conversation-dark.png'))
    b.setTheme('light')
    # Context and appearance survive stopping and rebuilding this service.
    g.save();assert json.loads(g.registry.read_text())['agents'][0]['sessionFile']==coordinator.file
    # Projects with identical folder names retain their user-assigned names.
    first=base/'client'/'workspace';second=base/'server'/'workspace'
    first.mkdir(parents=True);second.mkdir(parents=True)
    b.store.data['projects']=[{'id':'project-client','name':'客户端','path':str(first)},{'id':'project-server','name':'服务端','path':str(second)}]
    for sid,title,workspace in [('tree-client-one','修复输入框',first),('tree-client-two','调整布局',first),('tree-server','部署服务',second)]:
        b._sessions.append({'id':sid,'title':title,'workspace':str(workspace),'model':'fixture','provider':'internal','file':''})
    b.changed.emit();page.setProperty('selected','');QTest.qWait(800)
    assert find('globalSubagentsHeading').property('text')=='全局子智能体'
    window.grabWindow().save(str(out/'list.png'))
    click('agentBusTabButton')
    wait(lambda:find('agentBusProject_'+str(first)) is not None,'Project grouping missing')
    wait(lambda:find('agentBusConversation_session:tree-client-one') is not None,'Conversation row missing')
    click('agentBusConversation_session:tree-client-one')
    wait(lambda:find('agentBusCheckbox_session:tree-client-one_'+identifier) is not None,'Pair checkbox missing from secondary page')
    click('agentBusCheckbox_session:tree-client-one_'+identifier)
    wait(lambda:identifier in g.bridges.get('tree-client-one',[]),'Checkbox granted the wrong conversation')
    window.grabWindow().save(str(out/'bus-connections.png'));click('agentBusBackButton')
    assert not g.bridges.get('tree-client-two') and not g.bridges.get('tree-server')
    click('agentBusProject_'+str(first))
    wait(lambda:find('agentBusConversation_session:tree-client-one') is None,'Project did not collapse')
    assert find('agentBusConversation_session:tree-server') is not None
    find('agentBusSearch').setProperty('text','修复输入框')
    wait(lambda:find('agentBusProjectTree').property('count')==2,'Conversation search did not expand its project')
    assert find('agentBusConversation_session:tree-client-one') is not None
    find('agentBusSearch').setProperty('text','')
    wait(lambda:find('agentBusConversation_session:tree-client-one') is None,'Search changed the saved collapse state')
    click('agentBusProject_'+str(first));QTest.qWait(150)
    window.grabWindow().save(str(out/'agent-bus-projects.png'))
    click('globalSubagentsHelpButton')
    wait(lambda:find('globalSubagentsHelpPopup').property('opened'),'Help did not open')
    assert find('globalSubagentsHelpTitle').property('text')=='Agent Bus（智能体总线）'
    assert '勾选' in find('globalSubagentsHelpText').property('text')
    QTest.keyClick(window,Qt.Key_Escape);QTest.qWait(150)
    click('agentBusRequestsTabButton');click('globalSubagentsHelpButton')
    wait(lambda:find('globalSubagentsHelpPopup').property('opened'),'Request help did not open')
    assert find('globalSubagentsHelpTitle').property('text')=='请求'
    assert '返回结果' in find('globalSubagentsHelpText').property('text')
    assert '不会撤销' in find('globalSubagentsHelpText').property('text')
    window.grabWindow().save(str(out/'requests-help.png'))
    assert identifier in g.bridges.get('tree-client-one',[])
    QTest.keyClick(window,Qt.Key_Escape);QTest.qWait(150)
    # A project near the end of a long, virtualized tree must not jump back to
    # the top when it is collapsed or a background snapshot updates.
    for index in range(60):
        b._sessions.append({'id':f'long-tree-{index}','title':'后台对话','workspace':str(base/f'aaa-{index:02}'),'model':'fixture','provider':'internal','file':''})
    b.changed.emit();click('agentBusTabButton')
    wait(lambda:find('agentBusProjectTree').property('count')>120,'Long tree snapshot missing')
    from PySide6.QtCore import QMetaObject
    assert QMetaObject.invokeMethod(find('agentBusProjectTree'),'positionViewAtEnd')
    wait(lambda:find('agentBusProject_'+str(first)) is not None,'Could not scroll to the project')
    QTest.qWait(200);click('agentBusProject_'+str(first))
    wait(lambda:find('agentBusConversation_session:tree-client-one') is None,'Long project did not collapse')
    QTest.qWait(800)
    assert find('agentBusProject_'+str(first)) is not None,'Collapsing or polling jumped away from the project'
    click('agentBusProject_'+str(first))
    wait(lambda:find('agentBusConversation_session:tree-client-one') is not None,'Long project did not reopen')
    # Ordinary native sessions propose a fully filled creation form, never an
    # actual definition until the user confirms it in the Widget.
    page.setProperty('selected','');QTest.qWait(750);click('globalSubagentsTabButton');b.desktopPlugins.closePage();QTest.qWait(200)
    before=len(g.agents);caller=b._view
    proposal=g.execute('agent_bus.create',{'requestKey':'ui-proposal','name':'待用户确认','character':'kaju','instructions':'只协调已授权任务'},caller)
    wait(lambda:find('globalAgentName') and find('globalAgentName').isVisible(),'Model proposal did not open its final form')
    page=find('globalAgentsPage')
    wait(lambda:page.property('proposalId')==proposal['requestId'],'Proposal was not bound to its form')
    assert len(g.agents)==before and proposal['status']=='awaiting_approval'
    assert find('globalAgentName').property('text')=='待用户确认'
    assert find('globalAgentInstructions').property('text')=='只协调已授权任务'
    assert page.property('chosenCharacter')=='kaju'
    assert find('globalAgentModel').property('currentIndex')>=0
    QTest.qWait(1200)
    button=find('confirmCreateGlobalAgent');point=button.mapToScene(button.boundingRect().center())
    assert 0<point.x()<window.width() and 0<point.y()<window.height(),'Confirmation form outside window'
    window.grabWindow().save(str(out/'creation-proposal.png'))
    find('globalAgentName').setProperty('text','用户确认的佳树');click('confirmCreateGlobalAgent')
    wait(lambda:len(g.agents)==before+1,'Confirm did not create a global subagent')
    created=g.execute('agent_bus.creation_status',{'requestId':proposal['requestId']},caller)
    assert created['status']=='created' and created['name']=='用户确认的佳树'
    assert g.execute('agent_bus.create',{'requestKey':'ui-proposal'},caller)['id']==created['id']
    # The next request can be cancelled; closing a form does not create it.
    page.setProperty('selected','');QTest.qWait(750)
    cancelled=g.execute('agent_bus.create',{'requestKey':'ui-cancel'},caller)
    wait(lambda:page.property('proposalId')==cancelled['requestId'],'Cancel proposal not shown')
    click('cancelGlobalCreation')
    wait(lambda:g.creation_requests[cancelled['requestId']]['status']=='cancelled','Close did not cancel model creation')
    assert len(g.agents)==before+1
    # Only a real user checkbox action enables direct creation.
    click('allowAutomaticGlobalCreation');wait(lambda:g.allow_automatic_creation,'User checkbox did not enable auto creation')
    automatic=g.execute('agent_bus.create',{'requestKey':'ui-direct'},caller)
    assert automatic['status']=='created' and automatic['character'] in {row['id'] for row in b.subagentCharacterPacks}
    assert len(g.agents)==before+2
    QTest.qWait(800);assert not page.property('proposalId')
    window.grabWindow().save(str(out/'automatic-creation.png'))
    click('allowAutomaticGlobalCreation');wait(lambda:not g.allow_automatic_creation,'Auto creation preference did not turn off')
    # The conversation-specific page lists every global, with an independent
    # checkbox; pending incoming messages remain outside the active transcript.
    page.setProperty('busSessionId',g.identifier(caller));click('agentBusTabButton')
    wait(lambda:find('agentBusCheckbox_'+g.identifier(caller)+'_'+created['id']) is not None,'Secondary connection page missing')
    assert find('agentBusCheckbox_'+g.identifier(caller)+'_'+created['id']).property('checked')
    window.grabWindow().save(str(out/'source-connections.png'));click('agentBusBackButton')
    g.timer.stop();queued_target=g.ensure(created['id']);queued_target.busy=True
    requests=[g.execute('agent_bus.dispatch',{'targetId':created['targetId'],'text':text},caller)['requestId'] for text in ('先到的消息','稍后删除的消息','用户要求优先的消息')]
    page.setProperty('selected',created['id']);g.changed(False)
    wait(lambda:find('global_bus_steerQueued_2') is not None,'Pending queue did not appear in global chat')
    click('global_bus_steerQueued_2');wait(lambda:g.pending_queue(created['id'])[0]['id']==requests[2],'Priority button did not reorder the queue')
    click('global_bus_removeQueued_2');wait(lambda:g.requests[requests[1]]['status']=='cancelled','Queue removal did not cancel the message')
    click('global_bus_editQueued_0');wait(lambda:find('globalBusQueuePreviewText') is not None,'Read-only queued message preview missing')
    assert '用户要求优先的消息' in find('globalBusQueuePreviewText').property('text')
    QTest.keyClick(window,Qt.Key_Escape);QTest.mouseMove(window,window.contentItem().boundingRect().center().toPoint())
    QTest.qWait(750);window.grabWindow().save(str(out/'pending-bus-queue.png'))
    for request in (requests[0],requests[2]):g.handle('cancelRequest',{'id':request})
    queued_target.busy=False;g.outbox.clear();g.timer.start()
    kazuhiko=g.handle('create',{'character':'kazuhiko'})
    assert g.agents[kazuhiko['id']]['name']=='温水和彦'
    assert not [w for w in warnings if 'global-agents/qml' in w],warnings
    print('PASS: real Widget creation, current-character default, native cross-session dispatch/reply/wakeup, scoped tools, durable contexts and searchable project-tree bus authorizations.')
finally:
    fixture.pause.set()
    b.close();window.close();engine.deleteLater();QTest.qWait(200);work.cleanup()
