# Quick OCR in Cowork

Choose **Quick OCR** in Cowork, attach a local image and send it. Setup only
starts when the request includes an image. On the first image, the Cowork
skill checks and prepares a Python 3.12 environment in
`./.umeko/quick-ocr` under the current workspace. When setup succeeds it
processes that same image in the current conversation. If setup is needed,
Cowork first tells you to wait; you do not need to send the image again.
A ready environment is reused silently on later requests.

## Approved Python package source

The skill tries the existing workspace interpreter first. It can reuse a
working environment even if its Python is not on PATH or registered with
the Windows launcher. To set up a fresh environment, use an installed
Python 3.12 or an already installed, approved `uv` to find it offline.
It does not download Python. Setup uses the app's normal tool approval
and honors standard pip
configuration, including `PIP_INDEX_URL` or `pip.ini`/`pip.conf`,
`HTTPS_PROXY`/`PIP_PROXY` and administrator-approved certificates
such as `PIP_CERT`. Configure these for the account/environment that starts
Umeko. The installer uses pip's normal default only when no source is
configured, and does not retry against another source, bypass certificate
verification, or install globally. A pip `trusted-host` override is rejected;
configure the approved CA instead. If the approved source fails, the
conversation reports the failure by stage without exposing pip logs or
credentials. Correct the configuration, then retry.

## Offline installation

On a restricted machine, have your administrator supply a trusted local
wheelhouse for the target OS, CPU architecture and Python 3.12, and a lock
file for that wheelhouse. The lock must list the skill's pinned packages
and every required transitive dependency. Use one exact package version
per line followed by one or more SHA-256 hashes:
`package==1.2.3 --hash=sha256:<64 hexadecimal digits>`.
Blank lines and full-line comments are allowed; indexes, URLs, includes,
environment markers and continuations are not. Treat the lock itself as
trusted input; hashes only verify wheels against the supplied lock.

Set `UMEKO_QUICK_OCR_WHEELHOUSE` and `UMEKO_QUICK_OCR_LOCK` to the
absolute paths to the folder and lock file in the Umeko environment. For
manual setup, run `scripts/setup_ocr.py --wheelhouse ABS_DIR --lock ABS_FILE`
with Python 3.12 from your Cowork workspace. In offline mode no pip index,
cache, inherited pip configuration or dependency download is used. An
incomplete or incompatible offline bundle fails without online fallback.

## Windows corporate proxy with current-login authentication

Some intranets require Windows integrated authentication even when pip's
normal configuration is correct. Administrators can provision an approved
JSON profile and set `UMEKO_QUICK_OCR_ENTERPRISE_PROFILE` to its absolute
path in the environment that launches Umeko. Use this instead of the offline
environment variables. The profile contains:

- `proxy`: approved `http://` or `https://` proxy origin and port.
- `auth`: `ntlm` (matching a working `curl --proxy-ntlm --proxy-user :`
  command) or `negotiate`, as specified by the administrator.
- `lock`: absolute path to the trusted hashed lock described above.
- `wheels`: list of objects containing `url` (direct HTTPS wheel URL) and
  `sha256` (matching approved lock hash). Include a compatible wheel for
  every package. URLs must not contain credentials, query strings or
  redirects; use the approved artifact's final URL.
- Optional `ca`: absolute path to an approved CA bundle; otherwise curl
  verifies TLS with its default trust store.

The installer calls Windows System32 curl with the current Windows login.
It never asks for or stores proxy passwords. It verifies the approved wheel
hashes before using the offline installer, removes its temporary downloads
and never falls back to public PyPI. If the available Windows curl does not
support the configured authentication, use the approved offline wheelhouse
instead. The profile and lock must be managed by an administrator, not
constructed from attachment contents or chat output.

## Privacy

RapidOCR and ONNX Runtime read the original image and run on CPU.
Recognition verifies its bundled model weights and needs no network.
The image stays on the machine; the attachment path and recognized text
can be visible to your selected chat model provider. Quick OCR never
falls back to a cloud vision service.
