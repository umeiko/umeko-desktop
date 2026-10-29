# Umeko Provider SDK

`umeko-provider-sdk` is the public Python API for custom account login, model discovery and inference. The SDK has no imports from the desktop application. Protocol-specific login pages, OAuth flows, enterprise endpoints and routing belong in a separately distributed Provider package. Importing a package does not run its code or contact a network. Login, refresh and inference activate it on demand.

## Get started

Export the SDK and the developer Skill from **Settings → Accounts & Providers → + → Import custom provider implementation**. Unzip the SDK; its commands can run directly from that extracted directory without downloading dependencies. Optionally install it into a development environment with `python -m pip install .`. Umeko already bundles the SDK; app users do not need to install it separately.

Start from `examples/echo-provider`:

```text
my-provider/
  manifest.json
  config.json
  config.schema.json
  requirements.txt
  PROVIDER.md
  scripts/
    provider.py
    login.py             # optional
  vendor/                # optional prebundled dependencies
```

```bash
python -m umeko_provider_sdk validate my-provider
python -m umeko_provider_sdk pack my-provider my-provider.zip
```

Import the ZIP using the plus button. Each import creates an independent account instance; you can also add accounts from the installed plugin list. Deleting an account removes only that account and its credentials, preserving the plugin. **Uninstall plugin** removes that installed version and its associated accounts and credentials, then clears its canonical installation directory and loaded-code cache. A corrected ZIP with the same version can be installed immediately afterward. Other plugins and versions are preserved. Installed packages left by older releases are also listed, including packages with no accounts, so they can be explicitly uninstalled. Different contents with an already installed ID/version are rejected until uninstall; account deletion alone does not permit replacement.

ZIP entries and manifest paths may start with `./`; these harmless current-directory segments are normalized. Absolute paths, `..`, backslashes, Windows reserved names, symlinks, special files, and normalized file collisions are rejected before extraction. Import errors identify the exact original entry, rule code, and conflicting entry when applicable; the error dialog supports selection and copying.

## API v1

`manifest.json` specifies `apiVersion: 1`, a lowercase `id`, a semantic `version`, a display `name`, and `entrypoint: "scripts/provider.py:create_provider"`. The factory receives `ProviderContext` and must return a subclass of `Provider`.

An optional top-level `description` string explains the plugin's purpose, prerequisites and usage. For example: `"description": "Connects to your team's model service. Sign in with your assigned account."` Umeko displays a circled question mark next to the installed plugin and its account names; hover to read the description. It is plain text, supports line breaks, and contains no credentials. Omit it or leave it blank to hide the question mark. Existing API v1 packages remain compatible. When changing the description of an installed package, publish a new package version as for any other manifest change.

`auth.fields` is an array of `{key, label, secret, required}` descriptors. The host renders these fields without knowing the authentication protocol. `authenticate(credentials)` receives their values and returns only public display information, such as `{"label": "Signed in"}`. Do not return access tokens. Store tokens with `context.secrets.set("session", {...})`; `get` and `delete` are also available. The host protects this store with Windows DPAPI or the OS keyring. Password fields are never exposed back to QML. Blank secret fields reuse a saved value only when non-secret account fields have not changed.

`list_models(refresh=False)` returns dictionaries with a string `id`, optional integer `contextWindow` and optional boolean `vision`. An empty list removes stale available models. The host displays the list on the provider's own account card, supports aliases, context limits and vision overrides, and preserves explicit user overrides on refresh. Do not probe models by running billable inference just to discover availability.

Optional `card_fields()` returns local, nonblocking public descriptors for extra secret inputs: `key`, `label`, optional `hint`, `link`, `message` and boolean `hasValue`. Return an empty list until fields should be visible. The host does not activate a plugin just to render its card. After activation it can restore display state from protected secrets. Never include secret values in descriptors. `set_card_secret(key, value)` stores the submitted value using `context.secrets` and may return a public `{"message": "..."}`. The host runs it on the existing management worker, refreshes models, clears the input and displays the public message. The secret is not saved in config or exposed back to QML. Returning a rejection message with an updated model list lets a provider remove models for a rejected key without re-authentication. Existing providers inherit an empty list and need no changes.

`events(model, messages, tools, max_tokens, parameters)` yields OpenAI-compatible JSON objects. Preserve multimodal `messages[].content` arrays and image data URLs. `tools` contains function descriptors **without** the outer `{type, function}` wrapper; add that wrapper when required by your upstream API. Preserve tool-call IDs and fragmented arguments, reasoning deltas, finish reasons, and usage-only chunks (`choices: []`). Inference parameters belong in the request unless your upstream documents a different mapping. `response_events(response)` parses JSON or SSE responses; `collect_openai(events)` collects streams for development checks. Image input requires the model's **Vision** checkbox; declaring capability does not add image support to a text-only upstream.

Optional `card_actions()` returns public `{key, label, url?, hint?}` button descriptors. `card_status()` returns a public string. Both accessors must be local and nonblocking; neither is called before the provider has been activated. `card_action(key)` runs only after a user clicks an advertised button and returns a public `{message?, url?, refreshModels?}` result. The host opens a valid HTTP(S) result URL using the desktop browser after the action completes; descriptor URLs are informational and never opened automatically. Do not launch a browser yourself. `refreshModels: true` requests model discovery without another login. Omit it when starting a background workflow. The host ignores extra result fields. These optional methods default to no buttons and an empty status, preserving API v1 compatibility.

