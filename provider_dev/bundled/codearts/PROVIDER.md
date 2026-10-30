# CodeArts

This public Provider SDK API v1 package uses the official China-site CodeArts CLI.
It is bundled with Umeko, installed by default, and can be removed from Settings →
Accounts & Providers → Installed plugins. The plus button offers one-click
reinstallation. An explicit uninstall is remembered across application updates.

Click **Log in and refresh models** on its card. Existing credentials from the
earlier built-in preview are moved once into SDK protected storage; the old
Windows Credential Manager entry is deleted after the protected write succeeds.
Otherwise, open Huawei Cloud Console from the card:

右上角用户名 → 我的凭证 → 访问密钥 → 新增访问密钥 → 下载访问密钥

Each access key can be downloaded only once. The plugin watches new CSV files in
Downloads by their access-key headers, verifies the pair with the official CLI,
saves it in protected storage, then deletes that download. Existing and unrelated
files are kept. The private paste field accepts CSV or AK followed by SK.

Missing CLI installations use the complete official China installer. `cliPath`
in connection configuration can select an existing executable. There is no Node
runtime or third-party Python dependency inside this package.

Model requests use a private `codearts serve` process and a schema-only MCP
broker. Pi executes the tools; pending results continue the same CodeArts
session. Three slots bound concurrency. Text, thinking and usage travel through
the normal SDK gateway; timeout, cancellation and close release owned resources.
The context metadata and request-token defaults follow Umeko's existing defaults;
the plugin does not claim measured model limits.

Sources: the prior `runtime/codearts.mjs` bridge and `app/codearts_server.py` /
`app/codearts_account.py` implementation, adapted from @saccolabs/pi-claude-cli
0.10.0 (MIT attribution in `licenses/pi-claude-cli-MIT.txt`), pi-claude-cli and
claude-code-pi; official OpenCode 1.2.27 HTTP/SSE comparison; the public standalone
CodeArts fork's config/event behavior verified in the earlier real checks;
Provider SDK API v1 and Umeko's existing protected secrets and cards.
