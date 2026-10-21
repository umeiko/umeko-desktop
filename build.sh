#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
output="${1:-dist}"
.venv/bin/python - "$output" <<'PY'
from pathlib import Path
import sys
root = Path.cwd().resolve()
output = (root / sys.argv[1]).resolve()
if output == root or not output.is_relative_to(root):
    raise SystemExit('Build output must stay inside this workspace')
PY
.venv/bin/python -m pip install pyinstaller==6.19.0
.venv/bin/python scripts/bundle_node.py
.venv/bin/python prepare_runtime.py
.venv/bin/python scripts/fetch-search-tools.py
QT_QPA_PLATFORM=offscreen .venv/bin/python build_icons.py
.venv/bin/python scripts/write-build-info.py
.venv/bin/python scripts/build-provider-resources.py
extra=()
if [[ "$(uname -s)" == Darwin ]]; then
    extra+=(--icon app/icons/app.icns --hidden-import keyring.backends.macOS)
else
    extra+=(--hidden-import keyring.backends.SecretService --hidden-import keyring.backends.kwallet)
fi
.venv/bin/python -m PyInstaller --clean --noconfirm --windowed --onedir --name Umeko \
    --distpath "$output" "${extra[@]}" --collect-all keyring \
    --add-data 'app/qml:app/qml' --add-data 'app/icons:app/icons' \
    --add-data 'runtime/bridge.mjs:runtime' --add-data 'runtime/provider-policy.mjs:runtime' \
    --add-data 'runtime/resources.mjs:runtime' --add-data 'runtime/chatbox.mjs:runtime' \
    --add-data 'build/build-info.json:.' --add-data 'build/provider-resources:provider-resources' --add-data 'THIRD_PARTY_NOTICES.md:.' main.py
.venv/bin/python - "$output" <<'PY'
from pathlib import Path
import shutil, sys
from app.pi_runtime import RELEASE_NAME
root = Path.cwd().resolve()
output = (root / sys.argv[1]).resolve()
if not output.is_relative_to(root) or output == root:
    raise SystemExit('Build output must stay inside this workspace')
targets = [output / 'Umeko/_internal']
if sys.platform == 'darwin':
    targets.append(output / 'Umeko.app/Contents/Frameworks')
for target in targets:
    if target.is_dir():
        shutil.copytree(root / 'runtime/releases' / RELEASE_NAME, target / 'runtime/releases' / RELEASE_NAME, dirs_exist_ok=True)
        shutil.copytree(root / 'runtime/node', target / 'runtime/node', dirs_exist_ok=True, symlinks=True)
shutil.copy2(root / 'README.md', output / 'Umeko/README.md')
print('Build output:', output)
PY
if [[ "$(uname -s)" == Darwin ]]; then
    /usr/bin/codesign --force --deep --sign - "$output/Umeko.app"
fi
