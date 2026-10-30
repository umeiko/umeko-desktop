"""Old external kernels and newly downloaded kernels load desktop adapters."""
import json
import os
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import pi_runtime

ROOT = Path(__file__).resolve().parents[1]
FACTORY = ROOT / "runtime/releases" / pi_runtime.RELEASE_NAME


@contextmanager
def temporary():
    parent = Path("C:/UmekoTests/p373-runtime-review") if os.name == "nt" else None
    if parent:
        parent.mkdir(parents=True, exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix="adapter-dependencies-", dir=parent))
    try:
        yield str(base)
    finally:
        if parent and not base.resolve().is_relative_to(parent.resolve()):
            raise RuntimeError("Unexpected test cleanup target")
        shutil.rmtree("\\\\?\\" + str(base.resolve()) if os.name == "nt" else base)


def copy_modules(source, target, *, missing_tar=False):
    # Hard links keep the real SDK fixture small; project_runtime still performs
    # its normal copy, and tests never modify the linked package source files.
    source_path, target_path = source.resolve(), target.resolve()
    if os.name == "nt":
        source_path, target_path = Path("\\\\?\\" + str(source_path)), Path("\\\\?\\" + str(target_path))
    def ignore(directory, names):
        return ["tar"] if missing_tar and Path(directory) == source_path else []
    shutil.copytree(source_path, target_path, copy_function=os.link, ignore=ignore)


class RuntimeAdapterDependencyTests(unittest.TestCase):
    def test_existing_external_kernel_without_tar_is_migrated_offline(self):
        with temporary() as temp:
            release = Path(temp) / "old-kernel"
            copy_modules(FACTORY / "node_modules", release / "node_modules", missing_tar=True)
            shutil.copy2(FACTORY / "manifest.json", release / "manifest.json")
            bridge = ROOT / "runtime/bridge.mjs"
            node = os.environ.get("UMEKO_TEST_NODE") or pi_runtime.node_executable()
            with patch.object(pi_runtime, "node_executable", return_value=node):
                # Reproduce the prior copy-only verification path, with no
                # network or dependency installation hidden by the fixture.
                original_run, failures = pi_runtime.subprocess.run, []
                def observe(command, **options):
                    result = original_run(command, **options)
                    failures.append(result.stderr)
                    return result
                with patch.object(pi_runtime, "ensure_adapter_dependencies"), \
                     patch.object(pi_runtime.subprocess, "run", side_effect=observe), \
                     self.assertRaisesRegex(RuntimeError, "ERR_MODULE_NOT_FOUND"):
                    pi_runtime.verify_runtime(release, bridge)
                self.assertIn("Cannot find package 'tar'", failures[-1])
                pi_runtime.verify_runtime(release, bridge)
            self.assertEqual(json.loads((release / "node_modules/tar/package.json").read_text())["version"], "7.5.22")
            self.assertTrue((release / "node_modules/tar/node_modules/minipass/package.json").is_file())
            self.assertEqual(pi_runtime.installed_version(release), pi_runtime.PINNED_VERSION)

    def test_factory_dependency_closure_preserves_other_kernel_transitives(self):
        with temporary() as temp:
            base = Path(temp)
            source = base / "runtime/releases" / pi_runtime.RELEASE_NAME / "node_modules"
            release = base / "external"
            for location, data in (
                (source / "tar", {"name": "tar", "version": "7.5.22", "dependencies": {"minipass": "7"}}),
                (source / "minipass", {"name": "minipass", "version": "7.1.2"}),
                (release / "node_modules/minipass", {"name": "minipass", "version": "0.0.1", "preserved": True}),
            ):
                location.mkdir(parents=True)
                (location / "package.json").write_text(json.dumps(data))
            with patch.dict(pi_runtime.ADAPTER_DEPENDENCIES, {"tar": "7.5.22"}, clear=True):
                pi_runtime.ensure_adapter_dependencies(release, base / "runtime/bridge.mjs")
            old = json.loads((release / "node_modules/minipass/package.json").read_text())
            self.assertTrue(old["preserved"])
            self.assertEqual(json.loads((release / "node_modules/tar/node_modules/minipass/package.json").read_text())["version"], "7.1.2")

    def test_download_update_manifest_and_projected_runtime_include_adapters(self):
        from app.controller import Controller
        with temporary() as temp:
            base = Path(temp)
            jobs = []
            backend = SimpleNamespace(_kernel_busy=False, _view=SimpleNamespace(busy=False, workspace=""),
                _latest=pi_runtime.PINNED_VERSION, kernelVersion="0.0.0", changed=Mock(),
                store=SimpleNamespace(directory=base, data={"agent": {}}), root=ROOT,
                _job=lambda name, work: jobs.append((name, work)))
            real_run = pi_runtime.subprocess.run
            def download(command, **options):
                if "install" not in command:
                    return real_run(command, **options)
                stage = Path(command[command.index("--prefix") + 1])
                manifest = json.loads((stage / "package.json").read_text())
                expected = json.loads((ROOT / "runtime/package.json").read_text())["dependencies"]
                self.assertEqual(manifest["dependencies"], expected)
                self.assertEqual(options["creationflags"], pi_runtime.CREATE_NO_WINDOW)
                copy_modules(ROOT / "runtime/node_modules", stage / "node_modules")
                return SimpleNamespace(returncode=0)
            node = os.environ.get("UMEKO_TEST_NODE") or pi_runtime.node_executable()
            with patch("app.controller.npm_command", return_value=["fixture-node", "fixture-npm"]), \
                 patch("app.controller.subprocess.run", side_effect=download), \
                 patch.object(pi_runtime, "node_executable", return_value=node):
                Controller.updateKernel(backend)
                self.assertEqual(jobs[0][0], "update")
                final = Path(jobs[0][1]())
            self.assertEqual(final.name, pi_runtime.RELEASE_NAME)
            self.assertTrue((final / "node_modules/tar/package.json").is_file())
            self.assertEqual(json.loads((base / "kernels/active.json").read_text())["version"], pi_runtime.PINNED_VERSION)


if __name__ == "__main__":
    unittest.main()