`ProviderContext` also has optional `profile_dir` and `downloads_dir` paths (both default to `None`), `language` (default `"zh"`), and an optional `notify` callback. Umeko supplies its application profile directory, the operating-system downloads directory and current UI language. Keep all provider-specific translations in the package. A background task can call `context.notify({"message": "Import complete", "refreshModels": True})` to update its card and refresh the models after credentials have been stored in `context.secrets`. Call only when `notify` is not `None`; standalone and older hosts may not provide it. Messages, status, action descriptors, results and URLs are public: never include passwords, cookies, tokens, credential values or raw login responses. A notification never opens a browser. Stop work when `context.cancelled` is set; notifications from closed or invalidated instances are ignored.

`context.config` contains non-secret JSON settings validated against `config.schema.json`. The supported schema subset is `type` (object, array, string, boolean, integer, number), `properties`, `required`, `additionalProperties: false`, `items` and `enum`. Remote schema references are not fetched. Put credentials in the protected secret store, never in config or cache files. `context.state_dir` is instance-specific and is for non-secret caches only. `context.cancelled` is set when an instance closes; stop background work promptly. Override `close()` to close your resources and call `super().close()`.

For inference cancellation, capture `cancelled = context.request_cancelled` at the start of `events()` and pass that event to any request workers. It identifies only the current request, so one disconnected caller does not cancel other requests on the same provider. The host uses `with request_scope(event):` around the complete call and stream iteration. Context is isolated across threads and nested scopes; new worker threads must receive the captured event explicitly. Outside a request scope, the property returns `context.cancelled` for compatibility with standalone hosts. Request code should also respect `context.cancelled` when the entire instance closes.

## HTTP and dependencies

`HttpSession(allowed_urls=[...], environment_proxy=True)` provides cookies, certificate verification, a timeout and an explicit destination-origin list. Redirects to an unlisted origin fail. Authorization, Cookie and token headers are stripped on cross-origin redirects. List every intended login/callback/inference origin explicitly. Remote HTTP and credentials embedded in URLs are rejected; HTTP is allowed on loopback for local tests. `response_cookies(headers)` reads repeated Set-Cookie headers without splitting expiry dates at commas. `ConsentForm` can parse hidden and scope inputs in an HTML form. The SDK never disables certificate verification or installs dependencies. Its HTTP helpers and dependencies are included in frozen hosts; other standard-library or third-party imports must be checked against the packaged target, not just a source Python environment.

Provider packages execute trusted Python code in the host process; this is **not a sandbox**. Review imported packages. Declare dependencies in `requirements.txt`; prebundle them under `vendor/` for the target Python/OS/architecture. The Windows app currently uses Python 3.12. Do not bundle another SDK copy, alter global Python installations, or assume native libraries work on a different platform. Standard-library-only packages are the most portable. The host reports missing imports instead of running pip automatically.

The host treats card labels, hints, messages and statuses as plain text. It redacts stored secret values (including nested fields) and newly submitted credentials before truncating public management results and errors. Card links must be HTTP(S), contain no URL credentials or control characters, and must not expose saved secrets, including URL-encoded values. This is a backstop, not permission to return sensitive output: plugins remain responsible for safe public results. Card-secret input is limited to 65,536 characters. Card accessors must not perform network or other blocking work on the UI thread.

For a deployment that explicitly requires a plain HTTP service, `HttpSession(..., allowed_http_urls=["http://example.test/v1"])` permits that exact origin and base path (and descendants) only when its origin is also listed in `allowed_urls`. Other remote HTTP remains rejected; the default and standalone `origin()` remain HTTPS-only except loopback. Redirect validation uses the same scope. This opt-in does not disable HTTPS certificate or hostname verification.

## Distribution and default installation

Vendor-specific adapters can be packed as independent Provider SDK ZIPs and distributed as optional Release assets. Users choose whether to download, import and activate them; publishing a ZIP does not make it a default desktop component. CLI installation, account migration and provider-specific lifecycle belong in that plugin, with explicit user actions for setup.

The desktop build uses `provider_dev/default-providers.json` as its explicit maintainer-reviewed allow-list of default provider IDs. It is empty by default. Only listed IDs are built from matching `provider_dev/bundled/<id>` directories and included in the default-install catalog. Merely adding a directory never bundles or installs it. The resource directory is regenerated on every build to remove stale default ZIPs. Optional plugins must stay outside this catalog; their release packaging is separate from desktop installation. General SDK APIs stay provider-independent, and compatibility requests should include a minimal offline test case.

## Validation checklist

Use synthetic local fixtures for login success/failure, account switching, expiry/refresh, an empty model list, multiple accounts, text, tool calls and image content preservation. Test cancellation and redacted errors. Raise a short `ProviderError` without raw HTTP bodies, passwords, cookies or tokens. Never publish private endpoints, account data, credentials or login captures in the public repository or examples. ZIP imports reject traversal, symlinks, duplicate case-insensitive paths, more than 512 entries or more than 20 MiB expanded data. No hook is run during package validation.


## Host networking and diagnostics (SDK 0.2)

Provider API v1 remains compatible. Inside Umeko, `HttpSession` follows the provider card's proxy policy (system, direct or custom), including login, model discovery and inference. This host policy takes precedence over the standalone `environment_proxy` default. Avoid changing process-global proxy variables in provider code. The C++ worker also supplies the selected policy to conventional environment-aware transports.

During inference, the host captures the complete SDK call. `HttpSession` additionally records the actual HTTP request, status and error response for the local request-details window. Keep using `ProviderError` for concise user-facing failures; do not put passwords or raw authentication responses in it. Login requests are not recorded. Transports that bypass `HttpSession` must implement their own policy handling; their exact HTTP traffic cannot be captured by this helper. Existing v1 packages continue to load.
