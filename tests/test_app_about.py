import io
import json
import ssl
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QObject, Signal
from app.app_about import AppAbout, fetch_latest_release, version_key
from app.project_info import VERSION, PROJECT_URL, RELEASE_API, RELEASES_URL, build_metadata, project_info


class AboutTests(unittest.TestCase):
    def setUp(self):
        proxy = patch('app.app_about.system_proxy', return_value='')
        proxy.start(); self.addCleanup(proxy.stop)

    def release(self, tag, **extra):
        return {"tag_name": tag, "draft": False, "prerelease": False,
                "html_url": PROJECT_URL + "/releases/tag/" + tag, "body": "Fixture release notes", **extra}

    def fetch(self, value):
        with patch("urllib.request.OpenerDirector.open", return_value=io.BytesIO(json.dumps(value).encode())) as request:
            result = fetch_latest_release()
        req = request.call_args.args[0]
        self.assertEqual(req.full_url, RELEASE_API)
        self.assertIsNone(req.get_header("Authorization"))
        self.assertEqual(request.call_args.kwargs["timeout"], 20)
        return result

    def test_semantic_comparison_and_legacy_minor_versions(self):
        self.assertEqual(version_key("v0.2"), version_key("0.2.0+build.7"))
        versions = ["1.2.3-alpha", "1.2.3-alpha.1", "1.2.3-beta", "1.2.3-rc.2", "1.2.3-rc.10", "1.2.3", "1.10.0", "2.0.0"]
        self.assertEqual(sorted(versions, key=version_key), versions)
        for tag in ("nightly", "", "v1.2.3.4", "v01.2.0", "1.2.3-", "1.2.3-a_1", "1.2.3-."):
            self.assertIsNone(version_key(tag), tag)

    def test_release_states_and_unknown_tag_are_distinct(self):
        self.assertEqual(self.fetch(self.release("v99.0.0"))["state"], "available")
        self.assertEqual(self.fetch(self.release("v" + VERSION))["state"], "current")
        self.assertEqual(self.fetch(self.release("v0.1.0"))["state"], "ahead")
        self.assertEqual(self.fetch(self.release("nightly"))["state"], "unknown")

    def test_no_release_rate_limit_and_network_failure_never_report_current(self):
        for code, expected in ((404, "unpublished"), (403, "error"), (429, "error"), (500, "error")):
            error = urllib.error.HTTPError(RELEASE_API, code, "Fixture", {}, None)
            with patch("urllib.request.OpenerDirector.open", side_effect=error):
                self.assertEqual(fetch_latest_release()["state"], expected)
        for error in (urllib.error.URLError("fixture offline"), TimeoutError("fixture timeout")):
            with patch("urllib.request.OpenerDirector.open", side_effect=error):
                self.assertEqual(fetch_latest_release()["state"], "error")

    def test_untrusted_or_invalid_metadata(self):
        self.assertEqual(self.fetch(self.release("v0.3.0", html_url="https://example.invalid/untrusted"))["url"], RELEASES_URL)
        for value in ([], {}, self.release("v0.3.0", draft=True), self.release("v0.3.0", prerelease=True)):
            self.assertEqual(self.fetch(value)["state"], "error")
        for raw in (b"invalid-json", b" " * (2 * 1024 * 1024 + 1)):
            with patch("urllib.request.OpenerDirector.open", return_value=io.BytesIO(raw)):
                self.assertEqual(fetch_latest_release()["state"], "error")

    def test_proxy_network_failure_tries_direct_but_http_rejection_does_not(self):
        raw = json.dumps(self.release('v99.0.0')).encode()
        with patch('app.app_about.system_proxy', return_value='http://fixture.invalid:8080'), \
             patch('app.app_about._release_metadata', side_effect=[urllib.error.URLError('offline'),raw]) as read:
            self.assertEqual(fetch_latest_release()['state'], 'available')
            self.assertEqual([call.args[0] for call in read.call_args_list], ['http://fixture.invalid:8080',''])
        with patch('app.app_about.system_proxy', return_value='http://fixture.invalid:8080'), \
             patch('app.app_about._release_metadata', side_effect=urllib.error.HTTPError(RELEASE_API,407,'',{},None)) as read:
            self.assertEqual(fetch_latest_release()['state'], 'error')
            self.assertEqual(read.call_count, 1)

    def test_certificate_failure_has_system_trust_guidance_and_verified_context(self):
        error = urllib.error.URLError(ssl.SSLCertVerificationError(1,'synthetic untrusted chain'))
        with patch('app.app_about._release_metadata', side_effect=error):
            result = fetch_latest_release()
        self.assertEqual(result['state'], 'error')
        self.assertIn('系统信任证书', result['message'])
        with patch('urllib.request.build_opener') as build:
            build.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(self.release('v99.0.0')).encode()
            self.assertEqual(fetch_latest_release()['state'], 'available')
            context = build.call_args.args[1]._context
            self.assertTrue(context.check_hostname)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_packaged_info_uses_build_platform_and_never_guesses_build_date(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            info = project_info(root, frozen=True)
            self.assertEqual(info["builtAt"], "未记录")
            self.assertEqual(info["commit"], "未记录")
            metadata = {"version": VERSION, "system": "Darwin", "architecture": "arm64", "builtAt": "2026-10-20T00:00:00+00:00", "commit": "a" * 40, "dirty": False}
            (root / "build-info.json").write_text(json.dumps(metadata))
            info = project_info(root, frozen=True)
            self.assertEqual(info["buildPlatform"], "macOS · ARM64")
            self.assertEqual(info["commit"], "a" * 8)
            self.assertNotEqual(info["builtAt"], "未记录")
            metadata["version"] = "wrong-version"
            (root / "build-info.json").write_text(json.dumps(metadata))
            self.assertEqual(project_info(root, frozen=True)["commit"], "未记录")

    def test_source_and_build_metadata_are_public_and_separate(self):
        with tempfile.TemporaryDirectory() as temp, patch("app.project_info.git_output", return_value=""):
            metadata = build_metadata(Path(temp))
            self.assertEqual(set(metadata), {"version", "system", "architecture", "builtAt", "commit", "dirty"})
            source = project_info(Path(temp), frozen=False)
            self.assertEqual(source["buildType"], "源码运行")
            self.assertEqual(source["builtAt"], "源码运行")

    def test_checks_are_explicit_deduplicated_and_do_not_use_chat_state(self):
        class Host(QObject):
            jobDone = Signal(str, object)
            def __init__(self, root):
                super().__init__()
                self.root, self._closing, self.jobs = root, False, []
            def _job(self, name, work): self.jobs.append((name, work))
        with tempfile.TemporaryDirectory() as temp:
            host = Host(Path(temp))
            about = AppAbout(host)
            self.assertEqual(host.jobs, [])
            about.checkUpdates(); about.checkUpdates()
            self.assertTrue(about.busy)
            self.assertEqual(len(host.jobs), 1)
            host.jobDone.emit("other-task", {"ok": True, "value": {}})
            self.assertTrue(about.busy)
            host.jobDone.emit("app-update-check", {"ok": True, "value": {"state": "unpublished", "message": "Fixture"}})
            self.assertFalse(about.busy)
            self.assertTrue(about.checkedAt)
            self.assertEqual(about.release["state"], "unpublished")


if __name__ == "__main__": unittest.main()
