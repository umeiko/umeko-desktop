"""Isolated Qt job integration and launcher contracts; no application services."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import venv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from app.preview_channel import PreviewChannel
from app.preview_source import PreviewError, PreviewSource
from app import preview_launch


def qt_application():
    app = QCoreApplication.instance()
    if app is not None and not isinstance(app, QApplication):
        raise RuntimeError("Preview GUI tests require an isolated QApplication process")
    if app is None:
        app = QApplication([])
        # The Windows offscreen plugin can start without any registered fonts.
        # Reuse main.create_application's registration pattern without loading
        # its controller, tray, notification or storage services.
        if not QFontDatabase.families() and os.name == "nt":
            for font in ("msyh.ttc", "segoeui.ttf", "consola.ttf"):
                QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / font))
        if os.name == "nt":
            families = QFontDatabase.families()
            family = next((name for name in ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI") if name in families), None)
            if family:
                app.setFont(QFont(family, 10))
        else:
            app.setFont(QFontDatabase.systemFont(QFontDatabase.GeneralFont))
    return app


def isolated_test_module(case, filename):
    """Keep GUI cases away from legacy discovery's module-global QCoreApplication."""
    with tempfile.TemporaryDirectory(prefix="umeko-preview-isolated-") as directory:
        environment = dict(os.environ)
        environment.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                           QT_QUICK_CONTROLS_STYLE="Basic", UMEKO_DATA_DIR=directory)
        result = subprocess.run(
            [sys.executable, str(filename)], cwd=ROOT, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        output = result.stdout + result.stderr
        case.assertEqual(result.returncode, 0, output)
        print(output.strip())


class JobController(QObject):
    """Production job signal contract, with work advanced explicitly by a test."""
    jobDone = Signal(str, object)

    def __init__(self, directory):
        super().__init__()
        self.store = SimpleNamespace(directory=Path(directory), data={"agent": {}}, save=Mock())
        self._closing = False
        self.jobs = []
        self.close = Mock()

    def _job(self, name, work):
        self.jobs.append((name, work))

    def finish(self):
        name, work = self.jobs.pop(0)
        value = work()
        self.jobDone.emit(name, {"ok": True, "value": value})
        return value


class PreviewChannelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_application()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="umeko-preview-job-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {"UMEKO_DATA_DIR": str(self.directory)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.state = {"channel": "release", "releaseExecutable": "retained-release"}
        self.state_patch = patch("app.preview_channel.channel_state", side_effect=lambda _: dict(self.state))
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.controller = JobController(self.directory)
        self.channel = PreviewChannel(self.controller)
        self.channel._environment = Mock(return_value={})
        self.manager = Mock()
        self.channel._manager = self.manager
        self.notifications = []
        self.channel.changed.connect(lambda: self.notifications.append(dict(self.channel.status)))

    def test_preflight_requires_confirmation_and_does_not_restart(self):
        self.manager.preflight.return_value = {"ready": True, "detail": "Git, Python, Node and disk ready"}
        with patch("app.preview_channel.start_channel") as start:
            self.channel.switchToPreview()
            self.assertEqual(self.controller.jobs, [])
            self.channel.preflight()
            self.assertTrue(self.channel.busy)
            self.assertEqual(len(self.controller.jobs), 1)
            self.channel.preflight()
            self.assertEqual(len(self.controller.jobs), 1)
            self.controller.finish()
            self.assertEqual(self.channel.status["state"], "prerequisites")
            self.assertTrue(self.channel.status["ready"])
            self.assertFalse(self.channel.busy)
            self.manager.switch_to_preview.assert_not_called()
            start.assert_not_called()
            self.channel.switchToPreview()
            self.state["channel"] = "preview"
            self.manager.switch_to_preview.return_value = {"state": "restart-required", "message": "预览版已准备完成。保存后可重启。"}
            self.controller.finish()
            self.manager.switch_to_preview.assert_called_once_with()
            self.assertEqual(self.channel.channel, "preview")
            self.assertEqual(self.channel.status["state"], "restart-required")
            start.assert_not_called()
            self.controller.close.assert_not_called()
        self.assertGreaterEqual(len(self.notifications), 4)

    def test_failed_preflight_and_job_failure_are_visible_and_retryable(self):
        self.channel._environment.side_effect = [{'npm_config_registry': 'first'}, {'npm_config_registry': 'second'}, {}]
        self.manager.preflight.return_value = {"ready": False, "detail": "Node.js is missing"}
        self.channel.preflight()
        self.controller.finish()
        self.assertEqual(self.manager.environment['npm_config_registry'], 'first')
        self.channel.switchToPreview()
        self.assertEqual(self.controller.jobs, [])
        self.assertIn("Node.js", self.channel.status["detail"])
        self.manager.preflight.side_effect = PreviewError("无法检查运行前提", "Git unavailable")
        self.channel.preflight()
        self.controller.finish()
        self.assertEqual(self.manager.environment['npm_config_registry'], 'second')
        self.assertEqual(self.channel.status, {"state": "error", "message": "无法检查运行前提", "detail": "Git unavailable"})
        self.assertFalse(self.channel.busy)
        self.assertEqual(self.channel.channel, "release")
        self.manager.preflight.side_effect = None
        self.manager.preflight.return_value = {"ready": True}
        self.channel.preflight()
        self.controller.finish()
        self.assertTrue(self.channel.status["ready"])

    def test_update_uses_reviewed_plan_and_pending_dependency_retry(self):
        self.state.update(channel="preview", dependencyPending=True)
        self.channel._state = dict(self.state)
        plan = {"state": "available", "base": "112233aabbcc", "target": "112233aabbcc", "dependencyPending": True,
                "dependencies": ["requirements.txt"], "summary": "Retry dependency installation"}
        self.manager.check_update.return_value = plan
        self.manager.apply_update.side_effect = PreviewError("依赖安装失败", "Please retry")
        with patch("app.preview_channel.start_channel") as start:
            self.channel.checkUpdates()
            self.controller.finish()
            self.manager.apply_update.assert_not_called()
            self.channel.applyUpdate()
            self.controller.finish()
            self.assertEqual(self.channel.status["state"], "error")
            self.assertEqual(self.channel.channel, "preview")
            self.channel.checkUpdates()
            self.controller.finish()
            self.assertTrue(self.channel.status["dependencyPending"])
            self.assertEqual(self.channel.status["state"], "available")
            self.manager.apply_update.side_effect = None
            self.manager.apply_update.return_value = {"state": "restart-required", "message": "更新完成。"}
            self.channel.applyUpdate()
            self.controller.finish()
            self.assertEqual(self.manager.apply_update.call_args.args, (plan,))
            self.assertEqual(self.channel.status["state"], "restart-required")
            start.assert_not_called()

    def test_release_checkout_removal_option_is_forwarded(self):
        for remove in (False, True):
            with self.subTest(remove=remove):
                self.manager.switch_to_release.return_value = {"state": "restart-required"}
                self.channel.switchToRelease(remove)
                self.controller.finish()
                self.assertEqual(self.manager.switch_to_release.call_args.kwargs, {"remove_checkout": remove})
        self.controller.store.save.assert_not_called()
        self.controller.close.assert_not_called()

    def test_restart_is_explicit_and_launch_failure_keeps_application_open(self):
        with patch("app.preview_channel.start_channel", side_effect=OSError("launch unavailable")) as start:
            self.channel.restart()
            start.assert_not_called()
            self.channel._status = {"state": "restart-required"}
            self.channel.restart()
            start.assert_called_once_with(self.directory, self.channel._state)
            self.controller.store.save.assert_called_once_with()
            self.assertEqual(self.channel.status["state"], "error")
            self.assertIn("launch unavailable", self.channel.status["detail"])
            self.controller.close.assert_not_called()

    def test_confirmed_restart_saves_launches_and_closes_in_order(self):
        actions = Mock()
        self.controller.store.save = actions.save
        self.controller.close = actions.close
        application = Mock()
        application.quit = actions.quit
        self.channel._status = {"state": "restart-required"}
        with patch("app.preview_channel.start_channel", side_effect=actions.launch) as start, patch("app.preview_channel.QGuiApplication.instance", return_value=application):
            self.channel.restart()
        self.assertEqual([call[0] for call in actions.mock_calls], ["save", "launch", "close", "quit"])
        start.assert_called_once_with(self.directory, self.channel._state)

    def test_unrelated_completion_and_closing_progress_are_ignored(self):
        self.controller.jobDone.emit("another-job", {"ok": True, "value": {"state": "unrelated"}})
        self.assertEqual(self.channel.status, {})
        self.channel.progress.emit({"state": "installing", "message": "Installing"})
        self.assertEqual(self.channel.status["state"], "installing")
        self.controller._closing = True
        self.channel.progress.emit({"state": "wrong"})
        self.assertEqual(self.channel.status["state"], "installing")


class PreviewLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="umeko-preview-launch-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {"UMEKO_DATA_DIR": str(self.directory)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.source = self.directory / "preview/source"
        self.source.mkdir(parents=True)
        self.python = self.source / (".venv/Scripts/pythonw.exe" if os.name == "nt" else ".venv/bin/python")
        self.python.parent.mkdir(parents=True)
        self.python.touch()
        (self.source / "main.py").touch()
        (self.source / "dist").mkdir()
        (self.source / "dist/Umeko.exe").touch()
        self.release = self.directory / "release/Umeko.exe"
        self.release.parent.mkdir()
        self.release.touch()
        self.state = {"channel": "preview", "releaseExecutable": str(self.release)}

    def test_direct_venv_avoids_dist_and_release_selection(self):
        command, cwd = preview_launch.launch_command(self.directory, self.state)
        self.assertEqual(command, [str(self.python), str(self.source / "main.py")])
        self.assertEqual(cwd, self.source)
        self.state["channel"] = "release"
        self.assertEqual(preview_launch.launch_command(self.directory, self.state), ([str(self.release)], self.release.parent))

    def test_packaged_environment_is_cleaned_and_profile_is_preserved(self):
        polluted = {name: "bundled-path" for name in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QML_IMPORT_PATH", "PYTHONHOME", "PYTHONPATH")}
        polluted.update(LD_LIBRARY_PATH="packaged", LD_LIBRARY_PATH_ORIG="system-libraries")
        with patch.dict(os.environ, polluted), patch.object(sys, "frozen", True, create=True), patch("app.preview_launch.subprocess.Popen") as popen:
            preview_launch.start_channel(self.directory, self.state, ["--open", "conversation"])
        args, kwargs = popen.call_args
        self.assertEqual(args[0], [str(self.python), str(self.source / "main.py"), "--open", "conversation"])
        self.assertEqual(kwargs["env"]["UMEKO_DATA_DIR"], str(self.directory))
        self.assertEqual(kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        self.assertEqual(kwargs["env"]["LD_LIBRARY_PATH"], "system-libraries")
        for name in polluted:
            if name != "LD_LIBRARY_PATH":
                self.assertNotIn(name, kwargs["env"])
        self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
        if os.name == "nt":
            self.assertEqual(kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)

    def test_route_bypasses_installer_and_plugin_worker(self):
        for argument in ("--install-update", "--umeko-plugin-worker"):
            with self.subTest(argument=argument), patch.object(sys, "argv", ["main.py", argument]), patch("app.preview_launch.start_channel") as start:
                self.assertFalse(preview_launch.route_start(self.source))
                start.assert_not_called()

    def test_release_recovery_flag_selects_retained_release_without_changing_user_data(self):
        (self.directory / "preview-channel.json").write_text(json.dumps(self.state), encoding="utf-8")
        settings = self.directory / "settings.json"
        settings_text = '{"theme":"light","language":"en"}\n'
        settings.write_text(settings_text, encoding="utf-8")
        sessions = self.directory / "sessions"
        sessions.mkdir()
        session = sessions / "conversation.json"
        session_text = '{"messages":[{"role":"user","content":"Keep this conversation"}]}\n'
        session.write_text(session_text, encoding="utf-8")
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "argv", ["Umeko.exe", "--release-channel", "--open", "conversation"]), \
             patch("app.preview_launch.start_channel") as start:
            self.assertFalse(preview_launch.route_start(self.release.parent))
            start.assert_not_called()
            self.assertEqual(sys.argv, ["Umeko.exe", "--open", "conversation"])
        state = json.loads((self.directory / "preview-channel.json").read_text(encoding="utf-8"))
        self.assertEqual(state["channel"], "release")
        self.assertEqual(state["releaseExecutable"], str(self.release))
        self.assertEqual(settings.read_text(encoding="utf-8"), settings_text)
        self.assertEqual(session.read_text(encoding="utf-8"), session_text)

    def test_release_entry_routes_preview_and_managed_source_routes_release(self):
        (self.directory / "preview-channel.json").write_text(json.dumps(self.state), encoding="utf-8")
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "argv", ["Umeko.exe", "--open", "conversation"]), patch("app.preview_launch.start_channel") as start:
            self.assertTrue(preview_launch.route_start(self.release.parent))
            start.assert_called_once_with(self.directory, self.state, ["--open", "conversation"])
        self.state["channel"] = "release"
        (self.directory / "preview-channel.json").write_text(json.dumps(self.state), encoding="utf-8")
        with patch.object(sys, "argv", ["main.py"]), patch("app.preview_launch.start_channel") as start:
            self.assertTrue(preview_launch.route_start(self.source))
            start.assert_called_once_with(self.directory, self.state, [])

    def test_failed_preview_route_keeps_retained_release_entry_available(self):
        (self.directory / "preview-channel.json").write_text(json.dumps(self.state), encoding="utf-8")
        self.python.unlink()
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "argv", ["Umeko.exe"]), patch("app.preview_launch.subprocess.Popen") as popen:
            self.assertFalse(preview_launch.route_start(self.release.parent))
            self.assertIn("UMEKO_PREVIEW_LAUNCH_ERROR", os.environ)
            popen.assert_not_called()
        self.assertTrue(self.release.is_file())

    def test_pending_dependencies_block_direct_source_launch(self):
        self.state["dependencyPending"] = True
        with self.assertRaisesRegex(OSError, "依赖"):
            preview_launch.launch_command(self.directory, self.state)


