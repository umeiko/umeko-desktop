# CodeArts provider plugin

CodeArts is a public **Provider SDK API v1 package** in
[`provider_dev/bundled/codearts`](../provider_dev/bundled/codearts/PROVIDER.md).
Release builds pack it alongside the provider resources. It is installed on first
run and upgraded when a newer bundled version is available. **Settings → Accounts
& Providers → Installed plugins → Uninstall plugin** removes it and its accounts.
The saved uninstall choice survives restarts and application upgrades. The same
page's **+** menu offers one-click reinstallation.

Connect on the plugin's account card with **Log in and refresh models**. The
plugin installs the official China-site CLI if missing, reporting progress on the
card. Its **Open Huawei Cloud console** action opens the
[official console](https://console.huaweicloud.com/console/?locale=zh-cn):

**右上角用户名 → 我的凭证 → 访问密钥 → 新增访问密钥 → 下载访问密钥**

Each key can be downloaded only once, as described in the
[official access-key instructions](https://support.huaweicloud.com/usermanual-ca/ca_05_0003.html).
The plugin recognizes a newly downloaded CSV by its access-key headers, regardless
of filename. It preserves pre-existing and unrelated files. Only after the
official CLI verifies the pair and SDK protected storage succeeds does it delete
the imported download. The card's private paste field accepts CSV or AK followed
by SK. The input is cleared before the host submits it to the plugin.

The earlier preview's exact-profile Windows Credential Manager entry is migrated
once into SDK protected secrets. The old entry is deleted after the protected
write succeeds; failed deletion can be retried without rereading the old keys.
Existing protected credentials are authoritative. No settings field contains keys.
The plugin never reads the CLI's own stored browser-login credentials.

After connection, CLI model IDs appear in the normal model list. Python
`scripts/provider.py:create_provider` implements `events(model, messages, tools,
max_tokens, parameters)` through the normal SDK gateway; Pi and Umeko run their
usual tools and UI. The plugin uses only the Python standard library and the
host SDK, with no Node subprocess or third-party Python package dependency.
Optional `cliPath` selects an executable through the existing connection config.

The plugin starts its own loopback `codearts serve` with random Basic auth and
isolated config/data/work directories. Only that child receives account keys.
Native tools are disabled. The schema-only MCP broker parks each call before any
real execution, yields it to Pi, matches Pi's result by call ID on the next SDK
request and resumes the same server session. It waits for the tool-cache refresh
acknowledgment when schemas change. Incremental text, thinking and usage become
OpenAI-compatible SDK chunks. A shared three-slot FIFO bounds requests across
conversations, subagents and accounts. Request cancellation, inactivity timeout
and provider close release owned sessions, brokers and processes.

Follow-ups reuse a server session. Divergent history creates a separate session;
replay represents the full text/tool history as role-labelled content and images
as file parts. Previous thinking is not replayed. No history is truncated. The
official prompt endpoint selects its configured output/inference limits, so this
adapter does not forward SDK `max_tokens` or other inference parameters. Where
the CLI provides no model limits, Umeko's metadata defaults apply; they are not
measured context-window limits.

The Python broker/event/process structure is ported from this PR's earlier Node
bridge and CLI service, adapted from `@saccolabs/pi-claude-cli` 0.10.0,
`pi-claude-cli` 0.3.1 and `claude-code-pi`. See the
[MIT notice](../licenses/pi-claude-cli-MIT.txt). HTTP/SSE follows the official
OpenCode server API, with OpenCode 1.2.27 used only as a labelled comparison;
the fork's exact base remains unknown. CodeArts-specific strings and protocol
logic live in the plugin. The host supplies generic cards, protected secrets,
bundled-package lifecycle and request cancellation.

Start a source checkout with **Start-Umeko.cmd** after normal setup. Setup builds
the public provider resources; release packaging includes them automatically.
