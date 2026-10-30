"""TLS defaults and live credential replacement, using only local fakes."""
import copy
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from umeko_provider_sdk import ProviderContext, ProviderError
from test_codearts_transport import FakeServer, TOOLS, collect

PACKAGE = "_codearts_credential_tests"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(Path(__file__).resolve().parents[1] / "provider_dev/plugins/codearts/scripts")]
sys.modules[PACKAGE] = package
plugin = importlib.import_module(PACKAGE + ".provider")
account_module = importlib.import_module(PACKAGE + ".account")
transport_module = importlib.import_module(PACKAGE + ".transport")
server_module = importlib.import_module(PACKAGE + ".server")
OLD = ("FAKE_OLD_AK", "FAKE_OLD_SK")
NEW = ("FAKE_NEW_AK", "FAKE_NEW_SK")
MODEL = "fixture/model"


class MemorySecrets:
    def __init__(self):
        self.values = {"account": dict(zip(("ak", "sk"), OLD))}
        self.fail = False

    def get(self, name, default=None):
        return copy.deepcopy(self.values.get(name, default))

    def set(self, name, value):
        if self.fail:
            raise OSError("fixture storage failure")
        self.values[name] = copy.deepcopy(value)


class FakeProcess:
    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def kill(self):
        self.returncode = -1

    def wait(self, **_):
        return self.returncode


