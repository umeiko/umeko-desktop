# Install & update {#install-update}

## Choose an edition {#choose-an-edition}

| Edition | Download | Notes |
| --- | --- | --- |
| Python / Qt | [Stable Releases](https://github.com/umeiko/umeko-desktop/releases/latest) | The repository hosting this guide; a complete Qt desktop app |
| C++ / Qt | [Stable Releases](https://github.com/umeiko/umeko-desktop-cpp/releases/latest) | A native C++ host sharing the interface and most features |

Choose the asset matching your OS and CPU. Keep the editions in separate installation directories; their profile and credential formats differ.

## Install on your platform {#install-on-your-platform}

| Platform | Steps |
| --- | --- |
| Windows x64 | Extract the complete ZIP into a writable directory and run `Umeko.exe` or `UmekoCpp.exe`. Keep the whole directory. |
| macOS Apple Silicon / Intel | Open the matching DMG and drag the app into Applications, or use a complete ZIP. Current packages are not notarized; first launch may need confirmation in system Privacy & Security settings. |
| Linux x64 | Extract the complete `tar.gz` and run `Umeko` or `UmekoCpp` in a graphical desktop. Keep its libraries, plugins and runtimes together. |

Linux still needs desktop Qt platform dependencies and a working keyring. See [Troubleshooting](../troubleshooting#linux-input-methods) for input methods. Packaged apps include Pi, Node.js/npm, search binaries and the appropriate runtimes.

## Update inside the app {#update-inside-the-app}

1. Open **Settings → About**, check for a stable release and download it. The downloader follows the system proxy and checks the size and SHA-256.
2. After verification, click **Install new version** and confirm **Stop and install**. All agents stop, the main window closes, and the separate installer takes over.
3. Launch the new version when installation finishes. Restart unfinished model tasks yourself.

The application directory and its parent must be writable. Allow room for downloads, extraction and backups. The previous installation remains beside the app as a `.previous-…` backup; user data lives outside the bundle. Independently maintained source checkouts keep their own Git update workflow.

## Release and Preview channels {#release-and-preview-channels}

The Python edition offers **Release** and **Preview** under **Settings → About → Update channel**. Switching is available in packaged Windows, macOS and Linux apps, and in source checkouts managed by this feature. Ordinary source checkouts explain that you should update them through your own Git workflow.

Release uses published stable packages. Preview runs the latest official `main` before release and may be unstable. Before the first switch, wait for tasks to finish, exit the app, and back up the actual profile described below and your project files. Both channels share settings. Older Releases are not guaranteed to understand newer settings; retaining the old program does not restore its previous configuration.

Choosing Preview checks Git, Python 3.10+ with `venv`, Node.js 22.19+ with npm, the platform setup shell, at least 2 GiB of free space and access to the official repository. Review the result and confirm before preparation. The app clones `https://github.com/umeiko/umeko-desktop.git` into a dedicated Preview source directory under the profile and runs its `setup.ps1` or `setup.sh`. Progress and cancellation are available. A failed or cancelled preparation retains Release; failed dependency setup can be retried.

After success, channel state is stored separately from `settings.json`. The next start through the retained Release application launches `main.py` directly with Preview's virtual environment Python. It does not use the source launcher, which may prefer an older `dist` bundle.

Preview's **Check for updates** fetches official commits and shows the current → target commit and commit summary. After confirmation, it fast-forwards only to the confirmed target. Local modifications, staged changes, untracked-file overwrite risks, an unexpected origin or diverged history stop the update without discarding your work. Setup runs again only when relevant dependency inputs change; a failed setup remains pending for retry.

Returning to Release uses the retained original program and preserves the shared profile and settings. Returning does not reverse settings migrations. Keep the source by default; if Preview is running, optional removal waits for it to exit and Release to restart. Removal affects only managed source and dependencies. Local changes prevent removal. Profile data and settings are retained.

If Preview cannot start, run the retained packaged executable with `--release-channel` to open Release directly, without deleting settings or sessions. Examples: `Umeko.exe --release-channel` (Windows), `Umeko.app/Contents/MacOS/Umeko --release-channel` (macOS), or `./Umeko --release-channel` (Linux).

Network settings have separate scopes. The app's npm registry, `.npmrc` and CA overrides apply only to npm; model-provider proxies do not configure Git cloning or pip installation. Git and pip use their own configuration, proxy and CA settings, with the updater's system proxy passed to preparation. The app writes no global configuration and does not silently replace a failing configured endpoint with a public fallback.

## Data and backups {#data-and-backups}

| Edition | Default profile |
| --- | --- |
| Python / Qt | `~/.umeko/desktop` |
| C++ / Qt | `~/.umeko/desktop-cpp` |

`~` means your home directory. **Settings → Appearance → User data directory** opens the actual location; startup options or environment overrides may change it. Wait for tasks to finish and exit the app before backing up the profile and project files.

Account keys use OS-protected storage. Copying a profile to another machine does not guarantee working credentials; sign in or enter the keys again. Keep separate profiles for the two editions.
