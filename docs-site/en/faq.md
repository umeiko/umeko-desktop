# FAQ {#faq}

## Does Umeko include a model account or free credits? {#does-umeko-include-a-model-account-or-free-credits}

Umeko connects to the API or provider plugin you configure; it comes without a model account or credits. The provider determines access, subscription terms and charges.

## Is it the same instance as my system pi? {#is-it-the-same-instance-as-my-system-pi}

Umeko runs the full Pi kernel embedded in the desktop conversation, with model access coming from the desktop provider settings. A global `pi` has its own version and configuration. Ask agents to use `run_pi_command` for the embedded Pi, and open management terminals from inside the app. See [Extensions & MCP](./guide/skills).

## Why does the model not know a tool? {#why-does-the-model-not-know-a-tool}

Check that its extension or Widget is installed and enabled, and that this conversation has not hidden the tool. Some capabilities are found through tool search or by reading Widget documentation on demand. After installing into the embedded Pi, wait for tasks to finish, then refresh or reload.

## Why is the app still running after I close it? {#why-is-the-app-still-running-after-i-close-it}

Close hides the window in the tray and background tasks keep running. Right-click the tray avatar and choose **Exit** to quit. Background completions notify according to system settings. See [Conversations & notifications](./guide/conversations).

## Do historical file cards preserve the files? {#do-historical-file-cards-preserve-the-files}

Cards store references and open the original file. If the original moves or is deleted, the card can no longer open it. Keep important artifacts in a stable project directory and back them up. See [Artifact previews](./guide/artifacts).

## Why is there a separate webpage component on Linux? {#why-is-there-a-separate-webpage-component-on-linux}

The full Qt WebEngine is distributed separately to keep the base package smaller. Only webpage previews need it; Markdown, code and text previews work right away. See the [component flow](./guide/artifacts#linux-webpage-component).

## Why can I add several accounts from one provider? {#why-can-i-add-several-accounts-from-one-provider}

Each Key can have its own alias, region, models and proxy. `Kimi(Work)` and `Kimi(2)` are separate account entries; quota follows the upstream account each Key belongs to.

## Are Skills, plugins and MCP automatically sandboxed? {#are-skills-plugins-and-mcp-automatically-sandboxed}

Pi extensions, local MCP processes, provider plugins and Widgets can run local code with your user permissions. Package validation and host permissions limit some operations; hiding a tool only changes which tools the model sees. Install content from trusted sources.

## Where does my data go? {#where-does-my-data-go}

Configuration and native sessions are stored locally. Messages, tool results or file contents selected for inference are sent to your chosen provider. Third-party extensions may contact their own services.

## Why does the documentation differ from my app? {#why-does-the-documentation-differ-from-my-app}

These docs follow main, and stable Releases follow a little later. Check the version, commit and platform in **Settings → About**, then compare [Releases](https://github.com/umeiko/umeko-desktop/releases) or [C++ Releases](https://github.com/umeiko/umeko-desktop-cpp/releases). Pages also note differences between editions.
