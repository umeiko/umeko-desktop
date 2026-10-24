# In-app updates

In **Settings → About**, check for a stable release and click **下载新版本**. Umeko keeps the upstream release checks and downloader: it selects the archive for the running operating system and CPU, saves it to **Downloads/Umeko**, and checks the exact byte count and GitHub asset SHA-256 digest. The action then changes to **安装新版本**; the sidebar update badge opens the same installation confirmation. A missing checksum or a failed check prevents installation. Downloading can be cancelled.

Click **安装新版本**, then **停止并安装**. This stops all agents, saves the existing history and settings, and closes the main application after the independent installer and its worker have reported that they are ready. Unfinished agent requests must be started again after updating. Cancelling the confirmation leaves all work running.

The installer shows a separate working Yanami pixel bust during installation, then a short-haired smiling thumbs-up bust on completion. It checks SHA-256 again, extracts the archive into a sibling staging directory, validates the version, OS, CPU and required runtime files, and replaces the whole portable application directory. Extraction rejects unsafe paths, escaping links and writes through symlinks. The old directory remains beside the installation as `<application-directory>.previous-<id>`. Replacement errors restore the old directory. If automatic restoration fails, the error identifies the backup location.

When installation completes, click **启动**. The installer starts the new executable and exits. A failed launch leaves the completion window open so it can be retried. The copied installer runtime is cleaned after the installer exits. Downloaded packages remain in Downloads/Umeko, and old-version backups remain for manual recovery. Failed jobs retain `job.json.log` in the application's `CacheLocation/updates/<id>` directory.

Updates require a writable portable application directory and parent directory. Source checkouts can check and download releases, but must update their source using Git. The installer does not elevate privileges or modify application data stored outside the bundle. Allow disk space for the downloaded archive, an independent copy of the existing app, the unpacked replacement and the retained old version.

## Architecture and packaging

The installer is an independent process started from a complete copy of the current application outside its installation directory. It uses the app's existing Qt libraries and the bundled Node.js; no separate Python installation is needed by the native edition, including minimal builds. `--install-update <job.json>` enters installer mode before any controller, agent, provider or API server is created.

Both editions share `runtime/update-engine.mjs`, `app/qml/Installer.qml` and `app/icons/yanami-installer.png`. The native host is `src/update.cpp`; the Python host is `app/update.py`. The parent records a committed handoff only after the helper emits readiness. Without that commit, or after cancellation, the worker cannot install even if the parent later exits. It waits up to two minutes for the parent, and a per-destination lock prevents concurrent replacement.

Keep the updater engine in release resources. Native packages use `UmekoCpp/...` (macOS: `UmekoCpp/UmekoCpp.app/...`); Python packages use `Umeko/...` (macOS: `Umeko.app/...`). Build metadata and the complete bundled Node.js must be present in replacement packages. The native standard and minimal editions keep their upstream update channels; the installer validates the edition as well as the release version. Minimal release tags may end in `-minimal`.

## Verification

Run `node --test tests/update-engine.test.mjs` in either repository. It covers archive selection, streamed download verification, checksum sidecars, ZIP/TAR installation, symlink preservation, unsafe paths, changed packages, wrong versions, missing runtime files, failed replacement rollback, helper isolation and cancelled/uncommitted handoffs.

Native: build with CMake and run `ctest --test-dir build --output-on-failure`; `native_update` runs the real installer QML with successful and rejected packages. Python: run `python -m unittest discover -s tests -p 'test_*.py'`, `python tests/about_ui_smoke.py` and `python tests/installer_ui_smoke.py`. Use the project environment and an isolated/offscreen desktop as described in the build guide. Cross-platform CI runs the engine and installer UI tests; each OS still needs a real packaged-app update check for its filesystem permissions, process locks and unsigned-app launch behavior.

## System tray

Closing the main window hides it in the system tray; agents, providers and the API proxy continue running. A Yanami avatar remains in the notification area, and a desktop notification explains that the app is still running. Click the avatar, click the notification, or choose **打开 Umeko** from its right-click menu to restore the window. Choose **退出** from that menu to stop agents, save state and exit. Explicit updater and operating-system quit requests still exit normally. The standalone installer has no tray behavior. On desktops without a system tray the close button minimizes to the taskbar so the running app remains accessible.
