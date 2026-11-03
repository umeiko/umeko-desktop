# Preferences and upgrades

Both editions keep user data outside the application bundle:

| Edition | Directory on Windows, macOS and Linux |
| --- | --- |
| Python / Qt | `~/.umeko/desktop` |
| C++ / Qt | `~/.umeko/desktop-cpp` |

`~` is your home directory, such as `C:\Users\your-name` on Windows. **Settings → Appearance → User data directory** opens the actual location. `UMEKO_DATA_DIR` still overrides the profile path; the C++ edition also accepts `UMEKO_CPP_DATA_DIR` and `--data-dir`. Keep the editions in separate profiles because their credential formats differ.

The first launch copies an existing platform-specific profile into the new directory before activating it. Providers, plugin packages and state, themes, attachments and conversations are preserved. Managed session paths are remapped; user-authored messages are not rewritten. The original directory remains available for rollback. macOS/Linux keychain namespaces are preserved; credentials stay in the system credential store. Moving to another computer or OS still requires signing in again.

## Release and Preview channels

In **Settings → About → Update channel**, choose **Release** for published stable packages or **Preview** to run the latest official `main` source before release. Preview is unreleased software and may be unstable. The channel picker is available in Python packaged installations on Windows, macOS and Linux, and in source installations managed by this feature. An ordinary source checkout explains that its updates remain under your own Git workflow.

Before the first switch, wait for tasks to finish, exit the app and back up the actual user data directory shown in Appearance settings, along with your project files. Both channels use the same profile. Keeping the original Release executable makes returning possible, but there is no general downgrade migration for settings; newer settings are not guaranteed to work in an older Release.

Choosing Preview first checks Git, Python 3.10+ with `venv`, Node.js 22.19+ with npm, the platform setup shell, at least 2 GiB of free space and access to the official repository. Review the result and confirm before preparation starts. The app clones `https://github.com/umeiko/umeko-desktop.git` into a dedicated Preview source directory under the profile, then runs that checkout's `setup.ps1` or `setup.sh`. Preparation shows progress and supports cancellation. A failed or cancelled preparation leaves Release available; a failed dependency setup can be retried.

After preparation succeeds, the channel state is saved separately from `settings.json`. On the next start, the retained Release launch route opens Preview directly with its virtual environment's Python and `main.py`. It does not use the source checkout's `Start-Umeko` launcher, which may prefer an existing `dist` bundle.

In Preview, **Check for updates** fetches the official source and shows the current commit, proposed target and commit summary. Review and confirm that target before applying the fast-forward update. Modified files, staged changes, an overwrite risk from untracked files, an unexpected repository origin or diverged history prevent the update. Dependency setup runs only when its relevant inputs change; if it fails after the source update, the pending setup remains available to retry. The app does not reset or discard local work.

Choose Release to return through the retained original application. The shared profile, settings and projects remain in place; selecting Release does not reverse settings migrations. Keep the Preview source by default. When Preview is running, optional removal waits until it exits and Release restarts. Removal affects only the managed source and dependencies; local changes prevent removal. It does not remove the profile or settings.

If Preview cannot open its interface, start the retained packaged executable with `--release-channel` to select and open Release directly. For example, use `Umeko.exe --release-channel` on Windows, `Umeko.app/Contents/MacOS/Umeko --release-channel` on macOS, or `./Umeko --release-channel` on Linux. This preserves settings and conversations; it does not undo configuration migrations.

### Network settings during Preview preparation

The app's npm registry, `.npmrc` and CA overrides are inherited only by npm. Per-provider proxies configure model connections and do not configure cloning or dependency installation. Git and pip retain their own configuration, proxy and CA settings; the system proxy used by the updater is passed to the preparation process. No global Git, pip or npm configuration is written, and a failing configured endpoint is not silently replaced with a public fallback.

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

**Settings → Appearance** offers Simplified Chinese and English, plus a text-size slider from **50% to 200%**. Icons, arrows and button hit areas grow with the text. Both preferences apply immediately and are saved in the profile. The first run chooses Chinese when the system's preferred UI language is Chinese, otherwise English. A saved choice takes precedence on later launches. Conversation text, project names and custom provider data keep their original language.
