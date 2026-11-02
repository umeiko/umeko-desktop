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

Some detailed SDK and format references are currently in Chinese. The bilingual guides explain user-facing workflows; source references remain authoritative for exact interfaces.

## Run the Python edition from source {#run-the-python-edition-from-source}

Use Python 3.10+, Node.js 22.19+ and npm. Install dependencies on the target OS rather than copying a virtual environment from another system.

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

Build with `build.sh` or `build.ps1` on the target platform. See the [repository guide](https://github.com/umeiko/umeko-desktop/blob/main/docs/user-guide.md) for environments, tests and packaging. Use isolated profiles for development and acceptance rather than everyday credentials and conversations.

## Choose the right plugin interface {#choose-the-right-plugin-interface}

- Account authentication, model discovery and inference: Provider SDK.
- Desktop pages, app services, windows and conversation communication: Widget SDK.
- Pi kernel tools, commands and task behavior: a Pi extension installed into the embedded Pi.

Prefer SDKs and examples exported by your app version. Validate a package before importing it into an isolated environment. Do not depend on private host Python modules or put vendor-specific implementations into a generic SDK.

When an SDK lacks a capability, provide a minimal reproduction and a general interface requirement so compatibility fixes can be tested independently.
