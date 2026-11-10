# Projects & conversations {#projects-conversations}

## Organize by project {#organize-by-project}

A project in the sidebar points to a real working directory and can contain independent conversations. Drop a folder to add or reopen it. Right-click projects or conversations to rename, pin or archive them. Removing a project from the sidebar only takes it off the list; its files stay where they are.

Drag the sidebar edge to resize it, or use **Ctrl+B** to collapse and restore it. Switching chats shows a loading tip before native history arrives. Drafts, attachments and reading positions are retained separately.

## Understand task states {#understand-task-states}

A running indicator means the task is still working; a green unread mark indicates a background conversation finished and has not been viewed. Thinking, tool calls and replies appear separately. Expand their headings for details. The thinking section appears when the model returns reasoning.

[![Expanded thinking and tool records](/images/process-en.png)](/images/process-en.png)

*Expand Thinking process and the operations summary to inspect reasoning and tool results separately.*

Each tool record shows the result of that one operation; the final reply tells you whether the task is done. When a tool fails, inspect its result or the request details before retrying or changing the request.

## Queue and steer {#queue-and-steer}

| Action | Result |
| --- | --- |
| Enter while idle | Send a message |
| Enter while running | Queue a follow-up |
| Ctrl+S | Prioritize an intervention; with an empty input, promote the first queued message |
| Stop | Interrupt the task; files already written stay as they are |

Queued messages can be edited, deleted or promoted. Drop attachments into chat, or paste copied files, images and text. Reading older messages pauses automatic following; scroll to the bottom to resume it.

## Context and compaction {#context-and-compaction}

The ring beside the model shows context usage. Click it while idle to compact manually; automatic compaction follows Pi settings. Compaction replaces earlier content with a summary so the conversation can continue within the model's context window. Save important constraints in project files so every task can read them.

## Closing and notifications {#closing-and-notifications}

Closing the main window hides it in the system tray while tasks continue. Right-click the tray avatar and choose **Exit** to quit. On desktops without a tray, the app minimizes to the taskbar.

Tasks finishing while hidden or minimized send a system notification; foreground tasks lasting over three minutes also notify. Click a notification to return to its conversation. Sounds, Do Not Disturb and notification history follow Windows, macOS or Linux desktop settings.
