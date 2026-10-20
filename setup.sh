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
echo 'Ready. Run ./Start-Umeko.sh (or double-click Start-Umeko.command on macOS).'
