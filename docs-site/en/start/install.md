# Install & update {#install-update}

## Choose an edition {#choose-an-edition}

| Edition | Download | Notes |
| --- | --- | --- |
| Python / Qt | [Stable Releases](https://github.com/umeiko/umeko-desktop/releases/latest) | The repository hosting this guide; a complete Qt desktop app |
| C++ / Qt | [Stable Releases](https://github.com/umeiko/umeko-desktop-cpp/releases/latest) | A native C++ host sharing the interface and most features |

Choose the asset matching your OS and CPU. The editions use different profile and credential formats, so install them in separate directories.

## Install on your platform {#install-on-your-platform}

| Platform | Steps |
| --- | --- |
| Windows x64 | Extract the complete ZIP into a writable directory and run `Umeko.exe` or `UmekoCpp.exe` from it. The program needs the other files in that directory. |
| macOS Apple Silicon / Intel | Open the matching DMG and drag the app into Applications, or use a complete ZIP. Packages are not notarized; first launch may need confirmation in system Privacy & Security settings. |
| Linux x64 | Extract the complete `tar.gz` and run `Umeko` or `UmekoCpp` in a graphical desktop. Keep its libraries, plugins and runtimes together. |

Linux needs desktop Qt platform dependencies and a working keyring. See [Troubleshooting](../troubleshooting#linux-input-methods) for input methods. Packaged apps include Pi, Node.js/npm, search binaries and the matching runtimes.

## Update inside the app {#update-inside-the-app}

1. Open **Settings → About**, check for a stable release and download it. The downloader follows the system proxy and checks the size and SHA-256.
2. After verification, click **Install new version** and confirm **Stop and install**. All agents stop, the main window closes, and the separate installer takes over.
3. Launch the new version when installation finishes, then restart any unfinished model tasks.

The application directory and its parent need to be writable, with room for downloads, extraction and backups. The previous installation stays beside the app as a `.previous-…` backup; user data lives outside the bundle. Source checkouts you maintain yourself update through Git.

## Release and Preview channels {#release-and-preview-channels}

The Python edition offers **Release** and **Preview** under **Settings → About → Update channel**. You can switch in packaged Windows, macOS and Linux apps and in source checkouts managed by this feature. Update ordinary source checkouts with Git; the app shows a hint there.

Release uses published stable packages. Preview runs the latest official `main`, including unreleased changes, and is less stable. Before the first switch, wait for tasks to finish, exit the app, and back up the profile described below and your project files. Both channels share one set of settings. Preview may write settings an older Release cannot read; restore your backup when you need the old configuration back.

Choosing Preview checks Git, Python 3.10+ with `venv`, Node.js 22.19+ with npm, the platform setup shell, at least 2 GiB of free space and access to the official repository. After you review the result and confirm, the app clones `https://github.com/umeiko/umeko-desktop.git` into a dedicated Preview source directory under the profile and runs its `setup.ps1` or `setup.sh`, showing progress with a cancel option. If preparation fails or you cancel, Umeko stays on Release; failed dependency setup can be retried.

After success, channel state is stored separately from `settings.json`. From then on, starting the retained Release application launches `main.py` directly with Preview's virtual-environment Python, bypassing the source launcher, which prefers a packaged `dist` build.

Preview's **Check for updates** fetches official commits and shows the current → target commit and commit summary. After confirmation, it fast-forwards to that target. If it finds local modifications, staged changes, untracked files that would be overwritten, an unexpected origin or diverged history, the update stops and keeps your work. Setup runs again when dependency inputs change; a failed setup stays pending for retry.

Returning to Release uses the retained original program and keeps the shared profile and settings, including settings Preview migrated. The Preview source is kept by default. You can choose to remove it: if Preview is running, removal happens after it exits and Release restarts. Removal covers only managed source and dependencies, keeps the source if it has local changes, and leaves profile data and settings in place.

If Preview cannot start, run the retained packaged executable with `--release-channel` to open Release directly, with settings and sessions intact. Examples: `Umeko.exe --release-channel` (Windows), `Umeko.app/Contents/MacOS/Umeko --release-channel` (macOS), or `./Umeko --release-channel` (Linux).

During preparation and updates, each network setting applies to its own tool. The app's npm registry, `.npmrc` and CA settings apply to npm; model-provider proxies apply to model requests. Git and pip use their own configuration, proxy and CA settings, and the updater's system proxy is passed to preparation. The app uses only the endpoints you configure and leaves global configuration unchanged.

## Data and backups {#data-and-backups}

| Edition | Default profile |
| --- | --- |
| Python / Qt | `~/.umeko/desktop` |
| C++ / Qt | `~/.umeko/desktop-cpp` |

`~` means your home directory. **Settings → Appearance → User data directory** opens the actual location; startup options or environment overrides can change it. Wait for tasks to finish and exit the app before backing up the profile and project files.

Account keys use OS-protected storage. After copying a profile to another machine, sign in or enter the keys again. Keep separate profiles for the two editions.
