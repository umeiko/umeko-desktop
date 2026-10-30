"""ZIP diagnostics and benign path normalization, without executing provider code."""
import json
import shutil
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from umeko_provider_sdk import ProviderError
from umeko_provider_sdk.packages import PackageValidationError, pack_package, unpack_package, validate_folder

ROOT = Path(__file__).resolve().parents[1]


class PackagePathsTests(unittest.TestCase):
    def test_optional_description_is_plain_text_and_rejects_other_types(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder) / "provider"
            shutil.copytree(ROOT / "provider_dev/examples/echo-provider", folder)
            path = folder / "manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest.pop("description", None)
            path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(validate_folder(folder)[0]["description"], "")
            for value in ("", " \n ", "  插件说明\nUse <b>plain text</b>.  "):
                manifest["description"] = value
                path.write_text(json.dumps(manifest), encoding="utf-8")
                self.assertEqual(validate_folder(folder)[0]["description"], value.strip())
            for value in (None, 42, True, [], {}):
                with self.subTest(value=value):
                    manifest["description"] = value
                    path.write_text(json.dumps(manifest), encoding="utf-8")
                    with self.assertRaisesRegex(ProviderError, "description must be a string"):
                        validate_folder(folder)

    def test_dot_paths_and_wrapper_are_normalized_in_archive_and_manifest(self):
        for prefix in ("./", "./provider/"):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as folder:
                folder = Path(folder)
                original, archive = folder / "original.zip", folder / "input.zip"
                pack_package(ROOT / "provider_dev/examples/echo-provider", original)
                with zipfile.ZipFile(original) as source, zipfile.ZipFile(archive, "w") as output:
                    output.writestr("./", "")
                    for name in source.namelist():
                        data = source.read(name)
                        if name == "manifest.json":
                            manifest = json.loads(data)
                            for key in ("entrypoint", "config", "configSchema"):
                                manifest[key] = "./" + manifest.get(key, key + ".json")
                            data = json.dumps(manifest)
                        output.writestr(prefix + name, data)
                manifest, _, _ = unpack_package(archive, folder / "output")
                self.assertEqual(manifest["entrypoint"], "scripts/provider.py:create_provider")
                self.assertEqual(manifest["config"], "config.json")
                self.assertTrue((folder / "output/scripts/provider.py").is_file())

    def test_bad_paths_report_original_entry_and_specific_rule(self):
        cases = [("./scripts/../bad.py", "PARENT_PATH"), ("/bad.py", "ABSOLUTE_PATH"),
                 ("C:/bad.py", "COLON"), ("scripts\\bad.py", "BACKSLASH"),
                 ("scripts//bad.py", "EMPTY_SEGMENT"), ("scripts/bad. ", "TRAILING_DOT_SPACE"),
                 ("CON.txt", "RESERVED_NAME")]
        for name, rule in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                archive = Path(folder) / "input.zip"
                with zipfile.ZipFile(archive, "w") as output:
                    info = zipfile.ZipInfo(name)
                    info.filename = info.orig_filename = name  # Preserve raw backslashes on Windows.
                    output.writestr(info, "fixture")
                with self.assertRaises(PackageValidationError) as raised:
                    unpack_package(archive, Path(folder) / "out")
                self.assertEqual((raised.exception.entry, raised.exception.rule), (name, rule))
                self.assertIn(rule, str(raised.exception))
                self.assertFalse((Path(folder) / "out").exists())

    def test_symlinks_and_normalized_collisions_report_exact_entries(self):
        for names, rule in [(["scripts/a.py", "./scripts/a.py"], "DUPLICATE_PATH"),
                            (["scripts/A.py", "scripts/a.py"], "DUPLICATE_PATH"),
                            (["scripts", "./scripts/a.py"], "PATH_TYPE_CONFLICT"),
                            (["./scripts/link.py"], "SYMLINK")]:
            with self.subTest(names=names), tempfile.TemporaryDirectory() as folder:
                archive = Path(folder) / "input.zip"
                with zipfile.ZipFile(archive, "w") as output:
                    for name in names:
                        info = zipfile.ZipInfo(name)
                        if rule == "SYMLINK": info.external_attr = (stat.S_IFLNK | 0o777) << 16
                        output.writestr(info, "fixture")
                with self.assertRaises(PackageValidationError) as raised:
                    unpack_package(archive, Path(folder) / "out")
                self.assertEqual((raised.exception.entry, raised.exception.rule), (names[-1], rule))
                if len(names) > 1: self.assertEqual(raised.exception.conflict, names[0])


if __name__ == "__main__": unittest.main()
