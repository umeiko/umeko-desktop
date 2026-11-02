# Widgets & desktop pets {#widgets-desktop-pets}

A Widget is an Umeko desktop plugin: a side page, a headless service or a constrained window. Widgets, Pi extensions and provider plugins have separate SDKs; their ZIPs are not interchangeable.

## Open and manage {#open-and-manage}

Open enabled plugins through Widgets at the bottom-right of chat. **Settings → Agent → Widgets** lets you import trusted ZIPs, configure or disable Widgets, and export the SDK with examples.

[![Widget management and desktop pet settings](/images/widgets-en.png)](/images/widgets-en.png)

*Choose a Widget on the left, inspect its state and settings on the right, or use Import ZIP / Export SDK at the top. The current UI labels this entry Widgets.*

Bundled Widgets include a file tree, Git viewer, terminal, Skill manager, Pi plugin manager and global agents. Check your build's plugin management page for the actual list.

Closing a page and disabling a plugin differ. Background behavior depends on the Widget: global agents keep working with their page closed and stop when disabled; closing Pi plugin manager cancels installations it started.

## Desktop pet {#desktop-pet}

The official pet loads hidden by default. Enable its display in its plugin settings to drag it, interact with it and use its context menu. Its character selection is independent of the main interface. It can import WebP, GIF, PNG and multi-action character ZIPs.

Pet display does not change agent permissions. Configure reminders and related features in the pet's own settings.

## Let an agent use a Widget {#let-an-agent-use-a-widget}

> Open the file tree and help me find this project's configuration directory.

Agents use `umeko_desktop` operations under `widgets.*` to read documentation, open pages or call public methods. A third-party Widget is limited to declared, user-approved capabilities; it does not automatically receive application keys or unrestricted backend access.

To build one, export the SDK and development Skill, then validate and package it using the [development guide](../reference/development). Check sources and permissions before installing third-party plugins.
