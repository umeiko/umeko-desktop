"""Circle click -> anchored action -> real embedded Pi with a local provider."""
import copy
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("UMEKO_LANGUAGE", "zh")

from PySide6.QtCore import Qt, QUrl, QObject, QProcess
from PySide6.QtGui import QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.controller import Controller
from app.integration import Completion
from app.syntax_highlight import register_text_types
from app.transcript_index import TranscriptRepository


class FixtureProvider:
    ready = True

    def __init__(self):
        self.calls = []
        self.block_next = False
        self.block_summary = False
        self.fail_summary = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def complete(self, model, messages, tools, max_tokens):
        self.calls.append({"messages": copy.deepcopy(messages), "tools": bool(tools)})
        if (tools and self.block_next) or (not tools and self.block_summary):
            self.block_next = self.block_summary = False
            self.entered.set()
            if not self.release.wait(20):
                raise RuntimeError("Fixture provider was not released")
        if not tools and self.fail_summary:
            raise ValueError("测试压缩失败：请稍后重试")
        return Completion("本轮已收到。" if tools else "## 当前任务\n保留测试任务及重要决定。", input_tokens=600, output_tokens=20)


def items(window):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        yield item
        stack.extend(item.childItems())


class ContextCompactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if not QFontDatabase.families() and os.name == "nt":
            QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts/msyh.ttc"))
        register_text_types()
        # Test launchers can inject a hidden-child preload without weakening
        # production's deliberate NODE_OPTIONS filtering.
        preload = os.environ.get("UMEKO_TEST_NODE_PRELOAD")
        if preload:
            from app import pi_runtime
            original = pi_runtime.node_environment
            def hidden_environment(values=None):
                return {**original(values), "NODE_OPTIONS": "--require=" + json.dumps(preload)}
            cls.node_patch = patch.object(pi_runtime, "node_environment", hidden_environment)
            cls.node_patch.start()
            from app import pi_sessions
            class HiddenChildProcess(QProcess):
                def setProcessEnvironment(self, environment):
                    environment.insert("NODE_OPTIONS", "--require=" + json.dumps(preload))
                    super().setProcessEnvironment(environment)
            cls.pool_patch = patch.object(pi_sessions, "QProcess", HiddenChildProcess)
            cls.pool_patch.start()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "node_patch"):
            cls.node_patch.stop()
            cls.pool_patch.stop()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="umeko-context-ui-")
        self.path = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"UMEKO_DATA_DIR": str(self.path / "data")})
        self.env.start()
        agent, workspace = self.path / "agent", self.path / "workspace"
        agent.mkdir(); workspace.mkdir()
        (agent / "settings.json").write_text(json.dumps({"compaction": {"keepRecentTokens": 50, "reserveTokens": 100}}), encoding="utf-8")
        self.backend = Controller(ROOT)
        self.adapter = FixtureProvider()
        self.backend.adapter = self.backend.gateway.adapter = self.adapter
        self.backend.store.data.update(selectedProvider="fixture", selectedModel="Fixture", providers=[{
            "id": "fixture", "name": "Local fixture", "api": "internal", "baseUrl": "", "key": "",
            "models": [{"upstream": "fixture-model", "alias": "Fixture", "contextWindow": 128000}]}])
        self.backend.store.data["agent"].update(agentDir=str(agent), autoCompaction=False)
        self.backend.setWorkspace(QUrl.fromLocalFile(str(workspace)).toString())
        self.backend._view.model, self.backend._view.provider = "Fixture", "fixture"
        self.events, self.notices = [], []
        self.backend._pool.event.connect(lambda _record, event: self.events.append(copy.deepcopy(event)))
        self.backend.toast.connect(self.notices.append)
        self.engine = QQmlApplicationEngine()
        self.engine.rootContext().setContextProperty("backend", self.backend)
        self.engine.load(QUrl.fromLocalFile(str(ROOT / "app/qml/Main.qml")))
        self.assertTrue(self.engine.rootObjects(), "QML failed to load")
        self.window = self.engine.rootObjects()[0]
        self.window.setProperty("page", "chat")
        self.window.setWidth(1300); self.window.setHeight(1000)
        self.backend.changed.emit()
        QTest.qWait(60)

    def tearDown(self):
        self.adapter.release.set()
        self.backend.close()
        self.window.close()
        import shiboken6
        shiboken6.delete(self.engine)
        self.env.stop()
        self.temp.cleanup()

    def wait_for(self, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertTrue(predicate(), {"events": [{key: event[key] for key in ("type", "action", "message", "state") if key in event} for event in self.events[-8:]], "notices": self.notices})

    def find(self, name):
        return next((item for item in items(self.window) if item.objectName() == name), None)

    def click(self, name):
        self.wait_for(lambda: self.find(name) is not None and self.find(name).isVisible())
        item = self.find(name)
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())
        QTest.qWait(30)

    def enter(self, text):
        prompt = self.find("promptInput")
        prompt.setProperty("text", text); prompt.forceActiveFocus()
        QTest.keyClick(self.window, Qt.Key_Return)
        QTest.qWait(20)

    def send_and_wait(self, text):
        count = len([event for event in self.events if event.get("type") == "done"])
        self.enter(text)
        self.wait_for(lambda: len([e for e in self.events if e.get("type") == "done"]) > count and not self.backend.busy)

    def seed(self):
        for index in range(3):
            self.send_and_wait(f"任务材料 {index}：" + "fixture information " * 180)

    def open_popup(self):
        popup = self.window.findChild(QObject, "compactContextPopup")
        if popup is not None and popup.property("visible") and not popup.property("desiredOpen"):
            self.wait_for(lambda: not popup.property("visible"))
        self.click("contextUsageMouse")
        self.wait_for(lambda: (popup := self.window.findChild(QObject, "compactContextPopup")) is not None
                      and popup.property("visible") and popup.property("contentOpacity") > 0.98)

    def event_row(self):
        return next((item for item in items(self.window)
                     if item.objectName().startswith("compactionEvent_") and item.isVisible()), None)

    def begin_compaction(self):
        self.adapter.release.clear(); self.adapter.entered.clear(); self.adapter.block_summary = True
        self.open_popup()
        self.assertTrue(self.find("compactContextAction").isEnabled())
        self.click("compactContextAction")
        self.wait_for(self.adapter.entered.is_set)
        self.wait_for(lambda: self.event_row() is not None and self.event_row().property("eventState") == "running")
        row = self.event_row()
        self.assertTrue(self.backend.compacting)
        name = row.objectName()
        index = name.rsplit("_", 1)[1]
        self.click("compactionEventToggle_" + index)
        self.wait_for(lambda: row.property("expanded"))
        self.assertTrue(self.find("compactionEventDetails_" + index).isVisible())
        return row, name, index

    def assert_local_style(self, index):
        for prefix in ("assistantAvatar_", "messageBubble_", "messageActions_", "replyEndMascot_"):
            item = self.find(prefix + index)
            self.assertIsNotNone(item, prefix)
            self.assertFalse(item.isVisible(), prefix)

    def assert_finished(self, state, row, name, index):
        self.adapter.release.set()
        self.wait_for(lambda: not self.backend.busy and row.property("eventState") == state)
        self.assertIs(self.find(name), row, "Terminal result must update the original QML row")
        self.assertTrue(row.property("expanded"), "Updating a result must preserve disclosure state")
        self.assertEqual(len([item for item in items(self.window) if item.objectName().startswith("compactionEvent_") and item.isVisible()]), 1)
        self.assert_local_style(index)
        entries = [json.loads(line) for line in Path(self.backend._view.file).read_text(encoding="utf-8").splitlines()]
        events = [entry for entry in entries if entry.get("customType") == "umeko-compaction"]
        self.assertEqual([entry["data"]["state"] for entry in events], ["running", state])
        self.assertEqual(events[0]["data"]["eventId"], events[-1]["data"]["eventId"])
        self.assertEqual(events[-1]["data"]["version"], 2)
        self.assertNotIn("umeko-compaction", json.dumps([call["messages"] for call in self.adapter.calls], ensure_ascii=False))
        return events[-1]["data"]

    def test_circle_compacts_in_place_and_busy_action_is_disabled(self):
        self.seed()
        self.send_and_wait("/compact ordinary composer message")
        self.assertFalse(any(not call["tools"] for call in self.adapter.calls), "Slash input must remain an ordinary model message")
        self.assertIn("/compact ordinary composer message", json.dumps(self.adapter.calls[-1]["messages"]))
        self.adapter.block_next = True
        self.enter("继续当前任务")
        self.wait_for(self.adapter.entered.is_set)
        self.open_popup()
        self.assertFalse(self.find("compactContextAction").isEnabled())
        self.backend.compactSession()
        self.assertFalse(any(not call["tools"] for call in self.adapter.calls))
        self.adapter.release.set()
        self.wait_for(lambda: not self.backend.busy)
        self.click("contextUsageMouse")  # close the still-open popup
        row, name, index = self.begin_compaction()
        self.open_popup()
        self.assertFalse(self.find("compactContextAction").isEnabled())
        self.click("contextUsageMouse")
        details = self.assert_finished("success", row, name, index)
        self.assertIn("保留测试任务", details["summary"])
        self.assertIsInstance(details["before"], (int, float))
        self.assertTrue(details["afterEstimated"])
        self.click("compactionEventToggle_" + index)
        self.assertFalse(row.property("expanded"))
        repository = TranscriptRepository(self.path / "cold-cache")
        self.backend._view.transcript = repository.open(Path(self.backend._view.file))
        self.backend._view.messages = []
        self.backend.chatChanged.emit()
        self.wait_for(lambda: self.event_row() is not None and self.event_row().property("eventState") == "success")
        self.assertFalse(self.event_row().property("expanded"))
        cold_index = self.event_row().objectName().rsplit("_", 1)[1]
        self.click("compactionEventToggle_" + cold_index)
        self.wait_for(lambda: self.event_row().property("expanded"))
        self.assertIn("保留测试任务", self.find("compactionEventDetails_" + cold_index).property("text"))

    def test_failure_updates_the_running_row(self):
        self.seed()
        self.adapter.fail_summary = True
        row, name, index = self.begin_compaction()
        details = self.assert_finished("failure", row, name, index)
        self.assertTrue(details["error"])
        self.assertFalse(details["summary"])
        self.assertNotIn("Traceback", self.find("compactionEventDetails_" + index).property("text"))


if __name__ == "__main__":
    if "--mutation" in sys.argv:
        sys.argv.remove("--mutation")
        from app.controller_runtime import PiControllerMixin
        original = PiControllerMixin._request_compaction
        with patch.object(PiControllerMixin, "_request_compaction", lambda self: False):
            result = unittest.main(exit=False).result
        print("MUTATION_RESTORED=" + str(PiControllerMixin._request_compaction is original))
        sys.exit(0 if result.wasSuccessful() else 1)
    unittest.main()
