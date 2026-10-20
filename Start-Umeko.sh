#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
# Linux 输入法：vendored fcitx5 插件的 Qt 依赖必须解析到本应用自带的 Qt 库
#（否则 ld 会拉到系统旧版 Qt 的同名库，私有 ABI 冲突导致插件加载失败）
if [[ "$(uname -s)" == "Linux" ]] && [[ -d .local/fcitx5-qt6/lib ]]; then
    QT6LIB=".venv/lib/python3.12/site-packages/PySide6/Qt/lib"
    [[ -d "$QT6LIB" ]] || QT6LIB=$(.venv/bin/python -c "import sysconfig; print(sysconfig.get_paths()['purelib'] + '/PySide6/Qt/lib')")
    export LD_LIBRARY_PATH="$PWD/$QT6LIB:$PWD/.local/fcitx5-qt6/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
if [[ -x dist/Umeko.app/Contents/MacOS/Umeko ]]; then
    exec dist/Umeko.app/Contents/MacOS/Umeko "$@"
elif [[ -x dist/Umeko/Umeko ]]; then
    exec dist/Umeko/Umeko "$@"
elif [[ -x .venv/bin/python ]]; then
    exec .venv/bin/python main.py "$@"
else
    echo 'Run ./setup.sh first.' >&2
    exit 1
fi
