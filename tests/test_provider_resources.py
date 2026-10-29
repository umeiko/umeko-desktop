"""Build policy must keep unapproved provider code out of desktop resources."""
import importlib.util
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("provider_resource_builder", ROOT / "scripts/build-provider-resources.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ProviderResourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for source in ("umeko_provider_sdk", "provider_dev/examples", "provider_dev/skills"):
            shutil.copytree(ROOT / source, self.root / source, ignore=shutil.ignore_patterns("__pycache__"))
        for source in ("pyproject.toml", "provider_dev/README.md"):
            shutil.copyfile(ROOT / source, self.root / source)
        self.provider = self.root / "provider_dev/bundled/example-echo"
        shutil.copytree(ROOT / "provider_dev/examples/echo-provider", self.provider)
        (self.provider / "scripts/provider.py").write_text("raise AssertionError('build executed plugin')")
        self.output = self.root / "build/provider-resources"
        self.output.mkdir(parents=True)
        self.previous = builder.ROOT, builder.OUT
        builder.ROOT, builder.OUT = self.root, self.output
        self.addCleanup(self.restore)

    def restore(self): builder.ROOT, builder.OUT = self.previous

    def policy(self, ids):
        (self.root / "provider_dev/default-providers.json").write_text(json.dumps({"schemaVersion": 1, "providers": ids}))

    def test_unlisted_provider_and_stale_zip_are_excluded(self):
        self.policy([])
        (self.output / "unapproved-1.0.0.zip").write_bytes(b"stale")
        builder.main()
        catalog = json.loads((self.output / "bundled-providers.json").read_text())
        self.assertEqual(catalog["providers"], [])
        self.assertFalse((self.output / "unapproved-1.0.0.zip").exists())
        self.assertEqual(len(list(self.output.glob("*.zip"))), 2)
        for path in self.output.glob("*.zip"):
            with zipfile.ZipFile(path) as stream:
                self.assertFalse(any("bundled/" in name for name in stream.namelist()))

    def test_explicit_default_is_packaged_without_executing_it(self):
        self.policy(["example-echo"])
        builder.main()
        catalog = json.loads((self.output / "bundled-providers.json").read_text())
        self.assertEqual(catalog["providers"][0]["id"], "example-echo")
        self.assertTrue((self.output / catalog["providers"][0]["archive"]).is_file())

    def test_invalid_policy_cannot_replace_previous_resources(self):
        sentinel = self.output / "previous.txt"
        sentinel.write_text("previous successful build")
        for ids in (["../outside"], ["example-echo", "example-echo"], ["missing"], [123]):
            self.policy(ids)
            with self.subTest(ids=ids), self.assertRaises(ValueError): builder.main()
            self.assertTrue(sentinel.exists())
