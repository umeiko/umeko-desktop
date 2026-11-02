# Troubleshooting {#troubleshooting}

Record the version and reproduction steps, then check the smallest relevant area. Avoid deleting your entire profile as a first response.

## Model connection failures {#model-connection-failures}

Open **View request details** on the failed message. Check HTTP status, model ID, Key type and selected site. Common causes include insufficient permissions, incorrect aliases or regions, an unreachable proxy and upstream rate limits.

Verify the account works in an Umeko conversation before debugging an external API-proxy client. Reports redact keys but can contain prompts and code; review them before sharing.

## Slow downloads or failed checksums {#slow-downloads-or-failed-checksums}

The updater follows the system proxy. Verify that the proxy works, disk space is sufficient and a network gateway has not replaced the download with an error page. Do not bypass SHA-256 on failure. Download again or obtain the complete matching package from the official Release.

If GitHub is unreliable, use another network or device and transfer the package locally. Do not overwrite an installation with a mismatched edition, CPU build or untrusted file.

## Extension installation failures {#extension-installation-failures}

Model-provider proxies and npm configuration are separate. Search for npm under **Settings → Agent → Pi**, then check the registry, `.npmrc` and CA in npm and networking. Configure a CA for corporate certificates rather than disabling verification.

Confirm the package exists, the network can reach it, and installation targets this embedded Pi. See the [extension guide](./guide/skills).

## Linux input methods {#linux-input-methods}

Fcitx5 and its input engine must run in the current desktop session. Packages carry an input plugin matching their own Qt; do not overwrite it with a plugin built for a different system Qt.

Check input in another app first. If you selected an input frontend manually, inspect the startup environment. Source launches accept `UMEKO_QT_IM_MODULE=fcitx` or `ibus`; an empty value uses the platform default. Record X11 / Wayland, input method and Qt versions when reporting.

[Detailed build and verification notes](https://github.com/umeiko/umeko-desktop/blob/main/docs/linux-ime-fcitx5.md)

## Unavailable keyring {#unavailable-keyring}

Linux needs an unlocked Secret Service / KWallet in the current login session; macOS needs an accessible login Keychain. Check desktop credential services and OS prompts instead of switching to plain-text Key storage.

Sign in again after moving to another machine or OS. Do not overwrite Python and C++ profiles with each other.

## An extension prevents kernel startup {#an-extension-prevents-kernel-startup}

Use **Settings → Agent → Pi → Management and recovery** to restore the factory kernel. Read the confirmation first: it backs up relevant Pi configuration, enables recovery mode to skip third-party resources, and preserves projects, sessions and provider settings.

Recovery is not a full data wipe. Once startup works, investigate original extensions gradually. Running tasks must finish first.

## Report a problem {#report-a-problem}

Copy project information from **Settings → About**, then report to the relevant edition:

[![Version and Copy project information on the About page](/images/about-en.png)](/images/about-en.png)

*This demo runs from main source. Your installed build displays its own version and provenance.*

- [Python / Qt issues](https://github.com/umeiko/umeko-desktop/issues/new)
- [C++ / Qt issues](https://github.com/umeiko/umeko-desktop-cpp/issues/new)

Include version and commit, OS and CPU, reliable steps, expected versus actual behavior, screenshots or a short recording, and relevant error details. For Linux UI problems include the desktop environment and X11 / Wayland. Remove keys, cookies, private conversations and project contents before posting publicly.
