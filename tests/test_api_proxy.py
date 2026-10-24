"""Proxy administration against isolated profiles and loopback HTTP fixtures."""
import copy
import http.client
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication
from app.api_keys import KeyCatalog, generate_key, make_key, validate_key
from app.controller import Controller
from app.gateway import LocalServer
from app.storage import Store, protect

ROOT = Path(__file__).resolve().parents[1]
APP = QCoreApplication.instance() or QCoreApplication([])


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def status(port, key="", header="Authorization", origin=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        headers = {header: "Bearer " + key if header == "Authorization" else key}
        if origin:
            headers["Origin"] = origin
        connection.request("GET", "/v1/models", headers=headers)
        response = connection.getresponse()
        result = response.status, response.getheader("Access-Control-Allow-Origin")
        response.read()
        return result
    finally:
        connection.close()


class KeyTests(unittest.TestCase):
    def test_lan_addresses_prioritize_physical_interfaces_and_skip_unusable_ips(self):
        from types import SimpleNamespace
        from PySide6.QtNetwork import QHostAddress, QNetworkInterface
        from app.api_keys import lan_addresses
        def interface(name, ip, up=True):
            return SimpleNamespace(name=lambda:name, type=lambda:QNetworkInterface.Ethernet,
                flags=lambda:QNetworkInterface.IsUp if up else QNetworkInterface.InterfaceFlag(0),
                addressEntries=lambda:[SimpleNamespace(ip=lambda:QHostAddress(ip))])
        interfaces = [interface('docker0', '172.17.0.1'), interface('en0', '192.168.15.8'),
            interface('en1', '169.254.1.2'), interface('lo', '127.0.0.1'), interface('en2', '192.168.1.9', False)]
        with patch.object(QNetworkInterface, 'allInterfaces', return_value=interfaces):
            self.assertEqual(lan_addresses(), ['192.168.15.8', '172.17.0.1'])

    def test_generated_verifiers_validation_and_usage(self):
        key, other = generate_key(), generate_key()
        self.assertNotEqual(key, other)
        self.assertGreaterEqual(len(key), 48)
        row = make_key("Fixture", key)
        self.assertNotIn(key, json.dumps(row))
        catalog = KeyCatalog([row])
        for bad in ("", "wrong", row["digest"], "非 ASCII", "x" * 257):
            self.assertFalse(catalog.authorized(bad))
        self.assertEqual(catalog.usage()[row["id"]], "")
        self.assertTrue(catalog.authorized(key))
        used = catalog.usage()[row["id"]]
        self.assertTrue(used)
        catalog.update([{**row, "enabled": False}])
        self.assertFalse(catalog.authorized(key))
        catalog.update([row])
        self.assertEqual(catalog.usage()[row["id"]], used)
        self.assertTrue(catalog.authorized(key))
        catalog.update([])
        self.assertFalse(catalog.authorized(key))
        self.assertEqual(catalog.usage(), {})
        for bad in ("short", "a" * 257, "x" * 15 + "\nvalue", "非" * 20):
            with self.assertRaises(ValueError):
                validate_key(bad)
        for bad in ("", "a" * 81, "new\nline"):
            with self.assertRaises(ValueError):
                make_key(bad)

    def test_legacy_token_migrates_without_changing_credential_or_recreating_revoked_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp))
            self.assertEqual(store.data["server"]["keys"], [])
            key = generate_key()
            legacy = json.loads(store.path.read_text(encoding="utf-8"))
            legacy["server"] = {"port": 8787, "openai": True, "anthropic": True, "token": protect(key)}
            store.path.write_text(json.dumps(legacy), encoding="utf-8")
            migrated = Store(Path(temp))
            self.assertTrue(KeyCatalog(migrated.data["server"]["keys"]).authorized(key))
            self.assertFalse(migrated.data["server"]["lan"])
            raw = json.loads(migrated.path.read_text(encoding="utf-8"))
            self.assertNotIn("token", raw["server"])
            self.assertNotIn(key, json.dumps(raw))
            migrated.data["server"]["keys"] = []
            migrated.save()
            self.assertEqual(Store(Path(temp)).data["server"]["keys"], [])


class ProxyControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"UMEKO_DATA_DIR": self.temp.name})
        self.environment.start()
        self.controller = Controller(ROOT)

    def tearDown(self):
        self.controller.close()
        self.environment.stop()
        self.temp.cleanup()

    def create_key(self, name="Fixture", value=""):
        self.assertTrue(self.controller.saveProxyKey("", name, value))
        result = self.controller.takeCreatedProxyKey()
        self.assertEqual(self.controller.takeCreatedProxyKey(), {})
        return result["id"], result["key"]

    def start(self):
        self.assertTrue(self.controller.saveServer(free_port(), True, True, False))
        self.controller.toggleServer()
        self.assertIsNotNone(self.controller.public_server)
        return self.controller.public_server

    def test_create_rename_rotate_disable_revoke_live_and_private_channel_isolation(self):
        c = self.controller
        key_id, key = self.create_key()
        other_id, other = self.create_key("Other client", "synthetic-custom-key-1234")
        before = copy.deepcopy(c.store.data["server"]["keys"])
        for name, value in (("Duplicate", key), ("Fixture", generate_key()), ("Bad", "short")):
            self.assertFalse(c.saveProxyKey("", name, value))
            self.assertEqual(c.takeCreatedProxyKey(), {})
            self.assertEqual(c.store.data["server"]["keys"], before)
        server = self.start()
        self.assertEqual(server.host, "127.0.0.1")
        self.assertEqual(status(server.port, key)[0], 200)
        self.assertEqual(status(server.port, other, "x-api-key")[0], 200)
        self.assertEqual(status(server.port, "")[0], 401)
        self.assertEqual(status(server.port, c.private_token)[0], 401)
        self.assertEqual(status(c.private_server.port, key)[0], 401)
        self.assertEqual(status(c.private_server.port, c.private_token)[0], 200)
        self.assertTrue(c.saveProxyKey(key_id, "Renamed", ""))
        self.assertEqual(c.takeCreatedProxyKey(), {})
        self.assertEqual(status(server.port, key)[0], 200)
        fresh = generate_key()
        self.assertTrue(c.saveProxyKey(key_id, "Renamed", fresh))
        self.assertEqual(c.takeCreatedProxyKey()["key"], fresh)
        self.assertIs(c.public_server, server)
        self.assertEqual(status(server.port, key)[0], 401)
        self.assertEqual(status(server.port, fresh)[0], 200)
        c.setProxyKeyEnabled(key_id, False)
        self.assertEqual(status(server.port, fresh)[0], 401)
        self.assertEqual(status(server.port, other)[0], 200)
        c.setProxyKeyEnabled(key_id, True)
        self.assertEqual(status(server.port, fresh)[0], 200)
        c._sync_proxy_usage()
        self.assertTrue(c.proxyKeys[0]["lastUsedAt"])
        self.assertNotIn("keys", c.config["server"])
        self.assertNotIn(fresh, json.dumps(c.proxyKeys))
        self.assertNotIn("digest", json.dumps(c.proxyKeys))
        c.close()
        restored = Store(c.store.directory)
        self.assertTrue(restored.data["server"]["keys"][0]["lastUsedAt"])
        self.assertTrue(KeyCatalog(restored.data["server"]["keys"]).authorized(fresh))
        self.assertNotIn(fresh, restored.path.read_text(encoding="utf-8"))

    def test_keepalive_connection_rechecks_auth_and_revoking_all_fails_closed(self):
        c = self.controller
        key_id, key = self.create_key()
        server = self.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=3)
        try:
            connection.request("GET", "/v1/models", headers={"Authorization": "Bearer " + key})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            c.revokeProxyKey(key_id)
            connection.request("GET", "/v1/models", headers={"Authorization": "Bearer " + key})
            response = connection.getresponse()
            self.assertEqual(response.status, 401)
            response.read()
        finally:
            connection.close()
        c.toggleServer()
        c.toggleServer()
        self.assertIsNone(c.public_server)
        self.assertEqual(Store(c.store.directory).data["server"]["keys"], [])

    def test_persistence_failure_does_not_change_live_keys(self):
        c = self.controller
        key_id, key = self.create_key()
        server = self.start()
        with patch.object(c.store, "save", side_effect=OSError("fixture write denied")):
            self.assertFalse(c.saveProxyKey(key_id, "Replacement", generate_key()))
            c.revokeProxyKey(key_id)
            self.assertEqual(c.takeCreatedProxyKey(), {})
        self.assertEqual(status(server.port, key)[0], 200)
        self.assertEqual(c.proxyKeys[0]["name"], "Fixture")

    def test_lan_rebind_protocol_settings_and_binding_failure_rollback(self):
        c = self.controller
        _, key = self.create_key()
        server = self.start()
        original_port = server.port
        with patch("app.controller.lan_addresses", return_value=["192.0.2.10"]):
            self.assertEqual(c.proxyAddresses, ["127.0.0.1"])
            self.assertTrue(c.saveServer(original_port, True, True, True))
            self.assertEqual(c.proxyAddresses, ["127.0.0.1", "192.0.2.10"])
            self.assertEqual(c.public_server.host, "0.0.0.0")
            self.assertEqual(c.private_server.host, "127.0.0.1")
            origin = "http://192.168.1.20:3000"
            self.assertEqual(status(original_port, key, origin=origin), (200, origin))
            self.assertEqual(status(original_port, key, origin="https://example.com"), (200, None))
            self.assertTrue(c.saveServer(original_port, True, False, False))
            self.assertEqual(c.public_server.host, "127.0.0.1")
            self.assertEqual(status(original_port, key, origin=origin), (200, None))
        # Port collision keeps the old listener; same-port rebind failure restores it.
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            self.assertFalse(c.saveServer(occupied.getsockname()[1], True, True, False))
            self.assertEqual(c.public_server.port, original_port)
            self.assertEqual(c.config["server"]["port"], original_port)
        original_factory = c._new_proxy_listener
        def fail_lan(settings):
            if settings["lan"]: raise OSError("fixture denied")
            return original_factory(settings)
        with patch.object(c, "_new_proxy_listener", side_effect=fail_lan):
            self.assertFalse(c.saveServer(original_port, True, True, True))
        self.assertFalse(c.config["server"]["lan"])
        self.assertEqual(status(original_port, key)[0], 200)
        self.assertFalse(c.public_server.protocols["anthropic"])
        self.assertFalse(c.saveServer(80, True, True, False))
        self.assertFalse(c.saveServer(original_port, False, False, False))
        with self.assertRaises(ValueError):
            LocalServer(c.gateway, 0, "private", private=True, host="0.0.0.0")


if __name__ == "__main__":
    unittest.main()
