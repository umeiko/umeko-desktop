# Pi extensions and npm configuration

Open **Settings → Agent → Pi → npm & extension installation**.

| Setting | Purpose |
| --- | --- |
| npm registry | Complete HTTP(S) mirror URL, including any repository path |
| `.npmrc` file | Optional existing file for authentication, proxies, scoped registries and other npm settings |
| CA certificate | Optional PEM file trusted by npm when your mirror uses a company certificate authority |

Leave fields empty to inherit npm's own configuration. **Save and test** reports the actual registry selected by npm and checks its connection. **Use npm configuration** clears only Umeko's overrides; it does not edit or delete your `.npmrc`.

The settings apply to extension installation, Pi version checks, kernel updates, new agent processes and newly opened Pi management terminals. Existing tasks keep their current environment until they finish; they are not interrupted. Reopen an already running management terminal after changing these settings. Overrides are passed to child processes and never written into the system npm configuration. Registry credentials belong in `.npmrc`, not in the registry URL.

For example, a company mirror might be `https://npm.example.internal/repository/npm/`. This is an illustrative address, not a deployment default. Umeko does not fall back to the public registry when the configured mirror cannot serve a package.

## Web extension networking

Interactive Pi sessions can use extension networking, including `fetch`, HTTP and HTTPS. Web extensions such as [pi-web-access](https://github.com/nicobailon/pi-web-access) keep their own provider configuration. User-configured proxy environment variables remain available; the private model gateway is excluded from proxy routing.

The main Pi session's model providers are still registered explicitly from Umeko's provider settings. Bundled model catalogs and inherited model credentials are not imported. Resource inventory is a separate offline operation and does not execute extension code or download missing packages. Its offline flag is not inherited by chat sessions.

Versions before 0.2.2 incorrectly applied the model connection guard to all Node networking. An extension HTTP request could therefore fail while a shell command using `curl` succeeded. Upgrading to 0.2.2 and reloading Pi replaces that incorrect process-wide restriction.
