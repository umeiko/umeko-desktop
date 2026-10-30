"""Real native resource filters and repair/console paths, without public services."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication
from app.controller import Controller
from app.pi_management import resource_command, prepare_factory
from app.pi_terminal import prepare_terminal, powershell_literal
from app.pi_runtime import PACKAGE, node_executable

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "runtime/releases/coding-1.3.0"
APP = QCoreApplication.instance() or QCoreApplication([])


class NativeExtensionTests(unittest.TestCase):
    def test_extension_update_results_remain_scoped_to_the_original_pi_context(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR":temp}):
            controller = Controller(ROOT)
            try:
                manager = controller.piManagement
                manager._job_context = manager._resource_key()
                manager._extension_update = {"id":"fixture", "status":"checking"}
                manager._finished("pi-admin:extension-check", {"ok":True, "value":{"id":"fixture", "status":"available", "latest":"2.0.0"}})
                self.assertEqual(manager.extensionUpdate["latest"],"2.0.0")
                manager._finished("pi-admin:extension-check", {"ok":False, "value":"Registry unreachable"})
                self.assertEqual(manager.extensionUpdate["id"],"fixture")
                self.assertEqual(manager.extensionUpdate["status"],"error")
                controller._view.workspace = str(Path(temp)/"another-project")
                manager._finished("pi-admin:extension-check", {"ok":True, "value":{"id":"fixture", "latest":"3.0.0"}})
                self.assertEqual(manager.extensionUpdate,{})
            finally:
                controller.close()

    def test_package_entry_uses_manifest_name_without_executing_code(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / "packages/web-fixture"
            (package / "dist").mkdir(parents=True)
            (package / "dist/index.js").write_text("throw new Error('must not execute')")
            (package / "package.json").write_text(json.dumps({"name":"@fixture/web-access", "pi":{"extensions":["dist/index.js"]}}))
            agent, cwd = root / "agent", root / "workspace"
            agent.mkdir(); cwd.mkdir()
            (agent / "settings.json").write_text(json.dumps({"packages":[str(package)]}))
            rows = resource_command(RELEASE, cwd, agent, {}, action="scan")
            row = next(row for row in rows if row["path"] == str(package / "dist/index.js"))
            self.assertEqual(row["name"], "@fixture/web-access")
            disabled = resource_command(RELEASE, cwd, agent, {}, action="toggle", id=row["id"], enabled=False)
            self.assertEqual(next(item for item in disabled if item["id"] == row["id"])["name"], "@fixture/web-access")

    def test_damaged_pointer_falls_back_and_late_catalog_cannot_cross_projects(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": temp}):
            data = Path(temp)
            (data / "kernels").mkdir()
            (data / "kernels/active.json").write_text("damaged pointer")
            c = Controller(ROOT)
            try:
                self.assertEqual(c._release, RELEASE)
                c.store.data["agent"]["agentDir"] = str(data / "agent")
                manager = c.piManagement
                manager._job_context = manager._resource_key()
                project = data / "different-project"
                project.mkdir()
                c._view.workspace = str(project)
                manager._busy = True
                with patch.object(c, "_job") as job:
                    manager._finished("pi-admin:scan", {"ok": True, "value": [{"path": "previous-project.ts", "enabled": True}]})
                    self.assertEqual(manager.extensions, [])
                    self.assertTrue(manager.busy)
                    self.assertEqual(job.call_args.args[0], "pi-admin:scan")
                manager._busy = False
                c._view.phase = "running"
                manager.restoreFactory()
                self.assertFalse(manager.busy)
                self.assertFalse(c.kernelBusy)
                self.assertFalse((data / "pi-backups").exists())
            finally:
                c.close()

    def test_disabled_local_package_builtin_and_extra_paths_remain_discoverable(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            cwd, agent = base / "project", base / "agent"
            (cwd / ".pi/extensions").mkdir(parents=True)
            (agent / "extensions").mkdir(parents=True)
            personal = agent / "extensions/personal.ts"
            project = cwd / ".pi/extensions/project.ts"
            extra = base / "extra.ts"
            for file in (personal, project, extra):
                file.write_text("throw new Error('discovery must not execute extensions')", encoding="utf-8")
            package = base / "local-package"
            (package / "extensions").mkdir(parents=True)
            (package / "extensions/tool.ts").write_text("throw new Error('do not execute package')")
            settings = agent / "settings.json"
            settings.write_text(json.dumps({"packages": [str(package)], "theme": "dark", "compaction": {"reserveTokens": 10000}}))
            options = {"extensionPaths": [str(extra)]}
            def scan(**action): return resource_command(RELEASE, cwd, agent, options, **action)
            rows = scan(action="scan")
            self.assertGreaterEqual(len(rows), 7)
            paths = (str(personal), str(project), str(extra), str(package / "extensions/tool.ts"), "builtin:mcp")
            for path in paths:
                row = next(r for r in rows if r["path"] == path)
                rows = scan(action="toggle", id=row["id"], enabled=False)
                self.assertIn(path, {r["path"] for r in rows}, (path, rows))
                self.assertFalse(next(r for r in rows if r["path"] == path)["enabled"], path)
            # Reload through a new process, including an already-imported extra path.
            rows = scan(action="scan")
            self.assertTrue(all(not next(r for r in rows if r["path"] == path)["enabled"] for path in paths))
            native = json.loads(settings.read_text())
            self.assertEqual(native["theme"], "dark")
            self.assertEqual(native["compaction"]["reserveTokens"], 10000)
            self.assertIn("-" + str(project), json.loads((cwd / ".pi/settings.json").read_text())["extensions"])
            for path in paths:
                row = next(r for r in rows if r["path"] == path)
                rows = scan(action="toggle", id=row["id"], enabled=True)
                self.assertTrue(next(r for r in rows if r["path"] == path)["enabled"])
            # A native pi config edit is picked up without being overwritten.
            native = json.loads(settings.read_text()); native["extensions"].append("-" + str(extra))
            settings.write_text(json.dumps(native))
            self.assertFalse(next(r for r in scan(action="scan") if r["path"] == str(extra))["enabled"])
            options["safeMode"] = True
            settings.write_text("damaged JSON")
            (cwd / ".pi/settings.json").write_text("also damaged")
            safe = scan(action="scan")
        self.assertEqual({r["path"] for r in safe}, {"builtin:codemode", "builtin:tool-search", "builtin:mcp", "builtin:chatbox", "builtin:pi-commands", "builtin:umeko-control", "builtin:marketplace", "builtin:subagents"})

    def test_terminal_uses_exact_embedded_cli_and_quotes_user_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            agent, cwd = base / "agent ' 中文 & $test", base / "project ' 中文 & $test"
            agent.mkdir(); cwd.mkdir()
            shell = shutil.which("pwsh.exe") or shutil.which("powershell.exe") or shutil.which("pwsh")
            with patch("app.pi_terminal.shutil.which", return_value=shell or "powershell.exe"):
                command = prepare_terminal(RELEASE, base, agent, cwd, base / "sessions", platform="win32")
            script = Path(command[-1]).read_text(encoding="utf-8-sig")
            self.assertIn("function global:pi", script)
            self.assertIn("try { pi config }", script)
            self.assertIn("agent '' 中文 & $test", script)
            self.assertIn(str(RELEASE / "node_modules" / PACKAGE / "dist/cli.js"), script)
            # Ask PowerShell's parser only; never open a terminal during tests.
            parser = "$t=$null;$e=$null;[System.Management.Automation.Language.Parser]::ParseFile(" + powershell_literal(command[-1]) + ",[ref]$t,[ref]$e)|Out-Null;$e|ForEach-Object{$_.Message};if($e.Count){exit 1}"
            if shell:
                result = subprocess.run([command[0], "-NoProfile", "-Command", parser], capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            native = subprocess.run([node_executable(), str(RELEASE / "node_modules" / PACKAGE / "dist/cli.js"), "--version"], capture_output=True, text=True, timeout=15)
            self.assertEqual(native.returncode, 0, native.stderr)
            self.assertIn("1.3.0", native.stdout)
            with patch("app.pi_terminal.shutil.which", side_effect=lambda name: "/usr/bin/xterm" if name == "xterm" else None), patch("app.pi_terminal.node_executable", return_value="/usr/bin/node"):
                linux = prepare_terminal(RELEASE, base, agent, cwd, base / "sessions", platform="linux")
            self.assertEqual(linux[:2], ["/usr/bin/xterm", "-e"])
            self.assertIn("PI_OFFLINE=1 pi config", Path(linux[-2]).read_text(encoding="utf-8"))
            mac = prepare_terminal(RELEASE, base, agent, cwd, base / "sessions", platform="darwin")
            self.assertEqual(mac[0], "/usr/bin/osascript")

    def test_factory_keeps_original_configuration_sessions_and_projects(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": str(Path(temp) / "data")}):
            base = Path(temp)
            original = base / "original-agent"
            original.mkdir()
            (original / "settings.json").write_text("{invalid original fixture", encoding="utf-8")
            workspace = base / "project"
            (workspace / ".pi").mkdir(parents=True)
            project_config = workspace / ".pi/settings.json"
            project_config.write_text("also invalid")
            c = Controller(ROOT)
            try:
                c.store.data["agent"].update(agentDir=str(original), instructions="Original fixture", extensionPaths=[str(original)])
                sessions = c.store.directory / "pi/sessions/fixture.jsonl"
                sessions.parent.mkdir(parents=True); sessions.write_text("native fixture remains")
                c.store.save()
                before = json.loads(c.store.path.read_text(encoding="utf-8"))
                value = prepare_factory(ROOT, c.store.directory, c.store.data["agent"], workspace)
                c.piManagement._apply_factory(value)
                self.assertTrue(c.store.data["agent"]["safeMode"])
                self.assertNotEqual(c.store.data["agent"]["agentDir"], str(original))
                self.assertEqual((original / "settings.json").read_text(), "{invalid original fixture")
                self.assertEqual(project_config.read_text(), "also invalid")
                self.assertEqual(sessions.read_text(), "native fixture remains")
                after = json.loads(c.store.path.read_text(encoding="utf-8"))
                for name in ("providers", "projects", "server", "selectedModel"):
                    self.assertEqual(before[name], after[name])
                backup = Path(value["backup"])
                self.assertEqual((backup / "personal-settings.json").read_text(), "{invalid original fixture")
                self.assertEqual(json.loads((backup / "restore.json").read_text())["agent"]["instructions"], "Original fixture")
            finally:
                c.close()
            restarted = Controller(ROOT)
            try:
                self.assertEqual(restarted._release, Path(value["release"]))
                self.assertTrue(restarted.store.data["agent"]["safeMode"])
                self.assertEqual(restarted.piManagement.backupPath, value["backup"])
            finally:
                restarted.close()


if __name__ == "__main__": unittest.main()
