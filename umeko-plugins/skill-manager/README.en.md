# Skill management

The Widget shows two collapsible sections: **Workspace** and **Global**. Each compact 26px row represents an entire Skill folder. Search names and descriptions without expanding its contents. There are no availability checkboxes, activation controls or create button.

A single click only positions the row. Double-click attaches the whole folder to the current composer, preserving its draft and without sending a message. Right-click to attach, preview, edit SKILL.md with its system-associated application, show in the file manager, copy the folder, copy its path, paste, rename or delete. Rename changes the folder name; edit its metadata through the editor or Agent.

Copy uses the native file clipboard. Paste imports straight into the selected section; drop a local Skill folder, ZIP or `.skill` archive onto its destination section. Neither opens the import page nor asks for another confirmation. Success refreshes the list in place, preserving search, folds and scroll position. Only failures open an in-pane popup. Invalid documents or same-name conflicts reject the batch before writing; existing folders are never overwritten and Skill scripts are not executed.

The **Import** button retains explicit scope selection and validation previews. Use it to skip or replace conflicting skills, with host-owned confirmation before writing. Rename, delete and replacement-import confirmations stay within the Widget. Filesystem operations stay inside the approved global/workspace Skill roots; deletion does not follow asset links. Discovery, response size and rendering have explicit limits and pagination.

Workspace Skills live at `<workspace>/.pi/skills/<name>/SKILL.md`; global Skills live at the configured `<agentDir>/skills/<name>/SKILL.md`. With no custom agentDir, Pi uses `~/.pi/agent`. The Agent can create and maintain these folders with its existing file tools. The queryable Agent guide explains the format and how to discover the current directory; no new Agent management tools are added. Other resource paths and npm packages remain under Pi's own management.

Keyboard: arrows to position, Enter to attach, F2 to rename, Delete to delete, Ctrl+C to copy, Ctrl+V to paste, Ctrl+F to search. Preview reuses Umeko's side document viewer. The entry and rows share this project's SVG zipper archive-box icon.
