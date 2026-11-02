# Delegate to subagents {#delegate-to-subagents}

Ask the main agent to delegate independent parts of a task: review separate modules, check tests, or gather information, then combine their findings.

> Delegate to two subagents: one should review sign-in, the other error handling. Keep both read-only for now, then summarize their findings and recommendations.

## Follow their work {#follow-their-work}

Click a task card in the main chat or choose a running subagent from the top-right activity menu. Its side pane shows messages, thinking and tool calls. Closing the pane does not stop the task.

[![Subagent side pane and message queue](/images/subagents-en.png)](/images/subagents-en.png)

*Select a task card in the main chat to inspect its independent context. Follow-ups enter that subagent's own queue.*

Each pane has its own input, draft, attachments and queue. **Enter** queues a message; **Ctrl+S** prioritizes an intervention. Stop interrupts only that subagent. Historical tasks can continue if their native context files and configured models remain available.

## Session subagents versus global agents {#session-subagents-versus-global-agents}

| Type | Purpose |
| --- | --- |
| Session subagents | Helpers delegated by the main agent for the current task |
| Global agents Widget | Persistent coordinators with user-configured roles, models and conversation links |

Session delegation runs through the community package `@gotgenes/pi-subagents`; Umeko adapts its display and interaction. Current builds no longer impose a default limit of four. Explicit community-package concurrency settings still apply. More concurrent agents consume more model resources; use only what the task needs.

Open Global agents from Widgets at the bottom-right of chat. It retains up to 16 agents, with 4 running concurrently. Tasks can reach only conversations connected by the user in the agent bus. Closing its page keeps agents running; disabling the Widget stops them.

## Get better results {#get-better-results}

Give each helper a clear scope, expected output and file-editing policy. Concurrent edits to the same files can conflict. Assign independent areas and let the main agent perform final validation.
