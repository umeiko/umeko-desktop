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


class RuntimeReaderTests(unittest.TestCase):
    def test_prepared_runtime_is_not_rewritten_by_concurrent_test_lanes(self):
        with tempfile.TemporaryDirectory() as temporary:
            release=Path(temporary)/'release'
            retry=release/'node_modules/@earendil-works/pi-ai/dist/utils/retry.js'
            retry.parent.mkdir(parents=True)
            retry.write_text('const errorMessage = message.errorMessage;',encoding='utf-8')
            (release/'manifest.json').write_text(json.dumps({'package':PACKAGE,'projection':2}),encoding='utf-8')
            bridge=Path(__file__).resolve().parents[1]/'runtime/bridge.mjs'
            success=subprocess.CompletedProcess([],0,'{"ok":true}','')
            with patch('app.pi_runtime.node_executable',return_value='node'),patch('app.pi_runtime.node_environment',return_value={}),patch('app.pi_runtime.subprocess.run',return_value=success) as run:
                verify_runtime(release,bridge)
                before={str(p):p.stat().st_mtime_ns for p in release.rglob('*') if p.is_file()}
                with patch('app.pi_runtime.shutil.copy2',side_effect=AssertionError('Prepared adapters must remain immutable')):
                    verify_runtime(release,bridge)
                self.assertEqual(run.call_count,2)
                self.assertEqual(before,{str(p):p.stat().st_mtime_ns for p in release.rglob('*') if p.is_file()})

    def test_changed_adapter_is_only_published_after_the_copy_completes(self):
        from app.pi_runtime import copy_runtime_file
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source';target=root/'target'
            source.write_text('new helper',encoding='utf-8');target.write_text('old helper',encoding='utf-8')
            real_copy=shutil.copy2
            def copy(src,dst):
                self.assertEqual(target.read_text(encoding='utf-8'),'old helper')
                result=real_copy(src,dst)
                self.assertEqual(target.read_text(encoding='utf-8'),'old helper')
                return result
            with patch('app.pi_runtime.shutil.copy2',side_effect=copy):copy_runtime_file(source,target)
            self.assertEqual(target.read_text(encoding='utf-8'),'new helper')
            self.assertEqual(set(p.name for p in root.iterdir()),{'source','target'})


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
        for name in ("tool-visibility.mjs", "bridge.mjs", "package-install.mjs", "update-engine.mjs", "provider-policy.mjs", "resources.mjs", "chatbox.mjs", "network-retry.mjs", "pi-commands.mjs", "umeko-control.mjs", "umeko-documents.mjs", "widget-messages.mjs", "tool-permissions.mjs", "background-jobs.mjs", "process-guard.mjs", "subagents.mjs", "subagent-sdk.mjs", "subagent-settings.mjs", "input-queue.mjs", "recent-images.mjs", "auxiliary-vision.mjs", "rpc-ui.mjs", "umeko-operations.json", "webview-component.mjs", "webview-component.json"):
            (source_io / name).write_text("fixture")
        (source_io / "session-capabilities.mjs").write_text("fixture")
        (source_io / "skills.mjs").write_text("fixture")
        (source_io / "generation.mjs").write_text("fixture")
        (source_io / "markdown-preview.mjs").write_text("fixture")
        (source_io / "umeko-docs").mkdir()
        (source_io / "umeko-docs/guide.md").write_text("deep docs")
        with patch("app.pi_runtime.node_executable", return_value="node.exe"), patch("app.pi_runtime.node_environment", return_value={}), patch("app.pi_runtime.subprocess.run", return_value=subprocess.CompletedProcess([], 0, '{"ok":true}', '')) as run:
            verify_runtime(filesystem_path(release), source / "bridge.mjs")
        self.assertEqual(run.call_args.args[0][1], str(release / "bridge.mjs"))
        self.assertEqual((release_io / "umeko-docs/guide.md").read_text(), "deep docs")
        self.assertEqual((release_io / "tool-visibility.mjs").read_text(), "fixture")
        self.assertEqual((release_io / "session-capabilities.mjs").read_text(), "fixture")
        self.assertEqual((release_io / "markdown-preview.mjs").read_text(), "fixture")
        self.assertEqual((release_io / "generation.mjs").read_text(), "fixture")
        self.assertEqual(ordinary_path(filesystem_path(release)), release)


if __name__ == "__main__":
    unittest.main()
