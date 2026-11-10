# CodeArts provider plugin

CodeArts is an **unofficial, optional Provider SDK API v1 plugin** in
[`provider_dev/plugins/codearts`](../provider_dev/plugins/codearts/PROVIDER.md),
distributed separately from the desktop installer as a Provider ZIP Release
attachment for personal research, learning and exchange. It is not one of
Umeko's default providers. Use it at your own risk.

Requires **Umeko v0.6.1 or newer**. The plugin also checks the required SDK
capabilities at runtime.

Download the ZIP from the personally maintained
[CodeArts plugin Release](https://github.com/creegon2/umeko-codearts-provider/releases/tag/v0.1.0):
[umeko-codearts-provider-0.1.0.zip](https://github.com/creegon2/umeko-codearts-provider/releases/download/v0.1.0/umeko-codearts-provider-0.1.0.zip).
The [source and bilingual guide](https://github.com/creegon2/umeko-codearts-provider)
are maintained separately from Umeko.

In Umeko's model/account settings, **drag the ZIP onto the custom provider area**,
or use **+ → Import custom provider implementation** to select it.
Then activate the imported account with **Log in and refresh models**. Importing
the ZIP runs no plugin code; the plugin starts when you log in. If the official
China-site CLI is missing, the login action installs it and shows progress on the
card. Next, use the card to import the downloaded access-key CSV, or paste it into
the card's private field.
**Installed plugins → Uninstall plugin** removes the installed plugin version,
its accounts and credentials; removing an account alone keeps the plugin.

The card's **Open Huawei Cloud console** action opens the
[official console](https://console.huaweicloud.com/console/?locale=zh-cn):

**右上角用户名 → 我的凭证 → 访问密钥 → 新增访问密钥 → 下载访问密钥**

Each key can be downloaded only once, as described in the
[official access-key instructions](https://support.huaweicloud.com/usermanual-ca/ca_05_0003.html).
The plugin recognizes a newly downloaded CSV by its access-key headers, whatever
its filename. After the official CLI verifies the key pair and the SDK saves it
to protected storage, the plugin deletes the imported CSV; other files stay in
place. The card's private paste field accepts CSV, or AK followed by SK. The
field is cleared as soon as the host submits it to the plugin.

A Windows Credential Manager entry from the earlier preview is moved once into
SDK protected secrets and then deleted; if deletion fails, it is retried without
reading the old keys again. Existing protected credentials take precedence. Keys
are kept only in protected secrets, and the plugin does not read the CLI's own
stored browser-login credentials.

After connection, CLI model IDs appear in the normal model list. Python
`scripts/provider.py:create_provider` implements `events(model, messages, tools,
max_tokens, parameters)` through the normal SDK gateway; Pi and Umeko run their
usual tools and UI. The plugin uses only the Python standard library and the
host SDK. Optional `cliPath` selects an executable through the connection config.

The plugin starts its own loopback `codearts serve` with random Basic auth and
isolated config/data/work directories. Only that child process receives account
keys, and its native tools are disabled. The schema-only MCP broker pauses each
tool call, hands it to Pi, matches Pi's result by call ID on the next SDK
request and resumes the same server session. When schemas change, it waits for
the tool-cache refresh acknowledgment. Incremental text, thinking and usage become
OpenAI-compatible SDK chunks. A shared three-slot FIFO bounds requests across
conversations, subagents and accounts. Request cancellation, inactivity timeout
and provider close release owned sessions, brokers and processes.

Follow-ups reuse a server session. Divergent history creates a separate session
and replays the full text/tool history as role-labelled content, with images as
file parts; earlier thinking is omitted. The official prompt endpoint applies its
own output/inference limits, so SDK `max_tokens` and other inference parameters
are ignored. When the CLI reports no model limits, Umeko's default metadata
applies; set the context length in model settings to match your account.

The Python broker/event/process structure is adapted from
`@saccolabs/pi-claude-cli` 0.10.0, `pi-claude-cli` 0.3.1 and `claude-code-pi`. See the
[MIT notice](../provider_dev/plugins/codearts/licenses/pi-claude-cli-MIT.txt). HTTP/SSE follows the official
OpenCode server API, compared against OpenCode 1.2.27. CodeArts-specific strings
and protocol logic live in the plugin. The host supplies generic cards, protected
secrets, explicit plugin import lifecycle and request cancellation.

From a source checkout, build the optional ZIP separately:

```bash
python scripts/package-codearts-provider.py
```

This standard-library command uses the current Python interpreter to run the
SDK's `validate` and `pack` commands and writes
`build/optional-providers/umeko-codearts-provider-<version>.zip`. For another
output directory, pass `--output-dir <directory>`. The command only builds the
ZIP. The checks CI job uploads a development artifact for testing; users download
the Release ZIP. Version tags in the [personal plugin repository](https://github.com/creegon2/umeko-codearts-provider)
validate, test and pack with a pinned SDK, then publish the ZIP and its SHA-256
file on that repository's Release. The ZIP is kept outside
`build/provider-resources`, and the default-install list
`provider_dev/default-providers.json` is empty.
