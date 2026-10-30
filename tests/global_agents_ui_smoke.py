"""Real Widget, native Pi sessions and round-trip delegation; no paid model calls."""
import os,sys,tempfile,json,re
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
    def complete(self,model,messages,tools,max_tokens):
        self.calls.append((messages,tools));last=messages[-1];content=last.get('content','');content=content if isinstance(content,str) else '\n'.join(block.get('text','') for block in content if block.get('type')=='text')
        if last['role']=='tool':
            if last.get('tool_call_id')=='target-write':
                match=re.search(r'requestId=([a-f0-9]{32})',str(messages))
                return Completion(tool_calls=[{'id':'reply-'+match[1],'name':'umeko_desktop','arguments':{'operation':'agent_bus.reply','arguments':{'requestId':match[1],'status':'completed','result':'桥接测试完成：结果来自真实目标会话。'}}}])
            return Completion('已收到工具结果。')
        if 'Agent Bus result [completed]' in content:return Completion('汇总：目标会话已完成检查，结果已通过智能体总线送回。')
        match=re.search(r'requestId=([a-f0-9]{32})',content)
        if match:return Completion(tool_calls=[{'id':'target-write','name':'write','arguments':{'path':'bridge-proof.txt','content':'approved bridge work'}}])
        if content.startswith('coordinate '):return Completion(tool_calls=[{'id':'dispatch-fixture','name':'umeko_desktop','arguments':{'operation':'agent_bus.dispatch','arguments':{'targetId':content[11:],'text':'运行桥接验收并回传结果'}}}])
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
    find('globalAgentName').setProperty('text','小鞠 · 全局协调')
    find('globalAgentInstructions').setProperty('text','关注所有已开启智能体总线的工作区任务，委派后主动汇总结果。')
    window.grabWindow().save(str(out/'create.png'));click('confirmCreateGlobalAgent')
    wait(lambda:len(g.agents)==1,'Creation failed');identifier=next(iter(g.agents));assert g.agents[identifier]['character']==b.characterStyle['id']
    wait(lambda:page.property('selected')==identifier,'Context not opened')
    # The target is a genuine, separate native Pi session, initially a draft.
    target=g.identifier(b._view);g.handle('setBridge',{'id':target,'enabled':True})
    # Exercise the Widget's own host-dialog binding, then the real target gate.
    coordinator=g.ensure(identifier)
    b._pool.event.emit(coordinator,{'type':'ui_request','id':'fixture-confirm','method':'confirm','title':'确认测试','detail':'这是一个宿主 UI 对话框绑定测试。'})
    wait(lambda:find('confirmGlobalAgentApproval') and find('confirmGlobalAgentApproval').isVisible(),'Widget confirmation missing')
    click('confirmGlobalAgentApproval')
    assert not coordinator.approval
    b.setToolPermissionMode('ask')
    find('globalAgentInput').setProperty('text','coordinate '+target);click('sendGlobalAgentButton')
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
    wait(lambda:find('agentBusSwitch_session:tree-client-one') is not None,'Conversation switch missing')
    click('agentBusSwitch_session:tree-client-one')
    wait(lambda:g.bridges.get('tree-client-one') is True,'Switch granted the wrong conversation')
    assert not g.bridges.get('tree-client-two') and not g.bridges.get('tree-server')
    click('agentBusProject_'+str(first))
    wait(lambda:find('agentBusSwitch_session:tree-client-one') is None,'Project did not collapse')
    assert find('agentBusSwitch_session:tree-server') is not None
    find('agentBusSearch').setProperty('text','修复输入框')
    wait(lambda:find('agentBusProjectTree').property('count')==2,'Conversation search did not expand its project')
    assert find('agentBusSwitch_session:tree-client-one') is not None
    find('agentBusSearch').setProperty('text','')
    wait(lambda:find('agentBusSwitch_session:tree-client-one') is None,'Search changed the saved collapse state')
    click('agentBusProject_'+str(first));QTest.qWait(150)
    window.grabWindow().save(str(out/'agent-bus-projects.png'))
    click('globalSubagentsHelpButton')
    wait(lambda:find('globalSubagentsHelpPopup').property('opened'),'Help did not open')
    assert g.bridges.get('tree-client-one') is True
    assert not [w for w in warnings if 'global-agents/qml' in w],warnings
    print('PASS: real Widget creation, current-character default, native cross-session dispatch/reply/wakeup, scoped tools, durable contexts and searchable project-tree bus authorizations.')
finally:
    b.close();window.close();engine.deleteLater();QTest.qWait(200);work.cleanup()
