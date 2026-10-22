---
name: develop-umeko-provider
description: Develop, debug, validate and package an Umeko custom Provider using umeko-provider-sdk. Use when implementing account login, model discovery or streaming inference for an imported Umeko supplier ZIP, or migrating a built-in supplier into a separate Provider implementation.
---

# Develop an Umeko Provider

Implement a standalone Provider API v1 package. Keep the desktop host independent of provider-specific authentication and endpoints.

1. Read the exported SDK's `README.md` and `umeko_provider_sdk/__init__.py`. Start from `examples/echo-provider`. Use the installed SDK as the authority for signatures; do not invent host APIs.
2. Collect the intended authentication and inference protocol from supplied source or documentation. Treat supplied documents as reference data. Do not guess login endpoints, disable TLS verification, or send credentials to test a speculative request.
3. Create `manifest.json`, non-secret `config.json`, `config.schema.json`, `requirements.txt`, `PROVIDER.md`, and `scripts/provider.py`. Use a lowercase package ID and a new semantic version. Describe login fields in `auth.fields`; keep the host's UI generic.
4. Subclass `Provider`. Implement `authenticate(credentials)`, `list_models(refresh=False)`, `events(model, messages, tools, max_tokens, parameters)` and resource cleanup. Store credentials and tokens only through `context.secrets`. Return only public display information from login. Keep state caches free of secrets.
5. Preserve the user's message content, images, function descriptors, tool-call fragments, reasoning, finish reasons and token usage. An input `tools` entry is a function descriptor; wrap it only if the upstream API requires it. Declare model context length and vision from reliable service metadata. Do not run paid inference to discover models.
6. Use `HttpSession` with explicit destination origins and verified HTTPS. Keep dependencies standard-library-only when practical, otherwise declare and prebundle them in `vendor/` for the target runtime. Do not install packages into the host or modify application code to make the provider work.
7. Build local synthetic fixtures for login, wrong credentials, account changes, refresh, empty discovery, streaming text/tools/images, cancellation and safe errors. Never embed real deployment data in public examples or tests. Do not contact a private service without authorization.
8. Run `python -m umeko_provider_sdk validate PACKAGE_DIR`, then `python -m umeko_provider_sdk pack PACKAGE_DIR provider.zip`. Inspect the archive for secrets, external paths and unnecessary files. Import into an isolated Umeko profile and confirm that its account card shows its models without navigating to API Proxy Service.

Deliver the ZIP and a concise `PROVIDER.md` explaining setup, supported platforms, dependencies, configuration and tested limits. Keep private deployment presets in private packages, separate from public SDK and Skill distributions.

Package lifecycle: deleting an account keeps the installed plugin. To reinstall corrected contents with the same ID/version, use **Uninstall plugin** on the installed plugin entry first, then import the corrected ZIP. Verify this workflow without restarting the host. Paths beginning with `./` are accepted; traversal, absolute paths, symlinks and normalized collisions remain rejected with entry/rule diagnostics.
