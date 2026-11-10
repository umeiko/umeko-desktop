"""Native Pi/QML routing acceptance with a deterministic local model fixture."""
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
work=tempfile.TemporaryDirectory(prefix='umeko-routing-')
profile=Path(work.name)
os.environ.update(UMEKO_DATA_DIR=str(profile/'data'),PI_CODING_AGENT_DIR=str(profile/'agent'),
                  UMEKO_LANGUAGE=os.environ.get('UMEKO_TEST_LANGUAGE','zh'),QT_QPA_PLATFORM=os.environ.get('QT_QPA_PLATFORM','offscreen'),QT_QUICK_BACKEND='software')
from PySide6.QtCore import QObject,Qt,QUrl
from PySide6.QtGui import QFont,QFontDatabase
from PySide6.QtTest import QTest
from app.integration import Completion
from app.pi_runtime import verify_runtime,RELEASE_NAME
from app.storage import Store

verify_runtime(ROOT/'runtime/releases'/RELEASE_NAME,ROOT/'runtime/bridge.mjs')
saved=Store(profile/'data')
saved.data.update(selectedProvider='internal',selectedModel='routing-fixture',providers=[{
    'id':'internal','name':'Local fixture','api':'internal','baseUrl':'','key':'',
    'models':[{'upstream':'fixture','alias':'routing-fixture'}]}])
saved.data['agent']['agentDir']=str(profile/'agent')
saved.save()
from main import create_application
app,engine,b=create_application()
window=engine.rootObjects()[0]
font=os.environ.get('UMEKO_TEST_CJK_FONT','')
if font and QFontDatabase.addApplicationFont(font)>=0:
    app.setFont(QFont('Noto Sans CJK SC',10))
    b.setFontFamily('Noto Sans CJK SC')
warnings=[]
engine.warnings.connect(lambda values:warnings.extend(row.toString() for row in values))


class Fixture:
    ready=True
    calls=[]

    def reply(self,request):
        return Completion(tool_calls=[{'id':'reply-'+request,'name':'umeko_desktop','arguments':{
            'operation':'agent_bus.reply','arguments':{'requestId':request,'status':'completed',
            'result':'本地验收模型回报：实际目录与范围已关联，执行会话保留原权限，演示操作已结束。'}}}])

    def complete(self,model,messages,tools,max_tokens):
        last=messages[-1]
        raw=last.get('content','')
        text=raw if isinstance(raw,str) else '\n'.join(row.get('text','') for row in raw if row.get('type')=='text')
        self.calls.append((text,{row.get('name',row.get('function',{}).get('name')) for row in tools}))
        if last['role']=='tool':
            if last.get('tool_call_id','').startswith('target-write-'):
                return self.reply(last['tool_call_id'][len('target-write-'):])
            return Completion('已记录结果，请在任务记录中查看路由与执行者回报。')
        if '用户在任务入口明确提交' in text:
            context=json.loads(text[text.index('{"objective"'):])
            requested=context['requestedTask']
            args={'routeId':context['routeId'],'decision':'continue' if requested and requested!='new' else 'new',
                  'taskId':requested if requested!='new' else '', 'targetId':context['targets'][0]['id'],
                  'reason':'依据用户目标和实际目录，选择已有授权会话'}
            if '需要澄清' in context['objective']:
                args.update(decision='clarify',reason='这是原任务的补充还是独立目标？请在入口选择任务关联。')
            return Completion(tool_calls=[{'id':'route-'+context['routeId'],'name':'umeko_desktop',
                                           'arguments':{'operation':'agent_bus.route','arguments':args}}])
        if 'Agent Bus sender' in text:
            request=re.search(r'requestId=([a-f0-9]{32})',text)[1]
            if '补充检查' in text:
                return self.reply(request)
            return Completion(tool_calls=[{'id':'target-write-'+request,'name':'write',
                'arguments':{'path':'routing-proof.txt','content':'Isolated test: original permission approval retained.'}}])
        return Completion('已收到协调结果。')


fixture=Fixture()
b.adapter=fixture
b.gateway.adapter=fixture
g=b.desktopPlugins.global_agents
out=ROOT/'build/task-routing-ui'
out.mkdir(parents=True,exist_ok=True)


def find(name):
    stack=[window.contentItem()]
    while stack:
        item=stack.pop()
        if item.objectName()==name:return item
        if item.objectName() not in ('webSurfaceLoader','htmlPreviewBrowser'):
            stack.extend(item.childItems())
    return window.findChild(QObject,name)


def wait(check,label,timeout=25000):
    for _ in range(timeout//25):
        QTest.qWait(25)
        if check():return
    window.grabWindow().save(str(out/'failure.png'))
    raise AssertionError(label+'\n'+str(g.requests)+'\n'+str(fixture.calls[-3:])[:5000]+'\n'+'\n'.join(warnings))


def click(name):
    wait(lambda:find(name) is not None,'Missing '+name)
    item=find(name)
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(item.boundingRect().center()).toPoint())
    QTest.qWait(100)


def variant(value):
    return value.toVariant() if hasattr(value,'toVariant') else value


