"""Exercise the embedded installer with local packages and isolated Pi profiles."""
import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.pi_install import parse_install_command, install_package, remove_package
from app.pi_management import resource_command
from app.pi_runtime import PACKAGE

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "runtime/releases/coding-1.3.0"


class PiInstallTests(unittest.TestCase):
    def test_timeout_stops_the_installer_and_its_child(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            cli = base / "node_modules" / PACKAGE / "dist/cli.js"
            cli.parent.mkdir(parents=True)
            marker = base / "child-ran"
            started = base / "started"
            child = "setTimeout(() => require('fs').writeFileSync(" + json.dumps(str(marker)) + ", 'unexpected'), 2500)"
            cli.write_text("require('child_process').spawn(process.execPath, ['-e', " + json.dumps(child) + "]); require('fs').writeFileSync(" + json.dumps(str(started)) + ", 'started'); setTimeout(() => {}, 60000)", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "安装超时"):
                install_package(base, base, base / "agent", "npm:fixture", timeout=1)
            self.assertTrue(started.exists(), "fixture did not start")
            time.sleep(2)
            self.assertFalse(marker.exists(), "installer descendant survived the timeout")

    def test_real_zip_install_keeps_payload_after_temporary_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cwd=root/'workspace';agent=root/'agent';cwd.mkdir();agent.mkdir()
            archive=root/'offline plugin.zip'
            with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as stream:
                stream.writestr('plugin/package.json',json.dumps({'name':'@fixture/offline','version':'1.0.0','pi':{'extensions':['index.js']}}))
                stream.writestr('plugin/index.js','throw Error("installation must not import code");')
            output=install_package(RELEASE,cwd,agent,str(archive),True,timeout=30)
            self.assertIn('Installed',output)
            config=cwd/'.pi/settings.json';registered=json.loads(config.read_text())['packages'][0]
            package=(config.parent/registered).resolve()
            self.assertTrue(package.is_relative_to(cwd/'.pi/umeko-packages'))
            self.assertTrue((package/'index.js').is_file())
            self.assertFalse(any(p.name.startswith('preparing-') for p in (agent/'umeko-install-cache').iterdir()))

    def test_pasted_commands_preserve_native_sources_and_scope(self):
        for text, expected in [
            ("pi install npm:billion-context", ("npm:billion-context", False)),
            (" pi install npm:@example/tools@1.0.0 --local\n", ("npm:@example/tools@1.0.0", True)),
            ("pi install -l git:github.com/example/tools@v1", ("git:github.com/example/tools@v1", True)),
            ('pi install "C:\\sample project\\tools"', ("C:\\sample project\\tools", False)),
            ("./local-tools", ("./local-tools", False)),
        ]:
            with self.subTest(command=text): self.assertEqual(parse_install_command(text), expected)
        self.assertEqual(parse_install_command("npm:example", True), ("npm:example", True))
        for text in ("", "pi install", "pi update", "pi install npm:a npm:b", "pi install --approve",
                     'pi install "unfinished', "pi install npm:a && whoami", "pi install npm:a; whoami",
                     "pi install npm:a\npi install npm:b", "pi install $(whoami)", "npm:a|whoami"):
            with self.subTest(command=text), self.assertRaises(ValueError): parse_install_command(text)

    def test_native_install_persists_both_scopes_without_executing_extensions(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            cwd, agent = base / "project", base / "agent"
            cwd.mkdir(); agent.mkdir()
            (agent / "settings.json").write_text(json.dumps({"theme": "dark"}))
            (cwd / ".pi").mkdir()
            (cwd / ".pi/settings.json").write_text(json.dumps({"compaction": {"enabled": False}}))
            executed = base / "executed"
            files = []
            for local in (False, True):
                package = base / ("project package" if local else "personal package")
                (package / "extensions").mkdir(parents=True)
                file = package / "extensions/example.ts"
                file.write_text("import {writeFileSync} from 'node:fs'; writeFileSync(" + json.dumps(str(executed)) + ", 'unexpected'); export default () => {};", encoding="utf-8")
                source = str(package)
                # Simulate a host environment configured offline: explicit installation still works.
                with patch.dict(os.environ, {"PI_OFFLINE": "1", "NODE_OPTIONS": "--invalid-for-test"}):
                    output = install_package(RELEASE, cwd, agent, source, local, timeout=30)
                self.assertIn("Installed", output)
                settings = cwd / ".pi/settings.json" if local else agent / "settings.json"
                saved = json.loads(settings.read_text())["packages"]
                self.assertIn(package.resolve(), {(settings.parent / path).resolve() for path in saved})
                files.append((str(file), "project" if local else "global"))
            self.assertEqual(json.loads((agent / "settings.json").read_text())["theme"], "dark")
            self.assertFalse(json.loads((cwd / ".pi/settings.json").read_text())["compaction"]["enabled"])
            rows = resource_command(RELEASE, cwd, agent, {}, action="scan")
            for file, scope in files:
                self.assertTrue(any(row["path"] == file and row["scope"] == scope for row in rows), rows)
            self.assertFalse(executed.exists())
            # Discovery returns relative registrations too. Remove through the
            # same embedded CLI in each scope without importing the extension.
            for local in (False, True):
                settings = cwd / ".pi/settings.json" if local else agent / "settings.json"
                source = json.loads(settings.read_text())["packages"][0]
                output = remove_package(RELEASE, cwd, agent, source, local, timeout=30,
                                        package_root=(settings.parent/source).resolve())
                self.assertIn("Removed", output)
                self.assertFalse(json.loads(settings.read_text()).get("packages", []))
            self.assertEqual(json.loads((agent / "settings.json").read_text())["theme"], "dark")
            self.assertFalse(json.loads((cwd / ".pi/settings.json").read_text())["compaction"]["enabled"])
            self.assertFalse(executed.exists())
            with self.assertRaisesRegex(RuntimeError, "Pi 安装失败"):
                install_package(RELEASE, cwd, agent, str(base / "does-not-exist"), timeout=30)


if __name__ == "__main__": unittest.main()