class PreviewSourceLaunchIntegrationTests(unittest.TestCase):
    def test_local_clone_update_and_actual_source_launch_then_release_selection(self):
        """One local upstream connects real checkout operations to real Python launches.

        The fixture replaces only prerequisite/setup hooks: it creates a pip-free
        venv, with no Qt/Pi dependencies. Production Git/channel/launcher code
        consumes each preceding stage's output throughout this scenario.
        """
        with tempfile.TemporaryDirectory(prefix="umeko-preview-local-flow-") as directory:
            root = Path(directory).resolve()
            upstream = root / "upstream.git"
            author = root / "author"
            profile = root / "profile"
            release = root / "retained-release.exe"
            release.write_text("retained release metadata only", encoding="utf-8")
            environment = dict(os.environ)
            environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                               GIT_TERMINAL_PROMPT="0", UMEKO_DATA_DIR=str(profile))

            def git(cwd, *arguments):
                result = subprocess.run(
                    ["git", "-C", str(cwd), *arguments], check=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    encoding="utf-8", env=environment, timeout=20,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                return result.stdout.strip()

            def publish(version, title):
                program = (
                    "import json, os, sys\n"
                    "from pathlib import Path\n"
                    "profile = os.environ['UMEKO_DATA_DIR']\n"
                    "record = {'profile': profile, 'version': " + repr(version) + ", 'executable': sys.executable}\n"
                    "(Path(profile) / 'launch-record.json').write_text(json.dumps(record), encoding='utf-8')\n"
                )
                (author / "main.py").write_text(program, encoding="utf-8")
                git(author, "add", "main.py")
                git(author, "-c", "commit.gpgsign=false", "commit", "-m", title)
                git(author, "push", "origin", "main")

            class OfflineSource(PreviewSource):
                setups = 0

                def preflight(self):
                    return {"ready": True, "details": []}

                def _setup(self):
                    self.setups += 1
                    venv.EnvBuilder(with_pip=False).create(self.checkout / ".venv")
                    self._verify()

                def _verify(self):
                    if not self.python.is_file() or not (self.checkout / "main.py").is_file():
                        raise PreviewError("Offline source launch files missing")

            def launch_and_read(manager):
                process = preview_launch.start_channel(profile, manager.read_state())
                try:
                    self.assertEqual(process.wait(timeout=15), 0)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
                record = json.loads((profile / "launch-record.json").read_text(encoding="utf-8"))
                self.assertEqual(record["profile"], str(profile))
                command, _ = preview_launch.launch_command(profile, manager.read_state())
                self.assertEqual(Path(record["executable"]).resolve(), Path(command[0]).resolve())
                return record

            author.mkdir()
            git(root, "init", "--bare", "--initial-branch=main", str(upstream))
            git(author, "init", "--initial-branch=main")
            git(author, "config", "user.name", "Local Preview Scenario")
            git(author, "config", "user.email", "preview@example.invalid")
            git(author, "remote", "add", "origin", str(upstream))
            publish("version-one", "Add source launch marker")

            with patch.dict(os.environ, environment):
                manager = OfflineSource(profile, release, environment=environment, upstream=str(upstream))
                switched = manager.switch_to_preview()
                self.assertEqual(switched["state"], "restart-required")
                self.assertEqual(manager.read_state()["channel"], "preview")
                self.assertEqual(launch_and_read(manager)["version"], "version-one")

                publish("version-two", "Improve source launch marker")
                plan = manager.check_update()
                self.assertEqual(plan["state"], "available")
                self.assertIn("Improve source launch marker", plan["summary"])
                self.assertEqual(plan["changed"], ["main.py"])
                self.assertEqual(plan["dependencies"], [])
                applied = manager.apply_update(plan)
                self.assertEqual(applied["state"], "restart-required")
                self.assertEqual(manager.setups, 1)
                self.assertEqual(launch_and_read(manager)["version"], "version-two")

                returned = manager.switch_to_release(remove_checkout=False)
                self.assertEqual(returned["state"], "restart-required")
                state = manager.read_state()
                self.assertEqual(state["channel"], "release")
                self.assertFalse(state["dependencyPending"])
                self.assertEqual(preview_launch.launch_command(profile, state), ([str(release)], release.parent))
                self.assertTrue(manager.checkout.is_dir())


if __name__ != "__main__":
    class IsolatedPreviewChannelTests(unittest.TestCase):
        def test_preview_channel_in_isolated_process(self):
            isolated_test_module(self, Path(__file__).resolve())


def load_tests(loader, tests, pattern):
    if __name__ == "__main__":
        return tests
    return unittest.TestSuite([IsolatedPreviewChannelTests("test_preview_channel_in_isolated_process")])


if __name__ == "__main__":
    unittest.main()
