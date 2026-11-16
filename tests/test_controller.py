import os
import subprocess
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from app.controller import Controller
from app.storage import Store
from tests.test_session_files import wait

ROOT = Path(__file__).resolve().parents[1]


class KernelUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtCore import QCoreApplication
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_live_partial_failure_keeps_error_report_independent_from_prose(self):
        from app.chat_model import ChatModel
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": temp}):
            controller = Controller(ROOT)
            try:
                record = controller._view
                record.messages = [{'role':'assistant','text':'partial response'}]
                failure = 'Provider failed [Umeko:12345678-1234-1234-1234-123456789abc]'
                controller._handle_pi_event(record, {'type':'message','role':'assistant',
                    'text':'partial response','error':failure,'stopReason':'error'})
                self.assertEqual(record.messages[-1]['errorMessage'], failure)
                row = ChatModel.project(record.messages)[-1]
                self.assertEqual(row['diagnosticId'], '12345678-1234-1234-1234-123456789abc')
                self.assertEqual(row['activity'][0]['text'], 'partial response')
                self.assertTrue(row['activity'][-1]['error'])
                # Exceptions which bypass message_end must retain the same link.
                controller._handle_pi_event(record, {'type':'error','message':failure})
                self.assertEqual(ChatModel.project(record.messages)[-1]['diagnosticId'], row['diagnosticId'])
                self.assertEqual(record.messages[-1]['text'], 'partial response')
            finally:
                controller.close()

    def setUp(self):
        # Bundled release resources are covered by their own lifecycle tests.
        bundles = patch("app.provider_plugins.BundledProviders.sync", return_value=[])
        bundles.start()
        self.addCleanup(bundles.stop)

    def test_delete_session_removes_only_recent_image_sidecar(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": temp}):
            controller = Controller(ROOT)
            try:
                sessions = controller.store.directory / 'pi' / 'sessions'
                sessions.mkdir(parents=True, exist_ok=True)
                native = sessions / 'history.jsonl'
                native.write_text('fixture', encoding='utf-8')
                archive = Path(str(native) + '.images')
                archive.mkdir()
                (archive / 'entry.png').write_bytes(b'private image fixture')
                unrelated = sessions / 'unrelated.images'
                unrelated.mkdir()
                (unrelated / 'keep.png').write_bytes(b'keep')
                regular_file = sessions / 'regular.jsonl.images'
                regular_file.write_text('keep', encoding='utf-8')
                controller._view.id = 'other'
                controller._sessions = [{'id': 'history', 'file': str(native)}]
                controller.deleteSession('history')
                wait(lambda: not controller.sessionFiles.busy)
                self.assertFalse(native.exists())
                self.assertFalse(archive.exists())
                self.assertTrue((unrelated / 'keep.png').exists())
                self.assertTrue(regular_file.exists())

                external = Path(temp) / 'external'
                external.mkdir()
                (external / 'keep.png').write_bytes(b'keep')
                linked_native = sessions / 'linked.jsonl'
                linked_native.write_text('fixture', encoding='utf-8')
                linked_archive = Path(str(linked_native) + '.images')
                try:
                    linked_archive.symlink_to(external, target_is_directory=True)
                except (OSError, NotImplementedError):
                    pass
                else:
                    controller._sessions = [{'id': 'linked', 'file': str(linked_native)}]
                    controller.deleteSession('linked')
                    wait(lambda: not controller.sessionFiles.busy)
                    self.assertTrue((external / 'keep.png').exists())
            finally:
                controller.close()

    def test_project_archive_preserves_history_and_delete_erases_only_managed_history(self):
        from PySide6.QtCore import QUrl
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": str(Path(temp) / "data")}):
            workspace = Path(temp) / "existing-project"
            workspace.mkdir()
            source = workspace / "source.txt"
            source.write_text("project files remain untouched", encoding="utf-8")
            native = Path(temp) / "data/pi/sessions/fixture.jsonl"
            native.parent.mkdir(parents=True)
            native.write_text("native history", encoding="utf-8")
            controller = Controller(ROOT)
            try:
                project = controller._ensure_project(workspace, reopen=True)
                session = {"id": "history", "title": "Previous chat", "workspace": str(workspace), "file": str(native)}
                controller._sessions = [session]
                controller._view.id = session["id"]
                controller._view.messages = [{"role": "user", "text": "previous"}]
                with patch.object(controller, "_command_pi") as command:
                    controller.openProject(project["id"])
                    self.assertEqual(controller.messages, [])
                    self.assertEqual(controller.activeSession, "")
                    self.assertFalse(controller.busy)
                    controller.newSession()
                    command.assert_not_called()
                self.assertEqual(controller.sessions, [{"id": "history", "title": "Previous chat"}])
                controller.renameProject(project["id"], "Display name")
                self.assertEqual(controller.workspaceName, "Display name")
                controller.togglePinned("session", "history")
                controller.archiveProject(project["id"], True)
                self.assertFalse(any(r["kind"] == "session" for r in controller.projectRows))
                controller.toggleArchived()
                self.assertTrue(next(r for r in controller.projectRows if r["kind"] == "session")["pinned"])
                self.assertEqual(native.read_text(), "native history")
                controller.removeProject(project["id"])
                wait(lambda: not controller.sessionFiles.busy)
                self.assertFalse(controller.sessionFiles.failure)
                self.assertEqual(controller.projectRows, [])
                self.assertFalse(native.exists())
                self.assertEqual(source.read_text(), "project files remain untouched")
                self.assertIsNone(controller._ensure_project(workspace))
                controller.dropProjects(json.dumps([QUrl.fromLocalFile(str(workspace)).toString()]))
                self.assertEqual(controller.config["activeProject"], project["id"])
                self.assertEqual(len(controller.store.data["projects"]), 1)
                saved = Store(controller.store.directory)
                self.assertNotIn("history", saved.data["sessionMeta"])
            finally:
                controller.close()

    def test_drop_folder_reuses_project_and_file_attachments_are_paths(self):
        from PySide6.QtCore import QUrl
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": str(Path(temp) / "data")}):
            workspace = Path(temp) / "fixture-project"
            workspace.mkdir()
            text = workspace / "hello.txt"
            text.write_text("fixture")
            controller = Controller(ROOT)
            try:
                url = QUrl.fromLocalFile(str(workspace)).toString()
                controller.dropProjects(json.dumps([url]))
                project_id = controller.config["activeProject"]
                controller.dropProjects(json.dumps([url]))
                self.assertEqual(controller.config["activeProject"], project_id)
                self.assertEqual(len(controller.config["projects"]), 1)
                controller.addAttachments(json.dumps([QUrl.fromLocalFile(str(text)).toString(), url]))
                self.assertEqual([a["kind"] for a in controller.attachments], ["file", "folder"])
                controller.removeAttachment(controller.attachments[0]["id"])
                self.assertEqual(len(controller.attachments), 1)
            finally:
                controller.close()

    def test_provider_keeps_multiple_models_and_selected_alias(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": temp}):
            controller = Controller(ROOT)
            try:
                models = [{"upstream":"model-a","alias":"fast"},{"upstream":"model-b","alias":"reason"}]
                self.assertTrue(controller.saveProvider("", "Fixture", "openai", "http://127.0.0.1:18181/v1", "synthetic-key", json.dumps(models)))
                provider = controller.store.data["providers"][-1]
                controller.selectModel(provider["id"], "reason")
                models.append({"upstream":"model-c","alias":"large"})
                self.assertTrue(controller.saveProvider(provider["id"], "Fixture", "openai", provider["baseUrl"], "", json.dumps(models)))
                self.assertEqual(controller.store.data["selectedModel"], "reason")
                self.assertEqual(len(controller.store.data["providers"][-1]["models"]), 3)
                self.assertEqual(controller.store.data["providers"][-1]["key"], "synthetic-key")
                self.assertEqual(controller.gateway.resolve("large")[1], "model-c")
            finally:
                controller.close()

    def test_web_attachment_preserves_draft_deduplicates_and_rejects_unsafe_urls(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": str(Path(temp) / "data")}):
            controller = Controller(ROOT)
            try:
                controller.setDraft("Existing draft")
                url = "https://example.com/page?q=1#section"
                controller.attachChatboxUrl(url)
                controller.attachChatboxUrl(url)
                controller.attachChatboxUrl("javascript:alert(1)")
                controller.attachChatboxUrl("https://name:secret@example.com/")
                self.assertEqual(len(controller.attachments), 1)
                self.assertEqual(controller.attachments[0]["url"], url)
                self.assertEqual(controller._view.draft, "Existing draft")
                controller.removeAttachment(controller.attachments[0]["id"])
                self.assertEqual(controller.attachments, [])
            finally:
                controller.close()

    def test_context_limits_persist_across_provider_mapping_and_discovery_edits(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": str(Path(temp) / "data")}):
            controller = Controller(ROOT)
            try:
                # Raw names, not arbitrary display aliases, determine defaults.
                models = [{"upstream": "k3", "alias": "tiny"},
                          {"upstream": "k3-256", "alias": "large", "contextWindow": "200000", "contextWindowAuto": False, "vision": False, "visionAuto": False}]
                # Reasoning is fixed here; exercise context discovery explicitly below.
                for model in models:
                    model.update(reasoningLevels=[], reasoningLevelsAuto=False,
                                 reasoningFormat='openai', reasoningFormatAuto=False)
                self.assertTrue(controller.saveProvider("", "Fixture", "openai", "http://127.0.0.1:18181/v1", "synthetic", json.dumps(models)))
                provider = controller.gateway.provider(controller.config["providers"][-1]["id"])
                self.assertEqual([m["contextWindow"] for m in provider["models"]], [1048576, 200000])
                self.assertEqual([m["vision"] for m in provider["models"]], [True, False])
                self.assertEqual([m["contextWindow"] for m in controller.gateway.models()], [1048576, 200000])
                # Simulate an older editor that only submits names and aliases.
                edits = [{"upstream": "k3", "alias": "renamed"}, {"upstream": "k3-256", "alias": "large"}]
                controller._view.context_usage = {"model": "umeko-default", "contextWindow": 128000, "percent": 1}
                self.assertTrue(controller.saveProvider(provider["id"], "Fixture", "openai", provider["baseUrl"], "", json.dumps(edits)))
                provider = controller.gateway.provider(provider["id"])
                self.assertFalse(controller.contextUsage, "configuration invalidation retained old native window")
                self.assertEqual(provider["models"][1]["contextWindow"], 200000)
                self.assertFalse(provider["models"][1]["vision"])
                self.assertFalse(provider["models"][1]["visionAuto"])
                # Mapping edits retain custom context and vision settings.
                rows = [{"provider": p["id"], "upstream": m["upstream"], "alias": m["alias"]}
                        for p in controller.config["providers"] for m in p["models"]]
                rows[0].update(contextWindow="0.5M", contextWindowAuto=False, vision=False, visionAuto=False)
                controller.saveMappings(json.dumps(rows))
                self.assertEqual(controller.gateway.provider(provider["id"])["models"][0]["contextWindow"], 524288)
                self.assertEqual(controller.gateway.provider(provider["id"])["models"][1]["contextWindow"], 200000)
                # Drive the real discovery completion with a controlled catalog task.
                # Keep worker/network scheduling outside this persistence test.
                import queue
                manager = controller._reasoning_discovery
                with patch.object(manager, 'tasks', queue.Queue()):
                    self.assertTrue(manager.refresh(provider['id']))
                    kind, snapshot, upstream, alias, token = manager.tasks.get_nowait()
                    self.assertEqual(kind, 'catalog')
                    manager._finished((kind, snapshot, upstream, token,
                                       {'windows': {'k3': 300000, 'k3-256': 400000}}))
                    self.assertTrue(manager.tasks.empty())
                discovered = controller.gateway.provider(provider['id'])['models']
                self.assertEqual([model['providerContextWindow'] for model in discovered], [300000, 400000])
                self.assertEqual([model['contextWindow'] for model in discovered], [524288, 200000])
                self.assertEqual([model['vision'] for model in discovered], [False, False])
                self.assertEqual(Store(controller.store.directory).data["providers"], controller.store.data["providers"])
                # Invalid custom input is rejected atomically; keys and limits survive.
                before = json.dumps(controller.store.data["providers"], sort_keys=True)
                self.assertFalse(controller.saveProvider(provider["id"], "Fixture", "openai", provider["baseUrl"], "", json.dumps([
                    {"upstream": "k3", "alias": "bad", "contextWindow": "nonsense", "contextWindowAuto": False}])))
                self.assertEqual(json.dumps(controller.store.data["providers"], sort_keys=True), before)
            finally:
                controller.close()

    def test_image_path_fallback_vision_queue_and_prompt_has_no_secrets(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": str(Path(temp) / "data")}):
            controller = Controller(ROOT)
            try:
                controller.saveProvider("", "Fixture", "openai", "http://127.0.0.1:18181/v1", "fixture", '[{"upstream":"text-only","alias":"fixture"}]')
                record = controller._view
                record.attachments = [{"kind": "image", "path": "fixture.png", "mime": "image/png", "data": "synthetic-pixels"}]
                record.draft = "Keep this draft"
                notices = []
                controller.toast.connect(notices.append)
                with patch.object(controller, "_command_pi") as command, patch.object(controller, "_write_pi") as write:
                    command.return_value = True
                    self.assertTrue(controller._send("Look at the fixture"))
                    self.assertEqual(command.call_args.kwargs["images"], [])
                    self.assertIn("- file: fixture.png", command.call_args.kwargs["text"])
                    self.assertNotIn("synthetic-pixels", command.call_args.kwargs["text"])
                    controller.chatChanged.emit()
                    self.assertEqual(controller.displayMessages[0]["text"], "Look at the fixture")
                    self.assertEqual(controller.displayMessages[0]["attachments"][0]["name"], "fixture.png")
                    self.assertFalse(record.attachments)
                    record.phase = "running"
                    for steering in (False, True):
                        record.attachments = [{"kind": "image", "path": "fixture.png", "mime": "image/png", "data": "synthetic-pixels"}]
                        self.assertTrue(controller._send("Look at the fixture", steering=steering))
                        self.assertEqual(write.call_args.args[0]["images"], [])
                        self.assertEqual(write.call_args.args[0]["type"], "steer" if steering else "follow-up")
                    record.phase = "idle"
                    controller.store.data["providers"][0]["models"][0].update(vision=True, visionAuto=False)
                    record.attachments = [{"kind": "image", "path": "fixture.png", "mime": "image/png", "data": "synthetic-pixels"}]
                    self.assertTrue(controller._send("Look at the fixture"))
                    self.assertEqual(command.call_args.kwargs["images"][0]["data"], "synthetic-pixels")
                    command.return_value = False
                    controller.store.data["providers"][0]["models"][0].update(vision=False, visionAuto=False)
                    record.attachments = [{"kind": "image", "path": "fixture.png", "mime": "image/png", "data": "synthetic-pixels"}]
                    record.draft = "Keep this draft"
                    self.assertFalse(controller._send("Look at the fixture"))
                    self.assertEqual(record.draft, "Keep this draft")
                    self.assertEqual(record.attachments[0]["data"], "synthetic-pixels")
                self.assertIn("未启用视觉，降级为普通文件路径", notices)
                self.assertFalse(any(p["api"] == "internal" for p in controller.config["providers"]))
            finally:
                controller.close()

    def test_returned_attachment_queue_restores_clean_draft_and_file_tags(self):
        from app.message_attachments import attachment_prompt
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": str(Path(temp) / "data")}):
            controller = Controller(ROOT)
            try:
                record = controller._view
                raw = attachment_prompt("Please inspect", [{"kind":"image", "path":"/tmp/screenshot.png"}])
                controller._handle_pi_event(record, {"type":"queue", "steering":[], "followUp":[raw]})
                self.assertEqual(controller.queuedMessages[0]["text"], "Please inspect")
                self.assertEqual(controller.queuedMessages[0]["attachments"][0]["name"], "screenshot.png")
                controller._handle_pi_event(record, {"type":"queue_returned", "steering":[], "followUp":[raw]})
                self.assertEqual(record.draft, "Please inspect")
                self.assertEqual(record.attachments[0]["path"], "/tmp/screenshot.png")
                self.assertEqual(record.attachments[0]["kind"], "file")
                controller._handle_pi_event(record, {"type":"queue_rejected", "text":raw, "message":"fixture rejection"})
                self.assertEqual(len(record.attachments), 1)
                self.assertNotIn("用户提供的路径", record.draft)
            finally:
                controller.close()

    def test_mcp_scopes_and_native_validation_preserve_previous_config(self):
        from PySide6.QtCore import QUrl
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": str(Path(temp) / "data")}):
            workspace = Path(temp) / "project"
            workspace.mkdir()
            controller = Controller(ROOT)
            controller.store.data["agent"]["agentDir"] = str(Path(temp) / "agent")
            def synchronous_job(name, action):
                try:
                    result = {"ok": True, "value": action()}
                except Exception as exc:
                    result = {"ok": False, "value": str(exc)}
                controller._on_job_done(name, result)
            controller._job = synchronous_job
            try:
                controller.setWorkspace(QUrl.fromLocalFile(str(workspace)).toString())
                global_config = {"mcpServers": {"fixture": {"command": "node", "args": ["fixture.mjs"]}}}
                project_config = {"mcpServers": {"fixture": {"enabled": False}}}
                with patch.object(controller, "_command_pi"):
                    controller.saveMcp("global", json.dumps(global_config))
                    controller.saveMcp("project", json.dumps(project_config))
                    self.assertEqual(json.loads(controller.readMcp("global")), global_config)
                    self.assertEqual(json.loads(controller.readMcp("project")), project_config)
                    controller.saveMcp("project", '{"mcpServers":{"broken":{"args":42}}}')
                    self.assertEqual(json.loads(controller.readMcp("project")), project_config)
                    self.assertFalse(controller.busy)
                self.assertTrue((workspace / ".pi/mcp.json").is_file())
            finally:
                controller.close()

    def test_failed_download_preserves_current_kernel(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": temp}):
            controller = Controller(ROOT)
            previous = controller._release
            def synchronous_job(name, action):
                try:
                    result = {"ok": True, "value": action()}
                except Exception as exc:
                    result = {"ok": False, "value": str(exc)}
                controller._on_job_done(name, result)
            controller._job = synchronous_job
            controller._latest = "99.0.0"
            try:
                with patch("app.controller.subprocess.run", return_value=subprocess.CompletedProcess([], 1)):
                    controller.updateKernel()
                self.assertEqual(controller._release, previous)
                self.assertFalse((Path(temp) / "kernels/active.json").exists())
                self.assertFalse(controller.kernelBusy)
                self.assertIn("原有内核", controller.kernelStatus)
                self.assertEqual(controller.kernelVersion, "1.3.0")
            finally:
                controller.close()

    def test_old_data_migrates_without_changing_credentials_or_aliases(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ):
            os.environ.pop("UMEKO_DATA_DIR", None)
            os.environ["LOCALAPPDATA"] = temp
            old = Store(Path(temp) / "Umeko")
            old.data["password"] = "synthetic-password"
            old.data["providers"] = [{"id":"internal", "name":"Fixture", "api":"internal", "baseUrl":"", "key":"", "models":[{"upstream":"default", "alias":"umeko-default"}]}]
            old.data["providers"][0].update(models=[{"upstream":"original-model","alias":"existing-alias"}])
            old.data["selectedModel"] = "existing-alias"
            old.save()
            old.save_sessions([{"id":"fixture", "title":"fixture", "messages":[], "history":[]}])
            original = old.path.read_bytes()
            with patch("app.storage.data_directory", return_value=Path(temp)/"home/.umeko/desktop"), patch("app.storage.legacy_data_directory", return_value=Path(temp)/"Umeko"):
                migrated = Store()
            self.assertEqual(migrated.directory.name, "desktop")
            self.assertEqual(migrated.data["password"], "synthetic-password")
            self.assertEqual(migrated.data["selectedModel"], "existing-alias")
            self.assertEqual(migrated.data["providers"][0]["name"], "Fixture")
            self.assertEqual(len(migrated.load_sessions()), 1)
            self.assertTrue((migrated.directory / "sessions-legacy.json").is_file())
            self.assertEqual(old.path.read_bytes(), original)

    def test_checkpoint_workspace_lock_rejects_send_before_chat_mutation(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": str(Path(temp) / "data")}):
            controller = Controller(ROOT)
            try:
                controller._view.messages = []
                with patch.object(controller.desktopPlugins, 'checkpoint_locked', return_value=True), patch.object(controller, '_command_pi') as command:
                    self.assertFalse(controller.send('must not start'))
                    command.assert_not_called()
                self.assertEqual(controller._view.messages, [])
                self.assertIn('检查点', controller._last_send_error)
            finally:
                controller.close()

    def test_font_scale_and_family_persist_with_clamp(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": str(Path(temp) / "data")}):
            controller = Controller(ROOT)
            try:
                controller.setFontScale(1.5)
                self.assertEqual(controller.store.data["ui"]["fontScale"], 1.5)
                controller.setFontScale(99.0)
                self.assertEqual(controller.store.data["ui"]["fontScale"], 2.0)
                controller.setFontScale(0.01)
                self.assertEqual(controller.store.data["ui"]["fontScale"], 0.3)
                controller.setFontFamily("Noto Sans CJK SC")
                self.assertEqual(controller.store.data["fontFamily"], "Noto Sans CJK SC")
                controller.setFontFamily("系统默认")
                self.assertEqual(controller.store.data["fontFamily"], "")
                self.assertIn("系统默认", controller.availableFonts)
            finally:
                controller.close()
            self.assertFalse(controller._appearance_save.isActive())
            self.assertEqual(Store(Path(temp) / "data").data["ui"]["fontScale"], 0.3)


if __name__ == "__main__":
    unittest.main()
