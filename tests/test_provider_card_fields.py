"""Public card-secret extension checks use synthetic, offline providers only."""
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QUrl

from app.controller import Controller
from umeko_provider_sdk import HttpSession, Provider, ProviderError
from umeko_provider_sdk.http import origin
from umeko_provider_sdk.packages import pack_package


ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "fixture-login-password"
SESSION = "fixture-session-token"
EXTRA_SECRET = "fixture-extra-secret"
PUBLIC_MESSAGE = "Extra credential saved"

IMPLEMENTATION = '''from umeko_provider_sdk import Provider, ProviderError
class Fixture(Provider):
    def __init__(self, context):
        super().__init__(context)
        self.auth_calls = 0
        self.secret_updates = 0
        self.refreshes = []
    def authenticate(self, credentials):
        self.auth_calls += 1
        if credentials["password"] != "fixture-login-password":
            raise ProviderError("Invalid fixture credentials")
        self.context.secrets.set("session", {"access_token":"fixture-session-token"})
        return {"label":"Signed in"}
    def card_fields(self):
        if not self.context.secrets.get("session"):
            return []
        return [{"key":"extra_key", "label":"Extra credential",
                 "hint":"Paste an optional credential", "link":"https://example.test/keys",
                 "hasValue":bool(self.context.secrets.get("extra_key")),
                 "message":"Enables an additional model"}]
    def set_card_secret(self, key, value):
        self.secret_updates += 1
        if value.startswith("reject-"):
            raise ProviderError("Rejected credential: " + value)
        self.context.secrets.set(key, value)
        return {"message":"Extra credential saved"}
    def list_models(self, refresh=False):
        self.refreshes.append(refresh)
        model = "extended-model" if self.context.secrets.get("extra_key") else "basic-model"
        return [{"id":model, "contextWindow":32768}]
def create_provider(context):
    return Fixture(context)
'''


class ProviderCardFieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {
            "UMEKO_DATA_DIR": str(self.path / "data"),
            "QT_QPA_PLATFORM": "offscreen",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.folder = self.path / "fixture"
        shutil.copytree(ROOT / "provider_dev/examples/echo-provider", self.folder)
        manifest_path = self.folder / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["auth"]["fields"].append({
            "key": "password", "label": "Password", "secret": True, "required": True,
        })
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.marker = self.path / "activated.txt"
        code = (
            "from pathlib import Path\n"
            f"Path({str(self.marker)!r}).write_text('activated', encoding='utf-8')\n"
            + IMPLEMENTATION
        )
        (self.folder / "scripts/provider.py").write_text(code, encoding="utf-8")
        self.archive = self.path / "fixture.zip"
        pack_package(self.folder, self.archive)
        # Release bundles must not add unrelated accounts to this fixture.
        with patch("app.provider_plugins.BundledProviders.sync", return_value=[]):
            self.controller = Controller(ROOT)
        self.addCleanup(self.controller.close)
        self.manager = self.controller.providerPlugins
        self.notices = []
        self.controller.toast.connect(self.notices.append)

    def install(self):
        url = QUrl.fromLocalFile(str(self.archive)).toString()
        self.assertTrue(self.manager.importZip(url), self.notices)
        return self.manager.rows[-1]["id"]

    def wait(self, provider_id):
        deadline = time.monotonic() + 4
        while provider_id in self.manager.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.app.processEvents()
        self.assertNotIn(provider_id, self.manager.busy, "Provider operation timed out")

    def login(self, provider_id):
        self.assertTrue(self.manager.login(provider_id, json.dumps({
            "username": "fixture-user", "password": PASSWORD,
        })), self.notices)
        self.wait(provider_id)

    def test_import_is_inert_and_login_exposes_public_card_descriptors(self):
        provider_id = self.install()
        self.assertFalse(self.marker.exists(), "Import or rows executed provider code")
        self.assertNotIn(provider_id, self.manager.clients)
        self.assertEqual(self.manager.rows[0].get("cardFields", []), [])
        self.login(provider_id)
        self.assertTrue(self.marker.exists())
        fields = self.manager.rows[0]["cardFields"]
        self.assertEqual(fields, [{
            "key": "extra_key", "label": "Extra credential",
            "hint": "Paste an optional credential", "link": "https://example.test/keys",
            "hasValue": False, "message": "Enables an additional model",
        }])
        self.assertEqual(self.manager.clients[provider_id].auth_calls, 1)

