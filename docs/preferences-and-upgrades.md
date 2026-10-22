# Preferences and upgrades

Both editions keep user data outside the application bundle:

| Edition | Directory on Windows, macOS and Linux |
| --- | --- |
| Python / Qt | `~/.umeko/desktop` |
| C++ / Qt | `~/.umeko/desktop-cpp` |

`~` is your home directory, such as `C:\Users\your-name` on Windows. **Settings → Appearance → User data directory** opens the actual location. `UMEKO_DATA_DIR` still overrides the profile path; the C++ edition also accepts `UMEKO_CPP_DATA_DIR` and `--data-dir`. Keep the editions in separate profiles because their credential formats differ.

The first launch copies an existing platform-specific profile into the new directory before activating it. Providers, plugin packages and state, themes, attachments and conversations are preserved. Managed session paths are remapped; user-authored messages are not rewritten. The original directory remains available for rollback. macOS/Linux keychain namespaces are preserved; credentials stay in the system credential store. Moving to another computer or OS still requires signing in again.

## Provider proxies

Use the small gear on an API provider or imported provider card:

- **Use system proxy** follows the operating system and proxy environment configuration.
- **Do not use a proxy** connects directly, independently of system proxy variables.
- **Use custom proxy** uses the specified HTTP/HTTPS proxy, such as `http://127.0.0.1:7890`. Enter an address without embedded credentials; authenticated corporate proxies can use the system configuration.

The setting is per provider. It covers model inference and the provider SDK's sign-in/model discovery requests. Other providers and Pi extension networking keep their own settings. SDK-based plugins follow this policy automatically; plugins using custom networking must honor the host's policy. Proxy settings are preserved when editing model mappings or upgrading.

## Request error details

Failed model messages offer **View request details**. The window shows the complete model call, HTTP request/response metadata, response body and exception, and can copy the full report. Built-in API transports and SDK `HttpSession` calls capture HTTP details. If a plugin uses a different transport, the complete SDK call and available plugin error are still shown; exact HTTP details require the plugin to use `HttpSession`.

Keys, authorization headers and known credentials are redacted. Reports are stored only on this device under `request-errors/`; the latest 30 failures are retained. Reports can contain your prompts, code and file contents, so review them before sharing. They are excluded from builds and releases.

## Language and text size

**Settings → Appearance** offers Simplified Chinese and English, plus a text-size slider from **50% to 200%**. Both apply immediately and are saved in the profile. The first run chooses Chinese when the system's preferred UI language is Chinese, otherwise English. A saved choice takes precedence on later launches. Conversation text, project names and custom provider data keep their original language.
