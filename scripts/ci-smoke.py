"""Verify the frozen GUI and bundled Pi on the current build platform."""
from __future__ import annotations

import hashlib
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pi_runtime import RELEASE_NAME, PINNED_VERSION
from app.project_info import VERSION, git_output


def verify_windows_preview(executable, environment, report_dir):
    import ctypes
    from ctypes import wintypes
    ready = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/ready': ready.set()
            raw = b'<title>Packaged preview</title><h1>Umeko WebView</h1><script>requestAnimationFrame(()=>fetch("/ready"))</script>'
            self.send_response(200)
            self.send_header('Content-Type', 'text/html;charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    diagnostic = report_dir / 'web-preview.log'
    diagnostic.unlink(missing_ok=True)
    env = dict(environment, QT_QPA_PLATFORM='windows', UMEKO_DIAGNOSTICS=str(diagnostic),
               UMEKO_DATA_DIR=str(report_dir / 'preview-profile'), UMEKO_WEB_PREVIEW_URL=f'http://127.0.0.1:{server.server_port}/')
    user32 = ctypes.windll.user32
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback, wintypes.LPARAM]
    user32.EnumChildWindows.argtypes = [wintypes.HWND, callback, wintypes.LPARAM]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    seen = []
    with subprocess.Popen([str(executable), '--demo', '--smoke'], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        @callback
        def child(handle, unused):
            name = ctypes.create_unicode_buffer(200)
            user32.GetClassNameW(handle, name, len(name))
            if name.value == 'Chrome_RenderWidgetHostHWND' and user32.IsWindowVisible(handle):
                seen.append(True)
            return True
        @callback
        def window(handle, unused):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
            if pid.value == process.pid: user32.EnumChildWindows(handle, child, 0)
            return True
        try:
            deadline = time.monotonic() + 20
            while process.poll() is None and time.monotonic() < deadline:
                user32.EnumWindows(window, 0)
                time.sleep(0.05)
            if process.poll() is None:
                process.kill()
                raise RuntimeError('Frozen browser did not exit its smoke test')
            stdout, stderr = process.communicate(timeout=5)
            (report_dir / 'web-preview-output.log').write_bytes(stdout + stderr)
            log = diagnostic.read_text(encoding='utf-8') if diagnostic.exists() else ''
            if process.returncode or not ready.is_set() or not seen or 'WebSurface.qml:' in log or 'EXIT:0' not in log:
                raise RuntimeError('Frozen Windows browser failed: ' + log)
        finally:
            server.shutdown()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", default="dist")
    output = ROOT / parser.parse_args().dist
    if sys.platform == "darwin":
        executable = output / "Umeko.app/Contents/MacOS/Umeko"
        resources = output / "Umeko.app/Contents/Frameworks"
    else:
        executable = output / ("Umeko/Umeko.exe" if sys.platform == "win32" else "Umeko/Umeko")
        resources = output / "Umeko/_internal"
    if not executable.is_file(): raise RuntimeError("Packaged executable is missing")
    report_dir = ROOT / "build/ci-smoke"
    report_dir.mkdir(parents=True, exist_ok=True)
    diagnostic = report_dir / "application.log"
    screenshot = report_dir / "application.png"
    environment = dict(os.environ, UMEKO_DATA_DIR=str(report_dir / "profile"),
        UMEKO_DIAGNOSTICS=str(diagnostic), QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software")
    environment["PATH"] = str(report_dir / "no-system-node")
    environment.pop("NODE_OPTIONS", None); environment.pop("NODE_PATH", None)
    for name in ('QT_PLUGIN_PATH', 'LD_LIBRARY_PATH', 'QML_IMPORT_PATH', 'QML2_IMPORT_PATH'):
        environment.pop(name, None)
    node = resources / "runtime/node" / ("node.exe" if os.name == "nt" else "bin/node")
    if not node.is_file(): raise RuntimeError("Bundled Node.js is missing")
    diagnostic.unlink(missing_ok=True)
    result = subprocess.run([str(executable), "--smoke", "--snapshot", str(screenshot)],
        env=environment, timeout=45, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (report_dir / "application-output.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    log = diagnostic.read_text(encoding="utf-8") if diagnostic.exists() else ""
    lines = log.strip().splitlines()
    selected = next((line.split(":", 1)[1] for line in lines if line.startswith("NODE_EXECUTABLE:")), "")
    expected = ['QML_READY', 'NATIVE_NOTIFICATIONS_READY:1']
    if sys.platform.startswith('linux'): expected.append('IME_PLUGIN_READY:1')
    expected += ["NODE_EXECUTABLE:" + selected, "TRAY_ICON_READY:1", "EXIT:0"]
    if result.returncode or lines != expected or not selected or Path(selected).resolve() != node.resolve():
        raise RuntimeError("Frozen GUI startup failed: " + log + result.stderr[-2000:])
    if sys.platform == 'win32': verify_windows_preview(executable, environment, report_dir)
    if not screenshot.is_file() or screenshot.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError("Frozen GUI did not render a screenshot")
    from terminal_smoke import verify_terminal_worker
    verify_terminal_worker([str(executable),'--umeko-plugin-worker'],resources,environment,report_dir)
    metadata = json.loads((resources / "build-info.json").read_text(encoding="utf-8"))
    if metadata["version"] != VERSION or metadata["commit"] != git_output(ROOT, "rev-parse", "HEAD"):
        raise RuntimeError("Frozen build provenance is missing")
    for name in ("umeko-provider-sdk-0.2.1.zip", "develop-umeko-provider.zip", "create-umeko-character.zip"):
        if not (resources / "provider-resources" / name).is_file():
            raise RuntimeError("Provider development resource is missing: " + name)
    runtime = resources / "runtime/releases" / RELEASE_NAME
    for name in ("fd", "rg"):
        tool = runtime / "bin" / (name + (".exe" if os.name == "nt" else ""))
        subprocess.run([str(tool), "--version"], check=True, capture_output=True, timeout=15)
    for name in ("bridge.mjs", "provider-policy.mjs", "resources.mjs", "chatbox.mjs", "network-retry.mjs", "pi-commands.mjs", "umeko-control.mjs", "umeko-documents.mjs", "widget-messages.mjs", "umeko-operations.json", "webview-component.mjs", "webview-component.json"):
        if hashlib.sha256((runtime / name).read_bytes()).digest() != hashlib.sha256((ROOT / "runtime" / name).read_bytes()).digest():
            raise RuntimeError("Packaged Pi bridge differs from the source: " + name)
    for name in ("subagents.mjs", "subagent-sdk.mjs", "subagent-settings.mjs", "input-queue.mjs", "rpc-ui.mjs", "widget-messages.mjs"):
        if not (runtime / name).is_file() or not (resources / "runtime" / name).is_file():
            raise RuntimeError("Bundled subagent runtime module is missing: " + name)
    npm = resources / "runtime/node" / ("node_modules/npm/bin/npm-cli.js" if os.name == "nt" else "lib/node_modules/npm/bin/npm-cli.js")
    for document in (ROOT/'runtime/umeko-docs').glob('*.md'):
        if (runtime/'umeko-docs'/document.name).read_bytes() != document.read_bytes():
            raise RuntimeError('Packaged Umeko document differs: ' + document.name)
    subprocess.run([str(node), str(npm), "--version"], env=environment, check=True, capture_output=True, timeout=15)
    pi = subprocess.run([str(node), str(runtime / "bridge.mjs"), "--self-test"],
        env=environment, timeout=60, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (report_dir / "pi.log").write_text(pi.stdout + pi.stderr, encoding="utf-8")
    if pi.returncode or '"ok":true' not in pi.stdout or '"version":"' + PINNED_VERSION + '"' not in pi.stdout:
        raise RuntimeError("Packaged Pi self-test failed: " + pi.stdout[-1500:] + pi.stderr[-1500:])
    if sys.platform == "darwin":
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(output / "Umeko.app")], check=True)
    (report_dir / "result.json").write_text(json.dumps({"gui": "passed", "pi": "passed", "terminal":"passed", "build": metadata}, indent=2), encoding="utf-8")
    print("Packaged GUI rendered; bundled Pi self-test and build provenance verified")


if __name__ == "__main__": main()