    def test_save_refreshes_models_without_login_and_keeps_secrets_protected(self):
        provider_id = self.install()
        self.login(provider_id)
        client = self.manager.clients[provider_id]
        self.assertEqual(self.manager.rows[0]["models"][0]["upstream"], "basic-model")
        self.assertTrue(self.manager.saveCardSecret(provider_id, "extra_key", EXTRA_SECRET), self.notices)
        self.wait(provider_id)
        row = self.manager.rows[0]
        self.assertIs(self.manager.clients[provider_id], client)
        self.assertEqual(client.auth_calls, 1)
        self.assertEqual(client.secret_updates, 1)
        self.assertEqual(client.refreshes, [True, True])
        self.assertEqual(row["models"][0]["upstream"], "extended-model")
        self.assertTrue(row["cardFields"][0]["hasValue"])
        self.assertIn(PUBLIC_MESSAGE, row["status"])
        secrets = self.manager._secrets(provider_id)
        self.assertEqual(secrets.get("extra_key"), EXTRA_SECRET)
        public = json.dumps(self.manager.rows) + json.dumps(self.controller.config)
        public += self.controller.store.path.read_text(encoding="utf-8")
        protected = secrets.path.read_text(encoding="utf-8")
        for secret in (PASSWORD, SESSION, EXTRA_SECRET):
            with self.subTest(secret_kind=("login" if secret == PASSWORD else "provider")):
                self.assertNotIn(secret, public)
                self.assertNotIn(secret, protected)

    def test_blank_secret_and_unadvertised_field_are_rejected_before_worker(self):
        provider_id = self.install()
        self.login(provider_id)
        client = self.manager.clients[provider_id]
        for key, value in (("extra_key", ""), ("extra_key", "   "), ("unknown_key", EXTRA_SECRET)):
            with self.subTest(key=key, blank=not value.strip()):
                self.assertFalse(self.manager.saveCardSecret(provider_id, key, value))
                self.assertNotIn(provider_id, self.manager.busy)
        self.assertEqual(client.secret_updates, 0)
        self.assertEqual(client.refreshes, [True])
        self.assertIsNone(self.manager._secrets(provider_id).get("extra_key"))

    def test_worker_error_redacts_submitted_secret_in_public_status_and_toast(self):
        provider_id = self.install()
        self.login(provider_id)
        rejected = "reject-fixture-sensitive-value"
        self.assertTrue(self.manager.saveCardSecret(provider_id, "extra_key", rejected))
        self.wait(provider_id)
        status = self.manager.rows[0]["status"]
        self.assertIn("Rejected credential:", status)
        self.assertNotIn(rejected, status + json.dumps(self.notices))
        self.assertEqual(self.manager.clients[provider_id].refreshes, [True])


class ProviderCardSdkTests(unittest.TestCase):
    def test_existing_providers_default_to_no_card_fields(self):
        self.assertEqual(Provider(None).card_fields(), [])

    def test_non_loopback_http_requires_explicit_scoped_opt_in(self):
        insecure = "http://service.example.test/api"
        secure = "https://secure.example.test/api"
        with self.assertRaises(ProviderError):
            origin(insecure)
        with self.assertRaises(ProviderError):
            HttpSession([insecure], environment_proxy=False)
        session = HttpSession(
            [insecure, secure], environment_proxy=False, allowed_http_urls=[insecure],
        )
        for url in (insecure, insecure + "/", insecure + "/models?limit=1", secure + "/models"):
            with self.subTest(allowed=url):
                session.validate(url)
        self.assertEqual(origin(secure), ("https", "secure.example.test", 443))
        for url in (
            "http://service.example.test/",
            "http://service.example.test/api-other/models",
            "http://service.example.test/apix",
            "http://service.example.test:8080/api/models",
            "http://other.example.test/api/models",
            "http://service.example.test.lookalike.example.test/api/models",
            "http://secure.example.test/api/models",
            "https://unlisted.example.test/api/models",
        ):
            with self.subTest(rejected=url), self.assertRaises(ProviderError):
                session.validate(url)
