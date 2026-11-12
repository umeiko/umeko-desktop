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
        return Completion("演示周报已生成：本周完成定时调度，下一步验证审批和重启恢复。")

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
        click('scheduledNewOrBack')
        find('scheduledTaskName').setProperty('text', '【演示】每周项目周报' if language == 'zh' else '[Demo] Weekly project report')
        find('scheduledTaskPrompt').setProperty('text', '【演示】根据本周项目进展，整理已完成工作、待解决问题和下周计划。' if language == 'zh' else '[Demo] Summarize this week’s completed work, open questions and next week’s plan.')
        find('scheduledTaskFrequency').setProperty('currentIndex', 2)
        due = datetime.now(timezone.utc) + timedelta(seconds=12)
        find('scheduledTaskDate').setProperty('text', due.strftime('%Y-%m-%d'))
        find('scheduledTaskTime').setProperty('text', due.strftime('%H:%M:%S'))
        find('scheduledTaskZone').setProperty('text', 'UTC')
        find('scheduledTaskEnabled').setProperty('checked', True)
        screenshot('new')
        click('scheduledTaskSave')
        until(lambda: not panel.property('pending'), 'Save reply missing')
        until(lambda: panel.property('page') == 'list' and find('scheduledTaskHistory') is not None, 'Save failed')
        click('scheduledTaskHistory')
        until(lambda: panel.property('page') == 'history' and not panel.property('pending'), 'History did not open')
        click('scheduledTaskRunNow')
        def completed():
            runs = panel.property('runs')
            runs = runs.toVariant() if hasattr(runs, 'toVariant') else runs
            return len(runs) == 2 and all(r['state'] == 'completed' for r in runs)
        until(completed, 'Scheduled and manual runs did not both complete', attempts=1000)
        runs = panel.property('runs')
        runs = runs.toVariant() if hasattr(runs, 'toVariant') else runs
        assert len({r['session_id'] for r in runs}) == 2 and all(r['session_id'] for r in runs)
        assert sum(r['scheduled_at'] is not None for r in runs) == 1
        assert fixture.calls == 2, fixture.calls
        assert backend._view is foreground and (foreground.draft, foreground.attachments) == before
        assert not [w for w in warnings if 'scheduled-tasks/qml' in w], warnings
        screenshot('history')
        manager.closePage()
        assert manager.workers['scheduled-tasks']['ready']
        print(f'{language}: scheduled and manual Pi runs completed in separate sessions; foreground draft and attachment preserved')
    finally:
        backend.close()
        app.processEvents()
