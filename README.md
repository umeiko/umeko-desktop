<div align="center">

<img src="app/icons/yanami-pixel.png" alt="Umeko pixel Yanami logo" width="128">

# Umeko Desktop

**A desktop home for your coding agent.**

Your projects, your providers, the full Pi Coding Agent — with a little Yanami.

[English](README.md) · [简体中文](README.zh-CN.md)

[Download](#downloads) · [User guide](docs/user-guide.md) · [Provider SDK](provider_dev/README.md) · [Build status](https://github.com/umeiko/umeko-desktop/actions/workflows/build.yml)

[![Desktop packages](https://github.com/umeiko/umeko-desktop/actions/workflows/build.yml/badge.svg)](https://github.com/umeiko/umeko-desktop/actions/workflows/build.yml)
[![Release](https://img.shields.io/github/v/release/umeiko/umeko-desktop?color=4f74c8)](https://github.com/umeiko/umeko-desktop/releases/latest)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-2ea44f?logo=github)](https://github.com/umeiko/umeko-desktop/compare)
[![Issues welcome](https://img.shields.io/badge/Issues-welcome-4f74c8?logo=github)](https://github.com/umeiko/umeko-desktop/issues/new)

<a id="downloads"></a>

<!-- umeko-downloads:standard:start -->

**Download v0.6.0 · 点击下载**

[![Windows x64 ZIP](https://raw.githubusercontent.com/umeiko/umeko-desktop/main/docs/downloads/windows.svg)](https://github.com/umeiko/umeko-desktop/releases/download/v0.6.0/Umeko-0.6.0-windows-x64-736419c.zip)
[![macOS Apple Silicon DMG](https://raw.githubusercontent.com/umeiko/umeko-desktop/main/docs/downloads/macos-arm64.svg)](https://github.com/umeiko/umeko-desktop/releases/download/v0.6.0/Umeko-0.6.0-macos-arm64-736419c.dmg)
[![macOS Intel DMG](https://raw.githubusercontent.com/umeiko/umeko-desktop/main/docs/downloads/macos-x64.svg)](https://github.com/umeiko/umeko-desktop/releases/download/v0.6.0/Umeko-0.6.0-macos-x64-736419c.dmg)
[![Linux x64 TAR.GZ](https://raw.githubusercontent.com/umeiko/umeko-desktop/main/docs/downloads/linux.svg)](https://github.com/umeiko/umeko-desktop/releases/download/v0.6.0/Umeko-0.6.0-linux-x64-736419c.tar.gz)

<!-- umeko-downloads:standard:end -->

</div>

---

Umeko is a native desktop app for working with [Pi Coding Agent](https://github.com/earendil-works/pi). Keep conversations beside their project folders, follow the agent's work, and connect the model services you choose. Built with Python and Qt Quick for Windows, macOS and Linux.

![Project conversations in the pure white theme — English interface](docs/images/chat-white-en.png)

<details>
<summary>Explore the workflow · tools, subagents and custom providers</summary>

**See the work without losing the conversation.** Thinking and tool batches expand in place; click tool files to preview them, or right-click for file actions.

![Pure white theme with expanded thinking and grouped tool calls — English interface](docs/images/process-white-en.png)

**Work with a team of agents.** Open a subagent beside the main chat, queue follow-ups or interrupt its current task. Each conversation keeps its own draft and attachments.

![Subagent conversation with queued guidance — English interface](docs/images/subagents-white-en.png)

**Bring your own provider.** Drop in a ZIP, sign in and configure its models on the same page. Export the SDK and developer Skill directly from the import dialog.

![Custom provider import with ZIP drag-and-drop and SDK exports — English interface](docs/images/provider-white-en.png)

</details>

Screenshots show the actual app in the pure white theme with isolated demo data. No real accounts, credentials or model requests were used. The interface supports Simplified Chinese and English; its first-run language follows your system.

After a verified update download, the independent Yanami installer can stop all agents, install the new version and restart it. Closing the main window keeps agents running in the system tray; right-click the Yanami avatar to quit. [Updates and recovery](docs/updating.md).

## Why Umeko

| | What you get |
| --- | --- |
| **Pi, on your desktop** | Native file and shell tools, Skills, extensions, MCP, session branching and automatic context compaction. |
| **A workspace for each conversation** | Project folders, independent tasks, persistent history and a resizable sidebar. Queue follow-ups or steer running work with **Ctrl+S**. |
| **Readable agent work** | Foldable thinking and tool history, colored code blocks, inline attachments, stable scrolling and text selection across messages. |
| **Your model services** | OpenAI-compatible and Anthropic providers, per-model context limits and vision settings, plus importable account-provider plugins. |
| **An API for your other tools** | An optional OpenAI / Anthropic API proxy, model aliases, LAN access and named, revocable API keys. |
| **A little personality** | Light, dark and Yanami themes, twelve welcome portraits and greetings, and a pixel Yanami at the end of a reply. |

Pi can deliver images and compact file cards directly with [`submit_to_chatbox`](docs/chatbox-media.md). Click a file to open it; right-click to copy it, reveal it or attach it to chat again. Image previews support wheel zoom, drag to pan and click to close. Drag files anywhere in the chat to attach them and focus the input. Queued messages sit above the composer with editing and deletion; steering interrupts the active run and submits a normal message immediately. Hover a message for its timestamp and copy action. Double-click selects a word; triple-click selects a paragraph. Pi settings have searchable, nested sections and click-activated inline scrolling. Model selection, sidebar highlights and compact context menus use continuous PID motion.

On wide windows, hover either blank side margin to reveal a Yanami control and independently expand or collapse that side. Explicit output-length limits automatically continue up to five times, preserving completed tools and continuous code blocks.

Selecting a chat immediately shows an animated Yanami loading cover while cold history loads in the background. Rapid switching keeps only your latest choice; the conversation fades in after its layout is ready. File cards have themed hover details and clear menu states, and selected chat text offers a Copy / Select all context menu.

Providers and imported plugins stay in your home directory across upgrades. Configure a per-provider proxy from its gear, open complete redacted request diagnostics after failures, and adjust language and text size (50%–200%) in Appearance. See [preferences and upgrades](docs/preferences-and-upgrades.md).

## Get started

Pi web extensions can access the network. Configure company npm mirrors, an optional `.npmrc` and CA file under **Settings → Agent → Pi**; see [npm and extension networking](docs/npm-and-network.md).

The agent can find and install missing Pi tools from the npm package market, then continue the same task. Installation asks every time by default; the small wrench beside Send/Stop offers an opt-in fully automatic mode, install/use history, enable/disable and uninstall. See [package management](docs/package-market.md).

Use the [download buttons above](#downloads) for your platform, extract the package and open Umeko. Keep the complete application bundle together.

| Platform | Package | Launch |
| --- | --- | --- |
| Windows x64 | `windows-x64.zip` | `Umeko/Umeko.exe` |
| macOS Apple Silicon | `macos-arm64-*.dmg` or `.zip` | Drag `Umeko.app` to Applications |
| macOS Intel | `macos-x64-*.dmg` or `.zip` | Drag `Umeko.app` to Applications |
| Linux x64 | `linux-x64.tar.gz` | `Umeko/Umeko` |

Package names include the version and source commit. **Node.js, npm, Python, Qt, Pi and file-search binaries are bundled.** No separate Node.js or Python installation is required. Linux requires a graphical desktop and Qt runtime libraries; macOS packages are ad-hoc signed and are not notarized. See the [platform notes](docs/user-guide.md#requirements).

1. In **Settings → Accounts & Providers**, add a model API, or use **+** to import a trusted provider ZIP.
2. Open a project folder from the sidebar, or drag one into it.
3. Choose a model and start a conversation. While the agent is working, **Enter** queues your next message and **Ctrl+S** steers it.

No model account is included. Configure the services you want to use.

## Make it yours

- **Keep a desktop companion:** the official desktop-pet Widget is loaded by default with its window hidden. Enable the pet under **Settings → Agent → Plugin management → Desktop pet**. It follows task activity at a gentle pace, supports drag/click/right-click interactions, and accepts your own WebP/GIF/PNG or multi-action appearance ZIP. Agents manage it through the existing [Widget interface](runtime/umeko-docs/widget-plugins.md).
- **Extend the agent:** open **Settings → Agent → Pi** to manage extensions, MCP and tools, install a package such as `pi install npm:<package>`, or open the embedded Pi in a terminal.
- **Connect an account service:** build a provider ZIP with [umeko-provider-sdk](provider_dev/README.md). The [developer Skill](provider_dev/skills/develop-umeko-provider/SKILL.md) guides an AI through the same public interface; login implementations live in plugins.
- **Use Umeko as a gateway:** enable **Settings → API Proxy Service**, configure model aliases and create an API key for your other clients.

Provider ZIPs and Pi extensions run trusted local code. Account credentials use Windows DPAPI or the macOS/Linux system keyring. Conversations stay as local Pi JSONL files. See [local data](docs/user-guide.md#local-data) and [recovery](docs/user-guide.md#factory-recovery).

## Run from source

Clone this repository, then run the setup for your operating system. Development requires Python 3.10+, Node.js 22.19+ and npm.

**Windows · PowerShell**

```powershell
./setup.ps1
./Start-Umeko.cmd
```

**macOS / Linux**

```bash
bash setup.sh
bash Start-Umeko.sh
```

Build with `./build.ps1` on Windows or `bash build.sh` on macOS/Linux. Each platform is built on its native runner; CI checks packaged GUI startup, bundled search binaries, Pi and build provenance before uploading packages. The Windows job also runs the regression suite and provider import interaction checks.

[Build and platform details](docs/user-guide.md#build) · [Tests](docs/user-guide.md#validation) · [CI packages](https://github.com/umeiko/umeko-desktop/actions/workflows/build.yml)

## Credits

Created by [umeiko](https://github.com/umeiko). Powered by [Pi Coding Agent](https://github.com/earendil-works/pi), [Qt for Python](https://doc.qt.io/qtforpython-6/) and [Pygments](https://pygments.org/).

The pixel Yanami logo reuses the app's existing [fan-art asset and provenance](app/icons/yanami-pixel.provenance.json). This is an independent fan project, unaffiliated with the character's rights holders. Dependencies retain their upstream licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).

Custom color themes use portable JSON files. Import, update or delete them under **Settings → Appearance**, and copy a complete creation prompt from the same page. See the [theme format and example](docs/themes.md). Reply mascots react to taps, click combos and holds.

Common providers: **账号与供应商 → 添加常见供应商** offers Claude Code, Codex, Kimi Code, DeepSeek, GLM Coding Plan (including Z.ai) and MiniMax subscriptions (M Plan). GLM and MiniMax offer a site dropdown inside the Key form with just China and International; China is selected by default. Enter an API Key and optional account alias; endpoints and models are preconfigured. Multiple accounts receive distinct names and model mappings. See [Common provider accounts](docs/common-providers.md).

The Agent can manage this running desktop through **`umeko_desktop`**: providers, plugins, themes, settings, projects, chats and updates. Changes refresh the UI; operations that need idle tasks return a queued job. `/help` points to the bundled [Umeko management documentation](runtime/umeko-docs/README.md), loaded by topic instead of adding a large command list to every prompt. Umeko provider and theme settings are separate from Pi's terminal configuration.

Background task completion uses [native desktop notifications](docs/notifications.md) while the window is minimized or in the tray. Tasks lasting more than three minutes also notify while the window is visible. Click a notification to return to its conversation; permissions and sound follow system settings.

macOS releases include a [drag-to-Applications DMG](docs/macos-dmg.md) for Apple Silicon and Intel, alongside the ZIP used by automatic updates. API proxy aliases use [provider submenus and automatic Base URLs](docs/api-proxy-menus.md).
