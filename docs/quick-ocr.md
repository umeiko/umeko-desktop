# Quick OCR in Cowork

Select the built-in **Quick OCR** coworker. On its first use, Umeko prepares the
separate local OCR component in the background. Add one original local image
to the existing chat and send it. If installation is still running, use the
same chat's waiting and stop controls. Results are selectable plain text in
that conversation, not a new dialog. The original image is not modified.

The component uses RapidOCR 3.10.0 and PP-OCRv6 small on ONNX Runtime CPU. It
does not ask Pi or a cloud model to read the image. The first install downloads
a standalone Python and pinned binary wheels from their official release or
package hosts. The checked-in platform lock records the bytes and SHA-256 of
every asset; the installer does not resolve dependencies from an online index
at runtime. Umeko verifies the component before making it available.

The app package contains the small launcher, the pinned manifest, and worker
source only. The Linux x64 download is about 203 MiB, and the installed
component takes roughly 612 MiB in the test environment. Exact size varies by
platform. On installation failure, resending the image retries preparation.
Stop cancels the pending image without discarding a component installation
already running in the background. Once installed, subsequent recognition,
including after restart, can run without the download assets or a network
connection.

The pinned manifests currently cover Linux x64 and arm64, Windows x64, and
macOS arm64. This change's automated UI acceptance ran on Linux x64. This
does not establish native Windows/macOS installation or physical arm64
device coverage. Other configurations keep image contents local and report
that a compatible component is not available.
