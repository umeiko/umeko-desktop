# CI test locations

`Desktop packages` runs shared checks once on Linux: the Node list in
`.github/workflows/build.yml`, Python `unittest discover`, and the explicit
offscreen UI smoke list. The extra Python list after discovery was an exact
duplicate and has been removed.

After the usual setup, use those same commands locally with
`QT_QPA_PLATFORM=offscreen` and `QT_QUICK_BACKEND=software`. Linux checks also
use a private D-Bus session and an unlocked ephemeral keyring, as shown in the
workflow.
Discovery and the serial UI smoke list run concurrently inside that same
Linux job, with separate private D-Bus/keyring sessions. Both must succeed.
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
