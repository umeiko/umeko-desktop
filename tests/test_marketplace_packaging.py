"""Exercise external-runtime preparation using the real desktop build data lists."""
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import pi_runtime


ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = (
    "bridge.mjs", "provider-policy.mjs", "resources.mjs", "chatbox.mjs",
    "network-retry.mjs", "pi-commands.mjs", "umeko-control.mjs",
    "umeko-documents.mjs", "widget-messages.mjs", "tool-permissions.mjs", "subagents.mjs", "subagent-sdk.mjs",
    "subagent-settings.mjs", "input-queue.mjs", "rpc-ui.mjs",
    "umeko-operations.json", "webview-component.mjs", "webview-component.json",
    "marketplace.mjs", "marketplace-source.mjs", "package-source.mjs",
    "marketplace-LICENSE.txt",
)


def stage_build_runtime(script, destination):
    """Model PyInstaller's runtime data staging without duplicating its file list."""
    separator = ";" if script.suffix == ".ps1" else ":"
    specifications = re.findall(r"--add-data\s+(['\"])(.*?)\1", script.read_text(encoding="utf-8"))
    if not specifications:
        raise AssertionError(f"No --add-data arguments parsed from {script.name}")
    for _, specification in specifications:
        source, target = specification.split(separator, 1)
        source = Path(source)
        if not source.parts or source.parts[0] != "runtime":
            continue
        if (ROOT / source).is_dir():
            output = destination / target
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(ROOT / source, output)
        else:
            output = destination / target / source.name
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / source, output)


class MarketplacePackagingTests(unittest.TestCase):
    def test_both_packaged_layouts_prepare_full_external_runtime(self):
        fixture_parent = None
        if os.name == "nt":
            fixture_parent = Path("C:/UmekoTests/p373-runtime-review")
            fixture_parent.mkdir(parents=True, exist_ok=True)
        for script_name in ("build.ps1", "build.sh"):
            with self.subTest(build=script_name), tempfile.TemporaryDirectory(
                prefix="marketplace-packaging-", dir=fixture_parent
            ) as temporary:
                base = Path(temporary)
                internal = base / "bundle/_internal"
                stage_build_runtime(ROOT / script_name, internal)
                bridge_source = internal / "runtime/bridge.mjs"
                release = base / "external-runtime"
                retry = release / "node_modules/@earendil-works/pi-ai/dist/utils/retry.js"
                retry.parent.mkdir(parents=True)
                retry.write_text("const errorMessage = message.errorMessage;\n", encoding="utf-8")
                manifest = {
                    "package": pi_runtime.PACKAGE, "version": "fixture-external",
                    "projection": 2, "engine": "full-coding-agent", "nativeTools": True,
                    "providerCatalog": False, "preserved": "external-runtime-metadata",
                }
                (release / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

                def self_test(command, **options):
                    self.assertEqual(command, ["fixture-node", str(release / "bridge.mjs"), "--self-test"])
                    for name in ADAPTERS:
                        self.assertEqual((release / name).read_bytes(), (internal / "runtime" / name).read_bytes(), name)
                    docs = list((internal / "runtime/umeko-docs").rglob("*"))
                    self.assertTrue(docs)
                    for source in docs:
                        if source.is_file():
                            self.assertEqual(
                                (release / "umeko-docs" / source.relative_to(internal / "runtime/umeko-docs")).read_bytes(),
                                source.read_bytes(),
                            )
                    self.assertEqual(json.loads((release / "manifest.json").read_text()), manifest)
                    self.assertIn("Umeko report", retry.read_text(encoding="utf-8"))
                    self.assertEqual(options["env"]["PI_OFFLINE"], "1")
                    self.assertNotIn("NODE_OPTIONS", options["env"])
                    self.assertNotIn("NODE_PATH", options["env"])
                    self.assertEqual(options["creationflags"], pi_runtime.CREATE_NO_WINDOW)
                    return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")

                with patch.object(pi_runtime, "ensure_adapter_dependencies") as dependencies, \
                     patch.object(pi_runtime, "node_executable", return_value="fixture-node"), \
                     patch.object(pi_runtime.subprocess, "run", side_effect=self_test) as run, \
                     patch.dict(os.environ, {"NODE_OPTIONS": "fixture-option", "NODE_PATH": "fixture-path"}):
                    pi_runtime.verify_runtime(release, bridge_source)
                dependencies.assert_called_once_with(release, bridge_source)
                run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
