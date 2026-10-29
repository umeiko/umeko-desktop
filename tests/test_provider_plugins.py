"""Public Provider lifecycle checks use synthetic, offline implementations only."""
import copy
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QUrl

from app.controller import Controller
from umeko_provider_sdk import ProviderError, collect_openai, ConsentForm, HttpSession, response_cookies
from umeko_provider_sdk.packages import pack_package, unpack_package

ROOT = Path(__file__).resolve().parents[1]

IMPLEMENTATION = '''from umeko_provider_sdk import Provider, ProviderError
class Fixture(Provider):
    def __init__(self, context):
        super().__init__(context)
        self.models = [{"id":"k3", "contextWindow":32768, "vision":True}]
        self.received = None
    def authenticate(self, credentials):
        if credentials["password"] != "fixture-password": raise ProviderError("Invalid fixture credentials")
        self.context.secrets.set("session", {"access_token":"fixture-access-token"})
        return {"label":"Signed in"}
    def list_models(self, refresh=False): return self.models
    def events(self, model, messages, tools, max_tokens, parameters):
        self.received = (model, messages, tools, max_tokens, parameters)
        yield {"choices":[{"delta":{"content":"fixture", "tool_calls":None},"finish_reason":"stop"}]}
        yield {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":2}}
def create_provider(context): return Fixture(context)
'''


class ProviderPluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"UMEKO_DATA_DIR": str(self.path / "data")})
        self.environment.start()
        self.folder = self.path / "fixture"
        shutil.copytree(ROOT / "provider_dev/examples/echo-provider", self.folder)
        manifest = json.loads((self.folder / "manifest.json").read_text())
        manifest["auth"]["fields"] += [{"key":"password", "label":"Password", "secret":True, "required":True}]
        (self.folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.marker = self.path / "executed.txt"
        code = f"from pathlib import Path\nPath({str(self.marker)!r}).write_text('activated')\n" + IMPLEMENTATION
        (self.folder / "scripts/provider.py").write_text(code, encoding="utf-8")
        self.archive = self.path / "fixture.zip"
        pack_package(self.folder, self.archive)
        # Import lifecycle tests install only their synthetic package fixture.
        with patch("app.provider_plugins.BundledProviders.sync", return_value=[]):
            self.controller = Controller(ROOT)
        self.manager = self.controller.providerPlugins
        self.notices = []
        self.controller.toast.connect(self.notices.append)

    def tearDown(self):
        self.controller.close()
        self.environment.stop()
        self.temp.cleanup()

    def install(self):
        self.assertTrue(self.manager.importZip(QUrl.fromLocalFile(str(self.archive)).toString()), self.notices)
        return self.manager.rows[-1]["id"]

    def wait(self, provider_id):
        deadline = time.monotonic() + 4
        while provider_id in self.manager.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.app.processEvents()
        self.assertNotIn(provider_id, self.manager.busy)

    def login(self, provider_id, username="fixture-user", password="fixture-password"):
        self.manager.login(provider_id, json.dumps({"username": username, "password": password}))
        self.wait(provider_id)

    def wait_for_pi(self):
        deadline = time.monotonic() + 15
        while self.controller.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.app.processEvents()
        self.assertFalse(self.controller.busy, "Pi fixture timed out")

    def test_history_with_removed_model_continues_through_imported_provider(self):
        provider_id = self.install()
        self.login(provider_id)
        c = self.controller
        c.store.data["agent"].update(agentDir=str(self.path / "agent"), safeMode=True)
        file = self.path / "legacy.jsonl"
        rows = [
            {"type":"session", "id":"old-history", "version":3, "timestamp":"2026-01-01T00:00:00Z", "cwd":str(self.path)},
            {"type":"model_change", "id":"old-model", "parentId":None, "timestamp":"2026-01-01T00:00:00Z", "provider":"umeko", "modelId":"retired-model"},
            {"type":"message", "id":"old-user", "parentId":"old-model", "timestamp":"2026-01-01T00:00:00Z", "message":{"role":"user", "content":[{"type":"text", "text":"previous fixture question"}], "timestamp":1}},
        ]
        original = ("\n".join(json.dumps(row) for row in rows) + "\n").encode()
        file.write_bytes(original)
        c._sessions.append({"id":"old-history", "title":"Old fixture", "workspace":str(self.path), "file":str(file), "model":"retired-model", "provider":"removed-provider"})
        c.openSession("old-history")
        self.wait_for_pi()
        self.assertTrue(c._view.ready)
        self.assertEqual((c._view.provider, c._view.model), (provider_id, "k3"))
        self.assertTrue(c.send("continue fixture"))
        self.wait_for_pi()
        self.assertFalse(c.messages[-1]["error"], c.messages)
        self.assertEqual(c.messages[-1]["text"], "fixture")
        self.assertEqual(c._view.file, str(file))
        self.assertTrue(file.read_bytes().startswith(original), "Restoring a model rewrote existing history")
        self.assertEqual(c.messages[0]["text"], "previous fixture question")

    def test_failed_initialization_is_disposed_before_retry(self):
        self.login(self.install())
        c = self.controller
        c.store.data["agent"].update(agentDir=str(self.path / "agent"), safeMode=True)
        with patch.object(c.gateway, "models", return_value=[]):
            self.assertTrue(c._command_pi("inspect"))
            self.wait_for_pi()
        self.assertFalse(c._view.ready)
        self.assertIsNone(c._view.process, "An uninitialized Pi was kept for incremental requests")
        self.assertTrue(c.send("retry fixture"))
        self.wait_for_pi()
        self.assertTrue(c._view.ready)
        self.assertFalse(c.messages[-1]["error"], c.messages)
        self.assertEqual(c.messages[-1]["text"], "fixture")

    def test_import_is_inert_and_no_builtin_account_or_default_model(self):
        self.assertEqual(self.controller.config["providers"], [])
        self.assertEqual(self.controller.gateway.models(), [])
        provider_id = self.install()
        self.assertFalse(self.marker.exists(), "Import executed provider code")
        self.assertEqual(self.manager.rows[0]["models"], [])
        self.login(provider_id)
        self.assertTrue(self.marker.exists())
        self.assertEqual(self.controller.gateway.models()[0]["id"], "k3")
        self.assertEqual(self.controller.config["selectedProvider"], provider_id)

    def test_history_without_an_available_model_can_still_be_browsed(self):
        c = self.controller
        c._sessions.append({"id":"old-no-model", "title":"Old fixture", "workspace":"", "model":"retired-model", "provider":"removed-provider", "messages":[{"role":"user", "text":"previous fixture question"}]})
        c.openSession("old-no-model")
        self.assertFalse(c.busy)
        self.assertIsNone(c._view.process)
        self.assertEqual(c.messages[0]["text"], "previous fixture question")
        self.assertEqual((c._view.provider, c._view.model), ("", ""))

    def test_valid_history_selection_is_kept(self):
        first, second = self.install(), self.install()
        self.login(first)
        self.login(second, username="second-user")
        c = self.controller
        c.selectModel(second, self.manager.rows[1]["models"][0]["alias"])
        historical = c._new_view()
        historical.provider, historical.model = first, "k3"
        c._activate(historical)
        self.assertEqual((c.config["selectedProvider"], c.config["selectedModel"]), (first, "k3"))

    def test_protected_credentials_same_account_reuse_and_changed_account_requires_secret(self):
        provider_id = self.install()
        self.login(provider_id)
        public = json.dumps(self.manager.rows) + json.dumps(self.controller.config)
        self.assertNotIn("fixture-password", public)
        self.assertNotIn("fixture-access-token", public)
        secret_path = self.manager._secrets(provider_id).path
        self.assertNotIn("fixture-password", secret_path.read_text())
        self.assertNotIn("fixture-access-token", secret_path.read_text())
        self.login(provider_id, password="")
        self.assertEqual(len(self.manager.rows[0]["models"]), 1)
        self.manager.login(provider_id, json.dumps({"username":"different-user", "password":""}))
        self.assertIn("Password", self.notices[-1])
        self.assertNotIn(provider_id, self.manager.busy)

    def test_discovery_overrides_empty_models_and_multimodal_gateway(self):
        provider_id = self.install()
        self.login(provider_id)
        models = copy.deepcopy(self.manager.rows[0]["models"])
        models[0].update(alias="custom-alias", contextWindow=65536, contextWindowAuto=False, vision=True, visionAuto=False)
        self.assertTrue(self.manager.saveModels(provider_id, json.dumps(models)))
        self.manager.refreshModels(provider_id)
        self.wait(provider_id)
        row = self.manager.rows[0]["models"][0]
        self.assertEqual((row["alias"], row["contextWindow"], row["vision"]), ("custom-alias", 65536, True))
        messages = [{"role":"user", "content":[{"type":"text", "text":"fixture"}, {"type":"image_url", "image_url":{"url":"data:image/png;base64,cGl4ZWxz"}}]}]
        tools = [{"name":"read", "parameters":{"type":"object"}}]
        completion = self.controller.gateway.complete("custom-alias", messages, tools, 32, provider_id, {"temperature":.1, "reasoning_effort":"max"})
        self.assertEqual(completion.text, "fixture")
        self.assertEqual((completion.input_tokens, completion.output_tokens), (5, 2))
        client = self.manager.clients[provider_id]
        self.assertEqual(client.received, ("k3", messages, tools, 32, {"temperature":.1, "reasoning_effort":"max"}))
        client.models = []
        self.manager.refreshModels(provider_id)
        self.wait(provider_id)
        self.assertEqual(self.manager.rows[0]["models"], [])
        self.assertEqual(self.controller.config["selectedModel"], "")

    def test_instance_isolation_busy_guard_and_config_invalidation(self):
        first, second = self.install(), self.install()
        self.login(first)
        self.login(second, username="second-user")
        self.assertIsNot(self.manager.clients[first], self.manager.clients[second])
        self.assertNotEqual(self.manager._secrets(first).path, self.manager._secrets(second).path)
        self.manager.leases[first] = 1
        self.manager.remove(first)
        self.assertEqual(len(self.manager.rows), 2)
        self.assertFalse(self.manager.saveConfig(first, '{"prefix":"changed"}'))
        self.manager.leases[first] = 0
        self.assertTrue(self.manager.saveConfig(first, '{"prefix":"changed"}'))
        self.assertIsNone(self.manager._secrets(first).get("session"))
        self.assertIsNotNone(self.manager._secrets(second).get("session"))
        self.manager.remove(first)
        self.assertEqual(len(self.manager.rows), 1)
        self.assertEqual(self.controller.config["selectedProvider"], second)

    def test_service_metadata_updates_until_the_user_overrides_it(self):
        provider_id = self.install()
        self.login(provider_id)
        self.manager.clients[provider_id].models[0]["contextWindow"] = 131072
        self.manager.refreshModels(provider_id)
        self.wait(provider_id)
        self.assertEqual(self.manager.rows[0]["models"][0]["contextWindow"], 131072)
        models = copy.deepcopy(self.manager.rows[0]["models"])
        models[0]["contextWindow"] = 65536
        self.assertTrue(self.manager.saveModels(provider_id, json.dumps(models)))
        self.manager.clients[provider_id].models[0]["contextWindow"] = 262144
        self.manager.refreshModels(provider_id)
        self.wait(provider_id)
        self.assertEqual(self.manager.rows[0]["models"][0]["contextWindow"], 65536)

    def test_changed_code_requires_new_version_and_bad_archives_are_rejected(self):
        self.install()
        (self.folder / "scripts/provider.py").write_text(IMPLEMENTATION + "\n# modified", encoding="utf-8")
        pack_package(self.folder, self.archive)
        self.assertFalse(self.manager.importZip(QUrl.fromLocalFile(str(self.archive)).toString()))
        with zipfile.ZipFile(self.path / "traversal.zip", "w") as stream:
            stream.writestr("../escape.txt", "fixture")
            stream.writestr("manifest.json", "{}")
        with self.assertRaises(ProviderError): unpack_package(self.path / "traversal.zip", self.path / "bad")
        self.assertFalse((self.path / "escape.txt").exists())

    def replace_fixture_code(self):
        path = self.folder / "scripts/provider.py"
        path.write_text(path.read_text(encoding="utf-8").replace('"content":"fixture"', '"content":"reloaded"'), encoding="utf-8")
        pack_package(self.folder, self.archive)

    def assert_reloaded_code(self, provider_id):
        self.login(provider_id)
        events = list(self.manager.events(provider_id, "k3", [], [], 32, {}))
        self.assertEqual(events[0]["choices"][0]["delta"]["content"], "reloaded")

    def test_account_deletion_preserves_plugin_and_uninstall_releases_loaded_code(self):
        first, second = self.install(), self.install()
        self.login(first)
        self.login(second)
        old_class = type(self.manager.clients[first])
        package, _ = self.manager._package(self.manager._record(first))
        self.manager.remove(first)
        self.assertTrue(package.is_dir())
        self.assertIsNotNone(self.manager._secrets(second).get("session"))
        self.replace_fixture_code()
        self.assertFalse(self.manager.importZip(QUrl.fromLocalFile(str(self.archive)).toString()))
        self.manager.remove(second)
        self.assertEqual(self.manager.rows, [])
        self.assertTrue(package.is_dir())
        self.assertEqual(self.manager.packages[0]["accountCount"], 0)
        self.assertFalse(self.manager.importZip(QUrl.fromLocalFile(str(self.archive)).toString()))
        restored = self.manager.addAccount(package.parent.name, package.name)
        self.assertTrue(restored)
        self.assertTrue(self.manager.uninstall(package.parent.name, package.name))
        self.assertEqual(self.manager.rows, [])
        saved = json.loads(self.controller.store.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["selectedProvider"], "")
        self.assertEqual(saved["selectedModel"], "")
        self.assertEqual(self.manager.packages, [])
        self.assertFalse(package.exists())
        third = self.install()
        self.assert_reloaded_code(third)
        self.assertIsNot(type(self.manager.clients[third]), old_class)

    def test_legacy_orphan_package_can_be_uninstalled_and_reinstalled_without_restart(self):
        first = self.install()
        self.login(first)
        package, _ = self.manager._package(self.manager._record(first))
        self.manager._invalidate(first)
        self.controller.store.data["providers"] = []  # Simulate an older release's removal.
        self.controller.store.save()
        self.assertTrue(package.is_dir())
        self.replace_fixture_code()
        self.assertFalse(self.manager.importZip(QUrl.fromLocalFile(str(self.archive)).toString()))
        self.assertEqual(self.manager.packages[0]["accountCount"], 0)
        self.assertTrue(self.manager.uninstall(package.parent.name, package.name))
        self.assert_reloaded_code(self.install())

    def test_removal_keeps_other_package_versions(self):
        first = self.install()
        old, _ = self.manager._package(self.manager._record(first))
        manifest_path = self.folder / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "2.0.0"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        pack_package(self.folder, self.archive)
        second = self.install()
        newer, _ = self.manager._package(self.manager._record(second))
        self.manager.remove(first)
        self.assertTrue(old.is_dir())
        self.assertTrue(self.manager.uninstall(old.parent.name, old.name))
        self.assertFalse(old.exists())
        self.assertTrue(newer.is_dir())
        self.login(second)

    def test_failed_uninstall_restores_package_accounts_and_credentials(self):
        first = self.install()
        self.login(first)
        package, _ = self.manager._package(self.manager._record(first))
        original = (package / "scripts/provider.py").read_bytes()
        with patch.object(self.controller.store, "save", side_effect=OSError("fixture write failure")):
            self.assertFalse(self.manager.uninstall(package.parent.name, package.name))
        self.assertEqual(self.manager.rows[0]["id"], first)
        self.assertIsNotNone(self.manager._secrets(first).get("session"))
        self.assertEqual((package / "scripts/provider.py").read_bytes(), original)
        self.login(first)
        self.assertTrue(self.manager.uninstall(package.parent.name, package.name))
        self.replace_fixture_code()
        self.assert_reloaded_code(self.install())

    def test_uninstall_checks_every_account_before_removing_anything(self):
        first, second = self.install(), self.install()
        package, _ = self.manager._package(self.manager._record(first))
        self.manager.leases[second] = 1
        self.assertFalse(self.manager.uninstall(package.parent.name, package.name))
        self.assertEqual(len(self.manager.rows), 2)
        self.assertTrue(package.is_dir())
        self.manager.leases[second] = 0
        self.assertTrue(self.manager.uninstall(package.parent.name, package.name))
        self.assertEqual(self.manager.rows, [])

    def test_import_exposes_exact_path_rule_and_conflicting_entry(self):
        with zipfile.ZipFile(self.archive, "w") as stream:
            stream.writestr("./scripts/../outside.py", "fixture")
        self.assertFalse(self.manager.importZip(QUrl.fromLocalFile(str(self.archive)).toString()))
        self.assertEqual(self.manager.importError["entry"], "./scripts/../outside.py")
        self.assertEqual(self.manager.importError["rule"], "PARENT_PATH")
        self.assertFalse(list((self.manager.root / "staging").glob("*")))


class ProviderSdkTests(unittest.TestCase):
    def test_repeated_cookie_headers_preserve_expiry_commas(self):
        from email.message import Message
        headers = Message()
        headers.add_header("Set-Cookie", "one=fixture-one; Expires=Wed, 21 Oct 2037 07:28:00 GMT; Path=/")
        headers.add_header("Set-Cookie", "two=fixture-two; HttpOnly; Path=/")
        self.assertEqual(response_cookies(headers), {"one":"fixture-one", "two":"fixture-two"})

    def test_redirect_origins_and_sensitive_header_handling(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                received.append((self.path, dict(self.headers)))
                self.send_response(302 if self.path in ("/cross", "/unknown") else 200)
                if self.path == "/cross": self.send_header("Location", f"http://localhost:{self.server.server_port}/destination")
                if self.path == "/unknown": self.send_header("Location", "http://127.0.0.1:9/destination")
                self.send_header("Content-Length", "0")
                self.end_headers()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            session = HttpSession([base, base.replace("127.0.0.1", "localhost")], environment_proxy=False)
            with session.request(base + "/cross", headers={"Authorization":"Bearer fixture", "Cookie":"fixture=value", "x-api-key":"fixture", "x-auth-token":"fixture"}) as response: response.read()
            destination = {k.lower(): v for k, v in received[-1][1].items()}
            self.assertFalse(any(k in destination for k in ("authorization", "cookie", "x-api-key", "x-auth-token")))
            with self.assertRaises(ProviderError): session.request(base + "/unknown")
            with self.assertRaises(ProviderError): HttpSession(["http://remote.invalid"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_nullable_calls_usage_and_multiple_nonstream_calls(self):
        data = collect_openai([{"choices":[{"delta":{"content":"ok", "tool_calls":None}}]}, {"choices":[], "usage":{"prompt_tokens":7}}])
        self.assertEqual(data["usage"]["prompt_tokens"], 7)
        data = collect_openai([{"choices":[{"message":{"tool_calls":[{"id":"a", "function":{"name":"one", "arguments":"{}"}}, {"id":"b", "function":{"name":"two", "arguments":"{}"}}]}}]}])
        self.assertEqual(len(data["choices"][0]["message"]["tool_calls"]), 2)

    def test_consent_attribute_order_and_quotes(self):
        form = ConsentForm()
        form.feed("<form method='post' action='/consent'><input value='csrf-fixture' name='csrf' type='hidden'><input value='scope-one' type='checkbox' name='scope'></form>")
        self.assertEqual(form.action, "/consent")
        self.assertEqual(form.values, [("csrf", "csrf-fixture"), ("scope", "scope-one")])
