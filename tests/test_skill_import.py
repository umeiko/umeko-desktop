"""Focused inert import tests; native metadata parsing is exercised by the host smoke."""
import re
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app import skill_import
from app.skill_import_paths import ImportDirectories


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

    def test_python310_reparse_attribute_detects_junction_without_is_junction(self):
        from types import SimpleNamespace
        class Path310:
            def is_symlink(self):
                return False
            def lstat(self):
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        self.assertTrue(skill_import._linked(Path310()))

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
        with patch.object(ImportDirectories, "mkdir", side_effect=AssertionError("preview created temporary files")):
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

    def test_direct_import_keeps_folder_name_metadata_and_resources(self):
        source = self.folder('renamed-folder')
        content = document('original-metadata-name')
        (source / 'SKILL.md').write_bytes(content)
        (source / 'reference.txt').write_text('Resource')
        result = skill_import.import_local(source, self.destination, [], metadata)
        self.assertEqual(result['imported'], ['renamed-folder'])
        self.assertEqual((self.destination / 'renamed-folder/SKILL.md').read_bytes(), content)
        self.assertEqual((self.destination / 'renamed-folder/reference.txt').read_text(), 'Resource')
        self.assertFalse(skill_import._plans)

    def test_direct_import_refuses_entire_batch_on_conflict_or_invalid_document(self):
        batch = self.root / 'collection'
        self.folder('new-folder', parent=batch)
        source = self.folder('existing', parent=batch)
        old = self.folder('existing', body='Original files', parent=self.destination)
        with self.assertRaisesRegex(ValueError, '同名'):
            skill_import.import_local(batch, self.destination, [], metadata)
        self.assertFalse((self.destination / 'new-folder').exists())
        self.assertIn(b'Original files', (old / 'SKILL.md').read_bytes())
        self.assertFalse(skill_import._plans)
        (source / 'SKILL.md').write_text('Invalid frontmatter')
        with self.assertRaisesRegex(ValueError, 'SKILL.md'):
            skill_import.import_local(batch, self.destination, [], metadata)
        self.assertFalse((self.destination / 'new-folder').exists())
        self.assertFalse(skill_import._plans)

    def test_direct_import_does_not_overwrite_a_target_created_during_staging(self):
        source = self.folder()
        write = ImportDirectories.write
        def race(directories, path, content):
            write(directories, path, content)
            target = self.destination / 'alpha'
            target.mkdir(exist_ok=True)
            (target / 'SKILL.md').write_bytes(document('alpha', 'Created concurrently'))
        with patch.object(ImportDirectories, 'write', race):
            result = skill_import.import_local(source, self.destination, [], metadata)
        self.assertTrue(result['errors'])
        self.assertEqual(result['imported'], [])
        self.assertIn(b'Created concurrently', (self.destination / 'alpha/SKILL.md').read_bytes())
        self.assertFalse(skill_import._plans)

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
        rename = ImportDirectories.rename
        def fail_stage(directories, path, target):
            if path.name == "skill" and path.parent.name.startswith(".umeko-import-"):
                raise OSError("controlled rename failure")
            return rename(directories, path, target)
        with patch.object(ImportDirectories, "rename", fail_stage):
            result = skill_import.commit_import(preview, {"alpha": "replace"}, self.destination)
        self.assertEqual(result["skipped"], ["alpha"])
        self.assertTrue(result["errors"])
        self.assertIn(b"Old body", (old / "SKILL.md").read_bytes())

    def replace_preview(self):
        old = self.destination / 'group' / 'alpha'
        old.mkdir(parents=True)
        (old / 'SKILL.md').write_bytes(document('alpha', 'Original'))
        preview = self.preview(self.folder(), [{'name': 'alpha', 'path': str(old / 'SKILL.md'), 'source': 'global'}])
        self.assertTrue(preview['skills'][0]['replaceable'])
        outside = self.root / 'outside' / 'alpha'
        outside.mkdir(parents=True)
        (outside / 'SKILL.md').write_bytes(document('alpha', 'Outside'))
        (outside / 'keep.txt').write_text('Preserve me')
        return old, preview, outside

    def assert_outside_preserved(self, outside):
        self.assertIn(b'Outside', (outside / 'SKILL.md').read_bytes())
        self.assertEqual((outside / 'keep.txt').read_text(), 'Preserve me')

    @unittest.skipIf(os.name == 'nt', 'POSIX symlink boundary; Windows junction tested separately')
    def test_parent_replaced_after_preview_cannot_overwrite_external_skill(self):
        old, preview, outside = self.replace_preview()
        old.parent.rename(self.root / 'saved-group')
        old.parent.symlink_to(outside.parent, target_is_directory=True)
        result = skill_import.commit_import(preview, {'alpha': 'replace'}, self.destination)
        self.assertEqual(result['imported'], [])
        self.assertTrue(result['errors'])
        self.assert_outside_preserved(outside)

    def test_recreated_directory_requires_new_preview(self):
        old, preview, outside = self.replace_preview()
        old.parent.rename(self.root / 'saved-group')
        old.mkdir(parents=True)
        (old / 'SKILL.md').write_bytes(document('alpha', 'Changed'))
        result = skill_import.commit_import(preview, {'alpha': 'replace'}, self.destination)
        self.assertEqual(result['imported'], [])
        self.assertIn(b'Changed', (old / 'SKILL.md').read_bytes())
        self.assert_outside_preserved(outside)

    def test_many_asset_directories_keep_open_handle_count_bounded(self):
        source = self.folder()
        for index in range(80):
            folder = source / f'asset-{index}'
            folder.mkdir()
            (folder / 'example.txt').write_bytes(b'Inert asset')
        preview = self.preview(source)
        write = ImportDirectories.write
        counts = []
        def observe(directories, path, content):
            write(directories, path, content)
            counts.append(len(directories.opened))
        with patch.object(ImportDirectories, 'write', observe):
            result = skill_import.commit_import(preview, {}, self.destination)
        self.assertEqual(result['imported'], ['alpha'])
        self.assertEqual(len(list((self.destination / 'alpha').glob('asset-*/example.txt'))), 80)
        self.assertLessEqual(max(counts), len(self.destination.parents) + 5)

    @unittest.skipIf(os.name == 'nt', 'POSIX descriptor race')
    def test_parent_swapped_during_staging_uses_pinned_directory(self):
        old, preview, outside = self.replace_preview()
        write = ImportDirectories.write
        def swap(directories, path, content):
            old.parent.rename(self.root / 'saved-group')
            old.parent.symlink_to(outside.parent, target_is_directory=True)
            write(directories, path, content)
        with patch.object(ImportDirectories, 'write', swap):
            result = skill_import.commit_import(preview, {'alpha': 'replace'}, self.destination)
        self.assertEqual(result['imported'], ['alpha'])
        self.assertIn(b'Imported body', (self.root / 'saved-group/alpha/SKILL.md').read_bytes())
        self.assert_outside_preserved(outside)

    @unittest.skipIf(os.name == 'nt', 'POSIX symlink boundary')
    def test_destination_ancestor_replaced_before_commit(self):
        source = self.folder()
        self.destination.parent.mkdir(parents=True)
        preview = self.preview(source)
        self.destination.parent.rename(self.root / 'saved-agent')
        outside = self.root / 'outside'
        outside.mkdir()
        self.destination.parent.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, '目标目录'):
            skill_import.commit_import(preview, {}, self.destination)
        self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows junction and directory-handle boundary')
    def test_windows_junction_swap_cannot_overwrite_external_skill(self):
        import subprocess
        old, preview, outside = self.replace_preview()
        old.parent.rename(self.root / 'saved-group')
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(old.parent), str(outside.parent)], check=True, capture_output=True)
        result = skill_import.commit_import(preview, {'alpha': 'replace'}, self.destination)
        self.assertEqual(result['imported'], [])
        self.assert_outside_preserved(outside)
        old.parent.rmdir()

    @unittest.skipUnless(os.name == 'nt', 'Windows directory-handle boundary')
    def test_windows_pins_parent_during_staging_and_allows_own_replacement(self):
        old, preview, outside = self.replace_preview()
        write = ImportDirectories.write
        def attempt_swap(directories, path, content):
            with self.assertRaises(OSError):
                old.parent.rename(self.root / 'saved-group')
            write(directories, path, content)
        with patch.object(ImportDirectories, 'write', attempt_swap):
            result = skill_import.commit_import(preview, {'alpha': 'replace'}, self.destination)
        self.assertEqual(result['imported'], ['alpha'])
        self.assert_outside_preserved(outside)


if __name__ == "__main__":
    unittest.main()
