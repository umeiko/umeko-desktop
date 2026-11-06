"""Controller integration with an isolated profile and an in-memory ACP child.

No QML window, installed dsh, provider endpoint, user credential store or real
child process is used. The protocol/SDK transport has separate Node fixtures.
"""
import copy
import json
import os
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QProcess
from PySide6.QtTest import QTest

from app import dsh_backend
from app.controller import Controller
from app.controller_runtime import PiControllerMixin


ROOT = Path(__file__).resolve().parents[1]
APP = QCoreApplication.instance() or QCoreApplication([])


class FakeDshProcess:
    """Only the process handle; production pool writes and events remain real."""
    def __init__(self, pool, record, bridge, payload, environment):
        self.record = record
        self.bridge = Path(bridge)
        self.start = copy.deepcopy(payload)
        self.environment = dict(environment)
        self.writes = []
        self.running = True
        record.process = self

    def write(self, data):
        value = json.loads(data)
        self.writes.append(value)
        if value.get("type") == "shutdown":
            self.running = False

    def state(self):
        return QProcess.Running if self.running else QProcess.NotRunning

    def waitForFinished(self, milliseconds):
        return not self.running

    def kill(self):
        self.running = False


class DshBackendTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="umeko-dsh-controller-")))
        self.stack.enter_context(patch.dict(os.environ, {
            "UMEKO_DATA_DIR": str(self.directory / "data"), "UMEKO_LANGUAGE": "zh",
        }))
        # This opaque fixture protector never accesses the operating system's
        # credential store; only the in-memory fixture map contains test keys.
        self.protected = {}
        def protect(value, decrypt=False, account=""):
            if not value:
                return ""
            if decrypt:
                return self.protected[value]
            token = "test-protected-" + str(len(self.protected))
            self.protected[token] = value
            return token
        self.stack.enter_context(patch("app.storage.protect", side_effect=protect))
        self.stack.enter_context(patch("app.provider_plugins.BundledProviders.sync", return_value=[]))
        self.stack.enter_context(patch("app.controller.LocalServer"))
        self.stack.enter_context(patch("app.controller.ReasoningDiscovery.sync_active"))
        self.stack.enter_context(patch("app.gateway.Gateway._events", side_effect=AssertionError("No provider requests in this fixture")))
        self.discovery = self.stack.enter_context(patch("app.dsh_runtime.discover_dsh", return_value={
            "path": str(self.directory / "fake-dsh.js"), "source": "configured",
        }))
        self.stack.enter_context(patch.object(dsh_backend, "npm_environment", side_effect=lambda *_: {
            "PATH": os.environ.get("PATH", ""), "UNRELATED_API_KEY": "do-not-forward-fixture",
        }))
        self.launches = []
        def process(*args):
            handle = FakeDshProcess(*args)
            self.launches.append(handle)
            return handle
        self.stack.enter_context(patch.object(dsh_backend, "DshProcess", side_effect=process))
        self.controllers = []
        self.addCleanup(self.close_controllers)
        self.controller = self.make_controller()
        c = self.controller
        c.store.data.update(selectedProvider="fixture-openai", selectedModel="Alpha", providers=[{
            "id": "fixture-openai", "name": "Fixture OpenAI", "api": "openai",
            "baseUrl": "https://fixture.invalid/v1", "key": "fixture-openai-secret",
            "models": [{"alias": "Alpha", "upstream": "upstream-alpha", "contextWindow": 32000},
                       {"alias": "Beta", "upstream": "upstream-beta", "contextWindow": 64000}],
        }, {
            "id": "fixture-anthropic", "name": "Fixture Anthropic", "api": "anthropic",
            "baseUrl": "https://anthropic.fixture.invalid", "key": "fixture-anthropic-secret",
            "models": [{"alias": "Gamma", "upstream": "upstream-gamma"}],
        }])
        c._view.provider, c._view.model = "fixture-openai", "Alpha"

    def make_controller(self):
        controller = Controller(ROOT)
        self.controllers.append(controller)
        return controller

    def close_controllers(self):
        for controller in reversed(self.controllers):
            controller.close()

    def event(self, kind, controller=None, **values):
        c = controller or self.controller
        c._pool.event.emit(c._view, {"type": kind, **values})

    def start_dsh(self, text="第一条消息"):
        c = self.controller
        self.assertTrue(c.setSessionBackend("dsh"))
        self.assertTrue(c.send(text))
        self.event("dsh_session", sessionId="acp-session-fixture", configOptions=[])
        self.event("dsh_ready")
        return c._view, self.launches[-1]

    def test_default_and_new_chats_keep_pi_and_delegate_to_original_send(self):
        c = self.controller
        self.assertEqual(c.sessionBackend, "pi")
        self.assertTrue(c.canChooseBackend)
        with patch.object(PiControllerMixin, "_send", autospec=True, return_value=True) as send:
            self.assertTrue(c.send("Pi fixture"))
        send.assert_called_once_with(c, "Pi fixture", False)
        self.assertEqual(self.launches, [])
        self.assertTrue(c.setSessionBackend("dsh"))
        c.newSession()
        self.assertEqual(c.sessionBackend, "pi")

    def test_backend_selection_is_limited_to_an_empty_idle_chat(self):
        c = self.controller
        self.assertFalse(c.setSessionBackend("unknown"))
        self.assertTrue(c.setSessionBackend("dsh"))
        self.assertTrue(c.setSessionBackend("pi"))
        for change in ({"id": "existing"}, {"messages": [{"role": "user", "text": "existing"}]}, {"phase": "running"}):
            with self.subTest(change=change):
                record = c._new_view()
                c._activate(record)
                for key, value in change.items():
                    setattr(record, key, value)
                self.assertFalse(c.canChooseBackend)
                self.assertFalse(c.setSessionBackend("dsh"))
                self.assertEqual(c.sessionBackend, "pi")

    def test_mapped_events_persist_and_reopen_the_same_display_history(self):
        c = self.controller
        record, process = self.start_dsh()
        self.event("user_start", text="第一条消息", timestamp=1000)
        self.event("thinking_delta", text="已完成的思考")
        self.event("delta", text="已提交的完整回复")
        self.event("tool", id="tool-fixture", name="bash", state="running", args={"command": "fixture only"})
        self.event("tool", id="tool-fixture", name="bash", state="done", result="本地测试结果")
        self.event("context_usage", usage={"tokens": 123, "contextWindow": 32000})
        self.event("dsh_done", stopReason="end_turn")
        expected = copy.deepcopy(record.messages)
        expected_usage = copy.deepcopy(record.context_usage)
        session_id = record.id
        self.assertEqual([row["role"] for row in expected], ["user", "assistant"])
        self.assertEqual(expected[-1]["text"], "已提交的完整回复")
        self.assertEqual(expected[-1]["thinking"], "已完成的思考")
        self.assertEqual(expected[-1]["tools"][0]["state"], "done")
        c.close()
        self.controllers.remove(c)

        restored = self.make_controller()
        restored.openSession(session_id)
        deadline = time.monotonic() + 3
        while restored._view.messages != expected and time.monotonic() < deadline:
            QTest.qWait(5)
        self.assertEqual(restored._view.messages, expected)
        self.assertEqual(restored.contextUsage, expected_usage)
        self.assertEqual(restored.sessionBackend, "dsh")
        self.assertEqual(restored._view.acp_session_id, "acp-session-fixture")
        self.assertEqual(self.launches[-1].start["action"], "open")
        self.assertEqual(self.launches[-1].start["sessionId"], "acp-session-fixture")
        self.assertEqual(self.launches[-1].start["home"], process.start["home"])
        self.event("dsh_done", restored, stopReason="end_turn")

    def test_busy_messages_are_queued_and_sent_after_dsh_done(self):
        c = self.controller
        record, process = self.start_dsh("第一轮")
        self.assertTrue(c.send("下一轮"))
        self.assertEqual([row["text"] for row in record.queue], ["下一轮"])
        self.assertFalse(any(row.get("type") == "prompt" for row in process.writes))
        self.event("delta", text="第一轮回复")
        self.event("dsh_done", stopReason="end_turn")
        QTest.qWait(1)
        self.assertEqual(record.queue, [])
        prompts = [row for row in process.writes if row.get("type") == "prompt"]
        self.assertEqual([row["text"] for row in prompts], ["下一轮"])
        self.assertEqual([row["text"] for row in record.messages if row["role"] == "user"], ["第一轮", "下一轮"])
        self.assertTrue(record.busy)

    def test_tool_update_refreshes_initially_empty_arguments_and_path_preserving_result(self):
        record, _process = self.start_dsh()
        self.event("tool", id="late-arguments", name="write", state="running", args={})
        tool = record.messages[-1]["tools"][0]
        self.assertEqual((tool["arguments"], tool["path"]), ({}, ""))
        path = str(self.directory / "reported.txt")
        arguments = {"path": path, "content": "完整的写入内容"}
        self.event("tool", id="late-arguments", name="write", state="done",
                   args=arguments, result="文件写入成功")
        self.assertEqual(len(record.messages[-1]["tools"]), 1)
        self.assertEqual(tool["arguments"], arguments)
        self.assertEqual(tool["path"], str(Path(path).resolve()))
        self.assertEqual(tool["state"], "done")
        self.assertEqual(tool["result"], "文件写入成功")

    def test_max_tokens_shows_chinese_error_marks_failed_and_restores_queue(self):
        c = self.controller
        record, process = self.start_dsh()
        self.event("thinking_delta", text="只有思考，尚未提交正文")
        self.assertEqual(record.messages[-1]["text"], "")
        self.assertTrue(c.send("留到稍后的消息"))
        self.event("dsh_done", stopReason="max_tokens")
        QTest.qWait(1)
        reply = record.messages[-1]
        self.assertTrue(reply["error"])
        self.assertIn("输出", reply["text"])
        self.assertIn("上限", reply["text"])
        self.assertTrue(record.failed)
        self.assertFalse(record.busy)
        self.assertEqual(c.store.data["sessionMeta"][record.id]["lastTurn"]["state"], "failed")
        self.assertEqual(record.queue, [])
        self.assertEqual(record.draft, "留到稍后的消息")
        self.assertFalse(any(row.get("type") == "prompt" for row in process.writes))

    def test_approval_allow_and_reject_send_once_ui_response(self):
        c = self.controller
        record, process = self.start_dsh()
        for allowed in (True, False):
            with self.subTest(allowed=allowed):
                identifier = "approval-" + str(allowed)
                self.event("ui_request", id=identifier, method="confirm", title="运行测试命令？")
                self.assertEqual(c.pendingApproval["id"], identifier)
                self.assertFalse(c.canGrantDangerousApproval)
                c.respondApproval(allowed)
                self.assertEqual(process.writes[-1], {"type": "ui_response", "id": identifier, "value": allowed})
                self.assertEqual(record.approval, {})

    def test_stop_sends_cancel_and_returns_queued_message_to_draft(self):
        c = self.controller
        record, process = self.start_dsh()
        c.send("留到稍后")
        self.event("ui_request", id="approval", method="confirm", title="确认？")
        c.stop()
        self.assertEqual(process.writes[-1], {"type": "cancel"})
        self.assertTrue(record.cancelled)
        self.assertEqual(record.approval, {})
        self.event("dsh_done", stopReason="cancelled")
        self.assertFalse(record.busy)
        self.assertEqual(record.queue, [])
        self.assertEqual(record.draft, "留到稍后")
        self.assertEqual(record.messages[-1]["customType"], "umeko-dsh-interruption")
        self.assertEqual(record.messages[-1]["role"], "status")
        self.assertEqual(record.messages[-1]["text"], dsh_backend.INTERRUPTION_STATUS)
        self.assertTrue(record.dsh_interruption_pending)
        self.assertFalse(any(row['role'] == 'assistant' and not row.get('text')
                             and not row.get('thinking') and not row.get('tools') for row in record.messages))
        self.assertFalse(any(row.get("type") == "prompt" for row in process.writes))

    def test_stop_notice_is_separate_from_next_user_text_and_consumed_after_success(self):
        c = self.controller
        record, process = self.start_dsh("先前的任务")
        self.event("thinking_delta", text="尚未完成的思考")
        c.stop()
        self.event("dsh_done", stopReason="cancelled")
        self.assertEqual(record.messages[-2]['stopReason'], 'aborted')
        self.assertEqual(record.messages[-2]['thinking'], '尚未完成的思考')
        self.assertTrue(c._dsh_history.read(record.id)['interruptionPending'])
        self.assertTrue(c.send("1+1 等于几？"))
        prompt = next(row for row in reversed(process.writes) if row['type'] == 'prompt')
        self.assertEqual(prompt['text'], "1+1 等于几？")
        self.assertEqual(prompt['interruptionNotice'], dsh_backend.INTERRUPTION_NOTICE)
        self.assertEqual([row['text'] for row in record.messages if row['role'] == 'user'],
                         ['先前的任务', '1+1 等于几？'])
        self.event('delta', text='2')
        self.event('dsh_done', stopReason='end_turn')
        self.assertFalse(c._dsh_history.read(record.id)['interruptionPending'])
        c.send('下一个问题')
        self.assertEqual(process.writes[-1]['interruptionNotice'], '')

    def test_failed_next_prompt_keeps_pending_stop_notice(self):
        c = self.controller
        record, process = self.start_dsh()
        c.stop()
        self.event('dsh_done', stopReason='cancelled')
        c.send('新的问题')
        self.event('error', message='模型暂时不可用')
        self.event('dsh_done', stopReason='error')
        self.assertTrue(c._dsh_history.read(record.id)['interruptionPending'])
        c.send('再次发送新问题')
        self.assertEqual(process.writes[-1]['interruptionNotice'], dsh_backend.INTERRUPTION_NOTICE)

    def test_model_and_reasoning_changes_reuse_advertised_opaque_config_values(self):
        c = self.controller
        record, process = self.start_dsh()
        opaque_model = '["fixture-openai", "upstream-beta"]'
        self.event("dsh_config", configOptions=[{
            "id": "provider_model", "category": "model", "options": [{"name": "Fixture", "options": [
                {"name": "Beta", "value": opaque_model}]}],
        }, {"id": "reasoning_effort", "options": [
            {"name": "关闭", "value": "off"}, {"name": "高", "value": "high"}]}])
        self.event("dsh_done", stopReason="end_turn")
        c.selectModel("fixture-openai", "Beta")
        self.assertTrue(c.setReasoningEffort("high"))
        self.assertEqual(process.writes[-2:], [
            {"type": "set_config", "configId": "provider_model", "value": opaque_model},
            {"type": "set_config", "configId": "reasoning_effort", "value": "high"},
        ])
        self.assertEqual((record.model, record.reasoning_effort), ("Beta", "high"))
        self.assertFalse(c.setReasoningEffort("invented-effort"))

    def test_missing_runtime_adds_a_chinese_chat_error_without_starting_a_child(self):
        c = self.controller
        self.discovery.return_value = {"path": "", "source": "missing"}
        self.assertTrue(c.setSessionBackend("dsh"))
        self.assertFalse(c.send("测试缺失运行时"))
        self.assertFalse(c.busy)
        self.assertEqual(self.launches, [])
        reply = c._view.messages[-1]
        self.assertTrue(reply["error"])
        self.assertIn("未找到 DeepSeek Harness 运行时", reply["text"])
        self.assertIn("设置", reply["text"])

    def test_profile_patch_references_environment_keys_without_secret_files(self):
        record, process = self.start_dsh()
        home = Path(process.start["home"])
        profile = home / "profiles/acp/cordis.patch.yml"
        patch_text = profile.read_text(encoding="utf-8")
        patch_value = json.loads(patch_text)
        providers = next(row for row in patch_value if row["id"] == "llm-pi-ai")["config"]["providers"]
        self.assertEqual(providers["fixture-openai"]["apiKeyEnv"], "UMEKO_DSH_KEY_0")
        self.assertEqual(providers["fixture-anthropic"]["api"], "anthropic-messages")
        self.assertEqual(process.environment["UMEKO_DSH_KEY_0"], "fixture-openai-secret")
        self.assertEqual(process.environment["UMEKO_DSH_KEY_1"], "fixture-anthropic-secret")
        self.assertNotIn("UNRELATED_API_KEY", process.environment)
        self.assertNotIn("fixture-openai-secret", patch_text)
        self.assertNotIn("fixture-anthropic-secret", patch_text)
        self.assertNotIn("fixture-openai-secret", json.dumps(process.start))
        self.assertEqual([path.relative_to(home).as_posix() for path in home.rglob("*") if path.is_file()],
                         ["profiles/acp/cordis.patch.yml"])

    def test_dsh_exposes_no_compaction_or_session_permission_and_rejects_steering(self):
        c = self.controller
        record, process = self.start_dsh()
        notices = []
        c.toast.connect(notices.append)
        self.assertFalse(c.compactionAvailable)
        self.assertFalse(c.canGrantDangerousApproval)
        self.assertFalse(c.steer("不支持的插话"))
        self.assertEqual(record.queue, [])
        self.assertTrue(any("不支持引导" in notice for notice in notices))
        self.assertFalse(any(row.get("type") == "steer" for row in process.writes))


if __name__ == "__main__":
    unittest.main()
