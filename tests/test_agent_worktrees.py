from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.agent_worktrees import GitWorktrees, WorktreeConflict, WorktreeError, paths_overlap, worktree_display


class AgentWorktreeTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo = self.root / "中文 空格"
        self.repo.mkdir()
        self.trees = GitWorktrees(self.root / "tasks")
        self.git = self.trees.git
        self.git(self.repo, "init", "-b", "main")
        for key, value in (("user.name", "Test"), ("user.email", "test@example.com"),
                           ("core.autocrlf", "false")):
            self.git(self.repo, "config", key, value)
        self.lines = [f"line {n}\n" for n in range(40)]
        (self.repo / "shared.txt").write_text("".join(self.lines), encoding="utf-8")
        (self.repo / "dirty.txt").write_bytes(b"original\n")
        (self.repo / "staged.txt").write_bytes(b"original\n")
        self.git(self.repo, "add", "-A")
        self.git(self.repo, "commit", "-m", "base")

    def create(self, number):
        identifier = f"{number:032x}"
        info = self.trees.describe(self.repo, identifier, f"Writer {number}", "Update shared file")
        self.trees.create(info)
        return identifier, info

    def edit(self, number, line):
        identifier, info = self.create(number)
        content = self.lines[:]
        content[line] = f"agent {number}\n"
        (Path(info["cwd"]) / "shared.txt").write_text("".join(content), encoding="utf-8")
        self.trees.save(info)
        return info

    def test_three_writers_preserve_main_and_merge_disjoint_edits(self):
        (self.repo / "dirty.txt").write_bytes(b"user unstaged\n")
        (self.repo / "staged.txt").write_bytes(b"user staged\n")
        self.git(self.repo, "add", "staged.txt")
        (self.repo / "untracked.txt").write_bytes(b"user untracked\n")
        index = (self.repo / ".git/index").read_bytes()
        with ThreadPoolExecutor(3) as pool:
            futures = [pool.submit(self.edit, number, line)
                       for number, line in enumerate((4, 18, 34), 1)]
            tasks = [future.result() for future in futures]
        self.assertEqual((self.repo / ".git/index").read_bytes(), index)
        self.assertEqual((self.repo / "shared.txt").read_text(encoding="utf-8"), "".join(self.lines))
        for number, info in enumerate(tasks, 1):
            content = (Path(info["path"]) / "shared.txt").read_text(encoding="utf-8")
            self.assertEqual([line for line in content.splitlines() if line.startswith("agent")],
                             [f"agent {number}"])
            self.trees.merge(info)
        self.assertEqual([line for line in (self.repo / "shared.txt").read_text(encoding="utf-8").splitlines()
                          if line.startswith("agent")], ["agent 1", "agent 2", "agent 3"])
        for name, data in (("dirty", b"user unstaged\n"), ("staged", b"user staged\n"),
                           ("untracked", b"user untracked\n")):
            self.assertEqual((self.repo / f"{name}.txt").read_bytes(), data)
        self.assertEqual(self.git(self.repo, "show", ":staged.txt").stdout, "user staged\n")

    def test_conflict_preserves_both_worktrees_and_only_selected_cleanup(self):
        first, second = self.edit(1, 8), self.edit(2, 8)
        self.trees.merge(first)
        main = (self.repo / "shared.txt").read_bytes()
        branch = (Path(second["path"]) / "shared.txt").read_bytes()
        with self.assertRaisesRegex(WorktreeConflict, "合并冲突") as error:
            self.trees.merge(second)
        self.assertEqual(error.exception.files, ["shared.txt"])
        self.assertEqual((self.repo / "shared.txt").read_bytes(), main)
        self.assertEqual((Path(second["path"]) / "shared.txt").read_bytes(), branch)
        note = Path(first["path"]) / "not-saved.txt"
        note.write_bytes(b"preserve")
        self.assertEqual(self.trees.files(first), ["not-saved.txt"])
        with self.assertRaisesRegex(WorktreeError, "未提交"):
            self.trees.remove(first)
        note.unlink()
        self.trees.remove(first)
        self.assertFalse(Path(first["path"]).exists())
        self.assertTrue(Path(second["path"]).is_dir())
        self.assertIn(first["branch"], self.git(self.repo, "branch", "--list").stdout)

    def test_readable_names_reuse_short_prefix_and_preserve_legacy_checkout(self):
        name = "umeko/writer-3-修改-parser-166d96ef"
        identifier = "166d96ef" + "0" * 24
        first = self.trees.describe(self.repo, identifier, "Writer 3", "修改 / Parser")
        self.assertEqual(first["branch"], name)
        self.assertEqual(Path(first["path"]).name, name.split("/")[1])
        self.trees.create(first)
        self.trees.remove(first)
        second = self.trees.describe(self.repo, "166d96ef" + "1" * 24, "Writer 3", "修改 / Parser")
        self.assertEqual(second["branch"], name + "-2")

        legacy_path = str(self.trees.directory / identifier)
        legacy = {**first, "path": legacy_path, "cwd": legacy_path, "branch": "umeko/task-" + identifier}
        self.trees.create(legacy)
        self.assertEqual(worktree_display(legacy)["branch"], "umeko/task-166d96ef…")
        self.assertNotIn(identifier, worktree_display(legacy)["path"])
        self.assertEqual(self.trees.check_checkout(legacy), Path(legacy_path))
        self.trees.remove(legacy)
        self.assertIn(legacy["branch"], self.git(self.repo, "branch", "--list").stdout)

    def test_git_errors_and_containment(self):
        with self.assertRaisesRegex(WorktreeError, "不是可用的 Git"):
            self.trees.describe(self.root, "1" * 32)
        # Mock the OS lookup error, including on Windows where PATH alone need
        # not hide system directories.
        with patch("app.agent_worktrees.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(WorktreeError, "找不到 Git"):
                self.trees.describe(self.repo, "1" * 32)
        self.assertTrue(paths_overlap(self.repo, self.repo / "child"))
        self.assertFalse(paths_overlap(self.repo, self.root / "中文 空格-extra"))
