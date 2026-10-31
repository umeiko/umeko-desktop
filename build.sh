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
.venv/bin/python -m pip install pyinstaller==6.19.0 cmake==3.31.6
.venv/bin/python scripts/build-notifications.py
.venv/bin/python scripts/webview_package.py --frontend build/webview-support
if [[ "$(uname -s)" == Linux ]]; then .venv/bin/python scripts/build-input-method.py; fi
.venv/bin/python scripts/bundle_node.py
.venv/bin/python prepare_runtime.py
.venv/bin/python scripts/fetch-search-tools.py
QT_QPA_PLATFORM=offscreen .venv/bin/python build_icons.py
.venv/bin/python scripts/write-build-info.py
.venv/bin/python scripts/build-provider-resources.py
.venv/bin/python scripts/build-desktop-plugin-resources.py
extra=()
if [[ "$(uname -s)" == Darwin ]]; then
    extra+=(--icon app/icons/app.icns --osx-bundle-identifier io.github.umeiko.umeko-desktop --hidden-import keyring.backends.macOS --add-binary "build/notification-runtime/libumeko_notifications.dylib:notification-runtime")
else
    extra+=(--add-binary "build/input-method/plugins/platforminputcontexts/libfcitx5platforminputcontextplugin.so:PySide6/Qt/plugins/platforminputcontexts" --hidden-import PySide6.QtDBus)
    extra+=(--hidden-import keyring.backends.SecretService --hidden-import keyring.backends.kwallet)
fi
bundle_output="$output"
if [[ "$(uname -s)" == Linux ]]; then
    # PyInstaller creates library links; stage on a native filesystem, then copy.
    bundle_output=$(mktemp -d "${TMPDIR:-/tmp}/umeko-freeze.XXXXXX")
    trap 'rm -rf -- "$bundle_output"' EXIT
fi
.venv/bin/python -m PyInstaller --clean --noconfirm --windowed --onedir --name Umeko \
    --distpath "$bundle_output" "${extra[@]}" --collect-all keyring \
    --add-data 'build/desktop-plugin-resources:desktop-plugin-resources' --add-data 'plugin-runtime:plugin-runtime' --add-data 'umeko-plugins:umeko-plugins' --add-data 'app/qml:app/qml' --add-data 'app/theme-prompt.txt:app' --add-data 'app/character-defaults.json:app' --add-data 'app/provider-presets.json:app' --add-data 'app/icons:app/icons' \
    --add-data 'runtime/conversation-search.mjs:runtime' --add-data 'runtime/update-engine.mjs:runtime' --add-data 'runtime/bridge.mjs:runtime' --add-data 'runtime/input-queue.mjs:runtime' --add-data 'runtime/widget-messages.mjs:runtime' --add-data 'runtime/background-jobs.mjs:runtime' --add-data 'runtime/process-guard.mjs:runtime' --add-data 'runtime/tool-permissions.mjs:runtime' --add-data 'runtime/subagents.mjs:runtime' --add-data 'runtime/subagent-sdk.mjs:runtime' --add-data 'runtime/subagent-settings.mjs:runtime' --add-data 'runtime/rpc-ui.mjs:runtime' --add-data 'runtime/provider-policy.mjs:runtime' \
    --add-data 'runtime/resources.mjs:runtime' --add-data 'runtime/chatbox.mjs:runtime' --add-data 'runtime/network-retry.mjs:runtime' --add-data 'runtime/pi-commands.mjs:runtime' --add-data 'runtime/umeko-control.mjs:runtime' --add-data 'runtime/umeko-documents.mjs:runtime' --add-data 'runtime/umeko-operations.json:runtime' --add-data 'runtime/umeko-docs:runtime/umeko-docs' --add-data 'runtime/webview-component.mjs:runtime' --add-data 'runtime/webview-component.json:runtime' --add-data 'build/webview-support:webview-support' \
    --add-data 'build/build-info.json:.' --add-data 'build/provider-resources:provider-resources' --add-data 'THIRD_PARTY_NOTICES.md:.' --add-data 'licenses:licenses' main.py
.venv/bin/python - "$output" "$bundle_output" <<'PY'
from pathlib import Path
import shutil, sys
from app.pi_runtime import RELEASE_NAME
root = Path.cwd().resolve()
output = (root / sys.argv[1]).resolve()
bundle = (root / sys.argv[2]).resolve()
if not output.is_relative_to(root) or output == root:
    raise SystemExit('Build output must stay inside this workspace')
targets = [bundle / 'Umeko/_internal']
if sys.platform == 'darwin':
    targets.append(bundle / 'Umeko.app/Contents/Frameworks')
for target in targets:
    if target.is_dir():
        shutil.copytree(root / 'runtime/releases' / RELEASE_NAME, target / 'runtime/releases' / RELEASE_NAME, dirs_exist_ok=True, ignore=shutil.ignore_patterns('.cache'))
        shutil.copytree(root / 'runtime/node', target / 'runtime/node', dirs_exist_ok=True, symlinks=True)
shutil.copy2(root / 'README.md', bundle / 'Umeko/README.md')
if bundle != output:
    if (output / 'Umeko').exists(): shutil.rmtree(output / 'Umeko')
    shutil.copytree(bundle / 'Umeko', output / 'Umeko', symlinks=False)
print('Build output:', output)
PY
if [[ "$(uname -s)" == Darwin ]]; then
    /usr/bin/codesign --force --deep --sign - "$output/Umeko.app"
fi
