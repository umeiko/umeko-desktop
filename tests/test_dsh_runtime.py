"""DSH discovery, isolated SDK health and transactional npm installation.

All packages and subprocess results are local fixtures. No public registry,
provider endpoint, user's DSH profile or visible Qt window is used.
"""
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from PySide6.QtCore import QCoreApplication

from app import dsh_runtime as runtime


def package(root, version=runtime.PINNED_VERSION, name=runtime.PACKAGE):
    folder = Path(root) / "node_modules" / runtime.PACKAGE
    (folder / "lib").mkdir(parents=True, exist_ok=True)
    (folder / "package.json").write_text(json.dumps({"name": name, "version": version}), encoding="utf-8")
    entry = folder / "lib/bin.js"
    entry.write_text("// local DSH test fixture\n", encoding="utf-8")
    return entry


def health(*args, **kwargs):
    return 0, json.dumps({"type": "health", "ok": True, "result": {"protocolVersion": 1}})


class DshRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bridge = self.root / "dsh-acp-bridge.mjs"
        self.bridge.write_text("// local SDK bridge fixture\n", encoding="utf-8")
        self.node = patch.object(runtime, "node_executable", return_value=sys.executable)
        self.env = patch.object(runtime, "npm_environment", return_value={"PATH": os.environ.get("PATH", "")})
        self.node.start(); self.env.start()

    def tearDown(self):
        self.node.stop(); self.env.stop(); self.temp.cleanup()

    def test_discovery_prefers_configured_then_managed_then_path_and_resolves_npm_cmd(self):
        configured = self.root / "configured"
        external = package(configured)
        own = self.root / "own"
        managed = package(own / runtime.RELEASE_NAME)
        shim = configured / "dsh.cmd"
        shim.write_text("@echo off\n", encoding="utf-8")
        with patch.object(runtime.shutil, "which", return_value=str(shim)):
            for selected in (configured, external, shim):
                found = runtime.discover_dsh(str(selected), own)
                self.assertEqual(found, {"path": str(external.resolve()), "source": "configured"})
            self.assertEqual(runtime.discover_dsh("", own)["path"], str(managed.resolve()))
            self.assertEqual(runtime.discover_dsh("", self.root / "empty")["source"], "path")

    def test_missing_path_does_not_probe_or_silently_use_other_installation(self):
        with patch.object(runtime.shutil, "which", return_value=None), patch.object(runtime, "_run") as run:
            with self.assertRaises(runtime.RuntimeFailure) as missing:
                runtime.check_dsh(str(self.root / "missing"), self.root)
            self.assertEqual(missing.exception.code, "missing")
            run.assert_not_called()

    def test_version_floor_official_identity_and_real_initialize_result_are_required(self):
        for version, name, code in [("0.2.1", runtime.PACKAGE, "version"),
                                    ("0.2.2-rc.0", runtime.PACKAGE, "version"),
                                    ("0.2.2-rc.1", "dsh", "package")]:
            with self.subTest(version=version, name=name):
                entry = package(self.root / version, version, name)
                with patch.object(runtime, "_run") as run:
                    with self.assertRaises(runtime.RuntimeFailure) as error:
                        runtime.check_dsh(str(entry), bridge=self.bridge)
                    self.assertEqual(error.exception.code, code)
                    run.assert_not_called()
        entry = package(self.root / "supported", "0.2.2")
        with patch.object(runtime, "_run", return_value=(0, '{"type":"health","ok":true}')):
            with self.assertRaises(runtime.RuntimeFailure) as error:
                runtime.check_dsh(str(entry), bridge=self.bridge)
            self.assertEqual(error.exception.code, "acp")

    def test_check_calls_sdk_health_with_temporary_home_and_no_model_request(self):
        entry = package(self.root / "runtime")
        calls = []
        def probe(command, **kwargs):
            calls.append((command, kwargs))
            env = kwargs["env"]
            self.assertTrue(Path(env["HOME"]).is_dir())
            self.assertEqual(env["HOME"], env["USERPROFILE"])
            self.assertNotEqual(env["HOME"], os.environ.get("USERPROFILE"))
            self.assertEqual(command[2:4], ["--health", "--dsh-bin"])
            self.assertEqual(command[4], str(entry))
            self.assertNotIn("--prompt", command)
            return health()
        with patch.object(runtime, "_run", side_effect=probe):
            result = runtime.check_dsh(str(entry), bridge=self.bridge)
        self.assertTrue(result["ok"])
        self.assertEqual(result["version"], runtime.PINNED_VERSION)
        self.assertEqual(len(calls), 1)
        self.assertFalse(Path(calls[0][1]["env"]["HOME"]).exists())

    def test_successful_install_uses_pinned_official_registry_and_replaces_only_after_health(self):
        own = self.root / "own"
        old = package(own / runtime.RELEASE_NAME)
        old.write_text("old working installation", encoding="utf-8")
        commands, progress = [], []
        def run(command, **kwargs):
            commands.append(command)
            if "install" in command:
                target = Path(command[command.index("--prefix") + 1])
                self.assertEqual(kwargs["env"]["npm_config_registry"], runtime.OFFICIAL_REGISTRY)
                self.assertEqual(kwargs["env"]["npm_config_userconfig"], "fixture.npmrc")
                self.assertEqual(kwargs["env"]["HTTPS_PROXY"], "http://127.0.0.1:9999")
                self.assertNotIn("NPM_CONFIG_REGISTRY", kwargs["env"])
                self.assertIn(runtime.PACKAGE + "@" + runtime.PINNED_VERSION, command)
                self.assertIn("--no-audit", command); self.assertIn("--no-fund", command)
                package(target)
                return 0, "installed"
            self.assertEqual(old.read_text(encoding="utf-8"), "old working installation")
            return health()
        env = {"NPM_CONFIG_REGISTRY": "https://mirror.invalid/", "npm_config_userconfig": "fixture.npmrc",
               "HTTPS_PROXY": "http://127.0.0.1:9999"}
        with patch.object(runtime, "npm_environment", side_effect=lambda *_: dict(env)), \
             patch.object(runtime, "npm_command", return_value=["node", "npm-cli.js"]), \
             patch("app.update_proxy.system_proxy", return_value=""), \
             patch.object(runtime, "_run", side_effect=run):
            result = runtime.install_dsh(own, bridge=self.bridge, progress=progress.append)
        self.assertTrue(result["ok"])
        self.assertEqual(result["path"], str(old))
        self.assertIn("fixture", old.read_text(encoding="utf-8"))
        self.assertEqual(list(own.iterdir()), [own / runtime.RELEASE_NAME])
        self.assertEqual(len(commands), 2)
        self.assertEqual(progress[-1]["progress"], 1.)

    def test_download_failure_health_failure_and_cancel_remove_staging_preserve_old(self):
        for mode in ("download", "health", "cancel"):
            with self.subTest(mode=mode):
                own = self.root / mode
                old = package(own / runtime.RELEASE_NAME)
                old.write_text("keep existing", encoding="utf-8")
                cancelled = threading.Event()
                def run(command, **kwargs):
                    if "install" in command:
                        package(Path(command[command.index("--prefix") + 1]))
                        if mode == "download": return 1, "local fixture failed"
                        if mode == "cancel": cancelled.set(); raise InterruptedError("cancel fixture")
                        return 0, "installed"
                    return 1, "ACP initialize failed"
                with patch.object(runtime, "npm_command", return_value=["node", "npm-cli.js"]), \
                     patch("app.update_proxy.system_proxy", return_value=""), \
                     patch.object(runtime, "_run", side_effect=run):
                    with self.assertRaises((runtime.RuntimeFailure, InterruptedError)):
                        runtime.install_dsh(own, bridge=self.bridge, cancelled=cancelled.is_set)
                self.assertEqual(old.read_text(encoding="utf-8"), "keep existing")
                self.assertEqual(list(own.iterdir()), [own / runtime.RELEASE_NAME])

    def test_publish_failure_rolls_back_existing_directory(self):
        own = self.root / "rollback"
        old = package(own / runtime.RELEASE_NAME)
        old.write_text("keep existing", encoding="utf-8")
        real_replace = os.replace
        def replace(source, target):
            if Path(source).name.startswith(".dsh-install-"):
                raise OSError("local fixture cannot publish")
            return real_replace(source, target)
        def run(command, **kwargs):
            if "install" in command:
                package(Path(command[command.index("--prefix") + 1])); return 0, ""
            return health()
        with patch.object(runtime, "npm_command", return_value=["node", "npm-cli.js"]), \
             patch("app.update_proxy.system_proxy", return_value=""), \
             patch.object(runtime, "_run", side_effect=run), patch.object(runtime.os, "replace", side_effect=replace):
            with self.assertRaises(OSError): runtime.install_dsh(own, bridge=self.bridge)
        self.assertEqual(old.read_text(encoding="utf-8"), "keep existing")
        self.assertEqual(list(own.iterdir()), [own / runtime.RELEASE_NAME])

    def test_real_npm_download_from_local_fake_registry(self):
        """Exercise HTTP acquisition/extraction, not a mocked npm subprocess."""
        from app.pi_runtime import node_executable as real_node_executable
        from app.npm_config import npm_environment as real_npm_environment
        manifest = {"name": runtime.PACKAGE, "version": runtime.PINNED_VERSION,
                    "bin": {"dsh": "lib/bin.js"}}
        archive_bytes = io.BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode="w:gz") as archive:
            for name, content in {
                "package.json": json.dumps(manifest).encode(),
                "lib/bin.js": b'console.log("0.2.2-rc.1");\n',
            }.items():
                item = tarfile.TarInfo("package/" + name)
                item.size = len(content)
                archive.addfile(item, io.BytesIO(content))
        tarball, requests = archive_bytes.getvalue(), []
        class Registry(BaseHTTPRequestHandler):
            def do_GET(self):
                route = unquote(urlsplit(self.path).path)
                requests.append(route)
                if route == "/fixture.tgz":
                    body = tarball
                    content_type = "application/octet-stream"
                elif route == "/@deepseek-ai/dsh":
                    version = {**manifest, "dist": {
                        "tarball": f"http://127.0.0.1:{self.server.server_port}/fixture.tgz"}}
                    body = json.dumps({"name": runtime.PACKAGE,
                        "dist-tags": {"latest": runtime.PINNED_VERSION},
                        "versions": {runtime.PINNED_VERSION: version}}).encode()
                    content_type = "application/json"
                else:
                    self.send_error(404); return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *_): pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Registry)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        userconfig = self.root / "fixture.npmrc"
        userconfig.write_text("", encoding="utf-8")
        globalconfig = self.root / "fixture-global.npmrc"
        globalconfig.write_text("", encoding="utf-8")
        bridge = self.root / "fake-health.mjs"
        bridge.write_text(
            'if (!process.argv.includes("--health")) process.exit(2);\n'
            'console.log(JSON.stringify({type:"health",ok:true,result:{protocolVersion:1}}));\n',
            encoding="utf-8")
        own = self.root / "http-runtime"
        def environment(config):
            values = real_npm_environment({**config, "npmUserconfig": str(userconfig)})
            # This test has no credentials or global npm/cache writes, and all
            # HTTP requests go directly to its loopback registry.
            for key in list(values):
                if key.lower() in ("http_proxy", "https_proxy", "all_proxy", "npm_config_proxy", "npm_config_https_proxy"):
                    values.pop(key)
            values.update(npm_config_cache=str(self.root / "npm-cache"),
                          npm_config_globalconfig=str(globalconfig),
                          NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
            return values
        try:
            with patch.object(runtime, "OFFICIAL_REGISTRY", f"http://127.0.0.1:{server.server_port}/"), \
                 patch.object(runtime, "node_executable", side_effect=real_node_executable), \
                 patch.object(runtime, "npm_environment", side_effect=environment), \
                 patch("app.update_proxy.system_proxy", return_value=""):
                result = runtime.install_dsh(own, bridge=bridge)
            self.assertTrue(result["ok"])
            self.assertEqual(result["version"], runtime.PINNED_VERSION)
            self.assertTrue(Path(result["path"]).is_file())
            self.assertIn("/@deepseek-ai/dsh", requests)
            self.assertIn("/fixture.tgz", requests)
            self.assertEqual(list(own.iterdir()), [own / runtime.RELEASE_NAME])
        finally:
            server.shutdown(); server.server_close(); worker.join(2)

    def test_owned_subprocess_cancel_returns_promptly_without_visible_console(self):
        stop = threading.Event()
        timer = threading.Timer(.25, stop.set)
        timer.start()
        started = time.monotonic()
        try:
            with self.assertRaises(InterruptedError):
                runtime._run([sys.executable, "-c", "import time; time.sleep(30)"],
                             cwd=self.root, env=dict(os.environ), cancelled=stop.is_set)
        finally:
            timer.cancel()
        self.assertLess(time.monotonic() - started, 10)

    def test_download_keeps_managed_path_auto_and_persists_on_owner_thread(self):
        app = QCoreApplication.instance() or QCoreApplication([])
        owner = threading.get_ident()
        calls, saved, results = [], [], []
        config = {}
        service = runtime.DshRuntimeService(self.root / "own", config,
            lambda: saved.append(threading.get_ident()), bridge=self.bridge)
        service.setPath("fixture path")
        self.assertEqual(config["dshPath"], "fixture path")
        def download(*args, **kwargs):
            calls.append(threading.get_ident())
            kwargs["progress"]({"progress": .8, "message": "fixture health"})
            installed = package(self.root / "own" / runtime.RELEASE_NAME)
            return {"ok": True, "message": "fixture ready", "path": str(installed), "version": runtime.PINNED_VERSION}
        service.finished.connect(results.append)
        with patch.object(runtime, "install_dsh", side_effect=download):
            service.download()
            self.assertTrue(service.busy)
            deadline = time.monotonic() + 3
            while not results and time.monotonic() < deadline:
                app.processEvents(); time.sleep(.01)
        self.assertTrue(results)
        self.assertNotEqual(calls, [owner])
        self.assertEqual(saved, [owner, owner])
        self.assertEqual(config["dshPath"], "")
        self.assertEqual(service.path, "")
        found = runtime.discover_dsh(service.path, service.runtime_root)
        self.assertEqual(found, {"path": results[0]["path"], "source": "managed"})
        self.assertEqual(service.resolvedPath, found["path"])
        self.assertEqual(service.version, runtime.PINNED_VERSION)
        self.assertEqual(service.status, "fixture ready")
        self.assertTrue(service.ready)
        self.assertFalse(service.busy)


if __name__ == "__main__":
    unittest.main()
