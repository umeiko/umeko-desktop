# CI test locations

`Desktop packages` runs the shared checks once on Linux: the Node list in
`.github/workflows/build.yml`, Python unit-test discovery, and the explicit
offscreen UI smoke list.

To run the same commands locally after the usual setup, set
`QT_QPA_PLATFORM=offscreen` and `QT_QUICK_BACKEND=software`. Linux checks also
use a private D-Bus session and an unlocked ephemeral keyring, as shown in the
workflow.

## Parallel UI smokes

Discovery and the UI smokes run concurrently inside the Linux job.
Discovery gets `(nproc + 1) / 2` workers and the UI list gets `nproc / 2`
(at least one each). Use `bash scripts/ci-ui-smokes.bash --jobs N` to set the UI
worker budget locally; the default is all detected cores. GNU `xargs -P`
schedules the scripts.

Each script gets its own private D-Bus session, ephemeral keyring, XDG directories,
profile and `PI_CODING_AGENT_DIR`. An explicitly configured agent directory takes
precedence; the environment also isolates bundled-skill installation when that
setting is empty. Unit tests and all smoke scripts must succeed.
Completed-script output is grouped under its filename, with status and duration.
Full logs are kept in the run's `build/ui-smokes.*` directory; a failure prints its
full log and an error naming the script. Scripts run once each, ordered longest
first by measured duration, and any failure fails the step. If a smoke needs a
machine-exclusive resource that cannot be isolated, add a one-line resource reason
here and run it after the pool.

## Parallel unit tests

`scripts/ci-unit-tests.py` uses the same `unittest.TestLoader.discover` start
directory (`tests`) and pattern (`test_*.py`), including unittest skips and
module/class fixtures. It passes those suites to pinned `unittest-parallel`
1.8.6, which uses the requested worker budget (all detected cores by default)
and prints per-test results and failure tracebacks. The job also prints `nproc`.
Only the Linux unit-test step installs this test dependency.
Some `load_tests` hooks create local wrapper classes; a small suite adapter
reloads each module through the same hook inside its worker.

Modules run in separate spawned processes, with process reuse disabled, because
Qt modules require different application types. Tests within each module run
sequentially. Isolate shared directories, profiles, files and listeners in
fixtures (temporary directories and OS-assigned ports).

A module that needs an exclusive resource can be added to `SERIAL_MODULES` in the
script with its discovery name (for example `test_device`) and a one-line reason.
Keep such modules small. The script runs them once, in a fresh process, after the
unit pool finishes; the UI pool may still be running at that time, so a
machine-exclusive case belongs after both pools. The list is currently empty.

For local runs install `unittest-parallel==1.8.6` and run the same script;
`--jobs 4`, `--pattern test_context_compaction.py` and `-k circle` narrow a
focused run. `--list` prints the discovered IDs without executing them.

## Writing stable UI tests

- Wait for the actual delegate, control and viewport geometry rather than fixed
  sleeps or frame budgets. The compaction fixture, for example, creates QML
  delegates synchronously and releases its fixture request explicitly.
- Re-map a control's position after mouse movement has processed queued Qt
  layout work, then click it.
- Keep the original timeouts, retry caps and assertions when changing readiness
  conditions.
- Runtime verification replaces changed adapter files atomically, so concurrent
  readers always see a complete helper.

## Native regressions

`python scripts/ci-native-tests.py` runs the actual-host regressions. The
lists live in that script: native paths, PTY/process behavior, filesystem
boundaries and Preview source launching on each OS, plus Windows-only
ConPTY, font, argv, socket and process-tree checks. Preview and terminal
module entrypoints use their isolated Qt/PTY workers.
The same script selects native Node process-tree, search-tool and installer
cases by exact test name, plus Windows PowerShell and macOS symlink cases.
The remaining shared Node cases run in the Linux checks.

## Which jobs run

For PRs, a small scope job runs ordinary `app/`, QML, `runtime/` source and
test changes on the Linux shared checks plus the Windows native regression job.
It adds a Windows package for dependency/build inputs and copied non-source
resources: runtime package manifests, requirements, PyInstaller specs, app
icons/data files, runtime documentation/data, skills/plugins/licenses,
build/setup scripts and packaging workflows. Unclassified paths also add a
package. Within `app/` and `runtime/`, known source suffixes use the light path;
module manifests such as `qmldir`, SVGs and new data files add a package. The
exact rules live in `scripts/ci-package-changes.py`. Packaging PRs run the
Windows native list inside the Windows package job.

Main pushes and ordinary manual dispatches build Windows x64. A manual
`all_platforms=true` dispatch also builds Linux x64, macOS Intel and
Apple Silicon for a stable release. Linux IME caret checks run in the shared
UI pool. Windows window and embedded-browser checks, macOS DMG tests, and
frozen application/Pi smokes run on their own platforms.

A newer PR run cancels the previous one. After a successful main CI, a final job
publishes its verified Windows package to the rolling `preview` prerelease. It
stages and verifies uploads before replacing the old Release/tag, skips stale
main builds, and keeps Preview as a prerelease (never Latest). Only main runs
publish Preview. A stable release needs a successful main desktop run with all
four native artifacts; use the full-platform dispatch for that run.
