"""DSH model-source boundaries using isolated files and synthetic credentials.

The only HTTP request reaches an existing LocalServer with a fake SDK plugin.
No external service, installed CLI, real model or personal profile is accessed.
"""
import copy
import json
import os
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtTest import QTest

from app import dsh_backend
from app.gateway import Gateway, LocalServer, openai_response
from app.integration import Completion

try:
    from . import test_dsh_backend as backend_fixture
except ImportError:
    import test_dsh_backend as backend_fixture


LOCAL_TOKEN = "synthetic-local-proxy-token"
PROXY_URL = "http://127.0.0.1:19001/v1"


def source_providers():
    """Each transport has a distinct alias and an upstream-only identity."""
    return [{
        "id": kind, "name": "Fixture " + kind, "api": kind,
        "baseUrl": "https://" + kind + ".invalid/private-upstream",
        "key": "synthetic-upstream-secret-" + kind,
        "models": [{"alias": "Alias-" + kind, "upstream": "upstream-only-" + kind,
                    "contextWindow": 32000}],
    } for kind in ("openai", "anthropic", "plugin", "internal")]


def configured_providers(rows):
    return next(row for row in rows if row.get("id") == "llm-pi-ai")["config"]["providers"]


class DshProfileSourceTests(unittest.TestCase):
    def test_all_provider_kinds_use_existing_proxy_aliases_and_only_local_token(self):
        providers = source_providers()
        rows, environment = dsh_backend.profile_configuration(
            providers, "plugin", "Alias-plugin", 4096, "auto", None,
            proxy_url=PROXY_URL, proxy_token=LOCAL_TOKEN)
        configured = configured_providers(rows)
        self.assertEqual(set(configured), {provider["id"] for provider in providers})
        self.assertEqual(environment, {"UMEKO_DSH_PROXY_TOKEN": LOCAL_TOKEN})
        for provider in providers:
            with self.subTest(kind=provider["api"]):
                actual = configured[provider["id"]]
                self.assertEqual(actual["api"], "openai-completions")
                self.assertEqual(actual["baseURL"], PROXY_URL)
                self.assertEqual(actual["apiKeyEnv"], "UMEKO_DSH_PROXY_TOKEN")
                self.assertEqual([model["id"] for model in actual["models"]],
                                 [model["alias"] for model in provider["models"]])
        serialized = json.dumps(rows)
        self.assertNotIn(LOCAL_TOKEN, serialized)
        for provider in providers:
            for forbidden in (provider["key"], provider["baseUrl"], provider["models"][0]["upstream"]):
                self.assertNotIn(forbidden, serialized)
        for identifier in ("acp", "agent-default-model"):
            selection = next(row["config"] for row in rows if row.get("id") == identifier)
            self.assertEqual(selection, {"provider": "plugin", "model": "Alias-plugin"})

    def test_own_configuration_adds_policy_and_session_root_without_provider_selection(self):
        with tempfile.TemporaryDirectory(prefix="umeko-dsh-source-profile-") as directory:
            session_root = str(Path(directory) / "native-sessions")
            rows, environment = dsh_backend.profile_configuration(
                [], "", "", 4096, "ask", None, own_config=True,
                proxy_url=PROXY_URL, proxy_token=LOCAL_TOKEN, session_root=session_root)
        self.assertEqual(environment, {})
        ids = {row.get("id") for row in rows}
        self.assertFalse(ids.intersection({"llm-pi-ai", "acp", "agent-default-model",
                                          "llm-deepseek", "llm-deepseek-account", "deepseek-account"}))
        self.assertIn("sandbox-policy", ids)
        persistence = next(row for row in rows if row.get("id") == "session-persistence-jsonl")
        self.assertEqual(persistence["config"]["root"], session_root)
        self.assertNotIn(LOCAL_TOKEN, json.dumps(rows))

    def test_profile_alias_reaches_fake_login_plugin_through_same_localserver(self):
        providers = source_providers()
        calls = []

        class FakeLoginPlugin:
            def events(self, provider_id, model, messages, tools, max_tokens, parameters):
                calls.append((provider_id, model, messages))
                yield openai_response(Completion("existing-plugin-route", input_tokens=3, output_tokens=2), model)

        with tempfile.TemporaryDirectory(prefix="umeko-dsh-source-http-") as directory:
            store = SimpleNamespace(data={"providers": providers}, directory=Path(directory))
            gateway = Gateway(store, SimpleNamespace(ready=False), FakeLoginPlugin())
            server = LocalServer(gateway, 0, LOCAL_TOKEN, private=True)
            self.addCleanup(server.close)
            rows, environment = dsh_backend.profile_configuration(
                providers, "plugin", "Alias-plugin", 4096, "auto", None,
                proxy_url=f"http://127.0.0.1:{server.port}/v1", proxy_token=LOCAL_TOKEN)
            provider = configured_providers(rows)["plugin"]
            body = {"model": provider["models"][0]["id"],
                    "messages": [{"role": "user", "content": "synthetic request"}]}
            request = urllib.request.Request(provider["baseURL"] + "/chat/completions",
                data=json.dumps(body).encode(), headers={"Content-Type": "application/json",
                    "Authorization": "Bearer " + environment[provider["apiKeyEnv"]]})
            # Explicitly bypass machine proxy settings for this loopback fixture.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=3) as response:
                result = json.load(response)
        self.assertEqual(result["choices"][0]["message"]["content"], "existing-plugin-route")
        self.assertEqual(calls, [("plugin", "upstream-only-plugin", body["messages"])])


