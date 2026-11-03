# CI test locations

`Desktop packages` runs shared checks once on Linux: the Node list in
`.github/workflows/build.yml`, Python `unittest discover`, and the explicit
offscreen UI smoke list. The extra Python list after discovery was an exact
duplicate and has been removed.

After the usual setup, use those same commands locally with
`QT_QPA_PLATFORM=offscreen` and `QT_QUICK_BACKEND=software`. Linux checks also
use a private D-Bus session and an unlocked ephemeral keyring, as shown in the
workflow.

`python scripts/ci-native-tests.py` runs the actual-host regressions. The
lists live in that script: native paths, PTY/process behavior, filesystem
boundaries and Preview source launching on each OS, plus Windows-only
ConPTY, font, argv, socket and process-tree checks. Preview and terminal
module entrypoints preserve their existing isolated Qt/PTY workers.

For PRs, a small scope job skips native packaging when every changed file is
in `tests/`, `docs/` or `docs-site/`, or is the docs workflow/capture script.
Every other path builds all four packages, including unknown paths,
dependencies, application/QML files, skills, packaged Markdown and build
scripts. Tests-only PRs retain the dedicated Windows native regression job;
packaging PRs run that same native list in the Windows package job.

Main pushes and manual desktop dispatches always build Windows x64, Linux
x64, macOS Intel and Apple Silicon. Native IME caret checks, Windows window
and embedded-browser checks, macOS DMG tests, and frozen application/Pi
smokes remain on their original platforms. Shared tests are no longer
repeated in every package job; no test file is deleted.

The existing PR concurrency cancellation remains in place. Documentation
and release publishing workflows, their triggers and deployment conditions
are unchanged. Release publishing still requires a successful main desktop
run and its complete native artifacts; Preview still uses source main.
