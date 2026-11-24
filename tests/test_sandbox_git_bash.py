from pathlib import Path
import tarfile
import tempfile
import unittest

from app.sandbox_git_bash import REQUIRED_FILES, git_bash_ready, prepare_git_bash


class GitBashArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.archive = self.base / "git-bash.tar.xz"
        self.root = self.base / "cache" / "v1"

    def make_archive(self, extra_name=None):
        source = self.base / "payload"
        source.write_bytes(b"fixture")
        with tarfile.open(self.archive, "w:xz") as bundle:
            for name in REQUIRED_FILES:
                bundle.add(source, arcname=name)
            if extra_name:
                bundle.add(source, arcname=extra_name)

    def test_recover_interrupted_and_incomplete_version(self):
        self.make_archive()
        partial = self.root.parent / ".v1.partial"
        partial.mkdir(parents=True)
        (partial / "interrupted.txt").touch()
        progress = []
        prepare_git_bash(self.archive, self.root, progress.append)
        self.assertTrue(git_bash_ready(self.root))
        self.assertFalse(partial.exists())
        self.assertEqual(progress[-1], 100)
        (self.root / REQUIRED_FILES[0]).write_bytes(b"")
        self.assertFalse(git_bash_ready(self.root))
        prepare_git_bash(self.archive, self.root, progress.append)
        self.assertEqual((self.root / REQUIRED_FILES[0]).read_bytes(), b"fixture")

    def test_bad_payload_never_creates_a_ready_directory(self):
        self.make_archive("../../outside")
        with self.assertRaisesRegex(ValueError, "archive path"):
            prepare_git_bash(self.archive, self.root, lambda _: None)
        self.assertFalse(self.root.exists())
        self.assertFalse((self.root.parent / ".v1.partial").exists())
        self.assertFalse((self.base / "outside").exists())

    def test_corrupt_xz_footer_leaves_no_ready_version(self):
        self.make_archive()
        self.archive.write_bytes(self.archive.read_bytes()[:-4])
        with self.assertRaises(EOFError):
            prepare_git_bash(self.archive, self.root, lambda _: None)
        self.assertFalse(self.root.exists())
        self.assertFalse((self.root.parent / ".v1.partial").exists())
