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

`auth.fields` is an array of `{key, label, secret, required}` descriptors. The host renders these fields without knowing the authentication protocol. `authenticate(credentials)` receives their values and returns only public display information, such as `{"label": "Signed in"}`. Do not return access tokens. Store tokens with `context.secrets.set("session", {...})`; `get` and `delete` are also available. The host protects this store with Windows DPAPI or the OS keyring. Password fields are never exposed back to QML. Blank secret fields reuse a saved value only when non-secret account fields have not changed.

`list_models(refresh=False)` returns dictionaries with a string `id`, optional integer `contextWindow` and optional boolean `vision`. An empty list removes stale available models. The host displays the list on the provider's own account card, supports aliases, context limits and vision overrides, and preserves explicit user overrides on refresh. Do not probe models by running billable inference just to discover availability.

`events(model, messages, tools, max_tokens, parameters)` yields OpenAI-compatible JSON objects. Preserve multimodal `messages[].content` arrays and image data URLs. `tools` contains function descriptors **without** the outer `{type, function}` wrapper; add that wrapper when required by your upstream API. Preserve tool-call IDs and fragmented arguments, reasoning deltas, finish reasons, and usage-only chunks (`choices: []`). Inference parameters belong in the request unless your upstream documents a different mapping. `response_events(response)` parses JSON or SSE responses; `collect_openai(events)` collects streams for development checks. Image input requires the model's **Vision** checkbox; declaring capability does not add image support to a text-only upstream.

`context.config` contains non-secret JSON settings validated against `config.schema.json`. The supported schema subset is `type` (object, array, string, boolean, integer, number), `properties`, `required`, `additionalProperties: false`, `items` and `enum`. Remote schema references are not fetched. Put credentials in the protected secret store, never in config or cache files. `context.state_dir` is instance-specific and is for non-secret caches only. `context.cancelled` is set when an instance closes; stop background work promptly. Override `close()` to close your resources and call `super().close()`.

## HTTP and dependencies

`HttpSession(allowed_urls=[...], environment_proxy=True)` provides cookies, certificate verification, a timeout and an explicit destination-origin list. Redirects to an unlisted origin fail. Authorization, Cookie and token headers are stripped on cross-origin redirects. List every intended login/callback/inference origin explicitly. Remote HTTP and credentials embedded in URLs are rejected; HTTP is allowed on loopback for local tests. `response_cookies(headers)` reads repeated Set-Cookie headers without splitting expiry dates at commas. `ConsentForm` can parse hidden and scope inputs in an HTML form. The SDK never disables certificate verification or installs dependencies. Its HTTP helpers and dependencies are included in frozen hosts; other standard-library or third-party imports must be checked against the packaged target, not just a source Python environment.

Provider packages execute trusted Python code in the host process; this is **not a sandbox**. Review imported packages. Declare dependencies in `requirements.txt`; prebundle them under `vendor/` for the target Python/OS/architecture. The Windows app currently uses Python 3.12. Do not bundle another SDK copy, alter global Python installations, or assume native libraries work on a different platform. Standard-library-only packages are the most portable. The host reports missing imports instead of running pip automatically.

## Validation checklist

Use synthetic local fixtures for login success/failure, account switching, expiry/refresh, an empty model list, multiple accounts, text, tool calls and image content preservation. Test cancellation and redacted errors. Raise a short `ProviderError` without raw HTTP bodies, passwords, cookies or tokens. Never publish private endpoints, account data, credentials or login captures in the public repository or examples. ZIP imports reject traversal, symlinks, duplicate case-insensitive paths, more than 512 entries or more than 20 MiB expanded data. No hook is run during package validation.


## Host networking and diagnostics (SDK 0.2)

Provider API v1 remains compatible. Inside Umeko, `HttpSession` follows the provider card's proxy policy (system, direct or custom), including login, model discovery and inference. This host policy takes precedence over the standalone `environment_proxy` default. Avoid changing process-global proxy variables in provider code. The C++ worker also supplies the selected policy to conventional environment-aware transports.

During inference, the host captures the complete SDK call. `HttpSession` additionally records the actual HTTP request, status and error response for the local request-details window. Keep using `ProviderError` for concise user-facing failures; do not put passwords or raw authentication responses in it. Login requests are not recorded. Transports that bypass `HttpSession` must implement their own policy handling; their exact HTTP traffic cannot be captured by this helper. Existing v1 packages continue to load.
