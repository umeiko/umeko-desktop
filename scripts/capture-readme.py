"""Capture the real QML interface using isolated, synthetic documentation data."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
profile = tempfile.TemporaryDirectory(prefix="umeko-docs-")
os.environ.update(UMEKO_DATA_DIR=profile.name, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from app.storage import Store
from main import create_application

store = Store()
store.data["agent"].update(agentDir=str(Path(profile.name) / "agent"), safeMode=True)
store.data.update(theme="yanami", selectedProvider="demo", selectedModel="workspace-model", providers=[{
    "id": "demo", "name": "My Provider", "api": "openai", "baseUrl": "https://api.example.com/v1", "key": "",
    "models": [{"upstream": "workspace-model", "alias": "workspace-model", "contextWindow": 262144,
                "contextWindowAuto": False, "vision": True, "visionAuto": False}]}])
store.save()
app, engine, backend = create_application()
window = engine.rootObjects()[0]
window.resize(1320, 860)
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
    QTest.qWait(500)
    if not window.grabWindow().save(str(output / (name + ".png"))): raise RuntimeError(name)


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
        {"id": "documentation-demo", "title": "搭建一个轻量文档站", "workspace": project["path"]},
        {"id": "search-demo", "title": "整理搜索与导航", "workspace": project["path"]},
        {"id": "theme-demo", "title": "探索新的配色方案", "workspace": backend.store.data["projects"][1]["path"]}]
    backend._view.context_usage = {"tokens": 18432, "contextWindow": 262144, "percent": 7.03125, "model": "workspace-model"}
    backend._view.messages = [
        {"role": "user", "text": "帮我把笔记项目整理成一个轻量文档站，保留 Markdown，并加上搜索。", "error": False},
        {"role": "assistant", "thinking": "先检查现有目录，把内容与站点配置分开。保留 Markdown 源文件，使用静态索引，便于离线预览和后续维护。",
         "text": "我先检查笔记目录，再整理导航和搜索配置。", "tools": [
             {"id": "read-notes", "name": "ls", "arguments": {"path": "notes"}, "state": "done", "result": "getting-started.md\narchitecture.md\nideas.md"},
             {"id": "write-site", "name": "write", "arguments": {"path": "site.config.ts"}, "path": "/workspace/umeko-notes/site.config.ts", "state": "done", "result": "Site configuration saved."},
             {"id": "check-site", "name": "bash", "arguments": {"command": "npm run build"}, "state": "done", "result": "Static pages and local search index generated."}]},
        {"role": "assistant", "text": "文档站的结构已经整理好了。\n\n- **内容保留**：继续在 `notes/` 中编辑 Markdown。\n- **本地搜索**：构建时生成索引，预览时无需外部服务。\n- **清晰导航**：入门、架构与想法分开管理。\n\n```typescript\nexport default {\n  title: 'Umeko Notes',\n  contentDir: './notes',\n  search: { provider: 'local' },\n}\n```\n\n运行 `npm run dev` 即可预览，下一步可以继续调整首页。", "error": False}]
    backend.changed.emit(); backend.chatChanged.emit(); backend.contextUsageChanged.emit(); backend.viewChanged.emit()
    QTest.qWait(400)
    view = find("conversation")
    view.setProperty("followTail", False)
    view.setProperty("contentY", 0)
    capture("chat-yanami")

    backend.setTheme("dark")
    click("toggleThinking_1_0")
    click("toggleTools_1_20000")
    view.setProperty("followTail", False)
    view.setProperty("contentY", 0)
    capture("chat-process")

    backend.setTheme("light")
    window.setProperty("page", "settings")
    window.setProperty("settingsTab", 0)
    click("importCustomProviderButton")
    capture("provider-import")
    print("Captured three real QML screenshots with synthetic data; no inference requests made.")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
    profile.cleanup()
