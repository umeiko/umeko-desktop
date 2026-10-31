"""Focused inert import tests; native metadata parsing is exercised by the host smoke."""
import re
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app import skill_import


def metadata(documents):
    rows = []
    for document in documents:
        text = document["markdown"]
        name = re.search(r"^name: (.+)$", text, re.M)
        description = re.search(r"^description: (.+)$", text, re.M)
        rows.append({"key": document["key"], "name": name[1] if name else document["directoryName"],
                     "description": description[1] if description else "", "valid": bool(description),
                     "diagnostics": [] if description else ["description is required"]})
    return rows


def document(name, body="Imported body"):
    return f"---\nname: {name}\ndescription: {name} description\n---\n{body}\n".encode()


class SkillImportTests(unittest.TestCase):
    def test_link_detection_supports_python310_path_api(self):
        class Path310:
            def is_symlink(self):
                return False
        self.assertFalse(skill_import._linked(Path310()))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="umeko-import-test-")
        self.root = Path(self.temporary.name)
        self.destination = self.root / "agent" / "skills"

    def tearDown(self):
        skill_import._plans.clear()
        self.temporary.cleanup()

    def folder(self, name="alpha", body="Imported body", parent=None):
        path = (parent or self.root / "source") / name
        path.mkdir(parents=True)
        (path / "SKILL.md").write_bytes(document(name, body))
        return path

    def preview(self, source, catalog=()):
        return skill_import.preview_import(source, self.destination, catalog, metadata)

    def test_single_folder_preview_writes_nothing_and_commit_uses_preview_bytes(self):
        source = self.folder(parent=self.root / "中文来源")
        (source / "assets").mkdir()
        (source / "assets" / "说明.txt").write_bytes(b"local asset")
        before = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))
        with patch.object(skill_import.tempfile, "mkdtemp", side_effect=AssertionError("preview created temporary files")):
            preview = self.preview(source)
        self.assertFalse(preview["errors"])
        self.assertEqual(preview["skills"][0]["name"], "alpha")
        self.assertEqual(before, sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*")))
        (source / "SKILL.md").write_bytes(b"Changed after user preview")
        result = skill_import.commit_import(preview, {}, self.destination)
        self.assertEqual(result["imported"], ["alpha"])
        self.assertIn(b"Imported body", (self.destination / "alpha/SKILL.md").read_bytes())
        self.assertEqual((self.destination / "alpha/assets/说明.txt").read_bytes(), b"local asset")

    def test_multi_skill_folder_and_latest_preview_releases_old_plan(self):
        parent = self.root / "collection"
        self.folder("alpha", parent=parent)
        self.folder("beta", parent=parent / "nested")
        previous = self.preview(parent)
        current = self.preview(parent)
        self.assertEqual(len(skill_import._plans), 1)
        with self.assertRaisesRegex(ValueError, "预览"):
            skill_import.commit_import(previous, {}, self.destination)
        result = skill_import.commit_import(current, {"beta": "skip"}, self.destination)
        self.assertEqual(result["imported"], ["alpha"])
        self.assertEqual(result["skipped"], ["beta"])

    def test_zip_and_skill_archives_preview_without_extraction(self):
        for extension in (".zip", ".skill"):
            with self.subTest(extension=extension):
                archive = self.root / ("技能" + extension)
                with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as stream:
                    stream.writestr("wrapper/alpha/SKILL.md", document("alpha"))
                    stream.writestr("wrapper/alpha/references/example.txt", "reference")
                    stream.writestr("wrapper/beta/SKILL.md", document("beta"))
                preview = self.preview(archive)
                self.assertFalse(preview["errors"])
                self.assertEqual({row["name"] for row in preview["skills"]}, {"alpha", "beta"})
                self.assertFalse(self.destination.exists())
                skill_import.discard_import(preview)

    def test_invalid_skill_never_replaces_existing_files(self):
        old = self.destination / "alpha"
        old.mkdir(parents=True)
        (old / "SKILL.md").write_bytes(document("alpha", "Old body"))
        source = self.folder()
        (source / "SKILL.md").write_text("---\nname: alpha\n---\nmissing description", encoding="utf-8")
        preview = self.preview(source, [{"name": "alpha", "path": str(old / "SKILL.md"), "source": "global"}])
        self.assertIn("error", preview["skills"][0])
        result = skill_import.commit_import(preview, {"alpha": "replace"}, self.destination)
        self.assertEqual(result["imported"], [])
        self.assertIn(b"Old body", (old / "SKILL.md").read_bytes())

    def test_conflicts_default_skip_then_explicit_local_replace(self):
        old = self.destination / "old-directory"
        old.mkdir(parents=True)
        (old / "SKILL.md").write_bytes(document("alpha", "Old body"))
        catalog = [{"name": "alpha", "path": str(old / "SKILL.md"), "source": "global"}]
        source = self.folder()
        preview = self.preview(source, catalog)
        self.assertTrue(preview["skills"][0]["replaceable"])
        self.assertEqual(skill_import.commit_import(preview, {}, self.destination)["skipped"], ["alpha"])
        replacement = self.preview(source, catalog)
        result = skill_import.commit_import(replacement, {"alpha": "replace"}, self.destination)
        self.assertEqual(result["imported"], ["alpha"])
        self.assertIn(b"Imported body", (old / "SKILL.md").read_bytes())

    def test_package_and_external_name_conflicts_cannot_replace(self):
        source = self.folder()
        external = self.folder(parent=self.root / "outside")
        for row in ({"name": "alpha", "path": str(external / "SKILL.md"), "source": "extra"},
                    {"name": "alpha", "path": str(external / "SKILL.md"), "source": "package", "packageSource": "npm:fixture"}):
            with self.subTest(source=row["source"]):
                preview = self.preview(source, [row])
                self.assertFalse(preview["skills"][0]["replaceable"])
                self.assertEqual(skill_import.commit_import(preview, {"alpha": "replace"}, self.destination)["imported"], [])
        self.assertFalse(self.destination.exists())

    def test_unsafe_archives_and_expansion_limits_are_rejected_before_write(self):
        cases = [
            [("../escape/SKILL.md", document("alpha"))],
            [("Alpha/SKILL.md", document("alpha")), ("alpha/asset.txt", b"case conflict")],
            [("alpha", b"file"), ("alpha/SKILL.md", document("alpha"))],
        ]
        for index, entries in enumerate(cases):
            archive = self.root / f"unsafe-{index}.zip"
            with zipfile.ZipFile(archive, "w") as stream:
                for name, content in entries:
                    stream.writestr(name, content)
            self.assertTrue(self.preview(archive)["errors"])
        for kind in (stat.S_IFLNK, stat.S_IFIFO):
            archive = self.root / f"special-{kind}.zip"
            with zipfile.ZipFile(archive, "w") as stream:
                item = zipfile.ZipInfo("alpha/SKILL.md")
                item.external_attr = (kind | 0o777) << 16
                stream.writestr(item, document("alpha"))
            self.assertTrue(self.preview(archive)["errors"])
        archive = self.root / "large.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as stream:
            stream.writestr("alpha/SKILL.md", document("alpha", "large" * 10000))
        with patch.object(skill_import, "MAX_BYTES", 2048):
            self.assertTrue(self.preview(archive)["errors"])
        encrypted = self.root / "encrypted.zip"
        with zipfile.ZipFile(encrypted, "w") as stream:
            stream.writestr("alpha/SKILL.md", document("alpha"))
        data = bytearray(encrypted.read_bytes())
        data[6] |= 1
        data[data.index(b"PK\x01\x02") + 8] |= 1
        encrypted.write_bytes(data)
        self.assertTrue(self.preview(encrypted)["errors"])
        self.assertFalse(self.destination.exists())

    def test_failed_atomic_replacement_restores_old_skill(self):
        old = self.destination / "alpha"
        old.mkdir(parents=True)
        (old / "SKILL.md").write_bytes(document("alpha", "Old body"))
        preview = self.preview(self.folder(), [{"name": "alpha", "path": str(old / "SKILL.md"), "source": "global"}])
        rename = Path.rename
        def fail_stage(path, target):
            if path.name == "skill" and path.parent.name.startswith(".umeko-import-"):
                raise OSError("controlled rename failure")
            return rename(path, target)
        with patch.object(Path, "rename", fail_stage):
            result = skill_import.commit_import(preview, {"alpha": "replace"}, self.destination)
        self.assertEqual(result["skipped"], ["alpha"])
        self.assertTrue(result["errors"])
        self.assertIn(b"Old body", (old / "SKILL.md").read_bytes())


if __name__ == "__main__":
    unittest.main()
