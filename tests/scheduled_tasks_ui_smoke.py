"""Exercise the real Widget and Pi runtime with isolated demo data."""
from datetime import datetime, timedelta, timezone
import json
import os
import re
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QObject, Qt, QUrl
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from app.integration import Completion
from main import create_application

class Fixture:
    ready = True
    calls = 0
    def complete(self, model, messages, tools, max_tokens):
        self.calls += 1
        last = messages[-1]
        content = last.get('content', '')
        if not isinstance(content, str):
            content = '\n'.join(part.get('text', '') for part in content if part.get('type') == 'text')
        request = re.search(r'requestId=([a-f0-9]{32})', content)
        if request and 'Agent Bus sender' in content:
            return Completion(tool_calls=[{'id': 'timer-reply-' + request[1], 'name': 'umeko_desktop',
                'arguments': {'operation': 'agent_bus.reply', 'arguments': {'requestId': request[1],
                    'status': 'completed', 'result': 'Timer received by the real global Agent.'}}}])
        return Completion("【演示】任务已完成。" if language == "zh" else "[Demo] Task completed.")

def until(test, label, attempts=400):
    for _ in range(attempts):
        if test():
            return
        QTest.qWait(50)
    raise AssertionError(label)

language = sys.argv[1] if len(sys.argv) > 1 else 'zh'
output = sys.argv[2] if len(sys.argv) > 2 else str(root/'build/scheduled-tasks-ui/style')
Path(output).parent.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='umeko-scheduled-demo-') as temp:
    profile = Path(temp)
    os.environ.update(UMEKO_DATA_DIR=str(profile / 'data'),
                      PI_CODING_AGENT_DIR=str(profile / 'agent'))
    fixture = Fixture()
    with patch('app.controller.load_adapter', return_value=fixture):
        app, engine, backend = create_application()
    backend.store.data['ui']['language'] = language
    backend.appearanceChanged.emit()
    QFontDatabase.addApplicationFont('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
    window = engine.rootObjects()[0]
    window.setWidth(1440)
    window.setHeight(950)
    window.show()
    QTest.qWaitForWindowExposed(window, 2000)
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))

    def find(name):
        pending = [window.contentItem()]
        while pending:
            item = pending.pop()
            if item.objectName() == name:
                return item
            pending.extend(item.childItems())
        return window.findChild(QObject, name)

    def click(name):
        item = find(name)
        assert item is not None and item.property('enabled'), name
        item.clicked.emit()

    def screenshot(kind):
        QTest.qWait(200)
        image = window.grabWindow()
        assert image.width() == window.width() and image.height() == window.height() and image.width() >= 900, (image.size(), window.size())
        assert image.save(f'{output}-{kind}-{language}.png')

    workspace = profile / 'demo-project'
    workspace.mkdir()
    attachment = workspace / 'demo-notes.txt'
    attachment.write_text('DEMO / 演示数据', encoding='utf-8')
    backend.store.data.update(selectedProvider='internal', selectedModel='umeko-default',
        providers=[{'id':'internal','name':'Demo / 演示','api':'internal','baseUrl':'','key':'',
                    'models':[{'upstream':'default','alias':'umeko-default'}]}],
        )
    backend.setWorkspace(QUrl.fromLocalFile(str(workspace)).toString())
    assert backend.addAttachments(json.dumps([QUrl.fromLocalFile(str(attachment)).toString()]))
    foreground = backend._view
    draft = '【演示】这段未发送草稿应保持原样。' if language == 'zh' else '[Demo] Keep this unsent draft.'
    until(lambda: find('promptInput') is not None, 'Composer not ready')
    find('promptInput').setProperty('text', draft)
    assert foreground.draft == draft
    before = (foreground.draft, list(foreground.attachments))
    manager = backend.desktopPlugins
    bus = manager.global_agents
    connected = bus.handle('create', {'name': '演示 · 整理助手', 'model': 'umeko-default', 'instructions': 'Reply to every Agent Bus request explicitly.'})['id']
    unconnected = bus.handle('create', {'name': '演示 · 未关联助手', 'model': 'umeko-default'})['id']
    bus.handle('setBridge', {'id': 'session:' + foreground.key, 'agentId': connected, 'enabled': True})
    try:
        assert not manager.enabled('scheduled-tasks')
        manager.setEnabled('scheduled-tasks', True)
        menu = find('desktopPluginSessionMenu')
        assert menu is not None
        click('desktopPluginMenuButton')
        until(lambda: menu.property('desiredOpen') and not menu.property('animating'), 'Widget menu did not settle')
        until(lambda: find('openDesktopPlugin_scheduled-tasks') is not None, 'Widget menu entry missing')
        entry = find('openDesktopPlugin_scheduled-tasks')
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, entry.mapToScene(entry.boundingRect().center()).toPoint())
        until(lambda: find('scheduledTasksWidget') is not None, 'Scheduled Tasks did not open')
        panel = find('scheduledTasksWidget')
        until(lambda: panel.property('readyForInteraction') and not panel.property('pending') and not panel.property('hostRequest'), 'Widget not ready')
        assert panel.property('error') == '' and not manager.page['error'], (panel.property('error'), manager.page['error'])
        def values(name):
            value = panel.property(name)
            return value.toVariant() if hasattr(value, 'toVariant') else value

        def save_task(name, frequency, enabled, target=0):
            find('scheduledTaskName').setProperty('text', name)
            find('scheduledTaskPrompt').setProperty('text', '【演示】请整理任务摘要。' if language == 'zh' else '[Demo] Summarize this task.')
            find('scheduledTaskFrequency').setProperty('currentIndex', frequency)
            find('scheduledTaskTarget').setProperty('currentIndex', target)
            if frequency == 0:
                find('scheduledTaskDate').setProperty('text', due.strftime('%Y-%m-%d'))
                find('scheduledTaskTime').setProperty('text', due.strftime('%H:%M:%S'))
                find('scheduledTaskZone').setProperty('text', 'UTC')
            else:
                find('scheduledTaskIntervalUnit').setProperty('currentIndex', 2)
                find('scheduledTaskInterval').setProperty('text', '0.24999')
                assert not find('scheduledTaskSave').property('enabled')
                find('scheduledTaskInterval').setProperty('text', '0.25')
            find('scheduledTaskEnabled').setProperty('checked', enabled)
            screenshot('editor' if frequency == 0 else 'interval-editor')
            click('scheduledTaskSave')
            until(lambda: panel.property('page') == 'list' and not panel.property('pending'), 'Save failed')
            return next(task for task in values('tasks') if task['name'] == name)

        def agent(method, args=None, caller=None):
            result = manager.bridge.execute('widgets.call', {'id':'scheduled-tasks', 'method':method,
                'arguments':args or {}}, caller or foreground, backend._umeko_control)
            request = result['requestId']
            until(lambda: manager.bridge.calls[request]['status'] != 'running', 'Agent Widget call timed out')
            return manager.bridge.calls[request]['result']

        def color(task):
            name = 'scheduledTaskAccent_' + task['id']
            until(lambda: find(name) is not None, 'Task color marker missing')
            return find(name).property('color').name()

        def open_history(task):
            click('scheduledTaskHistory_' + task['id'])
            until(lambda: panel.property('page') == 'history' and not panel.property('pending'), 'History did not open')

        def complete_runs(count):
            until(lambda: len(values('runs')) == count and all(r['state'] == 'delivered' for r in values('runs')),
                  f'Expected {count} delivered runs: ' + str(values('runs')), attempts=1000)
            return values('runs')

        due = datetime.now(timezone.utc) + timedelta(seconds=24)
        names = (['【演示】项目摘要', '【演示】委派整理助手', '【演示】每隔 0.25 分钟检查']
                 if language == 'zh' else ['[Demo] Project digest', '[Demo] Delegate to global Agent', '[Demo] Every 0.25 minutes'])
        tasks = []
        colors = {}
        for name, frequency, enabled, target in zip(names, (0, 0, 1), (True, True, False), (0, 1, 0)):
            click('scheduledNewOrBack')
            task = save_task(name, frequency, enabled, target)
            tasks.append(task)
            colors[task['id']] = color(task)
        primary, linked, inactive = tasks
        assert len(set(colors.values())) == 3, colors
        assert {task['id']: color(task) for task in tasks} == colors
        assert primary['next_at'] == linked['next_at'] == int(due.timestamp())
        assert not inactive['enabled'] and inactive['next_at'] is None
        screenshot('multi-task-list')
        original_theme = backend.store.data['theme']
        backend.setTheme('dark')
        until(lambda: all(color(task) != colors[task['id']] for task in tasks), 'Dark task colors did not update')
        assert len({color(task) for task in tasks}) == 3
        screenshot('multi-task-dark')
        backend.setTheme(original_theme)
        until(lambda: all(color(task) == colors[task['id']] for task in tasks), 'Light task colors did not restore')

        open_history(primary)
        click('scheduledTaskRunNow')
        primary_runs = complete_runs(2)
        assert {r['scheduled_at'] for r in primary_runs} == {None, int(due.timestamp())}
        screenshot('multi-task-history')
        click('scheduledRunPrompt_' + primary_runs[0]['id'])
        until(lambda: find('scheduledPromptDialog').property('opened'), 'Prompt preview did not open')
        screenshot('prompt')
        click('scheduledPromptClose')
        until(lambda: not find('scheduledPromptDialog').property('visible'), 'Prompt preview did not close')
        click('scheduledNewOrBack')
        until(lambda: not panel.property('pending'), 'List did not refresh')
        assert {task['id']: color(task) for task in tasks} == colors

        open_history(linked)
        linked_runs = complete_runs(1)
        assert linked_runs[0]['scheduled_at'] == int(due.timestamp())
        sessions = [run['session_id'] for run in primary_runs + linked_runs]
        assert sessions[0] == sessions[1] == foreground.id and sessions[2]
        assert any(row['target'] == 'agent:' + connected for row in bus.requests.values())
        assert unconnected not in {row['id'].removeprefix('agent:') for row in values('targets')}
        click('scheduledNewOrBack')
        until(lambda: not panel.property('pending'), 'List did not refresh')

        open_history(inactive)
        assert values('runs') == []
        assert fixture.calls >= 3, fixture.calls
        assert backend._view is foreground and (foreground.draft, foreground.attachments) == before
        click('scheduledNewOrBack')
        until(lambda: not panel.property('pending'), 'List did not refresh')

        # Real Widget Agent entry point, including manifest/schema checks and
        # async widgets.result. Neither the model nor a foreground switch picks owner IDs.
        allowed_targets = agent('targets')['result']['targets']
        assert {row['id'] for row in allowed_targets} == {'main', 'agent:' + connected}
        extra = []
        for unit in ('hours', 'days'):
            reply = agent('create', {'name':'Agent-created ' + unit, 'message':'Demo interval', 'enabled':False,
                'schedule':{'frequency':'interval', 'interval_value':0.5, 'interval_unit':unit}})
            assert reply['ok'], reply
            extra.append(reply['result']['task_id'])
        assert not agent('create', {'name':'Sixth', 'message':'Must fail', 'enabled':False,
            'schedule':{'frequency':'interval','interval_value':1,'interval_unit':'hours'}})['ok']
        assert len(agent('list')['result']['tasks']) == 5
        assert agent('enable', {'task_id':extra[0]})['ok']
        assert agent('disable', {'task_id':extra[0]})['ok']
        from app.pi_sessions import SessionState
        other = SessionState(id='other-demo', workspace=str(workspace), model='umeko-default', provider='internal')
        backend._pool.touch(other)
        assert agent('list', caller=other)['result']['tasks'] == []
        assert not agent('delete', {'task_id':extra[0]}, caller=other)['ok']
        for key in extra:assert agent('delete', {'task_id':key})['ok']

        # A previously valid target is checked again when the timer fires.
        later = datetime.now(timezone.utc) + timedelta(seconds=4)
        revoked = agent('create', {'name':'Disconnected test', 'message':'Must not reach the unlinked Agent',
            'target':'agent:' + connected, 'schedule':{'frequency':'once','first_date':later.strftime('%Y-%m-%d'),
                'local_time':later.strftime('%H:%M:%S'),'zone':'UTC'}})
        assert revoked['ok'], revoked
        bus.handle('setBridge', {'id':'session:' + foreground.id,'agentId':connected,'enabled':False})
        key = revoked['result']['task_id']
        until(lambda: any(row['state'] == 'failed' for row in agent('history', {'task_id':key})['result']['runs']),
              'Disconnected target did not record a failure')
        assert agent('delete', {'task_id':key})['ok']
        bus.handle('setBridge', {'id':'session:' + foreground.id,'agentId':connected,'enabled':True})

        # The 15-second interval continues for the captured original chat even
        # while another chat is displayed. Drafts and attachments stay in place.
        assert agent('enable', {'task_id':inactive['id']})['ok']
        backend.newSession()
        other_view = backend._view
        until(lambda: backend._view is not foreground, 'New chat did not activate')
        def repeated():
            result = agent('history', {'task_id':inactive['id']})
            return result['ok'] and len([row for row in result['result']['runs'] if row['state'] == 'delivered']) >= 2
        until(repeated, 'Background periodic timer did not fire twice', attempts=1000)
        assert backend._view is other_view
        periodic = agent('history', {'task_id':inactive['id']})['result']['runs']
        assert abs(periodic[0]['scheduled_at'] - periodic[1]['scheduled_at'] - 15) < 0.000001
        assert all(row['session_id'] == foreground.id for row in periodic)
        assert agent('disable', {'task_id':inactive['id']})['ok']
        assert (foreground.draft, foreground.attachments) == before
        backend.openSession(foreground.id)
        until(lambda: backend._view is foreground, 'Original chat did not reactivate')
        assert manager.openPage('scheduled-tasks')
        until(lambda: find('scheduledTasksWidget') is not None, 'Timer page did not reopen')
        panel = find('scheduledTasksWidget')
        until(lambda: not panel.property('pending') and not panel.property('hostRequest') and values('tasks'), 'Timer page not ready')
        click('scheduledTaskEdit_' + inactive['id'])
        backend.setFontScale(2.0)
        window.setWidth(window.minimumWidth())
        until(lambda: not find('webPane').property('moving') and
              abs(panel.mapToScene(panel.boundingRect().bottomRight()).x() - window.width()) < 1,
              'Narrow pane did not settle inside the window')
        until(lambda: find('scheduledTaskSave').isVisible(), 'Editor footer missing at 200%')
        save = find('scheduledTaskSave')
        toggle = find('scheduledTaskEnabled')
        assert toggle.mapToScene(toggle.boundingRect().topRight()).x() <= save.mapToScene(save.boundingRect().topLeft()).x()
        assert save.mapToScene(save.boundingRect().bottomRight()).x() <= panel.mapToScene(panel.boundingRect().bottomRight()).x()
        assert save.mapToScene(save.boundingRect().bottomRight()).x() <= window.width(), (save.mapToScene(save.boundingRect().bottomRight()), panel.mapToScene(panel.boundingRect().bottomRight()), panel.width(), window.width())
        icon, title = find('webPaneWidgetIcon'), find('webPaneTitle')
        assert icon.mapToScene(icon.boundingRect().topRight()).x() < title.mapToScene(title.boundingRect().topLeft()).x()
        screenshot('large-font')
        backend.setFontScale(1.0)
        assert not [w for w in warnings if 'scheduled-tasks/qml' in w], warnings
        manager.closePage()
        assert manager.workers['scheduled-tasks']['ready']
        print(f'{language}: real main/AgentBus delivery; decimal 15s repeat across foreground switch; disconnected target rejected; Widget Agent CRUD/quota/owner boundaries; colors and 200% bounds; drafts/attachments preserved')
    finally:
        backend.close()
        app.processEvents()