class DshModelSourceControllerTests(unittest.TestCase):
    def setUp(self):
        # Reuse setup only: do not inherit or rerun the backend test suite.
        self.fixture = backend_fixture.DshBackendTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.controller = self.fixture.controller
        self.controller.private_server.port = 19001

    def test_default_child_environment_removes_upstream_credentials_and_files_have_no_token(self):
        fixture, controller = self.fixture, self.controller
        providers = controller.store.data["providers"]
        inherited = {"PATH": os.environ.get("PATH", ""), "OPENAI_API_KEY": "synthetic-inherited-key",
                     "ANTHROPIC_AUTH_TOKEN": "synthetic-inherited-auth",
                     "RENAMED_CREDENTIAL": providers[0]["key"],
                     "ANOTHER_RENAMED_CREDENTIAL": providers[1]["key"],
                     "SAFE_VALUE": "keep-this-value"}
        with patch.object(dsh_backend, "npm_environment", return_value=inherited.copy()):
            _record, process = fixture.start_dsh()
        self.assertEqual(process.start["model"], {"provider": "fixture-openai", "id": "Alpha"})
        self.assertEqual(process.environment["UMEKO_DSH_PROXY_TOKEN"], controller.private_token)
        self.assertEqual(process.environment["SAFE_VALUE"], "keep-this-value")
        for key in inherited.keys() - {"PATH", "SAFE_VALUE"}:
            self.assertNotIn(key, process.environment)
        for provider in providers:
            self.assertNotIn(provider["key"], process.environment.values())
        serialized_start = json.dumps(process.start)
        self.assertNotIn(controller.private_token, serialized_start)
        home = Path(process.start["home"])
        files = [path for path in home.rglob("*") if path.is_file()]
        self.assertTrue(files)
        for path in files:
            content = path.read_text(encoding="utf-8")
            self.assertNotIn(controller.private_token, content)
            for provider in providers:
                self.assertNotIn(provider["key"], content)
                self.assertNotIn(provider["baseUrl"], content)

    def test_own_mode_preserves_external_home_and_environment_and_uses_managed_overlay(self):
        fixture, controller = self.fixture, self.controller
        external = fixture.directory / "external-dsh-home"
        original = external / "profiles/acp/cordis.yml"
        original.parent.mkdir(parents=True)
        original_text = "# user's independent configuration\nnative-provider: keep-me\n"
        original.write_text(original_text, encoding="utf-8")
        inherited = {"PATH": os.environ.get("PATH", ""), "DSH_HOME": str(external),
                     "OPENAI_API_KEY": "synthetic-own-key", "ANTHROPIC_AUTH_TOKEN": "synthetic-own-auth"}
        controller.dshRuntime.setUseOwnConfig(True)
        with patch.object(dsh_backend, "npm_environment", return_value=inherited.copy()):
            _record, process = fixture.start_dsh()
        self.assertTrue(process.start["useOwnConfig"])
        for key in ("home", "model", "reasoningEffort"):
            self.assertNotIn(key, process.start)
        self.assertEqual(process.environment, {**inherited, "DSH_TELEMETRY_DISABLED": "1"})
        self.assertNotIn("UMEKO_DSH_PROXY_TOKEN", process.environment)
        self.assertEqual(original.read_text(encoding="utf-8"), original_text)
        self.assertEqual([path for path in external.rglob("*") if path.is_file()], [original])
        self.assertTrue(process.start["patchFiles"])
        for value in process.start["patchFiles"]:
            path = Path(value)
            self.assertTrue(path.is_relative_to(controller.store.directory))
            self.assertFalse(path.is_relative_to(external))
            rows = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse({row.get("id") for row in rows}.intersection(
                {"llm-pi-ai", "acp", "agent-default-model"}))

    def test_source_mode_is_persistent_but_existing_session_keeps_its_source_and_root(self):
        fixture, controller = self.fixture, self.controller
        self.assertFalse(controller.dshRuntime.useOwnConfig)
        controller.dshRuntime.setUseOwnConfig(True)
        self.assertTrue(controller.store.data["dsh"]["useOwnConfig"])
        record, process = fixture.start_dsh("独立配置会话")
        fixture.event("delta", text="fixture answer")
        fixture.event("dsh_done", stopReason="end_turn")
        first = next(row for row in controller._sessions if row["id"] == record.id)
        self.assertTrue(first["dshOwnConfig"])
        session_root = first["dshSessionRoot"]
        self.assertTrue(session_root)
        controller.dshRuntime.setUseOwnConfig(False)
        self.assertFalse(controller.store.data["dsh"]["useOwnConfig"])
        # Recreate an exited worker after the setting change. The fixture's
        # process handle is intentionally not a QObject for QTimer retirement.
        process.running = False
        record.process, record.ready = None, False
        self.assertTrue(controller.send("同一会话的新消息"))
        self.assertTrue(fixture.launches[-1].start["useOwnConfig"])
        fixture.event("dsh_ready")
        fixture.event("dsh_done", stopReason="end_turn")
        session_id = record.id
        controller.close()
        fixture.controllers.remove(controller)
        restored = fixture.make_controller()
        restored.private_server.port = 19001
        self.assertFalse(restored.dshRuntime.useOwnConfig)
        restored.openSession(session_id)
        deadline = time.monotonic() + 3
        while len(fixture.launches) < 3 and time.monotonic() < deadline:
            QTest.qWait(5)
        reopened = fixture.launches[-1]
        self.assertEqual(reopened.start["action"], "open")
        self.assertTrue(reopened.start["useOwnConfig"])
        restored_row = next(row for row in restored._sessions if row["id"] == session_id)
        self.assertEqual(restored_row["dshSessionRoot"], session_root)
        overlay = json.loads(Path(reopened.start["patchFiles"][0]).read_text(encoding="utf-8"))
        persistence = next(row for row in overlay if row.get("id") == "session-persistence-jsonl")
        self.assertEqual(persistence["config"]["root"], session_root)

    def test_native_model_option_is_selected_as_offered_opaque_value(self):
        fixture, controller = self.fixture, self.controller
        controller.dshRuntime.setUseOwnConfig(True)
        _record, process = fixture.start_dsh()
        opaque = '["native-login-account", "native-model?variant=2"]'
        fixture.event("dsh_config", configOptions=[{
            "id": "provider_model", "category": "model", "currentValue": "native-original",
            "options": [{"name": "Native account", "options": [{"name": "Native model", "value": opaque}]}],
        }])
        fixture.event("dsh_done", stopReason="end_turn")
        self.assertTrue(controller.selectDshModel(opaque))
        self.assertEqual(process.writes[-1], {"type": "set_config", "configId": "provider_model", "value": opaque})
        previous = copy.deepcopy(process.writes)
        self.assertFalse(controller.selectDshModel("invented-native-value"))
        self.assertEqual(process.writes, previous)


if __name__ == "__main__":
    unittest.main()
