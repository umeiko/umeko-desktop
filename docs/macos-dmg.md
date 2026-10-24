# macOS drag installation

macOS Apple Silicon and Intel builds now produce a **DMG** in addition to the existing ZIP. Open the DMG and drag the application icon onto **Applications**, then launch the installed copy from Applications and eject the image. The Finder window uses a minimal white icon view with the app on the left and an Applications shortcut on the right.

ZIP remains the in-app updater's verified replacement payload. Publishing both formats does not change update selection or the independent installer's stop/confirm/replace/relaunch flow. C++ standard and minimal editions both include matching disk images.

## Packaging and verification

`scripts/macos_dmg.py` copies the already verified, signed `.app` with `ditto`; it does not modify the bundle. It writes Finder layout metadata with pinned build-only `ds-store==1.3.1` / `mac-alias==2.2.3`, adds a link to `/Applications`, and creates a compressed HFS+ image with Apple's `hdiutil`.

Packaging verifies the image, mounts it read-only without opening Finder, verifies the app bundle and Applications link, checks the bundle's existing code signature, and always detaches the test mount. Only then is the DMG copied into release assets and its SHA-256 recorded. A failed mount/signature check fails the build and leaves no publishable DMG. No Finder automation permission is required.

Release metadata carries both archive and disk-image size/hash records. The publisher requires the DMG and its checksum for each macOS architecture, validates every artifact before creating a Release, and checks GitHub's upload digests. Complete releases now have 19 assets; retention still recognizes historical 15-asset releases.

The `.app` retains the project's existing signing/notarization status. A DMG is a delivery format, not a new signing identity. macOS builds and mount checks run on the macOS CI runners after user acceptance; Linux tests cover Finder metadata, the failure cleanup path, update selection and the release metadata logic but cannot create or mount a native DMG.
