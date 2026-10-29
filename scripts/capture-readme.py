"""Capture the real QML interface using isolated, synthetic documentation data."""
import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--language', choices=('zh', 'en'), default='en')
parser.add_argument('--theme-file', type=Path, required=True, help='Portable Umeko theme JSON, without account data')
args = parser.parse_args()
english = args.language == 'en'
def local(zh, en): return en if english else zh
profile = tempfile.TemporaryDirectory(prefix="umeko-docs-")
os.environ.update(UMEKO_DATA_DIR=profile.name, UMEKO_LANGUAGE=args.language, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from app.storage import Store
from app.themes import read_theme
from main import create_application

store = Store()
store.data["agent"].update(agentDir=str(Path(profile.name) / "agent"), safeMode=True)
theme = read_theme(args.theme_file)
store.data['ui'].update(language=args.language, fontScale=1.1)
store.data.update(theme='custom:' + theme['id'], themes=[theme], selectedProvider="demo", selectedModel="workspace-model", providers=[{
    "id": "demo", "name": local('示例供应商', 'My Provider'), "api": "openai", "baseUrl": "https://api.example.com/v1", "key": "",
    "models": [{"upstream": "workspace-model", "alias": "workspace-model", "contextWindow": 262144,
                "contextWindowAuto": False, "vision": True, "visionAuto": False}]}])
store.save()
app, engine, backend = create_application()
window = engine.rootObjects()[0]
window.resize(1480, 960)
output = ROOT / "docs/images"
output.mkdir(parents=True, exist_ok=True)


def find(name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name: return item
        stack.extend(item.childItems())
    return window.findChild(QQuickItem, name)


def click(name):
    QTest.qWait(100)
    item = find(name)
    if item is None: raise RuntimeError(name)
    point = item.mapToScene(QPointF(min(30, item.width() / 2), item.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(150)


def capture(name):
    window.setProperty("notification", "")
    QTest.mouseMove(window, QPointF(window.width() - 10, window.height() - 10).toPoint())
    # Allow background text projection and syntax highlighting to finish too.
    for _ in range(40):
        QTest.qWait(25)
        time.sleep(.005)
    if not window.grabWindow().save(str(output / (name + '-white-' + args.language + ".png"))): raise RuntimeError(name)


try:
    # Let the empty, isolated native index finish before adding display-only rows.
    QTest.qWait(600)
    for name in ("umeko-notes", "design-lab"):
        path = Path(profile.name) / name
        path.mkdir()
        backend._ensure_project(str(path))
    project = backend.store.data["projects"][0]
    backend.store.data.update(activeProject=project["id"], workspace=project["path"])
    backend._view.id = "documentation-demo"
    backend._view.workspace = project["path"]
    backend._sessions = [
        {"id": "documentation-demo", "title": local('搭建一个轻量文档站', 'Build a lightweight documentation site'), "workspace": project["path"]},
        {"id": "search-demo", "title": local('整理搜索与导航', 'Organize search and navigation'), "workspace": project["path"]},
        {"id": "theme-demo", "title": local('探索新的配色方案', 'Explore a new color palette'), "workspace": backend.store.data["projects"][1]["path"]}]
    backend._view.title = backend._sessions[0]['title']
    backend._view.context_usage = {"tokens": 18432, "contextWindow": 262144, "percent": 7.03125, "model": "workspace-model"}
    backend._view.messages = [
        {"role": "user", "text": local('帮我把笔记项目整理成一个轻量文档站，保留 Markdown，并加上搜索。', 'Turn my notes into a lightweight documentation site. Keep the Markdown files and add search.'), "error": False},
        {"role": "assistant", "thinking": local('先检查现有目录，把内容与站点配置分开。保留 Markdown 源文件，使用静态索引，便于离线预览和后续维护。', 'Inspect the notes first, separate content from site configuration, and build a local search index for offline previews.'),
         "text": local('我先检查笔记目录，再整理导航和搜索配置。', 'I will inspect the notes, then set up navigation and search.'), "tools": [
             {"id": "read-notes", "name": "ls", "arguments": {"path": "notes"}, "state": "done", "result": "getting-started.md\narchitecture.md\nideas.md"},
             {"id": "write-site", "name": "write", "arguments": {"path": "site.config.ts"}, "path": "/workspace/umeko-notes/site.config.ts", "state": "done", "result": "Site configuration saved."},
             {"id": "check-site", "name": "bash", "arguments": {"command": "npm run build"}, "state": "done", "result": "Static pages and local search index generated."}]},
        {"role": "assistant", "text": local('文档站的结构已经整理好了。\n\n- **内容保留**：继续在 `notes/` 中编辑 Markdown。\n- **本地搜索**：构建时生成索引，预览时无需外部服务。\n- **清晰导航**：入门、架构与想法分开管理。', 'The documentation site is ready.\n\n- **Your content stays yours:** edit Markdown in `notes/`.\n- **Local search:** the index is generated at build time.\n- **Clear navigation:** separate guides, architecture and ideas.') + "\n\n```typescript\nexport default {\n  title: 'Umeko Notes',\n  contentDir: './notes',\n  search: { provider: 'local' },\n}\n```\n\n" + local('运行 `npm run dev` 即可预览，下一步可以继续调整首页。', 'Run `npm run dev` to preview it. We can refine the home page next.'), "error": False}]
    backend.changed.emit(); backend.chatChanged.emit(); backend.contextUsageChanged.emit(); backend.viewChanged.emit()
    QTest.qWait(400)
    view = find("conversation")
    view.setProperty("followTail", False)
    view.setProperty("contentY", 0)
    capture("chat")

    click("toggleThinking_1_0")
    click("toggleTools_1_20000")
    view.setProperty("followTail", False)
    view.setProperty("contentY", 0)
    capture("process")

    record = backend._view
    tasks = [local('检查导航结构与目录组织', 'Review navigation and folder structure'),
             local('为本地搜索补充测试', 'Add tests for local search'),
             local('整理文档与使用说明', 'Polish the documentation')]
    tools = []
    for index, task in enumerate(tasks):
        child = {'id': 'docs-child-' + str(index), 'status': 'running' if index == 1 else 'completed',
                 'avatarSlot': index, 'task': task, 'activity': local('检查搜索边界情况', 'Checking search edge cases')}
        backend.subagents.merge(record, child)
        tools.append({'id': 'subagent:' + child['id'], 'name': 'subagent', 'state': child['status'], 'arguments': {}, 'subagent': child})
    record.messages = [
        {'role': 'user', 'text': local('请帮我检查文档站，分工检查导航、搜索和说明文档。', 'Review the documentation site. Delegate navigation, search and documentation checks.')},
        {'role': 'assistant', 'text': local('已经安排三个子智能体分别检查。', 'Three subagents are reviewing the site.'), 'tools': tools},
        {'role': 'assistant', 'text': local('导航和文档已完成，搜索测试还在进行。你可以在右侧继续给子智能体补充要求。', 'Navigation and documentation are done. Search tests are still running; you can add instructions in the side pane.')}]
    backend.chatChanged.emit()
    backend._command_pi = lambda *unused, **kwargs: True
    backend.subagents.open('docs-child-1')
    backend.subagents.handle(record, {'type': 'subagent_context', 'id': 'docs-child-1', 'messages': [
        {'role': 'user', 'text': tasks[1]},
        {'role': 'assistant', 'text': local('已覆盖精确匹配、空查询和无结果场景。\n\n正在补充中英文混合检索的测试，完成后会汇报主智能体。', 'Exact matches, empty queries and no-result cases are covered.\n\nI am adding mixed-language search tests, then I will report back to the parent agent.')}]})
    backend.subagents.handle(record, {'type': 'subagent_queue', 'id': 'docs-child-1', 'items': [
        {'id': 'docs-followup', 'text': local('也检查一下离线使用的情况。', 'Please also check offline usage.'), 'mode': 'followUp'}]})
    QTest.qWait(900)
    find('conversation').setProperty('contentY', 0)
    capture('subagents')
    backend.subagents.closeView()
    find('webPane').setProperty('opened', False)

    window.setProperty("page", "settings")
    window.setProperty("settingsTab", 0)
    click("importCustomProviderButton")
    capture("provider")
    print('Captured four real QML screenshots in ' + args.language + '; portable theme and synthetic data only.')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
    profile.cleanup()
