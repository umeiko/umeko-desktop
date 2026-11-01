# FAQ {#faq}

## Does Umeko include a model account or free credits? {#does-umeko-include-a-model-account-or-free-credits}

No. Configure your own API or provider plugin. The provider determines access, subscription terms and charges.

## Is it the same instance as my system pi? {#is-it-the-same-instance-as-my-system-pi}

Umeko runs the full Pi kernel embedded in a desktop conversation, with model access injected from desktop provider settings. A global `pi` may use another version or configuration. Ask agents to use `run_pi_command`, and open management terminals from inside the app. See [Extensions & MCP](./guide/skills).

## Why does the model not know a tool? {#why-does-the-model-not-know-a-tool}

Check that its extension or Widget is installed and enabled, and that this conversation has not hidden the tool. Some capabilities require tool search or reading Widget documentation on demand. Wait for tasks to finish before refreshing or reloading; installing into an unrelated system Pi will not solve it.

## Why is the app still running after I close it? {#why-is-the-app-still-running-after-i-close-it}

Close hides the window in the tray. Right-click the tray avatar and choose **Exit** to quit. Background completions notify according to system settings. See [Conversations & notifications](./guide/conversations).

## Do historical file cards preserve the files? {#do-historical-file-cards-preserve-the-files}

Cards store references, not copies. Moving or deleting originals can break them. Keep important artifacts in a stable project directory and back them up. See [Artifact previews](./guide/artifacts).

## Why is there a separate webpage component on Linux? {#why-is-there-a-separate-webpage-component-on-linux}

The full Qt WebEngine is distributed separately to keep the base package smaller. Only webpages need it; Markdown, code and text previews work without it. See the [component flow](./guide/artifacts#linux-webpage-component).

## Why can I add several accounts from one provider? {#why-can-i-add-several-accounts-from-one-provider}

Each Key can have its own alias, region, models and proxy. `Kimi(Work)` and `Kimi(2)` are separate accounts and do not share an upstream quota simply because they appear together.

## Are Skills, plugins and MCP automatically sandboxed? {#are-skills-plugins-and-mcp-automatically-sandboxed}

No. Package validation and host permissions limit some operations, but Pi extensions, local MCP processes, providers and Widgets may execute local code. Install trusted sources only. Hiding a tool is not an OS-level sandbox.

## Where does my data go? {#where-does-my-data-go}

Configuration and native sessions are stored locally. Messages, tool results or file contents selected for inference are sent to your chosen provider. Third-party extensions may contact their own services. Local history does not mean entirely offline processing.

## Why does the documentation differ from my app? {#why-does-the-documentation-differ-from-my-app}

These docs follow main; stable Releases may lag behind. Check the version, commit and platform in **Settings → About**, then compare [Releases](https://github.com/umeiko/umeko-desktop/releases) or [C++ Releases](https://github.com/umeiko/umeko-desktop-cpp/releases). Note edition differences called out in the guide.
