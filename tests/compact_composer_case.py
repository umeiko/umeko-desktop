"""QML Enter -> desktop dispatch -> real Pi, using an in-process provider."""
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("UMEKO_LANGUAGE", "zh")

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.controller import Controller
from app.integration import Completion
from app.syntax_highlight import register_text_types
from app.transcript_index import TranscriptRepository

ROOT = Path(__file__).resolve().parents[1]


class ComposerAdapter:
    ready = True

    def __init__(self):
        self.calls = []
        self.block_next = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.fail_summary = False

    def complete(self, model, messages, tools, max_tokens):
        self.calls.append({"model": model, "messages": copy.deepcopy(messages), "tools": bool(tools)})
        if tools and self.block_next:
            self.block_next = False
            self.entered.set()
            if not self.release.wait(15):
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


class CompactComposerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if not QFontDatabase.families() and os.name == "nt":
            QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts/msyh.ttc"))
        register_text_types()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="umeko-composer-")
        self.path = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"UMEKO_DATA_DIR": str(self.path / "data")})
        self.env.start()
        agent = self.path / "agent"
        agent.mkdir()
        (agent / "settings.json").write_text(json.dumps({"compaction": {"keepRecentTokens": 50, "reserveTokens": 100}}), encoding="utf-8")
        self.backend = Controller(ROOT)
        self.adapter = ComposerAdapter()
        self.backend.adapter = self.backend.gateway.adapter = self.adapter
        self.backend.store.data.update(selectedProvider="fixture", selectedModel="Fixture", providers=[{
            "id": "fixture", "name": "Local fixture", "api": "internal", "baseUrl": "", "key": "",
            "models": [{"upstream": "fixture-model", "alias": "Fixture", "contextWindow": 128000}]}])
        self.backend.store.data["agent"].update(agentDir=str(agent), autoCompaction=False)
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
        self.assertTrue(predicate(), {"events": [{key: event[key] for key in ("type", "action", "message", "mode") if key in event} for event in self.events[-8:]], "notices": self.notices})

    def enter(self, text):
        prompt = next(item for item in items(self.window) if item.objectName() == "promptInput")
        prompt.setProperty("text", text)
        prompt.forceActiveFocus()
        QTest.keyClick(self.window, Qt.Key_Return)
        QTest.qWait(20)

    def seed(self):
        for index in range(3):
            count = len([e for e in self.events if e.get("type") == "done"])
            self.enter(f"任务材料 {index}：" + "fixture information " * 180)
            self.wait_for(lambda: len([e for e in self.events if e.get("type") == "done"]) > count and not self.backend.busy)

    def assert_compacted(self, instructions):
        self.wait_for(lambda: any(e.get("type") == "compaction_result" for e in self.events) and not self.backend.busy)
        result = next(e for e in reversed(self.events) if e.get("type") == "compaction_result")
        self.assertEqual(result["mode"], "manual")
        self.assertIsInstance(result["before"], (int, float))
        self.assertIsInstance(result["after"], (int, float))
        self.assertTrue(result["entryId"])
        summaries = [call for call in self.adapter.calls if not call["tools"]]
        self.assertTrue(summaries, "Native compaction did not call the provider")
        self.assertIn(instructions, json.dumps(summaries[-1]["messages"], ensure_ascii=False))
        for call in self.adapter.calls:
            self.assertNotIn("/compact", json.dumps(call["messages"], ensure_ascii=False))
        self.wait_for(lambda: any("已压缩：" in str(item.property("text") or "") for item in items(self.window)))
        entries = [json.loads(line) for line in Path(self.backend._view.file).read_text(encoding="utf-8").splitlines()]
        notices = [entry for entry in entries if entry.get("type") == "custom" and entry.get("customType") == "umeko-compaction"]
        self.assertTrue(notices, "Compaction notice was not persisted in native history")
        self.assertEqual(notices[-1]["data"]["version"], 1)
        self.assertEqual(notices[-1]["data"]["before"], result["before"])
        self.assert_notice_style()

    def assert_notice_style(self):
        self.wait_for(lambda: any(item.objectName().startswith("compactionNotice_") and item.isVisible()
                                 for item in items(self.window)))
        notice = next(item for item in items(self.window)
                      if item.objectName().startswith("compactionNotice_") and item.isVisible())
        self.assertIn("已压缩：", notice.property("text"))
        self.assertFalse(notice.property("continuable"))
        index = notice.objectName().rsplit("_", 1)[1]
        for prefix in ("assistantAvatar_", "messageBubble_", "messageActions_", "replyEndMascot_"):
            row_item = next(item for item in items(self.window) if item.objectName() == prefix + index)
            self.assertFalse(row_item.isVisible(), prefix + " must not render for a local notice")

    def test_enter_dispatches_idle_compact_with_instructions(self):
        self.seed()
        self.enter("  /compact\t保留当前任务  ")
        self.assert_compacted("保留当前任务")
        # Rebuild the display from disk, without the live record's messages or cache.
        repository = TranscriptRepository(self.path / "cold-cache")
        self.backend._view.transcript = repository.open(Path(self.backend._view.file))
        self.backend._view.messages = []
        self.backend.chatChanged.emit()
        self.assert_notice_style()

    def test_busy_enter_queues_compact_until_original_turn_finishes(self):
        self.seed()
        self.adapter.block_next = True
        self.enter("继续当前任务")
        self.wait_for(self.adapter.entered.is_set)
        summaries_before = len([call for call in self.adapter.calls if not call["tools"]])
        self.enter("/compact 保留队列中的目标")
        self.assertEqual(self.backend._view.pending_compactions, ["保留队列中的目标"])
        self.assertIn("等待当前任务结束后压缩上下文", self.backend.toolStatus)
        self.assertEqual(len([call for call in self.adapter.calls if not call["tools"]]), summaries_before)
        self.adapter.release.set()
        self.assert_compacted("保留队列中的目标")
        self.assertEqual(self.backend._view.pending_compactions, [])

    def test_compaction_failure_is_shown_as_plain_text(self):
        self.seed()
        self.adapter.fail_summary = True
        self.enter("/compact 保留错误测试")
        self.wait_for(lambda: bool(self.notices) and not self.backend.busy)
        text = self.notices[-1]
        self.assertIn("供应商请求失败", text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("<html", text)
        self.assertNotIn('{"', text)
        self.assertFalse(any(e.get("type") == "compaction_result" for e in self.events))


if __name__ == "__main__":
    if "--mutation" in sys.argv:
        sys.argv.remove("--mutation")
        from app.controller_runtime import PiControllerMixin
        original = PiControllerMixin._send
        def broken(self, text, steering=False):
            if text.strip().startswith("/compact"):
                return False
            return original(self, text, steering)
        with patch.object(PiControllerMixin, "_send", broken):
            result = unittest.main(exit=False).result
        print("MUTATION_RESTORED=" + str(PiControllerMixin._send is original))
        sys.exit(0 if result.wasSuccessful() else 1)
    unittest.main()
