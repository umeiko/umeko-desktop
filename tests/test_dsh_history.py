"""Real Store/controller history round trip; no runtime or model calls."""
import copy
import time
import unittest

from PySide6.QtTest import QTest

from app import dsh_backend

try:
    from . import test_dsh_backend as backend_fixture
except ImportError:
    import test_dsh_backend as backend_fixture


class DshHistoryTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing isolated Store, opaque credential protector and
        # in-memory DSH process without inheriting or rerunning its tests.
        self.fixture = backend_fixture.DshBackendTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def test_reopen_preserves_text_thinking_tool_cards_and_cancelled_turn(self):
        fixture = self.fixture
        controller = fixture.controller
        record, process = fixture.start_dsh("请保存并总结这份记录。")
        fixture.event("thinking_delta", text="先保存原文，再汇报结果。")
        fixture.event("delta", text="记录已保存，原文和结果如下。")
        fixture.event("tool", id="history-write", name="write", state="running", args={})
        arguments = {"path": str(fixture.directory / "notes.txt"), "content": "需要保留的完整原文"}
        fixture.event("tool", id="history-write", name="write", state="done",
                      args=arguments, result="文件保存成功：保留原文")
        fixture.event("dsh_done", stopReason="end_turn")
        completed = copy.deepcopy(record.messages[-1])
        self.assertEqual(completed["text"], "记录已保存，原文和结果如下。")
        self.assertEqual(completed["thinking"], "先保存原文，再汇报结果。")
        self.assertEqual(completed["tools"][0]["arguments"], arguments)
        self.assertEqual(completed["tools"][0]["result"], "文件保存成功：保留原文")

        self.assertTrue(controller.send("再整理一版详细说明。"))
        fixture.event("thinking_delta", text="这一轮在正文提交前被用户取消。")
        controller.stop()
        fixture.event("dsh_done", stopReason="cancelled")
        cancelled = next(row for row in reversed(record.messages) if row.get("role") == "assistant")
        self.assertEqual(cancelled["stopReason"], "aborted")
        self.assertEqual(cancelled["thinking"], "这一轮在正文提交前被用户取消。")
        notice = record.messages[-1]
        self.assertEqual(notice["role"], "status")
        self.assertEqual(notice["customType"], "umeko-dsh-interruption")
        # The chat keeps the short status; the full instruction goes only to the model.
        self.assertEqual(notice["text"], dsh_backend.INTERRUPTION_STATUS)
        self.assertTrue(record.dsh_interruption_pending)
        self.assertEqual(controller._turn_status(record)["state"], "stopped")
        expected = copy.deepcopy(record.messages)
        session_id = record.id
        controller.close()  # Flush the production ordered history writer.
        fixture.controllers.remove(controller)

        restored = fixture.make_controller()
        restored.openSession(session_id)
        deadline = time.monotonic() + 3
        while restored._view.messages != expected and time.monotonic() < deadline:
            QTest.qWait(5)
        self.assertEqual(restored._view.messages, expected)
        self.assertEqual(restored._view.messages[1], completed)
        restored_cancelled = next(row for row in reversed(restored._view.messages) if row.get("role") == "assistant")
        self.assertEqual(restored_cancelled["stopReason"], "aborted")
        self.assertEqual(restored._view.messages[-1], notice)
        self.assertTrue(restored._view.dsh_interruption_pending)
        self.assertEqual(fixture.launches[-1].start["sessionId"], record.acp_session_id)
        fixture.event("dsh_ready", restored)
        fixture.event("dsh_done", restored, stopReason="end_turn")
        self.assertEqual(restored._turn_status(restored._view)["state"], "stopped")
        self.assertTrue(restored._view.dsh_interruption_pending, "Opening ACP must not consume the pending interruption")
        self.assertFalse(any(
            row.get("role") == "assistant" and not row.get("text") and not row.get("tools")
            and row.get("stopReason") != "aborted" and not row.get("error")
            for row in restored._view.messages
        ), "A bodyless cancelled reply must not become a blank completed turn on reopen")
        new_text = "请只回答这一个新问题。"
        self.assertTrue(restored.send(new_text))
        prompt = fixture.launches[-1].writes[-1]
        self.assertEqual(prompt["type"], "prompt")
        self.assertEqual(prompt["text"], new_text)
        self.assertEqual(prompt["interruptionNotice"], dsh_backend.INTERRUPTION_NOTICE)
        self.assertEqual(restored._view.messages[-2]["text"], new_text)
        self.assertEqual(sum(row.get("customType") == "umeko-dsh-interruption" for row in restored._view.messages), 1)
        self.assertTrue(restored._view.dsh_interruption_pending)
        fixture.event("delta", restored, text="新问题的回复。")
        fixture.event("dsh_done", restored, stopReason="end_turn")
        self.assertFalse(restored._view.dsh_interruption_pending)


if __name__ == "__main__":
    unittest.main()
