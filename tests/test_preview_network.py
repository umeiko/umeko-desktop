"""Offline Preview route handoff; subprocesses are captured, not connected."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.preview_network import NETWORK_MESSAGES, PreviewNetwork, network_failure
from app.preview_source import PreviewError, PreviewSource


class PreviewNetworkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="preview-network-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.manager = PreviewSource(self.directory / "profile", None, {"PATH": "tool-path"})

    def selected_network(self, proxy):
        def helper(command):
            ca = command[-1]
            Path(ca).write_text("fixture CA", encoding="utf-8")
            overrides = {key: ca for key in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
                         "PIP_CERT", "npm_config_cafile", "NODE_EXTRA_CA_CERTS", "GIT_SSL_CAINFO")}
            overrides.update(HTTPS_PROXY=proxy, HTTP_PROXY=proxy, NO_PROXY="" if proxy else "*")
            return json.dumps({"ok": True, "route": "系统代理" if proxy else "直连",
                               "environment": overrides, "removeEnvironment": ["all_proxy"]})
        network = PreviewNetwork(self.manager.environment, helper)
        self.addCleanup(network.close)
        with patch("app.pi_runtime.node_executable", return_value="fixture-node"):
            network.probe()
        return network

    def test_winning_route_and_ca_reach_clone_fetch_pull_and_setup(self):
        for proxy in ("", "http://proxy.invalid:8080"):
            with self.subTest(proxy=bool(proxy)):
                profile = self.directory / ("proxied" if proxy else "direct")
                self.manager = PreviewSource(profile, None, {"PATH": "tool-path", "ALL_PROXY": "stale"})
                self.manager._network = self.selected_network(proxy)
                self.manager.preflight = Mock(return_value={"ready": True})
                self.manager.system_python = sys.executable
                self.manager._verify = Mock()
                calls = []
                def popen(command, **options):
                    calls.append((command, dict(options["env"])))
                    options["stdout"].write(b"fixture output")
                    return Mock(poll=Mock(return_value=0), wait=Mock(return_value=0), returncode=0)
                with patch("app.preview_source.subprocess.Popen", side_effect=popen):
                    self.manager.switch_to_preview()
                    self.manager._git("fetch", "origin", "main")
                    self.manager._git("pull", "--ff-only", "origin", "main")
                self.assertEqual(len(calls), 4)
                self.assertEqual(calls[0][0][1], "clone")
                self.assertIn("setup.", " ".join(calls[1][0]))
                self.assertIn("fetch", calls[2][0])
                self.assertIn("pull", calls[3][0])
                for _, environment in calls:
                    self.assertEqual(environment["HTTPS_PROXY"], proxy)
                    self.assertNotIn("ALL_PROXY", environment)
                    self.assertEqual(environment["NO_PROXY"], "" if proxy else "*")
                    ca = environment["GIT_SSL_CAINFO"]
                    self.assertTrue(Path(ca).is_file())
                    for key in ("PIP_CERT", "npm_config_cafile", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
                                "CURL_CA_BUNDLE", "NODE_EXTRA_CA_CERTS"):
                        self.assertEqual(environment[key], ca)
                self.assertTrue(calls[1][1]["PATH"].startswith(str(Path(sys.executable).parent) + os.pathsep))

    def test_preflight_exposes_only_safe_category_and_hint(self):
        for category, (label, hint) in NETWORK_MESSAGES.items():
            with self.subTest(category=category):
                self.manager._prepare_network = Mock(return_value={
                    "ok": False, "category": category,
                    "attempts": [{"route": "直连", "category": category, "code": "FIXTURE"}]})
                self.manager._select_python = Mock(return_value="fixture-python")
                self.manager._run = Mock(side_effect=lambda command, **_: "v22.19.0" if "--version" in command else "OK")
                status = self.manager.preflight()
                check = status["details"][-1]
                self.assertFalse(status["ready"])
                self.assertEqual(check["category"], category)
                self.assertEqual(check["detail"], label)
                self.assertEqual(check["hint"], hint)
                self.assertEqual(check["command"], [])

    def test_later_command_failure_is_classified_without_raw_output(self):
        self.manager._network = Mock()
        self.manager._network.apply.side_effect = lambda value: value
        for category in NETWORK_MESSAGES:
            with self.subTest(category=category):
                self.manager._network.classify.return_value = category
                def popen(*_, **options):
                    options["stdout"].write(b"failed https://private.invalid/a via user:secret@proxy.invalid")
                    return Mock(poll=Mock(return_value=1), wait=Mock(return_value=1), returncode=1)
                with patch("app.preview_source.subprocess.Popen", side_effect=popen):
                    with self.assertRaises(PreviewError) as caught:
                        self.manager._run(["git", "fetch"], network=True)
                self.assertEqual(caught.exception.category, category)
                self.assertNotIn("private.invalid", str(caught.exception))
                self.assertNotIn("secret", str(caught.exception))

    def test_classifier_uses_private_file_and_removes_raw_diagnostics(self):
        seen = []
        def classify(command):
            file = Path(command[-1])
            seen.append(file)
            self.assertIn("certificate", file.read_text(encoding="utf-8"))
            return '{"category":"certificate","code":"FIXTURE"}'
        network = PreviewNetwork({}, classify)
        self.addCleanup(network.close)
        with patch("app.pi_runtime.node_executable", return_value="fixture-node"):
            self.assertEqual(network.classify("certificate failure at private.invalid"), "certificate")
        self.assertFalse(seen[0].exists())

    def test_categories_have_distinct_actionable_messages(self):
        self.assertEqual(set(NETWORK_MESSAGES), {"certificate", "proxy", "dns", "timeout", "other"})
        self.assertEqual(len({network_failure(key)["detail"] for key in NETWORK_MESSAGES}), 5)
        self.assertEqual(network_failure("unrecognized"), network_failure("other"))

    def test_pip_direct_argument_overrides_config_proxy_and_clears_trusted_hosts(self):
        from pip._internal.commands import create_command
        config = self.directory / "pip.ini"
        config.write_text("[global]\nproxy = http://stale.invalid:8080\ntrusted-host = unverified.invalid\n", encoding="utf-8")
        with patch.dict(os.environ, {"PIP_CONFIG_FILE": str(config), "PIP_PROXY": "", "PIP_TRUSTED_HOST": " "}):
            inherited, _ = create_command("install").parse_args([])
            direct, _ = create_command("install").parse_args(["--proxy="])
        self.assertEqual(inherited.proxy, "http://stale.invalid:8080")
        self.assertEqual(direct.proxy, "")
        self.assertEqual(direct.trusted_hosts, [])

    def test_unsupported_route_is_explained_when_direct_also_fails(self):
        result = {"ok": False, "category": "dns", "attempts": [
            {"route": "系统代理", "code": "PREVIEW_PROXY_UNSUPPORTED"},
            {"route": "直连", "code": "ENOTFOUND"}]}
        self.manager._network = Mock(result=result)
        with self.assertRaises(PreviewError) as caught:
            self.manager._ensure_network()
        self.assertEqual(caught.exception.category, "dns")
        self.assertIn("SOCKS", caught.exception.limitation)


if __name__ == "__main__":
    unittest.main()
