"""Deterministic preview lifecycle tests; only temporary local Git repositories."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.preview_source import PreviewError, PreviewSource


def git(cwd, *args):
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    result = subprocess.run(["git", "-C", str(cwd), *args], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=flags, check=True)
    return result.stdout.strip()


class LocalPreview(PreviewSource):
    setups = 0
    fail_setup = False

    def preflight(self):
        return {"ready": True, "details": [], "detail": "local fixture"}

    def _setup(self):
        self.setups += 1
        if self.fail_setup:
            raise PreviewError("fixture setup failure")
        self.python.parent.mkdir(parents=True, exist_ok=True)
        self.python.write_text("fixture Python", encoding="utf-8")

    def _verify(self):
        if not self.python.is_file():
            raise PreviewError("fixture Python missing")


@unittest.skipUnless(shutil.which("git"), "Git is required")
class PreviewSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.remote = self.root / "remote.git"
        self.author = self.root / "author"
        self.profile = self.root / "profile"
        self.release = self.root / "Umeko.exe"
        self.release.write_text("release untouched", encoding="utf-8")
        self.author.mkdir()
        git(self.root, "init", "--bare", str(self.remote))
        git(self.author, "init", "-b", "main")
        git(self.author, "config", "user.name", "Preview Fixture")
        git(self.author, "config", "user.email", "preview@example.invalid")
        (self.author / ".gitignore").write_text(".venv/\n", encoding="utf-8")
        git(self.author, "add", ".gitignore")
        self.commit("app.py", "initial", "initial")
        git(self.author, "remote", "add", "origin", str(self.remote))
        git(self.author, "push", "-u", "origin", "main")
        self.manager = LocalPreview(self.profile, self.release, upstream=str(self.remote))

    def commit(self, path, content, message="change", push=False):
        file = self.author / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
        git(self.author, "add", "--", path)
        git(self.author, "commit", "-m", message)
        if push:
            git(self.author, "push", "origin", "main")
        return git(self.author, "rev-parse", "HEAD")

    def preview(self):
        result = self.manager.switch_to_preview()
        self.assertEqual(result["state"], "restart-required")
        self.assertEqual(self.manager.read_state()["channel"], "preview")
        git(self.manager.checkout, "config", "user.name", "Preview Fixture")
        git(self.manager.checkout, "config", "user.email", "preview@example.invalid")

    def test_default_release_and_successful_clone_setup(self):
        self.assertEqual(self.manager.read_state()["channel"], "release")
        self.assertFalse(self.profile.exists())
        self.preview()
        self.assertEqual(self.manager.setups, 1)
        self.assertEqual(git(self.manager.checkout, "branch", "--show-current"), "main")
        self.assertEqual(self.manager.read_state()["releaseExecutable"], str(self.release.resolve()))
        self.assertEqual(self.release.read_text(), "release untouched")
        self.assertFalse((self.profile / "settings.json").exists())

    def test_setup_failure_and_retry_preserve_release(self):
        self.manager.fail_setup = True
        with self.assertRaises(PreviewError):
            self.manager.switch_to_preview()
        self.assertEqual(self.manager.read_state()["channel"], "release")
        self.assertTrue(self.manager.read_state()["dependencyPending"])
        self.assertEqual(self.release.read_text(), "release untouched")
        self.manager.fail_setup = False
        self.manager.switch_to_preview()
        self.assertEqual(self.manager.read_state()["channel"], "preview")

    def test_failed_clone_and_unrelated_directory_are_preserved(self):
        self.manager.checkout.mkdir(parents=True)
        (self.manager.checkout / "personal.txt").write_text("mine")
        with self.assertRaises(PreviewError):
            self.manager.switch_to_preview()
        self.assertEqual((self.manager.checkout / "personal.txt").read_text(), "mine")
        self.assertEqual(self.manager.read_state()["channel"], "release")

    def test_clone_failure_leaves_release_selected(self):
        original = self.manager._run
        def run(args, *a, **kw):
            if "clone" in args:
                raise PreviewError("fixture clone failure")
            return original(args, *a, **kw)
        self.manager._run = run
        with self.assertRaises(PreviewError):
            self.manager.switch_to_preview()
        self.assertFalse(self.manager.checkout.exists())
        self.assertEqual(self.manager.read_state()["channel"], "release")

    def test_fast_forward_only_confirmed_target_and_summary(self):
        self.preview()
        target = self.commit("app.py", "second", "visible summary", push=True)
        plan = self.manager.check_update()
        self.assertEqual(plan["state"], "available")
        self.assertIn("visible summary", plan["summary"])
        self.assertEqual(plan["changed"], ["app.py"])
        self.commit("app.py", "third", "later remote change", push=True)
        self.manager.apply_update(plan)
        self.assertEqual(git(self.manager.checkout, "rev-parse", "HEAD"), target)
        self.assertEqual((self.manager.checkout / "app.py").read_text(), "second")
        self.assertEqual(self.manager.setups, 1)

    def test_dependency_change_setup_failure_retries_same_head(self):
        self.preview()
        self.commit("requirements-extra.txt", "example==1", push=True)
        plan = self.manager.check_update()
        self.assertEqual(plan["dependencies"], ["requirements-extra.txt"])
        self.manager.fail_setup = True
        with self.assertRaises(PreviewError):
            self.manager.apply_update(plan)
        self.assertEqual(self.manager.read_state()["channel"], "preview")
        retry = self.manager.check_update()
        self.assertEqual(retry["base"], retry["target"])
        self.assertEqual(retry["state"], "available")
        self.assertTrue(retry["dependencyPending"])
        self.manager.fail_setup = False
        self.manager.apply_update(retry)
        self.assertEqual(self.manager.setups, 3)
        self.assertFalse(self.manager.read_state()["dependencyPending"])

    def test_dependency_inputs(self):
        for path in ["requirements.txt", "pyproject.toml", "runtime/package-lock.json", "setup.ps1", "setup.sh", "prepare_runtime.py", "scripts/build-input-method.py", "scripts/fetch-search-tools.py", "runtime/compat.mjs"]:
            with self.subTest(path=path):
                self.assertTrue(self.manager._dependency(path))
        self.assertFalse(self.manager._dependency("app/window.py"))

    def test_dirty_and_index_changes_refused(self):
        self.preview()
        path = self.manager.checkout / "app.py"
        path.write_text("local")
        with self.assertRaisesRegex(PreviewError, "本地修改"):
            self.manager.check_update()
        git(self.manager.checkout, "add", "app.py")
        with self.assertRaisesRegex(PreviewError, "本地修改"):
            self.manager.check_update()
        self.assertEqual(path.read_text(), "local")

    def test_untracked_overwrite_and_unrelated_untracked(self):
        self.preview()
        (self.manager.checkout / "mine.txt").write_text("mine")
        self.commit("new.txt", "remote", push=True)
        (self.manager.checkout / "new.txt").write_text("personal")
        with self.assertRaisesRegex(PreviewError, "new.txt"):
            self.manager.check_update()
        (self.manager.checkout / "new.txt").unlink()
        self.manager.apply_update(self.manager.check_update())
        self.assertEqual((self.manager.checkout / "mine.txt").read_text(), "mine")

    def test_ignored_untracked_file_is_never_overwritten(self):
        self.preview()
        (self.manager.checkout / ".git" / "info" / "exclude").write_text("personal.txt\n")
        personal = self.manager.checkout / "personal.txt"
        personal.write_text("mine")
        self.commit("personal.txt", "incoming", push=True)
        with self.assertRaisesRegex(PreviewError, "personal.txt"):
            self.manager.check_update()
        self.assertEqual(personal.read_text(), "mine")

    def test_ignored_directory_is_never_overwritten(self):
        self.preview()
        (self.manager.checkout / ".git" / "info" / "exclude").write_text("personal-dir/\n")
        personal = self.manager.checkout / "personal-dir" / "notes.txt"
        personal.parent.mkdir()
        personal.write_text("mine")
        self.commit("personal-dir/new.py", "incoming", push=True)
        with self.assertRaisesRegex(PreviewError, "personal-dir"):
            self.manager.check_update()
        self.assertEqual(personal.read_text(), "mine")

    def test_local_commit_divergence_detached_wrong_branch(self):
        self.preview()
        (self.manager.checkout / "local.txt").write_text("mine")
        git(self.manager.checkout, "add", "local.txt")
        git(self.manager.checkout, "commit", "-m", "local")
        with self.assertRaisesRegex(PreviewError, "领先或分叉"):
            self.manager.check_update()
        self.commit("remote.txt", "remote", push=True)
        with self.assertRaisesRegex(PreviewError, "领先或分叉"):
            self.manager.check_update()
        git(self.manager.checkout, "checkout", "--detach")
        with self.assertRaisesRegex(PreviewError, "main 分支"):
            self.manager.check_update()
        git(self.manager.checkout, "checkout", "-b", "personal")
        with self.assertRaisesRegex(PreviewError, "main 分支"):
            self.manager.check_update()

    def test_changed_origin_multiple_urls_and_apply_recheck(self):
        self.preview()
        self.commit("app.py", "update", push=True)
        plan = self.manager.check_update()
        git(self.manager.checkout, "config", "--add", "remote.origin.url", str(self.author))
        with self.assertRaisesRegex(PreviewError, "官方地址"):
            self.manager.apply_update(plan)
        self.assertEqual((self.manager.checkout / "app.py").read_text(), "initial")

    def test_git_insteadof_origin_redirect_is_refused(self):
        self.preview()
        git(self.manager.checkout, "config", "url." + str(self.author) + ".insteadOf", str(self.remote))
        with self.assertRaisesRegex(PreviewError, "官方地址"):
            self.manager.check_update()

    def test_confirmation_rechecks_worktree_and_head(self):
        self.preview()
        self.commit("app.py", "update", push=True)
        plan = self.manager.check_update()
        (self.manager.checkout / "app.py").write_text("personal")
        with self.assertRaisesRegex(PreviewError, "本地修改"):
            self.manager.apply_update(plan)
        git(self.manager.checkout, "add", "app.py")
        git(self.manager.checkout, "commit", "-m", "local")
        with self.assertRaisesRegex(PreviewError, "已变化"):
            self.manager.apply_update(plan)

    def test_switch_back_remove_protects_profile_and_personal_files(self):
        self.preview()
        (self.profile / "settings.json").write_text('{"personal":true}')
        data = self.profile / "data.txt"
        data.write_text("user data")
        personal = self.manager.checkout / "personal.txt"
        personal.write_text("personal source")
        with self.assertRaisesRegex(PreviewError, "未跟踪文件"):
            self.manager.switch_to_release(remove_checkout=True)
        self.assertEqual(self.manager.read_state()["channel"], "release")
        self.assertEqual(personal.read_text(), "personal source")
        personal.unlink()
        self.manager.switch_to_release(remove_checkout=True)
        self.assertFalse(self.manager.checkout.exists())
        self.assertEqual(data.read_text(), "user data")
        self.assertEqual(json.loads((self.profile / "settings.json").read_text()), {"personal": True})

    def test_switch_back_refuses_dirty_checkout_and_missing_release(self):
        self.preview()
        (self.manager.checkout / "app.py").write_text("personal")
        with self.assertRaisesRegex(PreviewError, "本地修改"):
            self.manager.switch_to_release(remove_checkout=True)
        self.assertTrue(self.manager.checkout.exists())
        self.release.unlink()
        with self.assertRaisesRegex(PreviewError, "正式版"):
            self.manager.switch_to_release()

    def test_running_preview_defers_removal_until_release_cleanup(self):
        self.preview()
        with patch("app.preview_source.sys.executable", str(self.manager.python)):
            result = self.manager.switch_to_release(remove_checkout=True)
            self.assertEqual(result["state"], "restart-required")
            self.assertTrue(self.manager.checkout.exists())
            self.assertTrue(self.manager.read_state()["removeCheckoutPending"])
            self.assertEqual(self.manager.read_state()["cleanupParentPid"], os.getpid())
            with self.assertRaisesRegex(PreviewError, "仍在运行"):
                self.manager.remove_retained_checkout()
        self.manager.remove_retained_checkout()
        self.assertFalse(self.manager.checkout.exists())
        self.assertFalse(self.manager.read_state()["removeCheckoutPending"])

    def test_cancel_before_clone_and_command(self):
        self.manager.cancelled = lambda: True
        with self.assertRaisesRegex(PreviewError, "取消"):
            self.manager.switch_to_preview()
        self.assertEqual(self.manager.read_state()["channel"], "release")
        self.assertFalse(self.manager.checkout.exists())

    def test_cancel_running_process_terminates_only_owned_process(self):
        manager = PreviewSource(self.profile, self.release, upstream=str(self.remote))
        manager.cancelled = Mock(side_effect=[False, True])
        process = Mock()
        process.poll.return_value = None
        process.pid = 12345
        with patch("app.preview_source.subprocess.Popen", return_value=process), \
             patch.object(manager, "_terminate") as terminate:
            with self.assertRaisesRegex(PreviewError, "取消"):
                manager._run(["fixture-command"])
        terminate.assert_called_once_with(process)
        process.wait.assert_called_once()

    @unittest.skipUnless(os.name == "nt", "Windows PID tree termination")
    def test_windows_cancellation_uses_exact_pid_tree(self):
        process = Mock(pid=12345)
        with patch("app.preview_source.subprocess.run") as run:
            self.manager._terminate(process)
        self.assertEqual(run.call_args.args[0], ["taskkill", "/PID", "12345", "/T", "/F"])
        self.assertEqual(run.call_args.kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)

    def test_preflight_failures_are_readonly_and_descriptive(self):
        manager = PreviewSource(self.profile, self.release, upstream=str(self.remote))
        manager._which = lambda name: "/fixture/" + name
        def run(args, *a, **kw):
            if "--version" in args and "node" in args[0]:
                return "v20.0.0"
            if "-c" in args:
                raise PreviewError("missing venv")
            if "ls-remote" in args:
                raise PreviewError("proxy unavailable")
            return "fixture"
        manager._run = run
        result = manager.preflight()
        self.assertFalse(result["ready"])
        self.assertIn("Node.js 22.19+", result["detail"])
        self.assertIn("missing venv", result["detail"])
        self.assertIn("proxy unavailable", result["detail"])
        self.assertFalse(self.profile.exists())

    def test_failed_preflight_never_clones_or_changes_selection(self):
        self.manager.preflight = lambda: {"ready": False, "details": [
            {"name": "Git", "ready": False, "detail": "Git unavailable"}]}
        with self.assertRaisesRegex(PreviewError, "Git unavailable"):
            self.manager.switch_to_preview()
        self.assertFalse(self.manager.checkout.exists())
        self.assertFalse(self.profile.exists())
        self.assertEqual(self.manager.read_state()["channel"], "release")

    def test_missing_retained_release_is_a_prerequisite_failure(self):
        self.release.unlink()
        manager = PreviewSource(self.profile, self.release, upstream=str(self.remote))
        manager._which = lambda name: None
        manager._run = Mock(side_effect=PreviewError('tool unavailable'))
        result = manager.preflight()
        release = next(item for item in result['details'] if item['name'] == '保留的正式版')
        self.assertFalse(release['ready'])
        self.assertFalse(result['ready'])
        self.assertFalse(self.profile.exists())

    def test_ignored_personal_source_is_not_removed(self):
        self.preview()
        (self.manager.checkout / ".git" / "info" / "exclude").write_text("personal.py\n")
        personal = self.manager.checkout / "personal.py"
        personal.write_text("personal source")
        with self.assertRaisesRegex(PreviewError, "personal.py"):
            self.manager.switch_to_release(remove_checkout=True)
        self.assertEqual(personal.read_text(), "personal source")
        self.assertEqual(self.manager.read_state()["channel"], "release")

    def test_known_setup_outputs_are_removable(self):
        self.preview()
        paths = ["runtime/releases/fixture/runtime.js", "runtime/downloads/fd.zip",
                 "runtime/node_modules/example/index.js", "build/provider-resources/providers.zip",
                 "build/desktop-plugin-resources/sdk.zip", "build/qt-sdk/fixture/sdk.txt",
                 "build/input-method/plugin.so"]
        (self.manager.checkout / ".git" / "info" / "exclude").write_text("runtime/\nbuild/\n")
        for name in paths:
            path = self.manager.checkout / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("generated")
        self.manager.switch_to_release(remove_checkout=True)
        self.assertFalse(self.manager.checkout.exists())

    def test_stored_system_python_is_reused_after_restart(self):
        self.manager._save(systemPython="/fixture/actual-python")
        manager = PreviewSource(self.profile, self.release, upstream=str(self.remote))
        manager._which = lambda name: None
        manager._run = Mock(return_value="/fixture/actual-python")
        self.assertEqual(manager._select_python(), "/fixture/actual-python")
        self.assertEqual(manager._run.call_args.args[0][0], "/fixture/actual-python")

    def test_python_launcher_resolves_actual_executable(self):
        manager = PreviewSource(self.profile, self.release, upstream=str(self.remote))
        manager._which = lambda name: "/fixture/py" if name == "py" else None
        manager._run = Mock(return_value="/fixture/Python/python.exe")
        self.assertEqual(manager._select_python(), "/fixture/Python/python.exe")

    def test_disk_space_preflight_failure(self):
        manager = PreviewSource(self.profile, self.release, upstream=str(self.remote))
        manager._which = lambda name: "/fixture/" + name
        manager._run = lambda args, **kwargs: "v22.19.0" if "node" in args[0] else "/fixture/python"
        with patch("app.preview_source.shutil.disk_usage", return_value=shutil._ntuple_diskusage(10, 9, 1)):
            result = manager.preflight()
        self.assertFalse(result["ready"])
        self.assertTrue(any("2 GiB" in item["name"] and not item["ready"] for item in result["details"]))

    def test_network_upstream_override_is_not_supported(self):
        with self.assertRaises(ValueError):
            PreviewSource(self.profile, self.release, upstream="https://other.invalid/repo.git")


if __name__ == "__main__":
    unittest.main()
