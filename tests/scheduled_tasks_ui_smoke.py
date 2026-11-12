"""Exercise the real Widget and Pi runtime with isolated demo data."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')
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
        return Completion("【演示】任务已完成。" if language == "zh" else "[Demo] Task completed.")

def until(test, label, attempts=400):
    for _ in range(attempts):
        if test():
            return
        QTest.qWait(50)
    raise AssertionError(label)

language, output = sys.argv[1:3]
with tempfile.TemporaryDirectory(prefix='umeko-scheduled-demo-') as temp:
    profile = Path(temp)
    os.environ.update(HOME=temp, UMEKO_DATA_DIR=str(profile / 'data'),
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
        assert image.width() >= 1200 and image.height() >= 800
        assert image.save(f'{output}-{kind}-{language}.png')

    workspace = profile / 'demo-project'
    workspace.mkdir()
    attachment = workspace / 'demo-notes.txt'
    attachment.write_text('DEMO / 演示数据', encoding='utf-8')
    backend.store.data.update(selectedProvider='internal', selectedModel='umeko-default',
        providers=[{'id':'internal','name':'Demo / 演示','api':'internal','baseUrl':'','key':'',
                    'models':[{'upstream':'default','alias':'umeko-default'}]}],
        pluginSessionProfiles={'scheduled-tasks': {'demo-weekly-report': {
            'workspace':str(workspace),'model':'umeko-default','provider':'internal','tools':[],
            'permissionMode':'ask'}}})
    backend.setWorkspace(QUrl.fromLocalFile(str(workspace)).toString())
    assert backend.addAttachments(json.dumps([QUrl.fromLocalFile(str(attachment)).toString()]))
    foreground = backend._view
    draft = '【演示】这段未发送草稿应保持原样。' if language == 'zh' else '[Demo] Keep this unsent draft.'
    until(lambda: find('promptInput') is not None, 'Composer not ready')
    find('promptInput').setProperty('text', draft)
    assert foreground.draft == draft
    before = (foreground.draft, list(foreground.attachments))
    manager = backend.desktopPlugins
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

        def save_task(name, frequency, enabled):
            find('scheduledTaskName').setProperty('text', name)
            find('scheduledTaskPrompt').setProperty(
                'text', '【演示】请整理任务摘要。' if language == 'zh' else '[Demo] Summarize this task.')
            find('scheduledTaskFrequency').setProperty('currentIndex', frequency)
            find('scheduledTaskDate').setProperty('text', due.strftime('%Y-%m-%d'))
            find('scheduledTaskTime').setProperty('text', due.strftime('%H:%M:%S'))
            find('scheduledTaskZone').setProperty('text', 'UTC')
            find('scheduledTaskEnabled').setProperty('checked', enabled)
            click('scheduledTaskSave')
            until(lambda: panel.property('page') == 'list' and not panel.property('pending'), 'Save failed')
            return next(task for task in values('tasks') if task['name'] == name)

        def color(task):
            name = 'scheduledTaskAccent_' + task['id']
            until(lambda: find(name) is not None, 'Task color marker missing')
            return find(name).property('color').name()

        def open_history(task):
            click('scheduledTaskHistory_' + task['id'])
            until(lambda: panel.property('page') == 'history' and not panel.property('pending'), 'History did not open')

        def complete_runs(count):
            until(lambda: len(values('runs')) == count and all(r['state'] == 'completed' for r in values('runs')),
                  f'Expected {count} completed runs', attempts=1000)
            return values('runs')

        due = datetime.now(timezone.utc) + timedelta(seconds=16)
        names = (['【演示】每周项目周报', '【演示】每日进度整理', '【演示】资料归档']
                 if language == 'zh' else ['[Demo] Weekly project report', '[Demo] Daily progress digest', '[Demo] Archive materials'])
        tasks = []
        colors = {}
        for name, frequency, enabled in zip(names, (2, 1, 0), (True, True, False)):
            click('scheduledNewOrBack')
            task = save_task(name, frequency, enabled)
            tasks.append(task)
            colors[task['id']] = color(task)
        weekly, daily, inactive = tasks
        assert len(set(colors.values())) == 3, colors
        assert {task['id']: color(task) for task in tasks} == colors
        assert weekly['next_at'] == daily['next_at'] == int(due.timestamp())
        assert not inactive['enabled'] and inactive['next_at'] is None
        screenshot('multi-task-list')
        original_theme = backend.store.data['theme']
        backend.setTheme('dark')
        until(lambda: all(color(task) != colors[task['id']] for task in tasks), 'Dark task colors did not update')
        assert len({color(task) for task in tasks}) == 3
        screenshot('multi-task-dark')
        backend.setTheme(original_theme)
        until(lambda: all(color(task) == colors[task['id']] for task in tasks), 'Light task colors did not restore')

        open_history(weekly)
        click('scheduledTaskRunNow')
        weekly_runs = complete_runs(2)
        assert {r['scheduled_at'] for r in weekly_runs} == {None, int(due.timestamp())}
        screenshot('multi-task-history')
        click('scheduledNewOrBack')
        until(lambda: not panel.property('pending'), 'List did not refresh')
        assert {task['id']: color(task) for task in tasks} == colors

        open_history(daily)
        daily_runs = complete_runs(1)
        assert daily_runs[0]['scheduled_at'] == int(due.timestamp())
        sessions = [run['session_id'] for run in weekly_runs + daily_runs]
        assert all(sessions) and len(set(sessions)) == 3
        click('scheduledNewOrBack')
        until(lambda: not panel.property('pending'), 'List did not refresh')

        open_history(inactive)
        assert values('runs') == []
        assert fixture.calls == 3, fixture.calls
        assert backend._view is foreground and (foreground.draft, foreground.attachments) == before
        assert not [w for w in warnings if 'scheduled-tasks/qml' in w], warnings
        manager.closePage()
        assert manager.workers['scheduled-tasks']['ready']
        print(f'{language}: 3 distinct colors; 2 tasks shared a due time; 3 separate Pi sessions including the manual run; inactive task did not run; foreground draft and attachment preserved')
    finally:
        backend.close()
        app.processEvents()
