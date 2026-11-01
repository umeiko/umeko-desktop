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

The application directory and its parent must be writable. Allow room for downloads, extraction and backups. The previous installation remains beside the app as a `.previous-…` backup; user data lives outside the bundle. Source checkouts should update through Git.

## Data and backups {#data-and-backups}

| Edition | Default profile |
| --- | --- |
| Python / Qt | `~/.umeko/desktop` |
| C++ / Qt | `~/.umeko/desktop-cpp` |

`~` means your home directory. **Settings → Appearance → User data directory** opens the actual location; startup options or environment overrides may change it. Wait for tasks to finish and exit the app before backing up the profile and project files.

Account keys use OS-protected storage. Copying a profile to another machine does not guarantee working credentials; sign in or enter the keys again. Keep separate profiles for the two editions.
