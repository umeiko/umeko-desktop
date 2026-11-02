"""Capture current real application UI in both languages, using disposable demo data.

Run once per language with the project's PySide6 Python after source setup.
No model inference, account credentials, public server or personal profile is used.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--language', choices=('zh', 'en'), required=True)
args = parser.parse_args()
english = args.language == 'en'
def local(zh, en): return en if english else zh

profile = tempfile.TemporaryDirectory(prefix='umeko-docs-capture-')
base = Path(profile.name)
workspace, agent = base / 'demo-project', base / 'pi-profile'
workspace.mkdir(); agent.mkdir()
os.environ.update(UMEKO_DATA_DIR=str(base / 'profile'), UMEKO_LANGUAGE=args.language,
                  PI_CODING_AGENT_DIR=str(agent), QT_QPA_PLATFORM='offscreen',
                  QT_QUICK_BACKEND='software')

from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtQml import QQmlExpression
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from app.storage import Store
from app.themes import read_theme
from app.project_info import VERSION
from main import create_application

store = Store()
store.data['agent'].update(agentDir=str(agent), safeMode=False)
store.data['ui'].update(language=args.language, fontScale=1.1)
theme = read_theme(ROOT / 'docs-site/public/examples/pure-white.umeko-theme.json')
theme['name'] = local('纯白', 'Pure white')
store.data.update(theme='custom:' + theme['id'], themes=[theme], workspace=str(workspace), selectedProvider='demo', selectedModel='workspace-model',
    providers=[{'id': 'demo', 'name': local('示例供应商', 'Demo Provider'), 'api': 'openai',
        'baseUrl': 'https://api.example.com/v1', 'key': '',
        'models': [{'upstream': 'workspace-model', 'alias': 'workspace-model', 'contextWindow': 262144,
                    'contextWindowAuto': False, 'vision': True, 'visionAuto': False}]}])
store.save()
for scope, name in ((workspace / '.pi/skills', 'project-review'), (workspace / '.pi/skills', 'write-report'),
                    (agent / 'skills', 'document-check'), (agent / 'skills', 'test-planner')):
    directory = scope / name; directory.mkdir(parents=True)
    (directory / 'SKILL.md').write_text(f'---\nname: {name}\ndescription: Documentation demo Skill.\n---\n\n# {name}\n\nRead the project and explain your findings before editing.\n', encoding='utf-8')
report = workspace / 'report.md'
report.write_text(local(
    '# 项目检查报告\n\n## 这次完成了什么\n\n- 阅读目录与启动说明\n- 检查测试入口\n- 整理下一步计划\n\n## 验收清单\n\n| 项目 | 状态 |\n| --- | --- |\n| 文档导航 | 已检查 |\n| 中英文页面 | 已对齐 |\n\n```python\ndef greet(name):\n    return f"Hello, {name}!"\n```\n',
    '# Project review\n\n## What we checked\n\n- Project structure and setup\n- Test entry points\n- Next steps\n\n## Acceptance checklist\n\n| Item | Status |\n| --- | --- |\n| Navigation | Reviewed |\n| Chinese / English | Matched |\n\n```python\ndef greet(name):\n    return f"Hello, {name}!"\n```\n'), encoding='utf-8')

app, engine, backend = create_application()
app.setQuitOnLastWindowClosed(False)
window = engine.rootObjects()[0]
window.resize(1440, 960)
output = ROOT / 'docs-site/public/images'
output.mkdir(parents=True, exist_ok=True)
captures = []

def variant(value):
    return value.toVariant() if hasattr(value, 'toVariant') else value

def wait_for(predicate, label, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QTest.qWait(20); time.sleep(.002)
        if predicate(): return
    raise RuntimeError(label() if callable(label) else label)

def find(name, optional=False):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name: return item
        if item.objectName() not in ('htmlPreviewBrowser', 'webSurfaceLoader'):
            stack.extend(item.childItems())
    item = window.findChild(QQuickItem, name)
    if item is None and not optional: raise RuntimeError('Missing item: ' + name)
    return item

def click(name):
    QTest.qWait(80)
    item = find(name)
    settings_view = find('settingsScroll').property('contentItem')
    ancestor = item.parentItem()
    while ancestor is not None and ancestor is not settings_view:
        ancestor = ancestor.parentItem()
    if ancestor is settings_view:
        settings_view.cancelFlick()
        point = item.mapToItem(settings_view, QPointF(0, 0))
        desired = settings_view.property('contentY') + point.y() - settings_view.height() / 2
        maximum = max(0, settings_view.property('contentHeight') - settings_view.height())
        settings_view.setProperty('contentY', max(0, min(desired, maximum)))
        QTest.qWait(250)
    target = item.mapToScene(item.boundingRect().center()).toPoint()
    assert 0 <= target.x() < window.width() and 0 <= target.y() < window.height(), (name, target)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, target)
    QTest.qWait(180)

def capture(name):
    window.setProperty('notification', '')
    QTest.mouseMove(window, QPointF(window.width()-4, window.height()-4).toPoint())
    QTest.qWait(700)
    path = output / f'{name}-{args.language}.png'
    if not window.grabWindow().save(str(path)): raise RuntimeError('Capture failed: ' + name)
    captures.append({'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    print('CAPTURED ' + path.name, flush=True)

def settings(tab):
    window.setProperty('page', 'settings'); window.setProperty('settingsTab', tab)
    QTest.qWait(200)
    find('settingsScroll').property('contentItem').setProperty('contentY', 0)

def scroll_settings_to(name, margin=20):
    QTest.qWait(150)
    scroll = find('settingsScroll').property('contentItem')
    scroll.cancelFlick()
    point = find(name).mapToItem(scroll, QPointF(0, 0))
    top = scroll.property('contentY') + point.y() - margin
    maximum = max(0, scroll.property('contentHeight') - scroll.height())
    scroll.setProperty('contentY', max(0, min(top, maximum)))
    QTest.qWait(300)

def chat():
    backend.desktopPlugins.closePage()
    backend.subagents.closeView()
    window.setProperty('page', 'chat')
    find('webPane').setProperty('opened', False)
    QTest.qWait(300)

try:
    QTest.qWait(800)
    backend._ensure_project(str(workspace))
    project = next(p for p in backend.store.data['projects'] if p['path'] == str(workspace))
    backend.store.data.update(activeProject=project['id'], workspace=str(workspace))
    record = backend._view
    record.id = 'documentation-demo'; record.workspace = str(workspace)
    record.title = local('检查项目并整理报告', 'Review the project and write a report')
    backend._sessions = [{'id': record.id, 'title': record.title, 'workspace': str(workspace)}]
    record.context_usage = {'tokens': 18432, 'contextWindow': 262144, 'percent': 7.03125, 'model': 'workspace-model'}
    messages = [
        {'role': 'user', 'text': local('帮我检查项目结构，整理一份带下一步建议的报告。先只读分析。', 'Review the project structure and prepare a report with next steps. Keep the review read-only.')},
        {'role': 'assistant', 'thinking': local('先读目录与说明，再检查测试入口。把结论和建议分开，避免把工具成功等同于整项任务完成。', 'Read the structure and setup notes, then check test entry points. Separate findings from recommendations.'),
         'text': local('我会先阅读目录与说明，再检查测试和配置。', 'I will read the structure and setup notes, then review tests and configuration.'),
         'tools': [{'id':'docs-list','name':'ls','arguments':{'path':'.'},'state':'done','result':'README.md\nsrc/\ntests/\npackage.json'},
                   {'id':'docs-read','name':'read','arguments':{'path':'README.md'},'state':'done','result':'# Demo project\n\nnpm install\nnpm test'}]},
        {'role': 'assistant', 'stopReason':'stop', 'text':local('项目结构已检查。\n\n- **启动**：依照 README 安装依赖。\n- **验证**：运行现有测试后再修改。\n- **下一步**：补充错误处理的边界测试。\n\n我把结论整理成报告，可以在右侧查看。', 'The structure is reviewed.\n\n- **Setup:** install dependencies as described in README.\n- **Validation:** run existing tests before editing.\n- **Next:** add edge-case tests for error handling.\n\nThe report is ready to inspect in the side pane.')}]
    record.messages = messages
    backend.changed.emit(); backend.chatChanged.emit(); backend.contextUsageChanged.emit(); backend.viewChanged.emit()
    QTest.qWait(300)
    find('conversation').setProperty('followTail', False); find('conversation').setProperty('contentY', 0)
    capture('chat')
    click('toggleThinking_1_0'); click('toggleTools_1_20000')
    find('conversation').setProperty('contentY', 0); capture('process')

    # Actual document reader and renderer, with a local synthetic artifact.
    backend._handle_pi_event(record, {'type':'tool','id':'docs-submit','name':'submit_to_chatbox','args':{},'state':'done',
        'media':[{'kind':'markdown','path':str(report),'title':'report.md'}]})
    wait_for(lambda: not backend.documentPreview.state.get('busy') and not find('webPane').property('moving'), 'Document preview did not settle')
    assert backend.documentPreview.state['mode'] == 'rendered'
    capture('artifact-rendered')
    click('documentMode_source'); capture('artifact-source')
    chat()

    # Native subagent projection: demonstration events, no model process.
    tools = []
    for index, task in enumerate([local('检查目录与配置', 'Review structure and configuration'), local('检查测试覆盖', 'Review test coverage')]):
        child = {'id':f'docs-child-{index}','status':'running' if index else 'completed','avatarSlot':index,'task':task,
                 'activity':local('检查边界测试', 'Checking edge-case tests')}
        backend.subagents.merge(record, child)
        tools.append({'id':'subagent:'+child['id'],'name':'subagent','state':child['status'],'arguments':{},'subagent':child})
    record.messages = [{'role':'user','text':local('请分工检查目录结构和测试覆盖，再汇总。', 'Delegate structure and test coverage reviews, then summarize.')},
        {'role':'assistant','text':local('两个子智能体分别检查中。', 'Two subagents are reviewing the project.'),'tools':tools}]
    backend.chatChanged.emit()
    original_command = backend._command_pi
    backend._command_pi = lambda *unused, **kwargs: True
    backend.subagents.open('docs-child-1')
    backend.subagents.handle(record, {'type':'subagent_context','id':'docs-child-1','messages':[
        {'role':'user','text':local('检查测试覆盖', 'Review test coverage')},
        {'role':'assistant','text':local('正常路径已有测试，我正在检查空输入、错误响应和取消场景。', 'The happy path is covered. I am reviewing empty input, failed responses and cancellation.')}]})
    backend.subagents.handle(record, {'type':'subagent_queue','id':'docs-child-1','items':[
        {'id':'docs-followup','text':local('也检查超时场景。', 'Please check timeouts too.'),'mode':'followUp'}]})
    QTest.qWait(700); capture('subagents'); chat()
    backend._command_pi = original_command
    record.subagents.clear(); record.subagents_active = False
    record.messages = messages; backend.chatChanged.emit()

    # Real Skill host discovers the disposable global/workspace folders.
    assert backend.desktopPlugins.openPage('skill-manager')
    wait_for(lambda: find('skillManagerWidget', True) is not None and
             len(variant(find('skillManagerWidget').property('skills'))) == 4 and
             not find('skillManagerWidget').property('working'),
             lambda: 'Skill manager did not load four real folders: ' + repr({
                 'page': backend.desktopPlugins.page,
                 'notice': find('skillManagerWidget').property('notice') if find('skillManagerWidget', True) else None,
                 'working': find('skillManagerWidget').property('working') if find('skillManagerWidget', True) else None,
                 'roots': str(find('skillManagerWidget').property('roots')) if find('skillManagerWidget', True) else None
             }), seconds=12)
    capture('skills')
    widget = find('skillManagerWidget')
    rows = variant(widget.property('skills'))
    assert len(rows) == 4, rows
    widget.setProperty('contextRow', rows[0])
    expr = QQmlExpression(engine.rootContext(), widget, 'showMenu(contextRow, contextRow.scope, Qt.point(70, 160))')
    expr.evaluate()
    assert not expr.hasError(), expr.error().toString()
    capture('skill-menu')
    chat()

    settings(0); capture('providers')
    click('addCommonProviderButton'); capture('provider-choices')
    click('commonProvider_kimi')
    assert variant(window.findChild(QObject, 'commonProviderDialog').property('selected'))['id'] == 'kimi'
    capture('provider-key')
    window.findChild(QObject, 'commonProviderDialog').close()

    settings(1); capture('api-proxy')
    click('mappingProvider_demo')
    assert find('settingsPage').property('mappingProviderId') == 'demo'
    scroll_settings_to('proxyMappingsSection')
    capture('model-mapping')
    settings(5); scroll_settings_to('interfaceLanguage', margin=80); capture('appearance')
    # Scroll the actual settings viewport to show the theme cards and entry.
    scroll_settings_to('chooseCharacterButton', margin=90)
    capture('themes'); click('chooseCharacterButton'); capture('characters'); click('closeCharacterDialog')
    settings(3); click('openDesktopPluginsButton')
    find('desktopPluginsPage').setProperty('selectedId', 'desktop-pet'); capture('widgets')
    click('backFromDesktopPluginsButton'); click('openPiSettingsButton')
    wait_for(lambda: not backend.piManagement.busy and bool(backend.piManagement.extensions), 'Pi inventory did not load')
    find('piSettingsSearch').setProperty('text', 'MCP')
    QTest.qWait(500); capture('mcp')
    settings(6); capture('about')

    manifest = {'sourceCommit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'applicationVersion':VERSION,'edition':'Python / Qt','language':args.language,'theme':'docs-white',
        'capturedAt':datetime.now(timezone.utc).isoformat(),'viewport':[1440,960],
        'data':'Disposable synthetic project, provider without keys, local Skills and subagent display events. No model requests.',
        'captures':captures}
    (output / f'capture-{args.language}.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
    app.processEvents()
    profile.cleanup()
