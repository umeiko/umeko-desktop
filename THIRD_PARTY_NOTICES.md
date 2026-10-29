# Third-party notices

## Bundled search tools

Release bundles include fd 10.3.0 (MIT or Apache-2.0, https://github.com/sharkdp/fd/tree/v10.3.0) and ripgrep 14.1.1 (MIT or Unlicense, https://github.com/BurntSushi/ripgrep/tree/14.1.1) so Pi's find/grep tools work without a first-run download. Their upstream license files accompany the binaries under `runtime/releases/coding-1.3.0/bin`. Archive SHA-256 values are pinned in `scripts/search-tools.json`.

Qt / PySide6 is provided under its upstream LGPLv3 / GPLv3 / commercial terms. The application dynamically loads the unmodified Qt libraries. Their notices and license files are included in the installed PySide6 distribution. Source and licensing: https://www.qt.io/licensing/ and https://code.qt.io/pyside/pyside-setup.git/ .

Pi Coding Agent and its dependencies are from https://github.com/earendil-works/pi (version 1.3.0). The complete upstream coding agent, tools, resource loader and session implementation are retained unmodified. The Pi AI built-in provider catalog and generated model list are replaced with empty catalogs; the application registers its explicit loopback gateway. Upstream protocol SDKs and their individual licenses remain in the runtime node_modules directory.

Copyright (c) 2025 Mario Zechner

MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

Dependencies retain their license files in the runtime's node_modules directory. PyInstaller uses GPLv2 with its bootloader exception; application packaging is permitted by that exception. Locally drawn SVG interface icons are part of this project. The application avatar icon was supplied by the user.

## Pi subagents

Release bundles include the unmodified npm package `@gotgenes/pi-subagents` 25.0.5 (MIT) in the runtime's `node_modules` directory. Official source: https://github.com/gotgenes/pi-packages/tree/pi-subagents-v25.0.5/packages/pi-subagents . The full upstream copyright and permission notice is included in `licenses/pi-subagents-MIT.txt` and retained with the package.

## Background jobs

The bundled background-job extension uses `@alexlikevibe/pi-bg` 2.3.0 (MIT), specifically its per-session registry and file-backed spawn primitive. Its default extension entry is not loaded. The hidden Windows spawn implementation is adapted from that primitive; process-tree termination and cursor-based reads are Umeko adaptations. Source: https://github.com/iefnaf/pi-bg . The upstream license is retained in `licenses/pi-bg-MIT.txt` and with the npm package. The bash guard follows the `tool_call` blocking mechanism in Pi's `permission-gate.ts` example; no confirmation UI is used.

## Pygments 2.19.2

Syntax tokenization uses Pygments, under its BSD 2-Clause license. Project: https://pygments.org/ . Authors: https://github.com/pygments/pygments/blob/2.19.2/AUTHORS .

Copyright (c) 2006-2022 by the respective authors (see AUTHORS file).
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

* Redistributions of source code must retain the above copyright
  notice, this list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright
  notice, this list of conditions and the following disclaimer in the
  documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

## Bundled Node.js and npm

Release packages include the official Node.js 22.23.3 distribution and npm from https://nodejs.org/dist/v22.23.3/ . The full distribution retains its LICENSE files and npm dependency notices under `runtime/node/`. Downloads are pinned by SHA-256 in `scripts/node-distributions.json`; the archive origin and version are recorded in build metadata.

## Provider brand icons

The Claude and MiniMax marks are from LobeHub Icons (MIT); see `licenses/LobeHub-Icons.txt`. OpenAI, Kimi, DeepSeek and the GLM/ZCode Z icon come from their official sites. Brand marks belong to their respective owners. Source URLs and SHA-256 values are recorded in `app/icons/providers/sources.json`.

## Native notifications

Windows notifications use WinToast 1.3.2 (MIT), pinned to commit 693efb90376809d1e1b4e6ce867171ce20fe7e76; license: `licenses/WinToast.txt`. Small local changes retain Notification Center click handlers after banner timeout and serialize notification-buffer access. macOS uses the system UserNotifications framework; Linux uses the desktop D-Bus service.

## Fcitx5 Qt input plugin

Linux builds compile fcitx5-qt 5.1.13 from https://github.com/fcitx/fcitx5-qt (archive SHA-256 74b2c43ca865ec9ede257bcd3bdadafc20f571900cb2440a4488335e4d4e91cc) against the bundled Qt. DBusAddons is linked into the plugin. BSD-3-Clause and LGPL-2.1-or-later texts are included under licenses/fcitx5-qt. The pinned unmodified source can be downloaded using native/input-method/fetch.py; the build configuration is included in this repository.

## dbus-next

Python Linux builds use dbus-next 0.2.3 (https://github.com/altdesktop/python-dbus-next), Copyright (c) 2019 Tony Crisci, under the MIT license; see licenses/dbus-next.txt.
