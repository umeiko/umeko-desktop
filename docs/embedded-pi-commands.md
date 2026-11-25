# Embedded Pi commands

Umeko runs the full Pi kernel inside each desktop chat. Its model and credential transport comes from the desktop provider settings. Agents call `umeko_desktop` with operation `pi.run` to manage the Pi instance in the current chat.

Pass `command` and an optional `scope` (`global` or `project`) in `arguments`. Supported commands include package and MCP management, `/session`, `/reload`, `/compact`, and commands registered by loaded extensions. `/help` returns the current session, workspace, configuration directory, and supported commands.

```json
{"operation":"pi.run","arguments":{"command":"pi list"}}
```

Prefix a shell command with `!`, for example `{"operation":"pi.run","arguments":{"command":"!pwd"}}`. The current session's Bash tool runs it with the usual tool approval, workspace, and Windows sandbox settings.

Extension administration invokes the current release's CLI with bundled Node and the active configuration directory. MCP and slash operations use the current native session. Management commands are parsed as an argument list. Reload, compaction, and extension slash commands requested during a model turn run after the turn finishes. Their results return as hidden native Pi messages so the agent can continue the user's task with the updated tools. Stopping or steering a task cancels its pending commands; queued commands always stay with their own session.

Settings → Agent → Pi → Extensions and tools → MCP includes **Add server**. Paste a `pi mcp add` command or named `mcpServers` JSON, then choose global or current project scope. The selected scope determines the native `mcp.json` file. JSON additions preserve existing servers; native validation runs before changes are written.

Profile migration recomputes path-derived project IDs and preserves the active project reference. Startup also merges duplicate records for the same canonical path while retaining project names and pins. Chat transcripts and stored credentials are kept as they are.
