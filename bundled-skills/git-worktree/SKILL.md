---
name: git-worktree
description: Prepare an isolated Git worktree for a coding task; inspect, retain, reopen and safely remove linked working directories. Use for parallel changes, separate task branches, worktree conflicts or cleanup (工作树隔离、独立任务目录、保留与清理). Reuse existing Umeko projects and sessions.
---

# Git worktree

Keep one task in one actual working directory. Apply this workflow when the
user requests directory isolation or worktree management; an ordinary coding
request does not require a new worktree.

Use existing Git and Umeko tools. This Skill is a procedure, not an automatic
session manager or a sandbox. Worktrees have separate files and indexes but
share Git objects, refs, hooks and some configuration. They do not isolate
network access, credentials, external files or processes. Do not install tools,
run setup scripts, copy secrets, merge or publish as a side effect.

## Inspect and choose

1. Read the caller's actual workspace and session metadata. If available, use
   `umeko_desktop` with `sessions.get` (omit `id` for the calling session),
   `sessions.list` and `projects.list`; follow pagination. The chat visible on
   screen need not be the caller.
2. Check `git --version`. Missing Git, inaccessible/non-Git directories, bare
   repositories, unborn HEADs or unsupported options block creation. Explain
   the limitation and keep the original directory.
3. Set `task_repo` to the verified absolute root. Inspect with:

   ```sh
   git -C "$task_repo" rev-parse --show-toplevel
   git -C "$task_repo" rev-parse --is-bare-repository
   git -C "$task_repo" status --porcelain=v1 -z --untracked-files=all --ignore-submodules=none
   git -C "$task_repo" worktree list --porcelain -z
   ```

   Check every exit status. Prefer argument arrays; quote paths in shells and
   set variables using the host shell's syntax (PowerShell on Windows, for
   example). Parse NUL records, not whitespace-separated paths. A linked tree
   normally has a `.git` file rather than a directory.
4. Preserve the original index, tracked changes and untracked files. A dirty
   tree permits creation from a commit, but its uncommitted changes will not
   appear in the new tree. Do not stash, reset, clean, commit or copy them
   without a separate request.
5. Offer the current directory or a separate worktree. Agree the baseline,
   branch and absolute destination; prefer a sibling outside existing trees.
   Reject existing destinations (including symlinks), overlapping directories
   and occupied branches. Do not guess `main` or silently change the baseline.
   For reuse, verify the exact registered path, repository and branch, and
   obtain consent before adopting a tree associated with another task.
6. Warn about sessions/tasks sharing the actual directory. A session list is
   not an OS process inventory; state any uncertainty about other use. Reuse
   may be acceptable if the user understands the overlap.

## Create and verify

For a new branch, set `task_branch`, `task_worktree` and `task_base` to the
agreed values. Validate its name and check that it does not exist:

```sh
git -C "$task_repo" check-ref-format --branch "$task_branch"
git -C "$task_repo" show-ref --verify --quiet "refs/heads/$task_branch"
git -C "$task_repo" rev-parse --verify --end-of-options "$task_base^{commit}"
```

Only exit 1 from `show-ref` means the branch is absent; an existing branch or a
different error is not permission to overwrite it. Save successful baseline
resolution as `task_base_sha`, then run:

```sh
git -C "$task_repo" worktree add -b "$task_branch" -- "$task_worktree" "$task_base_sha"
git -C "$task_repo" worktree list --porcelain -z
git -C "$task_worktree" rev-parse --show-toplevel
git -C "$task_worktree" symbolic-ref --short HEAD
git -C "$task_worktree" rev-parse HEAD
```

Confirm path, branch and exact commit match, and recheck the original index
and status. For an explicitly selected existing branch, first verify its
commit and that it has no registered tree, then use `worktree add` without
`-b`. If occupied, reuse the exact tree with consent or choose a different
branch. Do not bypass Git's occupancy check.

