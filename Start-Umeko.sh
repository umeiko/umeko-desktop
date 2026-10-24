#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
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
