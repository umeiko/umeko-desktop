# Troubleshooting {#troubleshooting}

Note the version and reproduction steps, then start with the part that is failing. Your profile holds settings, provider configuration and session history; keep it in place while you troubleshoot.

## Model connection failures {#model-connection-failures}

Open **View request details** on the failed message. Check HTTP status, model ID, Key type and selected site. Common causes include insufficient permissions, incorrect aliases or regions, an unreachable proxy and upstream rate limits.

Confirm the account works in an Umeko conversation before debugging an external API-proxy client. Request details redact keys but can contain prompts and code; review them before sharing.

## Slow downloads or failed checksums {#slow-downloads-or-failed-checksums}

The updater follows the system proxy. Check that the proxy works, disk space is sufficient, and the download is the package itself rather than a network gateway's error page. If the SHA-256 check fails, download again or get the complete matching package from the official Release.

If GitHub is unreliable, use another network or device and transfer the package to this machine. Install over an existing copy only with the official package for the same edition and CPU.

## Extension installation failures {#extension-installation-failures}

Model-provider proxies and npm configuration are separate. Search for npm under **Settings → Agent → Pi**, then check the registry, `.npmrc` and CA in npm and networking. On corporate networks with their own certificates, add the CA file there and keep certificate verification on.

Confirm the package exists, the network can reach it, and installation targets this embedded Pi. See the [extension guide](./guide/skills).

## Linux input methods {#linux-input-methods}

Fcitx5 and its input engine must run in the current desktop session. Packages include an input plugin matching their own Qt; keep the bundled plugin in place.

Check input in another app first. If you selected an input frontend manually, inspect the startup environment. Source launches accept `UMEKO_QT_IM_MODULE=fcitx` or `ibus`; an empty value uses the platform default. Include X11 / Wayland, input method and Qt versions when reporting.

[Detailed build and verification notes](https://github.com/umeiko/umeko-desktop/blob/main/docs/linux-ime-fcitx5.md)

## Unavailable keyring {#unavailable-keyring}

Linux needs an unlocked Secret Service / KWallet in the current login session; macOS needs an accessible login Keychain. When the app reports it unavailable, check that the desktop credential service is running and watch for OS prompts. Umeko stores Keys only in this OS-protected storage, so the service needs to be available.

Sign in again after moving to another machine or OS. The Python and C++ editions each use their own profile.

## An extension prevents kernel startup {#an-extension-prevents-kernel-startup}

Use **Settings → Agent → Pi → Management and recovery** to restore the factory kernel. The confirmation lists the scope: it backs up relevant Pi configuration, enables recovery mode to skip third-party resources, and keeps projects, sessions and provider settings.

Let running tasks finish before recovery. Once startup works, check the original extensions one at a time.

## Report a problem {#report-a-problem}

Copy project information from **Settings → About**, then report to the relevant edition:

[![Version and Copy project information on the About page](/images/about-en.png)](/images/about-en.png)

*This demo runs from main source. Your installed build displays its own version and provenance.*

- [Python / Qt issues](https://github.com/umeiko/umeko-desktop/issues/new)
- [C++ / Qt issues](https://github.com/umeiko/umeko-desktop-cpp/issues/new)

Include version and commit, OS and CPU, reliable steps, expected versus actual behavior, screenshots or a short recording, and relevant error details. For Linux UI problems include the desktop environment and X11 / Wayland. Remove keys, cookies, private conversations and project contents before posting publicly.
