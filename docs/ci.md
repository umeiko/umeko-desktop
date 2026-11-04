# CI test locations

`Desktop packages` runs shared checks once on Linux: the Node list in
`.github/workflows/build.yml`, Python unit-test discovery, and the explicit
offscreen UI smoke list. The extra Python list after discovery was an exact
duplicate and has been removed.

After the usual setup, use those same commands locally with
`QT_QPA_PLATFORM=offscreen` and `QT_QUICK_BACKEND=software`. Linux checks also
use a private D-Bus session and an unlocked ephemeral keyring, as shown in the
workflow.
Discovery runs first using all cores, followed by the same 43 UI smokes through
`bash scripts/ci-ui-smokes.bash --jobs "$(nproc)"` inside that same Linux job.
GNU `xargs -P` schedules scripts; no additional runner dependency is installed.
Each script gets its own private D-Bus session, ephemeral keyring, XDG directories,
profile and `PI_CODING_AGENT_DIR`. An explicitly configured agent directory still
takes precedence; the environment also isolates bundled-skill installation when
that setting is empty. Units and all smoke scripts must succeed.
Completed-script output is grouped under its filename, with status and duration.
Full logs are kept in the run's `build/ui-smokes.*` directory; failures print their
full log and an error naming the script. Other scripts finish without retries,
and any failure makes the step fail. There is currently no serial smoke tail.
If a smoke genuinely needs a machine-exclusive resource that cannot be isolated,
document its one-line resource reason here before adding it after the pool.
`scripts/ci-unit-tests.py` uses the same `unittest.TestLoader.discover` start
directory (`tests`) and pattern (`test_*.py`), including unittest skips and
module/class fixtures. It passes those suites to pinned `unittest-parallel`
1.8.6, which uses all detected CPU cores and prints per-test results and failure
tracebacks. The job prints `nproc` too. Only the Linux unit-test step installs
this test dependency; application requirements and other jobs are unchanged.
Some existing `load_tests` hooks create local wrapper classes. A small suite
adapter reloads each module through the same hook inside its worker instead
of trying to pickle those classes; the runner still owns all scheduling.

Modules run in separate spawned processes, with process reuse disabled: Qt
modules require different application types and cannot safely share one Qt
singleton. Tests within each module remain sequential. Shared directories,
profiles, files and listeners must be isolated in fixtures (temporary directories
and OS-assigned ports), rather than hidden behind serial execution. The character
export test builds provider downloads in its own temporary directory.

There are currently no suite-wide serial exceptions. If a module truly needs an
exclusive resource that cannot be isolated, add its discovery name (for example
`test_device`) and a one-line reason to `SERIAL_MODULES` in the script. Keep that
module small. The script removes it from the parallel group and runs it once,
in a fresh process, after the pool finishes; it never runs in both groups.
This exception is exclusive among unit tests; the UI pool starts after the unit
phase. Resources shared within either pool still need isolated fixtures.
For local runs install `unittest-parallel==1.8.6` and run the same script;
`--jobs 4`, `--pattern test_context_compaction.py` and `-k circle` can limit a
focused run. `--list` prints the discovered IDs without executing them.

The compaction offscreen fixture creates QML delegates synchronously instead of
depending on a rendered-frame incubation budget. Pi, provider requests and model
updates still run asynchronously. A fixture request is released explicitly by the
test (or teardown), and clicks wait for the actual control and viewport geometry.
Clicks remap that control after mouse movement processes queued Qt layout work.
Parallel execution also exposed an already-completed pet-import future replying
before its RPC token was registered. That response is now queued; the existing
RPC test covers both normal background completion and a completed future.

Runtime verification leaves identical prepared adapters untouched and replaces
changed files atomically, so concurrent readers cannot see a truncated helper.

`python scripts/ci-native-tests.py` runs the actual-host regressions. The
lists live in that script: native paths, PTY/process behavior, filesystem
boundaries and Preview source launching on each OS, plus Windows-only
ConPTY, font, argv, socket and process-tree checks. Preview and terminal
module entrypoints preserve their existing isolated Qt/PTY workers.
The same script selects native Node process-tree, search-tool and installer
cases by exact test name, plus Windows PowerShell and macOS symlink cases.
The remaining shared Node cases run only in Linux checks.

For PRs, a small scope job keeps ordinary `app/`, QML, `runtime/` source and
test changes on Linux shared checks plus the Windows native regression job.
It requests all four packages for dependency/build inputs and explicitly
copied non-source resources: runtime package manifests, requirements,
PyInstaller specs, app icons/data files, runtime documentation/data,
skills/plugins/licenses, build/setup scripts and packaging workflows.
Unclassified paths also request packages. The exact exceptions live in
`scripts/ci-package-changes.py`. Packaging PRs run the Windows native list
in the Windows package job instead of repeating it in a separate job.
Within `app/` and `runtime/`, only known source suffixes use the light path;
module manifests such as `qmldir`, SVGs and new data files still request packages.

Main pushes and manual desktop dispatches always build Windows x64, Linux
x64, macOS Intel and Apple Silicon. Native IME caret checks, Windows window
and embedded-browser checks, macOS DMG tests, and frozen application/Pi
smokes remain on their original platforms. Shared tests are no longer
repeated in every package job; no test file is deleted.

The existing PR concurrency cancellation remains in place. Documentation
and release publishing workflows, their triggers and deployment conditions
are unchanged. Release publishing still requires a successful main desktop
run and its complete native artifacts; Preview still uses source main.
