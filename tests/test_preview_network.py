"""Offline Preview route handoff; subprocesses are captured, not connected."""
import json
import os
from pathlib import Path
import shutil
import subprocess
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
            ca = command[3]
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

    def test_pip_direct_argument_overrides_only_the_config_proxy(self):
        from pip._internal.commands import create_command
        config = self.directory / "pip.ini"
        cert = self.directory / "pip-ca.pem"
        cert.write_text("fixture CA", encoding="utf-8")
        config.write_text(f"[global]\nproxy = http://stale.invalid:8080\ncert = {cert}\ntrusted-host = packages.example.test\nindex-url = https://packages.example.test/simple\n", encoding="utf-8")
        with patch.dict(os.environ, {"PIP_CONFIG_FILE": str(config), "PIP_PROXY": "", "PIP_TRUSTED_HOST": "packages.example.test", "PIP_CERT": str(cert)}):
            inherited, _ = create_command("install").parse_args([])
            direct, _ = create_command("install").parse_args(["--proxy="])
        self.assertEqual(inherited.proxy, "http://stale.invalid:8080")
        self.assertEqual(direct.proxy, "")
        self.assertEqual(direct.trusted_hosts, ["packages.example.test"])
        self.assertEqual(direct.cert, str(cert))
        self.assertEqual(direct.index_url, "https://packages.example.test/simple")

    def test_native_tool_queries_add_user_ca_files_without_changing_tool_choices(self):
        root = Path(__file__).resolve().parents[1]
        updater_ca = root / "tests/fixtures/update-tls/ca.pem"
        ca = updater_ca.read_text(encoding="utf-8")
        files = {}
        for name in ("pip", "npm", "requests", "git"):
            files[name] = self.directory / (name + ".pem")
            files[name].write_text(ca + f"\n# {name} fixture\n", encoding="utf-8")
        pip_config = self.directory / "pip.ini"
        pip_config.write_text(f"[global]\ncert = {files['pip']}\ntrusted-host = packages.example.test\nindex-url = https://packages.example.test/simple\n", encoding="utf-8")
        npm_config = self.directory / ".npmrc"
        npm_config.write_text(f"cafile={files['npm'].as_posix()}\nstrict-ssl=false\nregistry=https://registry.example.test/\n", encoding="utf-8")
        git_config = self.directory / ".gitconfig"
        git_config.write_text(f'[http]\nsslCAInfo = "{files["git"].as_posix()}"\nsslVerify = false\n', encoding="utf-8")
        empty = self.directory / "empty-config"
        empty.write_text("", encoding="utf-8")
        original = {file: file.read_bytes() for file in (pip_config, npm_config, git_config)}
        # Every tool reads only this fixture's config locations, never the
        # developer's profile; all transport calls below are injected fakes.
        environment = {key: value for key, value in os.environ.items() if not key.upper().startswith((
            "PIP_", "NPM_CONFIG_", "GIT_CONFIG", "GIT_SSL", "GIT_PROXY_SSL", "NODE_EXTRA_CA", "NODE_TLS", "SSL_CERT", "REQUESTS_CA", "CURL_CA"))}
        environment.update(HOME=str(self.directory), USERPROFILE=str(self.directory),
            APPDATA=str(self.directory), LOCALAPPDATA=str(self.directory), PROGRAMDATA=str(self.directory),
            XDG_CONFIG_HOME=str(self.directory), XDG_CONFIG_DIRS=str(self.directory),
            PIP_CONFIG_FILE=str(pip_config), NPM_CONFIG_USERCONFIG=str(npm_config),
            NPM_CONFIG_GLOBALCONFIG=str(empty), NPM_CONFIG_CACHE=str(self.directory / "npm-cache"),
            GIT_CONFIG_GLOBAL=str(git_config), GIT_CONFIG_NOSYSTEM="1",
            REQUESTS_CA_BUNDLE=str(files["requests"]), NO_PROXY="keep.example.test")
        options = {"caFile": str(self.directory / "combined.pem"), "python": sys.executable,
                   "cwd": str(self.directory), "fixture": str(updater_ca), "proxy": ""}
        script = """import fs from 'node:fs';
const {probePreviewNetwork}=await import(process.argv[1]);
const options=JSON.parse(process.argv[2]);
options.certificateReader=()=>[fs.readFileSync(options.fixture,'utf8')];
const result=await probePreviewNetwork(options,async()=>({stdout:'fixture refs/heads/main'}));
console.log(JSON.stringify(result));"""
        result = subprocess.run([shutil.which("node"), "--input-type=module", "-e", script,
            (root / "runtime/preview-network.mjs").as_uri(), json.dumps(options)],
            cwd=self.directory, env=environment, capture_output=True, text=True, timeout=40,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.assertEqual(result.returncode, 0, result.stderr)
        network = json.loads(result.stdout)
        self.assertTrue(network["ok"], network)
        bundle = Path(options["caFile"]).read_text(encoding="utf-8")
        self.assertTrue(bundle.startswith(ca + "\n"))
        for name in files:
            self.assertIn(f"# {name} fixture", bundle)
        for key in ("PIP_CERT", "npm_config_cafile", "GIT_SSL_CAINFO", "REQUESTS_CA_BUNDLE"):
            self.assertEqual(network["environment"][key], options["caFile"])
        self.assertNotIn("PIP_TRUSTED_HOST", network["environment"])
        self.assertNotIn("npm_config_strict_ssl", network["environment"])
        self.assertEqual(network["environment"]["NO_PROXY"], "keep.example.test,*")
        handed = dict(environment, **network["environment"])
        with patch.dict(os.environ, handed, clear=True):
            from pip._internal.commands import create_command
            pip_options, _ = create_command("install").parse_args(["--proxy="])
        self.assertEqual(pip_options.cert, options["caFile"])
        self.assertEqual(pip_options.trusted_hosts, ["packages.example.test"])
        self.assertEqual(pip_options.index_url, "https://packages.example.test/simple")
        git = subprocess.run(["git", "config", "--get", "http.sslVerify"], cwd=self.directory,
            env=handed, capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.assertEqual(git.stdout.strip(), "false")
        npm_command = ([environment.get("COMSPEC", "cmd.exe"), "/d", "/c", "npm.cmd --prefix runtime config get strict-ssl"]
                       if os.name == "nt" else ["npm", "--prefix", "runtime", "config", "get", "strict-ssl"])
        npm = subprocess.run(npm_command, cwd=self.directory, env=handed,
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.assertEqual(npm.returncode, 0, npm.stderr)
        self.assertEqual(npm.stdout.strip(), "false")
        for file, content in original.items():
            self.assertEqual(file.read_bytes(), content)

    def test_unsupported_route_is_explained_when_direct_also_fails(self):
        result = {"ok": False, "category": "dns", "attempts": [
            {"route": "系统代理", "code": "PREVIEW_PROXY_UNSUPPORTED"},
            {"route": "直连", "code": "ENOTFOUND"}]}
        self.manager._network = Mock(result=result)
        with self.assertRaises(PreviewError) as caught:
            self.manager._ensure_network()
        self.assertEqual(caught.exception.category, "dns")
        self.assertIn("SOCKS", caught.exception.limitation)

    def test_unix_setup_forwards_default_and_direct_pip_arguments_with_nounset(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "setup.sh").read_text(encoding="utf-8")
        function = "preview_pip() {" + text.split("preview_pip() {", 1)[1].split("\n}", 1)[0] + "\n}\n"
        script = self.directory / "check.bash"
        script.write_text('set -eu\n' + function + '\npreview_pip install -r requirements.txt\n', encoding="utf-8")
        python = self.directory / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@"\n', encoding="utf-8")
        python.chmod(0o755)
        bash = shutil.which("bash")
        if os.name == "nt":
            bash = str(Path(shutil.which("git")).resolve().parent.parent / "bin/bash.exe")
        self.assertTrue(bash, "Bash is required for the setup contract")
        for direct in ("0", "1"):
            with self.subTest(direct=direct):
                env = dict(os.environ, HOME=str(self.directory), UMEKO_PREVIEW_DIRECT=direct)
                result = subprocess.run([bash, script.as_posix()], cwd=self.directory, env=env,
                    capture_output=True, text=True, check=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                expected = ["-m", "pip", "install", "-r", "requirements.txt"]
                if direct == "1": expected.append("--proxy=")
                self.assertEqual(result.stdout.splitlines(), expected)


if __name__ == "__main__":
    unittest.main()
