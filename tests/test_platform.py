import tempfile
import hashlib
import json
import os
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from app.platform_support import configure_input_method, data_directory, legacy_data_directory, migrate_profile
from app.storage import Store, keyring_protect


class PlatformTests(unittest.TestCase):
    def test_moving_profile_rekeys_projects_and_preserves_chat_history(self):
        with tempfile.TemporaryDirectory() as temp:
            previous, target = Path(temp)/'old', Path(temp)/'new'
            (previous/'workspace').mkdir(parents=True)
            (previous/'pi/sessions').mkdir(parents=True)
            (previous/'settings.json').write_text(json.dumps({'workspace':str(previous/'workspace'),
                'activeProject':'old-id','projects':[{'id':'old-id','path':str(previous/'workspace'),'name':'My project','pinned':True}]}))
            log = previous/'pi/sessions/one.jsonl'
            body = b'{"type":"message","text":"preserved history"}\n'
            log.write_bytes(json.dumps({'type':'session','cwd':str(previous/'workspace')}).encode()+b'\n'+body)
            migrate_profile(previous, target)
            data = json.loads((target/'settings.json').read_text())
            expected = hashlib.sha256(os.path.normcase(str((target/'workspace').resolve())).encode()).hexdigest()[:16]
            self.assertEqual(data['activeProject'], expected)
            self.assertEqual(data['projects'], [{'id':expected,'path':str((target/'workspace').resolve()),'name':'My project','pinned':True}])
            self.assertEqual((target/'pi/sessions/one.jsonl').read_bytes().split(b'\n',1)[1], body)
            self.assertTrue(log.exists())

    def test_existing_duplicate_projects_are_repaired_once_on_startup(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'workspace'; path.mkdir()
            (Path(temp)/'settings.json').write_text(json.dumps({'activeProject':'duplicate-id','projects':[
                {'id':'old-id','path':str(path),'name':'My project'},
                {'id':'duplicate-id','path':str(path)+os.sep+'.','name':'workspace','pinned':True}]}))
            repaired = Store(Path(temp))
            projects = repaired.data['projects']
            self.assertEqual(len(projects), 1)
            self.assertEqual(projects[0]['name'], 'My project')
            self.assertTrue(projects[0]['pinned'])
            self.assertEqual(repaired.data['activeProject'], projects[0]['id'])
            self.assertEqual(Store(Path(temp)).data['projects'], projects)

    def test_profile_migration_remaps_stored_paths_through_parent_alias(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            actual = root/'actual'; actual.mkdir()
            alias = root/'alias'
            try:
                alias.symlink_to(actual, target_is_directory=True)
            except OSError as error:
                self.skipTest(f'Directory symlinks unavailable: {error}')
            previous, target = alias/'old', alias/'new'
            workspace = previous/'workspace'; workspace.mkdir(parents=True)
            (previous/'pi/sessions').mkdir(parents=True)
            settings = {'workspace':str(workspace), 'agent':{'agentDir':str(previous/'pi')},
                'activeProject':'old-id', 'projects':[{'id':'old-id','path':str(workspace)}]}
            (previous/'settings.json').write_text(json.dumps(settings))
            session_file = previous/'pi/sessions/one.jsonl'
            session_file.write_text(json.dumps({'type':'session','cwd':str(workspace)})+'\n')
            (previous/'sessions.json').write_text(json.dumps([{'file':str(session_file),'workspace':str(workspace)}]))

            migrate_profile(previous, target)

            data = json.loads((target/'settings.json').read_text())
            expected_workspace = str((target/'workspace').resolve())
            expected_id = hashlib.sha256(os.path.normcase(expected_workspace).encode()).hexdigest()[:16]
            self.assertEqual(data['workspace'], expected_workspace)
            self.assertEqual(data['agent']['agentDir'], str((target/'pi').resolve()))
            self.assertEqual(data['activeProject'], expected_id)
            self.assertEqual(data['projects'], [{'id':expected_id,'path':expected_workspace}])
            self.assertEqual(json.loads((target/'sessions.json').read_text()),
                [{'file':str((target/'pi/sessions/one.jsonl').resolve()),'workspace':expected_workspace}])
            self.assertEqual(json.loads((target/'pi/sessions/one.jsonl').read_text())['cwd'], expected_workspace)
            self.assertEqual(json.loads((previous/'settings.json').read_text()), settings)

    def test_platform_data_locations(self):
        home = Path("/users/example")
        for system in ('win32', 'darwin', 'linux'):
            self.assertEqual(data_directory(system, {}, home), home / '.umeko/desktop')
        self.assertEqual(legacy_data_directory("darwin", {}, home), home / "Library/Application Support/Umeko")
        self.assertEqual(legacy_data_directory("linux", {}, home), home / ".local/share/umeko")
        self.assertEqual(legacy_data_directory("linux", {"XDG_DATA_HOME": "/custom"}, home), Path("/custom/umeko"))
        self.assertEqual(legacy_data_directory("win32", {"LOCALAPPDATA": "/local"}, home), Path("/local/Umeko"))

    def test_fcitx_uses_only_compatible_bundled_plugins_and_preserves_overrides(self):
        with tempfile.TemporaryDirectory() as temp:
            plugins = Path(temp)
            (plugins / "libibusplatforminputcontextplugin.so").touch()
            env = {"QT_IM_MODULE": "fcitx", "XMODIFIERS": "@im=fcitx"}
            configure_input_method("linux", env, plugins)
            self.assertEqual(env["QT_IM_MODULE"], "fcitx")
            (plugins / "libfcitx5platforminputcontextplugin.so").touch()
            env = {"XMODIFIERS": "@im=fcitx"}
            configure_input_method("linux", env, plugins)
            self.assertEqual(env["QT_IM_MODULE"], "fcitx")
            for module in ("ibus", "", "wayland"):
                env = {"QT_IM_MODULE": "fcitx", "UMEKO_QT_IM_MODULE": module}
                configure_input_method("linux", env, plugins)
                self.assertEqual(env["QT_IM_MODULE"], module)
            env = {"WAYLAND_DISPLAY": "wayland-0"}
            configure_input_method("linux", env, plugins)
            self.assertNotIn("QT_IM_MODULE", env)
            env = {"QT_IM_MODULE": "other"}
            configure_input_method("linux", env, plugins)
            self.assertEqual(env["QT_IM_MODULE"], "other")

    def test_keyring_reuses_field_account_and_never_serializes_secret(self):
        class Backend:
            priority = 1
            def __init__(self): self.values = {}
            def set_password(self, service, account, secret): self.values[(service, account)] = secret
            def get_password(self, service, account): return self.values.get((service, account))
        Backend.__module__ = "keyring.backends.SecretService"
        backend = Backend()
        with patch.dict("sys.modules", {"keyring": types.SimpleNamespace(get_keyring=lambda: backend)}):
            first = keyring_protect("first-secret", account="fixture:provider")
            second = keyring_protect("second-secret", account="fixture:provider")
            self.assertEqual(first, second)
            self.assertNotIn("secret", second)
            self.assertEqual(keyring_protect(second, True), "second-secret")
            self.assertEqual(len(backend.values), 1)
            with self.assertRaises(RuntimeError): keyring_protect("copied-windows-blob", True)
            with self.assertRaises(RuntimeError): keyring_protect("keyring:missing", True)
            Backend.__module__ = "keyrings.alt.file"
            with self.assertRaises(RuntimeError): keyring_protect("secret", account="fixture")