try:
    window.resize(1580,1000)
    cwd=profile/'验收工作区'
    cwd.mkdir()
    b.setWorkspace(QUrl.fromLocalFile(str(cwd)).toString())
    b.setToolPermissionMode('ask')
    target=b._view
    identifier=g.handle('create',{'name':'任务协调者'})['id']
    g.handle('setBridge',{'id':g.identifier(target),'agentId':identifier,'enabled':True})
    assert b.desktopPlugins.openPage('global-agents')
    wait(lambda:find('globalAgentsPage') is not None,'Widget missing')
    page=find('globalAgentsPage')
    wait(lambda:len(variant(page.property('state'))['agents'])==1,'Roster missing')
    QTest.qWait(800)
    click('taskRoutingTabButton')
    wait(lambda:page.property('section')=='tasks','Task entry tab did not activate')
    router=find('taskRoutingPage')
    wait(lambda:bool(find('taskDirectoryPicker').property('currentText')),'Authorized directory missing')
    find('taskRoutingObjective').setProperty('text','[演示 / Demo] 检查任务入口与授权流程')
    find('taskRoutingScope').setProperty('text','在隔离验收目录生成测试凭据文件，保留原工具审批；不得修改其他文件。')
    click('submitTaskRoute')
    wait(lambda:bool(g.requests),'Routing did not dispatch')
    first=next(iter(g.requests))
    wait(lambda:b.pendingApproval,'Execution permission approval was bypassed')
    assert not (cwd/'routing-proof.txt').exists()
    b.respondApproval(True)
    wait(lambda:g.requests[first]['status']=='completed','Native result missing')
    wait(lambda:not g.ensure(identifier).busy and not target.busy,'Sessions not idle')
    store=b._task_records.store
    routed=store.route(first)
    assert routed['execution']=='completed' and routed['status']=='accepted'
    assert routed['targetId']==g.identifier(target) and routed['cwd']==str(cwd)
    assert (cwd/'routing-proof.txt').read_text().startswith('Isolated test:')
    assert any(names=={'umeko_desktop'} and '用户在任务入口' in text for text,names in fixture.calls)
    assert any('read' in names and 'Agent Bus sender' in text for text,names in fixture.calls)
    click('submitTaskRoute')
    QTest.qWait(200)
    assert len(g.requests)==1 and len(store.tasks())==1
    click('resetTaskRoute')
    router.setProperty('taskChoice',routed['taskId'])
    find('taskRoutingObjective').setProperty('text','[演示 / Demo] Follow-up：补充检查任务关联和重复请求')
    find('taskRoutingScope').setProperty('text',routed['scope'])
    click('submitTaskRoute')
    wait(lambda:len(g.requests)==2 and all(row['status']=='completed' for row in g.requests.values()),'Continuation did not finish')
    wait(lambda:not g.ensure(identifier).busy and not target.busy,'Continuation not idle')
    assert len(store.tasks())==1 and all(row['taskId']==routed['taskId'] for row in store.routes())
    assert router.property('taskChoice')==routed['taskId'],'Polling reset task selection'
    click('submitTaskRoute')
    QTest.qWait(200)
    assert len(g.requests)==2,'Retry after list refresh duplicated work'
    click('resetTaskRoute')
    find('taskRoutingObjective').setProperty('text','[演示 / Demo] 需要澄清 / Clarify task association')
    find('taskRoutingScope').setProperty('text',routed['scope'])
    click('submitTaskRoute')
    wait(lambda:len(store.routes())==3 and any(row['status']=='clarify' for row in store.routes()),'Clarification missing')
    wait(lambda:len(variant(router.property('history')))==3 and any(row['status']=='clarify' for row in variant(router.property('history'))),'Route history or clarification missing')
    QTest.qWait(300)
    assert window.grabWindow().save(str(out/('task-entry-'+os.environ.get('UMEKO_TEST_LANGUAGE','zh')+'.png')))
    b.desktopPlugins.setEnabled('task-records', True)
    assert b.desktopPlugins.openPage('task-records')
    wait(lambda:find('taskRecordsWidget') is not None,'Shared task Widget missing')
    click('openTask_'+routed['taskId'])
    wait(lambda:find('taskRouteDetails') is not None and any(row['id']==first for row in variant(find('taskRecordsWidget').property('routes'))),'Route missing from shared ledger')
    assert '本地验收模型回报' in find('taskRouteDetails').property('text')
    assert first not in find('taskRouteDetails').property('text')
    find('taskRecordsWidget').setProperty('technical',True)
    assert first in find('taskRouteDetails').property('text')
    find('taskRecordsWidget').setProperty('technical',False)
    find('taskRecordsWidget').setProperty('routesExpanded',True)
    QTest.qWait(300)
    assert window.grabWindow().save(str(out/('shared-task-route-'+os.environ.get('UMEKO_TEST_LANGUAGE','zh')+'.png')))
    assert not [row for row in warnings if 'global-agents/qml' in row or 'task-records/qml' in row],warnings
    print('PASS: real Widget/Pi routing, original tool approval, deduplication, same-task continuation, clarification, shared task history.')
    if os.environ.get('UMEKO_ACCEPTANCE_PREVIEW')=='1':
        b.desktopPlugins.openPage('global-agents')
        wait(lambda:find('globalAgentsPage') is not None,'Preview missing')
        find('globalAgentsPage').setProperty('section','tasks')
        print('ACCEPTANCE_PREVIEW_READY',flush=True)
        app.exec()
finally:
    b.close()
    window.close()
    engine.deleteLater()
    QTest.qWait(200)
    work.cleanup()
