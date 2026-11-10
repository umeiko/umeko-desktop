# Skills, extensions & MCP {#skills-extensions-mcp}

## Know which kind you need {#know-which-kind-you-need}

| Type | Purpose | Typical source |
| --- | --- | --- |
| Skill | Instructions and resources for a kind of task | A folder containing `SKILL.md`, a ZIP or `.skill` archive |
| Pi extension | Adds kernel tools, commands or behavior | npm, Git or a local extension |
| MCP server | Connects external tools and resources | A local process or remote server |
| Widget | A desktop page, app service or window | An Umeko Widget ZIP; see [Widgets](./widgets) |

Skill manager is enabled by default. Its question mark explains discovery: the prompt lists available names, descriptions and paths, while instructions and references are read as needed. Double-clicking attaches a folder to chat. Disabling the Widget globally or for a chat stops discovery and loading in that scope after the current turn; closing the panel only hides it. Type `/` for commands, enabled Widgets and Skills; `/s` through `/skills` expand Skills, with visible-name and Chinese pinyin matching.

## Manage Skill folders {#manage-skill-folders}

Open **Widgets → Skill manager** at the bottom-right of chat. It has Workspace and Global sections. Workspace Skills belong to the project; global Skills live in the selected Pi configuration directory and serve projects using it.

[![Workspace and Global Skill sections](/images/skills-en.png)](/images/skills-en.png)

*Manage complete packages in their scope. Drop or paste into the section where you want to import.*

- Single-click selects; double-click attaches the whole folder without sending.
- Right-click to preview, edit, reveal, copy, paste, rename or delete a package.
- Drop a Skill folder, ZIP or `.skill` onto the target section, or paste there, to import in place. A dialog opens only when import fails; on a name conflict the existing package is kept.
- Use the explicit Import entry to preview results or replace an existing package.

[![Whole-folder Skill context menu](/images/skill-menu-en.png)](/images/skill-menu-en.png)

*The context menu manages the whole Skill folder. Double-click attaches it without sending a message.*

Skills live in `<workspace>/.pi/skills/<name>/SKILL.md` and `<agentDir>/skills/<name>/SKILL.md`. The default `agentDir` is `~/.pi/agent`, separate from Umeko's user-data directory.

## Install and inspect extensions {#install-and-inspect-extensions}

**Widgets → Plugin management** shows installed Pi extensions, their descriptions, tools, homepages and source links, with update checks. Paste `pi install npm:package`, a Git source or a local path to install after host confirmation.

Extensions can be enabled globally, enabled for this conversation or temporarily disabled here. Change tool visibility after tasks and subagents finish; it applies on the next run. Hiding a tool only changes which tools the model sees; plugins and shell commands still run locally with your user permissions, so install only trusted extensions.

## Connect MCP {#connect-mcp}

Configure MCP under **Settings → Agent → Pi**. Paste a `pi mcp add …` command or named `mcpServers` JSON and select global or current-project scope. Enable the MCP extension first. Remote services may require their own credentials.

[![MCP configuration inside Pi settings](/images/mcp-en.png)](/images/mcp-en.png)

*Search for MCP in Pi settings to find server configuration and the add action.*

## Ask the agent to manage it {#ask-the-agent-to-manage-it}

> Inspect the extensions installed in this embedded Pi and explain their tools. Tell me the source before installing anything new.

The Pi kernel is embedded in the current desktop conversation. Agents use `run_pi_command` to run supported `pi install`, `pi mcp`, `/reload` or `/compact` operations on this instance.

Extensions and local MCP processes can execute code. Install trusted sources and read their documentation first. Configuration changes may require a refresh or the next task to take effect.
