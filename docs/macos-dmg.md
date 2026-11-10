# macOS drag installation

macOS Apple Silicon and Intel builds produce a **DMG** in addition to the ZIP. Open the DMG and drag the application icon onto **Applications**, then launch the installed copy from Applications and eject the image. The Finder window uses a minimal white icon view with the app on the left and an Applications shortcut on the right.

The in-app updater uses the ZIP; installing from the DMG and updating from the app work side by side. C++ standard and minimal editions both include matching disk images.

## Packaging and verification

`scripts/macos_dmg.py` copies the verified, signed `.app` with `ditto`, leaving the bundle as built. It writes Finder layout metadata with pinned build-only `ds-store==1.3.1` / `mac-alias==2.2.3`, adds a link to `/Applications`, and creates a compressed HFS+ image with Apple's `hdiutil`.

Packaging verifies the image, mounts it read-only without opening Finder, verifies the app bundle and Applications link, checks the bundle's code signature, and always detaches the test mount. The DMG is then copied into release assets and its SHA-256 recorded. If the mount or signature check fails, the build fails and no DMG is published. No Finder automation permission is needed.

Release metadata carries size/hash records for both the archive and the disk image. The publisher requires the DMG and its checksum for each macOS architecture, validates every artifact before creating a Release, and checks GitHub's upload digests. Complete releases have 19 assets; retention also recognizes historical 15-asset releases.

The `.app` keeps the project's signing/notarization status; the DMG simply packages that app for delivery. macOS builds and mount checks run on the macOS CI runners. Linux tests cover Finder metadata, the failure cleanup path, update selection and the release metadata logic.
