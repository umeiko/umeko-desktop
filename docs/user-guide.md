# Umeko Desktop user guide

[Project home](../README.md) · [简体中文](../README.zh-CN.md) · [Downloads](https://github.com/umeiko/umeko-desktop/releases/latest)

A Qt Quick / QML desktop shell for the full [Pi Coding Agent](https://github.com/earendil-works/pi). The frontend runs independently of Pi; native tools, Skills, extensions, MCP, JSONL sessions, compaction, follow-up queues and steering power the agent.

## Requirements

- Python 3.10+, Node.js 22.19+, and npm for initial setup, npm extensions and kernel updates.
- Windows, macOS, or a Linux desktop with the required Qt platform libraries.
- An accessible login Keychain on macOS, or an unlocked Secret Service keyring / KWallet in the current Linux desktop D-Bus session. Windows uses DPAPI.

Pi is pinned to `@earendil-works/pi-coding-agent@1.3.0`. No public model supplier or external MCP server is preconfigured.

## Run from source

Windows, in PowerShell:

```powershell
./setup.ps1
./Start-Umeko.cmd
```

Linux and macOS:

```bash
chmod +x setup.sh build.sh Start-Umeko.sh Start-Umeko.command
./setup.sh
./Start-Umeko.sh
```

On macOS, `Start-Umeko.command` also opens from Finder. The launcher includes standard Homebrew locations when finding Node.js. Setup uses `.venv` and disables npm lifecycle scripts. Run setup on each target OS rather than copying a Windows virtual environment or dependency tree.

On Linux, install your distribution's Qt/X11/Wayland runtime libraries and desktop keyring first. A locked or unavailable keyring is reported instead of storing credentials in plain text.

## Build

Build on the target OS and CPU architecture:

```powershell
# Windows
./build.ps1
```

```bash
# Linux or macOS
./build.sh
```

Outputs: `dist/Umeko/Umeko.exe` (Windows), `dist/Umeko/Umeko` (Linux), and `dist/Umeko.app` (macOS). Keep the complete bundle directory. Node.js 22.23.3 and npm are bundled; no separate Node.js installation is needed. macOS builds use local ad-hoc signing; Developer ID signing and notarization are not automated.

Use the fixed `dist` output rather than creating a new preview folder for every build. Windows packaging refuses to overwrite a running target bundle. To reclaim older generated Windows builds, review `./scripts/clean-builds.ps1 -WhatIf`, then run `./scripts/clean-builds.ps1`. It skips running applications, linked directories and unrecognized folders, preserves the canonical `dist/Umeko` bundle, and retains a latest fallback preview if that bundle is missing. Source, profiles, projects and conversation files are outside its cleanup targets.

The release workflow checks frozen GUI rendering and the bundled Pi on Windows x64, Linux x64, macOS Apple Silicon and macOS Intel. Native keyring dialogs and IME composition still require interactive checks on their respective desktops.

### CI packages

[Desktop packages](https://github.com/umeiko/umeko-desktop/actions/workflows/build.yml) runs on pushes to `main`, pull requests, or **Run workflow**. It builds Windows x64, Linux x64, macOS Apple Silicon and macOS Intel on native runners using Python 3.12 and Node.js 22. The Windows job runs the regression suite and provider import interaction checks; every platform must render the packaged GUI, run its bundled search binaries and pass the bundled Pi self-test before upload.

Download stable builds from [Releases](https://github.com/umeiko/umeko-desktop/releases/latest). Development artifacts are available from completed CI runs for seven days: versioned ZIP (Windows/macOS) or tar.gz (Linux), SHA-256 checksum and verification details. Separate Provider SDK and developer Skill ZIPs are included. Release assets are published from successful CI packages; the build workflow itself only uploads artifacts. Node.js and npm are included in the release; destination computers do not need a separate Node.js installation. macOS packages are ad-hoc signed and are not notarized. GUI smoke checks do not replace interactive IME, keyring or real-provider checks.

### Offline search tools

Setup and build scripts fetch fd 10.3.0 and ripgrep 14.1.1 from their official upstream releases. Eight platform archives are pinned by SHA-256 in `scripts/search-tools.json`; downloads are cached in `runtime/downloads`. The matching binaries and their license files are copied into the embedded Pi's `bin` directory and added to its process PATH. File search therefore works without downloading executables during a conversation. Node.js and npm are bundled. Tool commands still use the operating system shell.

## About and application updates

**Settings → About** shows the project repository, author, application version, build OS/architecture, build time, source commit and active Pi kernel version. **Copy project information** copies these public details. Application identity and the single version constant live in `app/project_info.py`; build scripts record provenance in the bundled `build-info.json`. Source runs are labelled separately from packaged builds.

**Check for updates** explicitly queries this project's latest stable [GitHub Release](https://github.com/umeiko/umeko-desktop/releases). Opening settings makes no update request. Checks run in the background independently of chats and never use account or supplier credentials. The UI distinguishes a new version, the current release, a newer development build, no published release and a failed/rate-limited request. **Go to download** opens the project's release page to choose the appropriate platform package; it does not replace a running application or update the Pi kernel.

## Fcitx5 on Linux

Umeko bundles an Fcitx5 input plugin built from pinned sources against the same Qt as PySide. It uses its own plugin and Qt libraries, without changing system Qt or silently switching to an inactive IBus frontend. Native Wayland input and explicit IME choices are preserved. Fcitx5 and a Chinese engine must already be running in the same desktop session. See the [build and verification guide](linux-ime-fcitx5.md).

Override the per-application choice if needed:

```bash
UMEKO_QT_IM_MODULE=ibus ./Start-Umeko.sh
UMEKO_QT_IM_MODULE=fcitx ./Start-Umeko.sh
# An empty override uses Qt's platform default.
UMEKO_QT_IM_MODULE= ./Start-Umeko.sh
```

No global IME settings or system Qt plugins are modified. See the official [Fcitx setup guide](https://fcitx-im.org/wiki/Setup_Fcitx_5) and [Wayland guide](https://fcitx-im.org/wiki/Using_Fcitx_5_on_Wayland/en).

## Projects and conversations

- Drag any window edge or corner to resize. Corners have larger diagonal resize targets and direction cursors; maximized and fullscreen windows leave those targets inactive. Resizing uses the operating system's native window operation.
- Drop a directory onto the sidebar to create or reopen its project. Projects open a blank entry; conversations open their saved history.
- Drag the sidebar's right edge to adjust its width. The header's sidebar button or **Ctrl+B** collapses and restores it. Width and collapsed state survive restarts; smaller windows temporarily limit the visible width to preserve space for the conversation and settings, without forgetting your preferred size. Dragging updates the layout immediately and saves only when released.
- Conversations run independently. An eight-entry LRU cache retains recent Pi processes; running processes are never evicted. Native history appears before a cold kernel finishes loading.
- If a saved conversation references a removed provider or model, reopening it uses the current available selection (or the first available model). With no configured models, history remains readable. Failed kernel initialization is discarded before retrying, so later messages receive the full connection configuration. Existing transcript entries are preserved.
- Spinners mark running work; green dots mark completed, unread conversations. Drafts, attachments and reading positions are retained per conversation.
- A small ring beside the model selector shows the current conversation's context usage from Pi's native statistics. Hover for the estimated token count and window size; unavailable or post-compaction statistics remain explicitly unknown until Pi updates them.
- Right-click to rename, pin, archive, fork, export or remove items. Removing a project from the sidebar never deletes its directory or conversation files.
- The composer folder button opens the current conversation directory in the file manager. It does not change project membership.
- Drag files and directories into the composer, or paste text, images and copied files.
- Sent attachments appear as compact filename tags inside the user bubble, alongside the text. File paths and the tool-reading note remain available to Pi without being printed in the bubble. Existing native history uses the same display, including after reopening a session; filenames remain selectable and copyable with the conversation.
- Scroll with the wheel, touchpad or scrollbar. Browsing older output pauses automatic following; reaching the bottom resumes it. Mouse dragging selects text instead of panning.
- Select across prose, code blocks and messages. Drag near a viewport edge to scroll while selecting. Every code block also has a copy button.
- User messages appear in compact bubbles on the right. Fenced code supports syntax colors for common programming languages in light, dark and Yanami themes; coloring never rewrites copied text.
- The latest assistant reply ends with a 56 px transparent pixel-art Yanami mascot, hidden during generation. It is a static, cached local image with no pointer handling or animation. Its [generation prompt and provenance](../app/icons/yanami-pixel.provenance.json) are included with the asset.
- Assistant progress stays in order under one reply. Command batches show compact collapsible summaries with failure counts; expand a batch, then an individual operation to inspect its arguments and result. Click file names to copy absolute paths. Expanded folds stay open during streaming updates.
- Native reasoning, when returned by the configured model, appears in a separate collapsed “Thinking process” section. Live output and saved sessions use the same presentation; no reasoning is synthesized. Native transcripts remain unchanged.
- Light, dark and Yanami sea-salt blue themes are available. The Yanami theme uses a faint full-area watermark. Empty conversations randomly select from twelve transparent portraits and twelve greetings.
- Settings tabs share one moving highlight. A frame-driven PID controller follows both its position and width; rapid retargeting preserves velocity instead of restarting a transition. Bounded acceleration, damped overshoot and anti-windup keep the response controlled. The controller stops when settled and snaps to the selected tab when the settings page is hidden or reopened.
- The welcome mascot responds to a click with a squash-and-bounce animation and a temporary greeting. Drag it to tilt and stretch, then release to spring back; a long press or three quick taps reveal a small cookie surprise. Keyboard focus supports Space/Enter. Interactions stay local, preserve drafts, and reset when switching conversations or leaving the welcome page. Animations run only in response to interaction and stop when hidden.

Syntax coloring waits for a 180 ms pause in code changes and uses one background worker, at most eight distinct pending blocks, and a weighted 4 MiB / 64-entry cache. Theme changes reuse tokens, and unchanged code documents survive prose streaming. Limits are 48,000 UTF-16 positions, 1,000 lines, 2,000 characters per line and 12,000 colored ranges per block, with a best-effort 150 ms tokenization budget. Oversized or unknown-language blocks retain plain text and full copying. These limits bound coloring work; Qt still lays out the displayed text.

## Pi capabilities

All eight native tools are enabled: `read`, `bash`, `powershell`, `edit`, `write`, `grep`, `find`, `ls`. `codemode`, `tool_search`, and directly callable extension tools are enabled too. Host executables are still required; using PowerShell on Unix requires PowerShell to be installed.

Skills, extensions, templates and commands load from the configured Pi agent directory and project `.pi` resources. Settings accepts additional Skill/extension paths. “View native capabilities” shows the actual registry, activation states and schemas. Deferred tools retain native discovery; explicitly hidden or disabled tools remain unavailable. New sessions, resume, fork and reload preserve this behavior without overwriting Pi settings files.

Extension confirmation, selection and input dialogs are supported. Custom terminal components still require Pi's terminal UI. Extensions cannot register an additional model supplier behind the application's configuration. Kernel updates verify a candidate before switching; failures retain the existing kernel.

### Extension management and native terminal

Open **Settings → Agent** and select the **Pi** card to enter its configuration. Native capabilities, extensions, MCP, runtime settings, updates and recovery are collected here. There is no separate Pi kernel tab.

**Tools and resources → View tools** opens a settings page with category navigation for native tools, MCP tools, extension tools, Skills, prompt templates and commands. Search names, descriptions and sources, and expand an entry to inspect its description, source and parameter schema. Tool categories and direct/on-demand/hidden status come from the current native registry, including extension overrides of built-in names. Long lists render only visible entries; schemas are formatted when expanded. While a task is running, this page shows its loaded capabilities; configuration changes apply after the task finishes.

**MCP** has its own configuration card alongside **Pi extensions**. Its controls are disabled unless the native `builtin:mcp` extension is enabled; disabling it retains both saved configuration and the open editor draft. Re-enable it in **Pi extensions** to configure servers again.

**Install extension** opens an in-app installation dialog. Paste a command such as `pi install npm:billion-context`, or enter an npm/Git/local source directly. Choose **Global** for the selected Pi profile or **Project** for the current project's `.pi/settings.json`; pasted `--local` / `-l` also selects project scope. Only one package source and the optional local flag are accepted. The app invokes the embedded version's CLI directly with an argument list, without a shell or a globally installed Pi. Installation runs in the background, reports its result in the dialog and refreshes the list; close it to let installation continue. An installation times out after three minutes. **View online extensions** opens the official [Pi package catalog](https://pi.dev/packages).

The extension list includes native built-ins, personal/project extensions, installed package resources and disabled entries, so a disabled extension can be enabled again. Changes use Pi's own scoped settings and resource filters, shared with `pi config`; desktop extra paths are imported into native settings once. Scanning reads installed resources without executing extension factories, installing missing packages or contacting model services.

Changing an extension retires idle cached kernels; running conversations finish with the extensions they already loaded. **Refresh** also applies changes made in a management terminal. Simply viewing the list preserves cached conversations. Session resources retain Pi's personal/project scopes; desktop generation and compaction overrides remain in memory.

In **Settings → Agent → Pi → Management and recovery**, **Manage Pi in terminal** opens a local terminal and immediately runs the embedded version's native `pi config`. Exit configuration to return to the shell, where a session-local `pi` function supports native commands such as `pi install npm:<package>`, `pi list`, `pi remove <source>` and `pi config --local`. It invokes the bundled CLI entry with Node directly, never a globally installed Pi or `npx`. Windows uses PowerShell; macOS uses Terminal; Linux uses an available terminal emulator. Node and the terminal must be installed on the host.

The first launch prepares a private runtime copy under the app's data directory. This protects the factory baseline if native `pi update` changes the console copy. The terminal shares the selected Pi agent directory, project directory and native session storage with the desktop; recovery mode starts it in a clean management directory. The initial configuration command runs offline; subsequent explicit installation commands use normal native Pi behavior. Native CLI model/auth configuration is independent of the desktop's supplier gateway; desktop account passwords, supplier keys and private gateway tokens are never written into shell scripts. Close and reopen an existing terminal after changing the desktop's Pi directory or restoring the kernel.

### Factory recovery

**Restore factory kernel** confirms its scope before running and waits for all conversations to be idle. It backs up the previous agent settings, personal/project Pi settings files and active kernel pointer under `pi-backups/`, verifies a fresh copy of the application's bundled kernel, and switches to a new personal Pi directory with **Recovery mode** enabled. Projects, chat transcripts, supplier/account settings and proxy keys are retained; original Pi directories and extension files are not deleted or modified. **Open configuration backup** remains available after restarting the app.

Recovery mode skips third-party extensions, Skills, prompt templates, themes and project context files while retaining the native built-in tools. It also skips project MCP settings. Turn it off to investigate and re-enable resources gradually; the original personal directory can be selected again in Agent settings. A damaged active-kernel pointer falls back to the bundled version so the recovery UI remains accessible. Backups and previous console/runtime copies are kept locally for manual review.

Automatic context compaction follows Pi's native timing, summary generation and retention settings. Its enable/disable switch is in Agent settings; the chat footer has no manual compaction action.

### Model context windows

Each model in the provider editor and model mapping page has a **Context length** field. Automatic mode suggests a token limit from the upstream model ID, independently of its display alias. A capacity suffix takes priority: `k3` / `kimi-k3` suggests 1,048,576 tokens, while `k3-256` / `k3-256k` suggests 262,144. Unrecognized names use the previous 128,000-token default.

Type an integer token count or `256K` / `1M` to override it (`K = 1024`, `M = 1048576`; allowed range 1,024–16,777,216). **Restore automatic** resumes name matching. Custom limits persist across restarts, alias edits and internal model refreshes. Saving retires idle cached kernels; the next load passes the effective limit to native Pi for usage statistics and automatic compaction. Editing a provider used by a running conversation remains blocked until that work finishes.

The small offline rule table also covers Kimi K2.5/K2.7, Kimi coding aliases, DeepSeek V4/V4.1 Flash/Pro, GPT-4.1/4o, Claude 4.5/4.6 and Gemini 2.5 Pro/Flash. Defaults were checked on 2026-10-20 against [Kimi model configuration](https://www.kimi.com/en/help/kimi-code/models), [DeepSeek model metadata](https://api-docs.deepseek.com/api/list-models/), [GPT-4.1 specifications](https://developers.openai.com/api/docs/models/gpt-4.1), [GPT-4o specifications](https://developers.openai.com/api/docs/models/gpt-4o), [Claude context windows](https://platform.claude.com/docs/en/build-with-claude/context-windows) and [Gemini 2.5 specifications](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash). These are name-based suggestions, not live capability detection: accounts and gateways may impose smaller limits. For example, some Kimi plans limit `k3` to 256K. Set a custom value to match the actual service allowance.

### Image input

The provider editor and model mapping page include a **Vision** checkbox for each model. Automatic mode matches the upstream model ID; it recognizes common Kimi K3/K2.5+ coding models, GPT-4o/4.1/5, Claude 3/4/5, Gemini 1.5/2/3, Qwen-VL and Qwen 3.5–3.8 families, GLM-4V/5.3-Flash, and DeepSeek's image-capable Flash IDs. Unknown names default to text only. Check or uncheck Vision to override the suggestion, or choose **Restore automatic**. Explicit choices survive provider edits, alias changes, internal discovery and restarts. Legacy entries without a choice start in automatic mode.

The choice is passed to Pi's actual model input modalities. With Vision enabled, image attachments, including clipboard screenshots and dragged images, travel as image content. OpenAI-compatible providers receive `text` / `image_url` content parts with an inline base64 data URL; Anthropic providers receive `text` / `image` parts with a base64 source. The configured supplier protocol remains unchanged. Without Vision, desktop image attachments fall back to ordinary file paths, with a brief notice; no image bytes are submitted. This also applies to follow-up and steering messages. The API proxy continues to reject unsupported image payloads, which do not provide a usable local file path.

This UI supports image understanding and text replies. Native audio/video input and image generation are not implemented. Pi can display local images and deliver compact file cards through [submit_to_chatbox](chatbox-media.md), independently of model Vision input. Models and gateways may expose fewer capabilities than a public name suggests; the checkbox should reflect the actual deployment. Rules were checked on 2026-10-20 against the [Kimi model table](https://www.kimi.com/en/help/kimi-code/models), [OpenAI image input guide](https://developers.openai.com/api/docs/guides/images-vision), [Claude image input examples](https://platform.claude.com/cookbook/multimodal-getting-started-with-vision), [Gemini image understanding](https://ai.google.dev/gemini-api/docs/image-understanding), [Qwen vision models](https://help.aliyun.com/zh/model-studio/vision-model/), [Z.ai's model catalog](https://huggingface.co/zai-org/models) and [DeepSeek vision guide](https://api-docs.deepseek.com/guides/vision/).

### Custom account providers

**Settings → Accounts & Providers → +** opens **Import custom provider implementation**. Drag a trusted Provider ZIP into the highlighted import area or click to select it; there is no permanent internal-account panel. Imported providers render their own login fields and available models on this page. **Log in and refresh models** signs in and discovers models; **Model settings** edits aliases, context length and vision without navigating to API Proxy Service. API model mappings remain under that service's settings.

The import dialog also exports **umeko-provider-sdk** and a **develop-umeko-provider Skill** for your AI assistant. The public SDK defines login, model discovery, inference streams, protected secrets and configuration. See [Provider development](../provider_dev/README.md) for the contract, offline example, dependency layout and validation/pack commands. Run `python scripts/build-provider-resources.py` before exporting resources from a source checkout; both platform build scripts bundle them automatically.

Providers are trusted Python implementations, not sandboxed extensions. Validation and import execute no provider code. Implementations activate only on login, refresh or inference; credentials and sessions are isolated per account and protected by DPAPI or the OS keyring. A separate private deployment ZIP can contain enterprise login logic and non-secret connection presets. No enterprise login implementation or private endpoint is built into the public application, SDK or developer Skill. Legacy conversation files are preserved; previously built-in account connections must be reconnected through an imported provider.

### MCP

Paste JSON into either scope:

- Global: `mcp.json` in the Pi agent directory, default `~/.pi/agent`.
- Project: `<project>/.pi/mcp.json`; same-name project entries override global entries.

Native Pi validates JSON before saving. Stdio and Streamable HTTP, `${NAME}` environment references, and native `codemode`, `deferred`, `direct` exposure modes are supported.

```json
{
  "mcpServers": {
    "local-docs": {
      "command": "python3",
      "args": ["/absolute/path/to/mcp_server.py"]
    }
  }
}
```

### Sending and steering

| Action | Shortcut |
| --- | --- |
| Send while idle; add a follow-up while running | Enter |
| New line | Shift+Enter |
| Steer with the draft; promote pending messages when the draft is empty | Ctrl+S |
| New conversation | Ctrl+N |
| Settings | Ctrl+, |
| Collapse or restore the sidebar | Ctrl+B |

Loading disables Send. Stopping is a separate action affecting only the current conversation; queued text returns to the editor. Follow-ups never implicitly stop a running task.

## Suppliers and API proxy service

Configure suppliers, keys and multiple models in Settings. The composer switches supplier/model; aliases map user-facing names to upstream identifiers. Pi model requests use an authenticated private loopback gateway to explicitly configured suppliers. Built-in public catalogs, inherited model credentials and supplier redirects are disabled. Configured MCP HTTP endpoints are separately permitted. This is not an OS sandbox: shell tools and child processes retain the launching user's permissions.

**Settings → API proxy service** contains the listener settings, connection addresses, API key management and model mappings. Model mappings no longer have a separate settings tab; their aliases remain available to both chat and API clients.

The proxy defaults to `127.0.0.1:8787` and starts only when requested. Configure its port, enable OpenAI and/or Anthropic, create at least one enabled key, and choose **Start service**. Closing the app stops the proxy; reopening does not start it automatically. Saving a running listener applies protocol changes immediately and rebinds when the port or access scope changes. If binding fails, the previous settings and listener are restored when possible; otherwise the UI reports that the service stopped.

Enable **Allow LAN access** to bind all IPv4 interfaces (`0.0.0.0`). Other devices can use one of the enumerated interface addresses; copy its OpenAI or Anthropic base URL from **Connection addresses**. Enumeration is local and makes no discovery requests. Switching back to local-only closes the LAN listener. Pi's private gateway always remains on loopback with its own unrelated, temporary credential. The proxy uses HTTP, so use LAN access on a trusted network; the app does not change firewall or router settings. Cross-origin browser requests are allowed from loopback, and additionally private IP origins when LAN mode is enabled; API authentication is still required.

### API keys

The table shows a stable API ID, masked key, name, creation time, last activity, status and actions. Last activity means the most recent successful authentication, including requests to the model list; it updates within about two seconds while the app is running and is saved on normal exit. Narrow windows expose a horizontal table scrollbar.

- **New API key** creates a named key. Leave the value empty for automatic generation, choose **Generate key**, or enter a custom 16–256-character value using ASCII letters, digits, `.`, `_`, `~` and `-`. Names and key values must be unique; up to 100 entries are supported.
- Generated keys use 32 cryptographically random bytes. The complete key appears only in the creation/replacement dialog, with a copy action. The saved profile contains a SHA-256 verifier and masked suffix, never a recoverable copy of the proxy key. Keep your copy; lost keys must be replaced.
- **Edit** can rename a key while leaving its value empty, or replace its credential. Replacements keep the same API ID and creation time and invalidate the previous value.
- **Disable/Enable** temporarily changes access; **Revoke** removes a key after confirmation. Changes apply to new requests, including those on existing keep-alive connections, without restarting the proxy or interrupting already accepted requests. With no enabled keys, authentication rejects every request and a stopped proxy cannot start.
- Existing profiles migrate their former single proxy key into a default named entry without changing the credential. That entry can subsequently be renamed, replaced, disabled or revoked. Restarting never recreates removed keys.

| Protocol | Endpoint | Authentication |
| --- | --- | --- |
| OpenAI | `POST /v1/chat/completions` | Bearer key |
| Anthropic | `POST /v1/messages` | `x-api-key` |
| Models | `GET /v1/models` | Bearer key or `x-api-key` |

Use a configured model alias. Streaming, tool calls and image messages are supported. Responses API and token-count endpoints are not implemented.

Private provider packages, profiles and protocol notes stay in Git-ignored `.private/` and are excluded from application bundles. Account protocols are implemented through the public Provider SDK.

See [preferences and upgrades](preferences-and-upgrades.md) for automatic profile migration, per-provider proxy settings, request-error diagnostics and Chinese/English text-size preferences.

## Local data

| Platform | Default directory |
| --- | --- |
| Windows | `~/.umeko/desktop` |
| macOS | `~/.umeko/desktop` |
| Linux | `~/.umeko/desktop` |

`UMEKO_DATA_DIR` overrides the location. Account and supplier credentials use Windows DPAPI or the macOS/Linux system keyring; Unix settings contain opaque keyring references. Proxy keys use the one-way verifiers described above. Re-enter account and supplier credentials after migrating operating systems. Conversation JSONL and attachments are local, unencrypted files and are not automatically synchronized. Interface JSON is an index; native Pi JSONL is the source of truth.

## Validation

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
.venv/bin/python tests/ui_smoke.py
.venv/bin/python tests/chat_interaction_smoke.py
.venv/bin/python tests/api_proxy_ui_smoke.py
.venv/bin/python tests/sidebar_ui_smoke.py
.venv/bin/python tests/pi_management_ui_smoke.py
```

On Windows use `.venv/Scripts/python.exe`. Fixtures use temporary directories and local services, without real internal endpoints or external models. Native Fcitx5 composition, system keyring dialogs and packaged Unix applications require platform-level checks.

### Conversation and settings interaction

**Enter** during a run queues a follow-up. Ordinary follow-ups start in order when the current run finishes. Click a queued row to edit it, use its trash button to remove it, or choose **Steer** to interrupt the active model/tool execution and insert that message as a normal user turn immediately. **Ctrl+S** sends the editor text this way; with an empty editor it sends the oldest queued message, keeping the remaining follow-ups in order.

Hover a conversation message to reveal its recorded time and copy action. Double-click selects a word; triple-click selects a paragraph. Model selection and sidebar highlights use continuous PID motion.

**Settings → Agent → Pi** groups configuration into two levels. Search opens matching sections without discarding their collapsed state or unsaved input. Inline editors, the API Key table, tool catalog and release notes follow the page wheel until clicked; click outside to return to page scrolling. Help popups stay open for 3 seconds after leaving, or indefinitely while their text is selected; click outside to dismiss them.

For macOS, open the matching DMG, drag Umeko into Applications, eject the image and open the installed app. API proxy model aliases are grouped by provider account; the connection panel automatically displays copyable local or LAN Base URLs. See [DMG installation](macos-dmg.md) and [proxy menus](api-proxy-menus.md).
