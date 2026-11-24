"""Git worktrees owned by Agent Bus requests.

Directory isolation follows @wjj865-code/dsh-orchestrator 0.33.1
(src/write-guard.js, src/worktree.js). Sync and merge follow
opencode-mission-control 2.0.1 (src/tools/{sync,merge}.ts, src/lib/worktree.ts).
Notices: ../licenses/{dsh-orchestrator,opencode-mission-control}-MIT.txt.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess


class WorktreeError(ValueError):
    pass


def paths_overlap(left, right):
    """Directory containment includes the whole directory component."""
    if not left or not right:
        return False
    left, right = Path(left).resolve(), Path(right).resolve()
    return left.is_relative_to(right) or right.is_relative_to(left)


class GitWorktrees:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()

    @staticmethod
    def git(cwd, *args, accepted=(0,)):
        env = {key: value for key, value in os.environ.items() if key not in {
            "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
            "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
        }}
        env.update(LC_ALL="C", GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
        try:
            result = subprocess.run(
                ["git", "-c", "core.quotepath=false", "-C", str(cwd), *args],
                env=env, capture_output=True, encoding="utf-8", errors="replace",
                timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError:
            raise WorktreeError("找不到 Git。请安装 Git 并将其加入 PATH。") from None
        except subprocess.TimeoutExpired:
            raise WorktreeError("Git 操作超时。请检查工作树和分支后再试。") from None
        if result.returncode not in accepted:
            reason = result.stderr.strip() or result.stdout.strip()
            raise WorktreeError(reason[:4000] or f"Git 退出码 {result.returncode}")
        return result

    def describe(self, cwd, identifier):
        if not re.fullmatch(r"[0-9a-f]{32}", identifier):
            raise WorktreeError("任务标识无效。")
        result = self.git(cwd, "rev-parse", "--show-toplevel", accepted=(0, 128))
        if result.returncode:
            raise WorktreeError("任务目录不是可用的 Git 仓库。")
        repo = Path(result.stdout.strip()).resolve()
        working_directory = Path(cwd).resolve()
        path = self.directory / identifier
        if path.is_relative_to(repo):
            raise WorktreeError("请将应用数据目录放在任务仓库之外。")
        ref = self.git(repo, "symbolic-ref", "-q", "HEAD", accepted=(0, 1)).stdout.strip()
        if not ref.startswith("refs/heads/"):
            raise WorktreeError("原目录需要检出一个 Git 分支。")
        result = self.git(repo, "rev-parse", "--verify", "HEAD", accepted=(0, 128))
        if result.returncode:
            raise WorktreeError("Git 仓库需要至少一次提交。")
        return {
            "repository": str(repo), "baseRef": ref, "baseCommit": result.stdout.strip(),
            "branch": f"umeko/task-{identifier}", "path": str(path),
            "cwd": str(path / working_directory.relative_to(repo)),
        }

    def create(self, info):
        path = self.managed_path(info)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.git(info["repository"], "worktree", "add", "-b", info["branch"],
                 str(path), info["baseCommit"])
        if not Path(info["cwd"]).is_dir():
            raise WorktreeError("原会话的子目录没有出现在任务分支中。")

    def managed_path(self, info):
        path = Path(info["path"])
        if path != self.directory / path.name or path.resolve() != path or not re.fullmatch(r"[0-9a-f]{32}", path.name):
            raise WorktreeError("这不是本应用创建的任务工作树。")
        if info["branch"] != f"umeko/task-{path.name}":
            raise WorktreeError("工作树与任务分支不匹配。")
        return path

    def check_checkout(self, info):
        path = self.managed_path(info)
        entries = self.git(info["repository"], "worktree", "list", "--porcelain", "-z").stdout
        for entry in entries.split("\0\0"):
            fields = entry.split("\0")
            if fields[0].startswith("worktree ") and Path(fields[0][9:]).resolve() == path:
                if f'branch refs/heads/{info["branch"]}' in fields:
                    return path
                raise WorktreeError("任务工作树已切换分支，请在 Git 中检查。")
        raise WorktreeError("任务工作树不存在或已被移动。")

    def save(self, info, identifier):
        path = self.check_checkout(info)
        self.git(path, "add", "-A")
        changed = self.git(path, "diff", "--cached", "--quiet", accepted=(0, 1))
        if changed.returncode:
            self.git(path, "-c", "user.name=Umeko", "-c", "user.email=umeko@users.noreply.github.com",
                     "commit", "-m", f"Save Agent Bus task {identifier}")

    def merge(self, info):
        repo = info["repository"]
        ref = self.git(repo, "symbolic-ref", "-q", "HEAD", accepted=(0, 1)).stdout.strip()
        if ref != info["baseRef"]:
            raise WorktreeError("原目录已切换分支。任务分支已保留。")
        head = self.git(repo, "rev-parse", "--verify", "HEAD").stdout.strip()
        branch = self.git(repo, "rev-parse", "--verify", f'refs/heads/{info["branch"]}').stdout.strip()
        if self.git(repo, "merge-base", "--is-ancestor", branch, head, accepted=(0, 1)).returncode == 0:
            return
        if self.git(repo, "merge-base", "--is-ancestor", head, branch, accepted=(0, 1)).returncode:
            # Compute the merge without writing to the original index or files.
            merged = self.git(repo, "merge-tree", "--write-tree", head, branch, accepted=(0, 1))
            if merged.returncode:
                detail = "\n".join(merged.stdout.splitlines()[1:])[:2000]
                raise WorktreeError("合并冲突。原目录和任务分支均已保留。\n" + detail)
            tree = merged.stdout.splitlines()[0]
            branch = self.git(repo, "-c", "user.name=Umeko", "-c",
                              "user.email=umeko@users.noreply.github.com", "commit-tree", tree,
                              "-p", head, "-p", branch, "-m", f'Merge {info["branch"]}').stdout.strip()
        try:
            # Git refuses to overwrite colliding user files. No stash, clean or reset.
            self.git(repo, "merge", "--ff-only", "--no-autostash", "--no-overwrite-ignore", branch)
        except WorktreeError as error:
            raise WorktreeError(f"原目录无法安全合并。任务分支已保留。\n{error}") from error

    def files(self, info):
        path = self.check_checkout(info)
        status = self.git(path, "status", "--porcelain=v1", "-z", "--untracked-files=all",
                          "--ignored=matching", "--no-renames").stdout
        return [entry[3:] for entry in status.split("\0") if entry]

    def remove(self, info):
        path = self.check_checkout(info)
        if self.files(info):
            raise WorktreeError("工作树还有未提交或忽略的文件。请先保存在别处。")
        self.git(info["repository"], "worktree", "remove", str(path))