On failure, inspect the directory, branch and registration and report what
remains. Retain uncertain files. Never use `-B`, `--force`,
`--ignore-other-worktrees`, `reset --hard`, `git clean` or recursive deletion
to make creation succeed. Do not change shared Git configuration. Inspect
tracked setup instructions before running anything; creating a directory is
not authorization to install dependencies or copy `.env` files. Keep task
dependencies separate. Submodule worktrees require extra care; report unsupported
layouts instead of automatically initializing, moving or deleting submodules.

## Verify actual execution

Use the new absolute directory explicitly in every file, terminal, test and
delegated operation. A shell's `cd` affects only that shell. A conversation
fork is Pi history, not a Git branch or worktree.

Read available operation documentation before project/session actions. In
Umeko, `projects.add` accepts `paths`, `workspace.set` opens `path`, and
`sessions.new` makes a draft in the current project; a persistent session ID
exists only after the first user-sent message. These actions do not retarget
the already-running caller. Offer to open the worktree as a project and start
a separate chat there; preserve the original chat, draft and attachments.

After that chat exists, verify its `workspace` with `sessions.get` or
`sessions.list`, and its execution root with `git rev-parse --show-toplevel`.
Check the terminal, file and Git Widget directories before use. If a tool
still targets the original directory, stop that path; use explicitly scoped
operations or let the user open the right project. Opening a project alone
does not prove the caller or all tools were rebound.

Verify a delegated target's existing directory and authorization before
dispatch. Do not silently retarget it. This Skill grants no new permissions.
Report repository, baseline SHA, branch, absolute path and verified session
ID (or "draft / not yet verified"). Retain this association in an existing
task record or handoff under the user's retention rules; do not create a
second registry, copy private chats or store credentials.

## Retain and reopen

Keep the directory and branch by default when work pauses, finishes, or the
chat closes or is archived. Report unfinished changes and the exact reopen
path. After restart, compare the retained association with `worktree list`,
the real directory, branch and session workspace before resuming. A missing
or replaced path is not the old worktree; do not recreate it and call it
recovered work.

For an externally moved tree or offline volume, retain files and explain
Git's `worktree repair` or `lock` options. Inspect first and obtain a specific
recovery request before changing registrations. Do not automatically prune,
unlock another task, move directories or delete branches.

## Remove only after a reviewed cleanup request

1. Identify the exact registered linked tree by canonical absolute path.
   Reject the main tree, the caller's current working directory, replaced
   symlinks, unregistered folders, locked trees or uncertain registrations.
2. Check associated sessions, queued/running tasks and terminal/background
   processes. Ask the user to stop or detach them explicitly; archival alone
   does not prove a tree is unused. If use cannot be verified, retain it.
   Do not close sessions or stop work as a cleanup side effect.
3. Inspect all results, including ignored files and submodules:

   ```sh
   git -C "$task_worktree" status --porcelain=v1 -z --untracked-files=all --ignored --ignore-submodules=none
   git -C "$task_worktree" rev-parse --show-toplevel
   git -C "$task_worktree" symbolic-ref --short HEAD
   git -C "$task_repo" worktree list --porcelain -z
   ```

   Tracked/staged changes, untracked or ignored files, submodules, active users
   and uncertain results block removal. Ignored `.env`, outputs or dependency
   files may be valuable even if ordinary status looks clean. Preserve them;
   do not use force to bypass this check.
4. Show the directory to remove, branch to retain, associations, checks and
   uncertainty. Get explicit confirmation for that directory. Recheck path
   identity, status and occupancy immediately before acting; stop if changed.
   This cooperative workflow is not an atomic defense against external
   concurrent filesystem changes.
5. Only for a confirmed, unused, clean linked tree, run from a different
   directory:

   ```sh
   git -C "$task_repo" worktree remove -- "$task_worktree"
   git -C "$task_repo" worktree list --porcelain -z
   ```

   Keep the branch and commits. Do not append branch deletion, prune, force,
   recursive filesystem deletion or merge. If Git refuses, preserve its
   reason and stop. Report removed only when both directory and registration
   are gone.

Consult the installed version's [Git manual](https://git-scm.com/docs/git-worktree)
when behavior differs. Distinguish checked, created, verified, retained and
removed states; do not report planned work as completed.
