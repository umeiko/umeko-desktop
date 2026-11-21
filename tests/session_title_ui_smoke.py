"""Real QML title presentation with synthetic data; no Pi or model calls.

Run with python tests/session_title_ui_smoke.py. --before only captures the
instrumented original UI for comparison; it does not assert the fixed behavior.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
temporary = tempfile.TemporaryDirectory(prefix="umeko-title-")
os.environ.update(
    UMEKO_DATA_DIR=temporary.name,
    PI_CODING_AGENT_DIR=temporary.name + "/agent",
    QT_QPA_PLATFORM="offscreen",
    QT_QUICK_BACKEND="software",
    UMEKO_LANGUAGE="zh",
)
from PySide6.QtCore import QObject
from PySide6.QtTest import QTest
from PySide6.QtQml import QQmlExpression, QQmlEngine
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
output = ROOT / "build/title-176"
output.mkdir(parents=True, exist_ok=True)


def evaluate(obj, code):
    expression = QQmlExpression(QQmlEngine.contextForObject(obj), obj, code)
    result = expression.evaluate()[0]
    assert not expression.hasError(), expression.error().toString()
    return result


def find(name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name:
            return item
        stack.extend(item.childItems())
    raise AssertionError(name)


def refresh_title(value):
    backend._sessions[0]["title"] = value
    backend._last_sidebar_rows = None
    backend.sidebarChanged.emit()
    backend.chatChanged.emit()
    QTest.qWait(100)


raw = "去做：\n1. 下载工具\r\n2. 检查结果\t继续\u0085下一步\u2028确保成功\u2029保留记录\u3000中文项目"
try:
    backend._sessions = [
        {"id": backend._view.id, "title": raw, "workspace": ""},
        {"id": "next", "title": "下一条会话：不应被遮挡", "workspace": ""},
    ]
    refresh_title(raw)
    window.setWidth(1100)
    window.setHeight(740)
    window.show()
    QTest.qWait(800)
    title = find("sidebarTitle_" + backend._view.id)
    neighbor = find("sidebarTitle_next")
    header = find("sessionHeaderTitle")
    before = "--before" in sys.argv
    assert window.grabWindow().save(str(output / ("before.png" if before else "after.png")))
    if before:
        print("Baseline line counts:", title.property("lineCount"), header.property("lineCount"))
    else:
        expected = " ".join(raw.split())
        for item in (title, header):
            assert item.property("text") == expected
            assert item.property("lineCount") == 1
            assert item.property("truncated")
        assert title.mapToScene(title.boundingRect().bottomLeft()).y() < neighbor.mapToScene(neighbor.boundingRect().topLeft()).y()
        assert backend._sessions[0]["title"] == raw
        assert backend.sessionTitle == raw

        # Rename still receives the original data, never the normalized display.
        menus = window.findChild(QObject, "sidebarMenus")
        target = {"id": backend._view.id, "kind": "session", "title": raw}
        evaluate(menus, "target = " + json.dumps(target) + "; rename()")
        QTest.qWait(100)
        rename = window.findChild(QObject, "renameInput")
        assert rename.property("text") == raw
        edited = "编辑后的中文\t标题\n下一行"
        rename.setProperty("text", edited)
        backend._session_action = Mock()
        evaluate(menus, "saveRename()")
        backend._session_action.assert_called_once_with("rename", backend._view.id, title=edited)
        assert backend._sessions[0]["title"] == raw

        # Pending navigation uses the same presentation, without changing its data.
        window.setProperty("pendingSidebarTitle", raw)
        window.setProperty("pendingSidebarId", "fixture-pending")
        assert header.property("text") == expected
        assert window.property("pendingSidebarTitle") == raw
        window.setProperty("pendingSidebarId", "")

        cases = [
            " 甲\t\r\n乙\u0085丙\u00a0丁\u1680戊\u2000己\u2028庚\u2029辛\u202f壬\u205f癸\u3000 ",
            "<b>原始标题</b>", "", "普通中文标题", "长标题" * 90,
        ]
        for value in cases:
            refresh_title(value)
            assert find("sidebarTitle_" + backend._view.id).property("text") == " ".join(value.split())
            assert header.property("text") == " ".join(value.split())
            assert backend._sessions[0]["title"] == value

        for scale in (1.0, 1.35, 2.0):
            backend.setFontScale(scale)
            for width in (1060, 1500):
                window.setWidth(width)
                QTest.qWait(120)
                title = find("sidebarTitle_" + backend._view.id)
                neighbor = find("sidebarTitle_next")
                assert title.property("lineCount") == header.property("lineCount") == 1
                assert title.height() <= title.parentItem().height()
                assert title.mapToScene(title.boundingRect().bottomLeft()).y() < neighbor.mapToScene(neighbor.boundingRect().topLeft()).y()
                button = find("minimizeWindowButton")
                assert header.mapToScene(header.boundingRect().bottomRight()).x() <= button.mapToScene(button.boundingRect().topLeft()).x()
        print("Title normalization, elision, geometry, rename and raw data preservation passed")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
    app.processEvents()
    temporary.cleanup()
