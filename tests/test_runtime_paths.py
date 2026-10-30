"""Real Windows filesystem regressions for runtime preparation."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.filesystem_paths import filesystem_path, ordinary_path
from app.pi_runtime import PACKAGE, project_runtime, verify_runtime


@unittest.skipUnless(os.name == "nt", "Windows extended-length paths")
class RuntimePathTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, filesystem_path(self.base))
        self.deep = self.base / ("segment_" * 14) / ("nested_" * 14) / ("level_" * 10)
        filesystem_path(self.deep).mkdir(parents=True)
        self.assertGreater(len(str(self.deep)), 260)

    def test_preparation_copies_deep_source_and_destination(self):
        source, target = self.deep / "source", self.deep / "release"
        modules = filesystem_path(source) / "node_modules"
        package = modules / PACKAGE
        package.mkdir(parents=True)
        (package / "package.json").write_text(json.dumps({"version":"1.3.0"}))
        ai = modules / "@earendil-works/pi-ai/dist"
        (ai / "providers").mkdir(parents=True)
        (ai / "providers/all.js").write_text("original catalog")
        (ai / "models.generated.js").write_text("original models")
        payload = package / "nested/dependency/resource.txt"
        payload.parent.mkdir(parents=True)
        payload.write_text("original dependency data")
        project_runtime(source, target)
        self.assertEqual((filesystem_path(target) / "node_modules" / PACKAGE / "nested/dependency/resource.txt").read_text(), "original dependency data")
        self.assertEqual(json.loads((filesystem_path(target) / "manifest.json").read_text())["version"], "1.3.0")

    def test_verification_keeps_node_argv_ordinary(self):
        release, source = self.deep / "release", self.deep / "bridge"
        release_io, source_io = filesystem_path(release), filesystem_path(source)
        retry = release_io / "node_modules/@earendil-works/pi-ai/dist/utils/retry.js"
        retry.parent.mkdir(parents=True)
        retry.write_text("const errorMessage = message.errorMessage;")
        (release_io / "manifest.json").write_text(json.dumps({"package":PACKAGE, "projection":2}))
        source_io.mkdir(parents=True)
        for name in ("bridge.mjs", "provider-policy.mjs", "resources.mjs", "chatbox.mjs", "network-retry.mjs", "pi-commands.mjs", "umeko-control.mjs", "umeko-documents.mjs", "widget-messages.mjs", "tool-permissions.mjs", "background-jobs.mjs", "process-guard.mjs", "subagents.mjs", "subagent-sdk.mjs", "subagent-settings.mjs", "input-queue.mjs", "rpc-ui.mjs", "umeko-operations.json", "webview-component.mjs", "webview-component.json", "marketplace.mjs", "marketplace-source.mjs", "package-source.mjs", "marketplace-LICENSE.txt"):
            (source_io / name).write_text("fixture")
        (source_io / "umeko-docs").mkdir()
        (source_io / "umeko-docs/guide.md").write_text("deep docs")
        with patch("app.pi_runtime.ensure_adapter_dependencies"), patch("app.pi_runtime.node_executable", return_value="node.exe"), patch("app.pi_runtime.node_environment", return_value={}), patch("app.pi_runtime.subprocess.run", return_value=subprocess.CompletedProcess([], 0, '{"ok":true}', '')) as run:
            verify_runtime(filesystem_path(release), source / "bridge.mjs")
        self.assertEqual(run.call_args.args[0][1], str(release / "bridge.mjs"))
        self.assertEqual((release_io / "umeko-docs/guide.md").read_text(), "deep docs")
        self.assertEqual(ordinary_path(filesystem_path(release)), release)


if __name__ == "__main__":
    unittest.main()
