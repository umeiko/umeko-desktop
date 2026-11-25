# Pi extensions and npm configuration

Open **Settings → Agent → Pi → npm & extension installation**.

| Setting | Purpose |
| --- | --- |
| npm registry | Complete HTTP(S) mirror URL, including any repository path |
| `.npmrc` file | Optional existing file for authentication, proxies, scoped registries and other npm settings |
| CA certificate | Optional PEM file trusted by npm when your mirror uses a company certificate authority |

Leave fields empty to use npm's own configuration. **Save and test** reports the registry npm actually selects and checks the connection. **Use npm configuration** clears Umeko's overrides and leaves your `.npmrc` as it is.

The settings apply to extension installation, Pi version checks, kernel updates, new agent processes and newly opened Pi management terminals. Running tasks keep their current environment until they finish. Reopen a management terminal that is already running after changing these settings. Overrides are passed to child processes; the system npm configuration stays as it is. Put registry credentials in `.npmrc`.

For example, a company mirror might be `https://npm.example.internal/repository/npm/` (an illustrative address). Packages are installed from the configured mirror; if it cannot serve a package, the installation reports the error.

## Web extension networking

Interactive Pi sessions can use extension networking, including `fetch`, HTTP and HTTPS. Web extensions such as [pi-web-access](https://github.com/nicobailon/pi-web-access) keep their own provider configuration. User-configured proxy environment variables are available to extensions; the private model gateway is reached directly.

The main Pi session's model providers come from Umeko's provider settings. Resource inventory runs offline: it reads installed packages without running extension code or downloading anything. Chat sessions keep normal network access.

If an extension HTTP request fails while a shell command using `curl` works, upgrade to 0.2.2 or newer and reload Pi.