class CredentialLifecycleTests(unittest.TestCase):
    def setUp(self):
        base = Path("C:/UmekoTests") if os.name == "nt" else Path(tempfile.gettempdir())
        base.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(prefix="codearts-keys-", dir=base)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.cli = self.root / "codearts.exe"
        self.cli.touch()
        self.downloads = self.root / "Downloads"
        self.downloads.mkdir()
        self.secrets = MemorySecrets()
        self.context = ProviderContext(config={}, state_dir=self.root / "state", secrets=self.secrets,
                                       downloads_dir=self.downloads, language="en")
        self.validation_ok = True
        self.launches = []
        self.controllers = []
        self.validation_environments = []

        def runner(command, *, env, **_):
            self.assertEqual(command, [str(self.cli), "models"])
            self.validation_environments.append(dict(env))
            return subprocess.CompletedProcess(command, 0 if self.validation_ok else 1,
                                               (MODEL + "\n").encode(), b"")

        def account(context, **kwargs):
            result = account_module.CodeartsAccount(context, runner=runner, **kwargs)
            result._find_cli = lambda: self.cli
            return result

        def controller(account, state_dir, **kwargs):
            fake = FakeServer("silent")
            self.addCleanup(fake.close)

            def launcher(command, **options):
                self.assertIn("serve", command)
                self.assertEqual(options["creationflags"], getattr(subprocess, "CREATE_NO_WINDOW", 0))
                process = FakeProcess()
                self.launches.append((dict(options["env"]), process, fake))
                return process

            result = server_module.CodeartsServer(account, state_dir, launcher=launcher,
                                                  request=lambda *_args, **_kw: True, **kwargs)
            result._port = lambda: fake.http.server_port
            self.controllers.append(result)
            return result

        self.addCleanup(patch.stopall)
        patch.object(plugin, "CodeartsAccount", side_effect=account).start()
        patch.object(transport_module, "CodeartsServer", side_effect=controller).start()
        patch.object(plugin, "CodeartsTransport", side_effect=lambda context, account:
                     transport_module.CodeartsTransport(context, account, request_timeout=1,
                                                        inactivity_timeout=3, handoff_timeout=4)).start()
        self.provider = plugin.CodeartsProvider(self.context)
        self.addCleanup(self.provider.close)

    def request(self, label):
        transport = self.provider.transport
        transport.server.connection()
        env, process, fake = self.launches[-1]
        count = len(fake.prompts) + 1
        with ThreadPoolExecutor() as pool:
            future = pool.submit(collect, self.provider.events(MODEL, [{"role": "user", "content": label}], TOOLS, 20, {}))
            self.assertTrue(fake.wait_prompts(count))
            sid = fake.prompts[-1][0]
            fake.emit("message.part.delta", sessionID=sid, partID="text", field="text", delta=label)
            fake.emit("session.idle", sessionID=sid)
            self.assertEqual(future.result(timeout=3)[0]["content"], label)
        return transport, env, process, fake

    def assert_pair(self, env, expected):
        self.assertEqual((env["CODEARTS_CLI_AK"], env["CODEARTS_CLI_SK"]), expected)

    def assert_retired(self, transport, process, fake):
        self.assertTrue(transport._closed)
        self.assertFalse(transport._states)
        self.assertEqual(fake.deleted, ["/session/ses-1"])
        self.assertEqual(transport.server._leases, {})
        self.assertFalse(transport.server._processes)
        self.assertIsNotNone(process.poll())
        self.assertFalse(self.context.cancelled.is_set())

    def test_no_default_tls_bypass_in_validation_or_service_and_trusted_ca_is_preserved(self):
        with patch.dict(os.environ, {"NODE_EXTRA_CA_CERTS": str(self.root / "enterprise-ca.pem")}):
            os.environ.pop("NODE_TLS_REJECT_UNAUTHORIZED", None)
            result = self.provider.account.begin()
            self.assertTrue(result["ready"])
            _, env, _, _ = self.request("tls-default")
        for child_env in [self.validation_environments[0], env]:
            self.assertNotIn("NODE_TLS_REJECT_UNAUTHORIZED", child_env)
            self.assertNotIn("PYTHONHTTPSVERIFY", child_env)
            self.assertNotIn("BUN_TLS_REJECT_UNAUTHORIZED", child_env)
            self.assertEqual(child_env["NODE_EXTRA_CA_CERTS"], str(self.root / "enterprise-ca.pem"))

    def test_successful_key_change_retires_sessions_and_next_model_request_uses_new_keys(self):
        old, env, process, fake = self.request("old-account")
        self.assert_pair(env, OLD)
        self.provider.set_card_secret("credentials", "\n".join(NEW))
        self.assert_retired(old, process, fake)
        current, env, _, _ = self.request("new-account")
        self.assertIsNot(current, old)
        self.assert_pair(env, NEW)
        self.assertEqual(len(self.launches), 2)

    def test_failed_validation_or_save_keeps_the_old_working_service(self):
        old, env, process, fake = self.request("before-failure")
        for failure in ("validation", "save"):
            with self.subTest(failure=failure):
                self.validation_ok = failure != "validation"
                self.secrets.fail = failure == "save"
                with self.assertRaises(ProviderError):
                    self.provider.set_card_secret("credentials", "\n".join(NEW))
                current, env, current_process, _ = self.request(failure)
                self.assertIs(current, old)
                self.assertIs(current_process, process)
                self.assertIsNone(process.poll())
                self.assert_pair(env, OLD)
                self.assertEqual(self.secrets.get("account"), dict(zip(("ak", "sk"), OLD)))
                self.assertEqual(len(self.launches), 1)
                self.assertEqual(fake.deleted, [])

    def test_same_verified_keys_keep_the_live_service(self):
        old, _, process, _ = self.request("before-same-key")
        self.provider.set_card_secret("credentials", "\n".join(OLD))
        current, _, _, _ = self.request("after-same-key")
        self.assertIs(current, old)
        self.assertIsNone(process.poll())
        self.assertEqual(len(self.launches), 1)

    def test_automatic_csv_import_uses_the_same_service_update_path(self):
        old, _, process, fake = self.request("before-csv")
        ready = threading.Event()
        self.context.notify = lambda event: ready.set() if event.get("refreshModels") else None
        self.provider.card_action("open_console")
        csv = self.downloads / "browser-renamed.csv"
        csv.write_text("Access Key Id,Secret Access Key\n" + ",".join(NEW) + "\n", encoding="utf-8")
        self.assertTrue(ready.wait(4))
        self.provider._stop_watch()
        self.assertFalse(csv.exists())
        self.assert_retired(old, process, fake)
        _, env, _, _ = self.request("after-csv")
        self.assert_pair(env, NEW)


if __name__ == "__main__":
    unittest.main()
