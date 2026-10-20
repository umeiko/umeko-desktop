#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
command -v python3 >/dev/null || { echo 'Python 3.10+ is required.' >&2; exit 1; }
command -v node >/dev/null || { echo 'Node.js 22.19+ is required.' >&2; exit 1; }
command -v npm >/dev/null || { echo 'npm is required to install the Pi kernel.' >&2; exit 1; }
[[ -x .venv/bin/python ]] || python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci --prefix runtime --ignore-scripts --no-audit --no-fund
.venv/bin/python prepare_runtime.py
.venv/bin/python scripts/fetch-search-tools.py

# Linux + fcitx5：安装预编译输入法插件（Qt 6.10 构建，来源见 docs/linux-ime-fcitx5.md）
if [[ "$(uname -s)" == "Linux" ]] && command -v fcitx5-remote >/dev/null 2>&1; then
    IME_DIR=.local/fcitx5-qt6
    IME_URL="https://github.com/umeiko/umeko-desktop/releases/download/linux-ime-fcitx5-qt6-v1/umeko-fcitx5-qt6-linux-x64.tar.gz"
    if [[ ! -f "$IME_DIR/plugin/libfcitx5platforminputcontextplugin.so" ]]; then
        mkdir -p "$IME_DIR"
        curl -fsSL "$IME_URL" | tar xz -C "$IME_DIR"
        SITE_PLUGINS=$(.venv/bin/python -c "import sysconfig; print(sysconfig.get_paths()['purelib'] + '/PySide6/Qt/plugins/platforminputcontexts')")
        cp "$IME_DIR/plugin/libfcitx5platforminputcontextplugin.so" "$SITE_PLUGINS/"
        echo 'fcitx5 输入法插件已安装。'
    fi
fi

echo 'Ready. Run ./Start-Umeko.sh (or double-click Start-Umeko.command on macOS).'
