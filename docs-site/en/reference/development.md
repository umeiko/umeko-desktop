# Development & SDKs {#development-sdks}

The user guide covers both editions; source code remains in separate repositories.

| Resource | Link |
| --- | --- |
| Python / Qt source | [umeko-desktop](https://github.com/umeiko/umeko-desktop) |
| C++ / Qt source and builds | [umeko-desktop-cpp](https://github.com/umeiko/umeko-desktop-cpp) |
| Provider SDK | [API, authentication, model discovery and inference](https://github.com/umeiko/umeko-desktop/blob/main/provider_dev/README.md) |
| Widget SDK | [Manifest, permissions, lifecycle and host interfaces](https://github.com/umeiko/umeko-desktop/blob/main/plugin-runtime/README.md) |
| Widget examples | [File tree, Git viewer, terminal and more](https://github.com/umeiko/umeko-desktop/tree/main/umeko-plugins) |
| Theme format | [JSON colors and creation prompt](https://github.com/umeiko/umeko-desktop/blob/main/docs/themes.md) |
| Character format | [Art, dialogue and ZIP limits](https://github.com/umeiko/umeko-desktop/blob/main/docs/characters.md) |
| submit tool | [Parameters, results and preview boundaries](https://github.com/umeiko/umeko-desktop/blob/main/docs/chatbox-media.md) |
| Embedded Pi commands | [run_pi_command behavior](https://github.com/umeiko/umeko-desktop/blob/main/docs/embedded-pi-commands.md) |

Some detailed SDK and format references are written in Chinese. This guide covers user workflows; the source references define exact interfaces.

## Run the Python edition from source {#run-the-python-edition-from-source}

Use Python 3.10+, Node.js 22.19+ and npm. Virtual environments are tied to their OS, so run the setup script on the system where you will run Umeko.

::: code-group
```bash [Linux / macOS]
bash setup.sh
bash Start-Umeko.sh
```
```powershell [Windows]
./setup.ps1
./Start-Umeko.cmd
```
:::

Build with `build.sh` or `build.ps1` on the target platform. See the [repository guide](https://github.com/umeiko/umeko-desktop/blob/main/docs/user-guide.md) for environments, tests and packaging. Use a separate profile for development and testing, apart from your everyday accounts and conversations.

## Choose the right plugin interface {#choose-the-right-plugin-interface}

- Account authentication, model discovery and inference: Provider SDK.
- Desktop pages, app services, windows and conversation communication: Widget SDK.
- Pi kernel tools, commands and task behavior: a Pi extension installed into the embedded Pi.

Use the SDKs and examples exported by your app version. Validate a package, then import it into a separate test environment. Plugins call public SDK interfaces only, and vendor-specific code lives in each vendor's own plugin.

When you need a new SDK capability, open an issue with a minimal reproduction and a general interface requirement.
