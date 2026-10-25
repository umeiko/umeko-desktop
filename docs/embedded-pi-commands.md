# Embedded Pi commands

Umeko runs the full Pi kernel inside each desktop chat. Its model and credential transport comes from the desktop provider settings. The appended system prompt identifies this host and directs agents to `run_pi_command` instead of a system Pi installation.

The tool accepts `command` and an optional `scope` (`global` or `project`). Examples are `pi install npm:package`, `pi remove npm:package`, `pi list`, `pi mcp add tools --url https://example.com/mcp`, `/session`, `/reload`, `/compact keep the current task`, and commands registered by loaded extensions. `/help` returns the current session, workspace, configuration directory, and supported commands.

Extension administration invokes the current release's CLI with bundled Node and the active configuration directory. MCP and slash operations use the current native session. Commands are parsed as arguments without shell evaluation. Reload, compaction, and extension slash commands requested during a model turn run after the turn finishes. Their actual results return as hidden native Pi messages so the agent can continue the user's task with the updated tools. Stopping or steering a task cancels its pending commands; queued commands are never transferred to another session.

Settings → Agent → Pi → Extensions and tools → MCP includes **Add server**. Paste a `pi mcp add` command or named `mcpServers` JSON, then choose global or current project scope. The selected scope determines the native `mcp.json` file. JSON additions preserve existing servers; native validation runs before changes are written.

Profile migration recomputes path-derived project IDs and preserves the active project reference. Startup also merges duplicate records for the same canonical path while retaining project names and pins. Chat transcripts and the credential namespace remain unchanged.
