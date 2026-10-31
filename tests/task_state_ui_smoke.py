"""Render task lifecycle labels with deterministic events and no model calls."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ["UMEKO_LANGUAGE"] = "zh"
profile = tempfile.TemporaryDirectory(prefix="umeko-task-state-ui-")
os.environ["UMEKO_DATA_DIR"] = profile.name

from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlComponent
from PySide6.QtTest import QTest
from app.storage import Store
from main import create_application

app, engine, backend = create_application()
assert engine.rootObjects(), "Actual Main.qml did not load"
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))


def find(name, root=None):
    pending = [root if root is not None else window.contentItem()]
    while pending:
        item = pending.pop()
        if item.objectName() == name:
            return item
        pending.extend(item.childItems())
    raise AssertionError("Missing rendered item: " + name)


def settle():
    QTest.qWait(150)


def live_turn(session_id, phase="running"):
    record = backend._view
    record.id, record.title = session_id, "Task status fixture"
    record.action, record.phase, record.ready = "prompt", phase, True
    record.failed, record.cancelled = False, False
    record.prompt_started = time.monotonic() - 12
    record.messages = [{"role": "user", "text": "Fixture task", "error": False},
        {"role": "assistant", "text": "Fixture response", "error": False}]
    backend._pool.touch(record, current=True)
    backend._index_record(record)
    backend.changed.emit()
    backend.chatChanged.emit()
    settle()
    return record


def assert_turn(state, label, icon=None):
    status = find("turnStatus")
    assert status.isVisible(), "Conversation task status is hidden"
    assert status.property("state") == state, status.property("state")
    text = find("taskStatusText", status)
    assert text.isVisible() and label in text.property("text"), text.property("text")
    spinner = find("taskStatusSpinner", status)
    assert spinner.isVisible() == (state in ("running", "stopping"))
    if icon:
        glyph = find("taskStatusIcon", status)
        assert glyph.isVisible() and glyph.property("name") == icon
    composer_status = find("composerTaskStatus")
    composer_label = find("taskStatusText", composer_status)
    assert label in composer_label.property("text"), composer_label.property("text")
    if not backend.loading:
        shortcut = find("composerStatus")
        assert "Enter" in shortcut.property("text"), "Task label removed the keyboard hint"


def check_turn_lifecycle():
    settle()
    # Prompt startup must already show a running label and active indicator.
    record = live_turn("ui-finished", phase="loading")
    assert_turn("running", "运行中")
    record.phase = "running"
    backend._handle_pi_event(record, {"type": "done"})
    settle()
    assert_turn("finished", "已完成", "check")

    record = live_turn("ui-failed")
    backend._handle_pi_event(record, {"type": "error", "message": "Fixture provider error"})
    backend._handle_pi_event(record, {"type": "done"})
    settle()
    assert_turn("failed", "失败", "x")

    record = live_turn("ui-stopped")
    backend.stop()
    settle()
    assert_turn("stopping", "正在停止")
    backend._handle_pi_event(record, {"type": "done"})
    settle()
    assert_turn("stopped", "已停止", "stop")

    # A background completion keeps its terminal marker and unread distinction.
    background = live_turn("ui-background")
    backend._activate(backend._new_view())
    backend._handle_pi_event(background, {"type": "done"})
    settle()
    sidebar = find("sessionStatus_ui-background")
    assert sidebar.isVisible()
    assert sidebar.property("state") == "finished"
    assert sidebar.property("unread") is True
    assert not find("taskStatusSpinner", sidebar).isVisible()
    assert find("taskStatusIcon", sidebar).property("name") == "check"
    assert not backend.running

    # Recreate the view from history and the real saved metadata, with no Pi launch.
    row = next(row for row in backend._sessions if row["id"] == background.id)
    row["messages"] = copy.deepcopy(background.messages)
    backend._pool.records.pop(background.key)
    backend.store = Store(backend.store.directory)
    backend.setConversationVisible(True)
    with patch.object(backend, "_command_pi", return_value=True):
        backend.openSession(background.id)
    settle()
    assert backend._view is not background
    assert not backend.running
    assert_turn("finished", "已完成", "check")
    assert find("sessionStatus_ui-background").property("unread") is False
    assert not warnings, "\n".join(warnings)
    print("TASK_STATE_UI_OK: live spinner, terminal labels, background unread and persisted history", flush=True)


def check_child_status_and_translations():
    components, items = [], []

    def create(filename, properties):
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(ROOT / "app/qml" / filename)))
        component.setParent(engine)
        components.append(component)
        item = component.createWithInitialProperties(properties)
        assert item is not None, "\n".join(error.toString() for error in component.errors())
        item.setParent(engine)
        items.append(item)
        return item

    original_language = backend.store.data["ui"]["language"]
    try:
        child = create("SubagentTile.qml", {"agent": {"id": "fixture-child", "status": "running"}, "showStatus": False})
        status = create("TaskStatus.qml", {"status": {"state": "running", "elapsed": 12}})
        labels = {
            "zh": {"running": "运行中", "stopping": "正在停止", "finished": "已完成", "failed": "失败", "stopped": "已停止"},
            "en": {"running": "Running", "stopping": "Stopping", "finished": "Done", "failed": "Failed", "stopped": "Stopped"},
        }
        for language, expected in labels.items():
            backend.store.data["ui"]["language"] = language
            backend.appearanceChanged.emit()
            for state, label in expected.items():
                status.setProperty("status", {"state": state, "elapsed": 12})
                QTest.qWait(10)
                assert status.property("label") == label, (language, state, status.property("label"))
            for state, outcome in (("running", "running"), ("completed", "finished"), ("error", "failed"), ("stopped", "stopped")):
                child.setProperty("agent", {"id": "fixture-child", "status": state, "name": "Fixture child", "task": "Fixture task"})
                QTest.qWait(10)
                label = expected[outcome]
                title = child.findChild(QObject, "subagentTitle_fixture-child")
                assert title is not None
                assert child.property("showStatus") is False
                assert child.property("statusLabel") == label, (language, state, child.property("statusLabel"))
                assert title.property("visible") and label in title.property("text"), title.property("text")
        assert not warnings, "\n".join(warnings)
        print("TASK_STATE_EXTRA_UI_OK: inline child outcomes and Chinese/English labels", flush=True)
    finally:
        backend.store.data["ui"]["language"] = original_language
        backend.appearanceChanged.emit()


def check_legacy_unread():
    backend._sessions.append({"id": "legacy-unread", "title": "Older unread session", "file": "", "workspace": ""})
    backend.store.data['sessionMeta']['legacy-unread'] = {'unread': True}
    backend.changed.emit()
    backend.chatChanged.emit()
    settle()
    status = find('sessionStatus_legacy-unread')
    assert status.isVisible() and status.property('state') == 'unread'
    assert find('taskStatusText', status).property('text') == '未读'
    assert find('taskStatusIcon', status).property('name') == 'chat'
    print('LEGACY_UNREAD_UI_OK', flush=True)


try:
    if "--legacy-only" not in sys.argv and "--extra-only" not in sys.argv:
        check_turn_lifecycle()
    if "--legacy-only" not in sys.argv:
        check_child_status_and_translations()
    if "--extra-only" not in sys.argv:
        check_legacy_unread()
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
    app.processEvents()
    profile.cleanup()
