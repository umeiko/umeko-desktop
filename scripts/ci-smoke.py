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
from scripts.ci_process import run_logged


def isolated_profile(directory):
    # This verifier intentionally runs with system Python, outside the app's
    # virtualenv. Seed only the preference override using the standard library.
    directory.mkdir(parents=True, exist_ok=True)
    settings = directory / 'settings.json'
    data = json.loads(settings.read_text(encoding='utf-8')) if settings.exists() else {}
    data.setdefault('agent', {})['agentDir'] = str((directory / 'agent').resolve())
    settings.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def verify_preview_network(node, resources, environment):
    """Exercise the packaged helper's imports and safe protocol without networking."""
    result = subprocess.run([str(node), str(resources / 'runtime/preview-network.mjs'), 'classify'],
        input='CERTIFICATE_VERIFY_FAILED', capture_output=True, text=True, env=environment,
        timeout=15, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        category = json.loads(result.stdout).get('category')
    except (ValueError, AttributeError):
        category = None
    if result.returncode or category != 'certificate':
        raise RuntimeError('Packaged Preview network helper is unavailable')


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
    isolated_profile(report_dir / 'preview-profile')
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
                raise RuntimeError('Frozen Windows browser failed: '
                    + f'returncode={process.returncode}, ready={ready.is_set()}, visibleChromeChild={bool(seen)}\n'
                    + log + '\nstderr:\n' + stderr.decode('utf-8', errors='replace'))
        finally:
            server.shutdown()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", default="dist")
    parser.add_argument("--preview", action="store_true",
                        help="Only package startup and core runtime checks; skip extended UI scenarios")
    args = parser.parse_args()
    output = ROOT / args.dist
    if sys.platform == "darwin":
        executable = output / "Umeko.app/Contents/MacOS/Umeko"
        resources = output / "Umeko.app/Contents/Frameworks"
    else:
        executable = output / ("Umeko/Umeko.exe" if sys.platform == "win32" else "Umeko/Umeko")
        resources = output / "Umeko/_internal"
    if not executable.is_file(): raise RuntimeError("Packaged executable is missing")
    skill_source = resources / 'bundled-skills/sources.json'
    skills = json.loads(skill_source.read_text(encoding='utf-8'))
    if len(skills) != 9 or any(not (skill_source.parent / row['name'] / 'SKILL.md').is_file() for row in skills):
        raise RuntimeError('Preinstalled Skill distribution is incomplete')
    report_dir = ROOT / "build/ci-smoke"
    report_dir.mkdir(parents=True, exist_ok=True)
    diagnostic = report_dir / "application.log"
    screenshot = report_dir / "application.png"
    stacks = report_dir / "application-stacks.log"
    isolated_profile(report_dir / 'profile')
    environment = dict(os.environ, UMEKO_DATA_DIR=str(report_dir / "profile"),
        UMEKO_DIAGNOSTICS=str(diagnostic), UMEKO_SMOKE_STACKS=str(stacks),
        QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software")
    environment["PATH"] = str(report_dir / "no-system-node")
    environment.pop("NODE_OPTIONS", None); environment.pop("NODE_PATH", None)
    for name in ('QT_PLUGIN_PATH', 'LD_LIBRARY_PATH', 'QML_IMPORT_PATH', 'QML2_IMPORT_PATH'):
        environment.pop(name, None)
    node = resources / "runtime/node" / ("node.exe" if os.name == "nt" else "bin/node")
    if not node.is_file(): raise RuntimeError("Bundled Node.js is missing")
    verify_preview_network(node, resources, environment)
    diagnostic.unlink(missing_ok=True)
    stacks.unlink(missing_ok=True)
    output_log = report_dir / "application-output.log"
    try:
        result = run_logged([str(executable), "--smoke", "--snapshot", str(screenshot)],
            output_log, env=environment, timeout=45)
    except subprocess.TimeoutExpired:
        for path in (output_log, diagnostic, stacks):
            if path.is_file():
                print(path.name + ':\n' + path.read_text(encoding='utf-8', errors='replace'), flush=True)
        raise
    gui_output = output_log.read_text(encoding="utf-8", errors="replace")
    log = diagnostic.read_text(encoding="utf-8") if diagnostic.exists() else ""
    lines = log.strip().splitlines()
    selected = next((line.split(":", 1)[1] for line in lines if line.startswith("NODE_EXECUTABLE:")), "")
    expected = ['QML_READY', 'NATIVE_NOTIFICATIONS_READY:1']
    if sys.platform.startswith('linux'): expected.append('IME_PLUGIN_READY:1')
    expected += ["NODE_EXECUTABLE:" + selected, "TRAY_ICON_READY:1", "EXIT:0"]
    if result.returncode or lines != expected or not selected or Path(selected).resolve() != node.resolve():
        raise RuntimeError("Frozen GUI startup failed: " + log + gui_output[-2000:])
    if sys.platform == 'win32' and not args.preview:
        verify_windows_preview(executable, environment, report_dir)
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
    for name in ("bridge.mjs", "package-install.mjs", "update-engine.mjs", "update-cleanup.mjs", "provider-policy.mjs", "resources.mjs", "chatbox.mjs", "network-retry.mjs", "pi-commands.mjs", "umeko-control.mjs", "umeko-documents.mjs", "widget-messages.mjs", "background-jobs.mjs", "process-guard.mjs", "tool-permissions.mjs", "umeko-operations.json", "webview-component.mjs", "webview-component.json"):
        if hashlib.sha256((runtime / name).read_bytes()).digest() != hashlib.sha256((ROOT / "runtime" / name).read_bytes()).digest():
            raise RuntimeError("Packaged Pi bridge differs from the source: " + name)
    for name in ("subagents.mjs", "subagent-sdk.mjs", "subagent-settings.mjs", "input-queue.mjs", "rpc-ui.mjs", "widget-messages.mjs", "background-jobs.mjs", "process-guard.mjs", "tool-permissions.mjs"):
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
    if not args.preview:
        subprocess.run([str(node), str(ROOT / "scripts/background_jobs_smoke.mjs"), str(runtime)],
                       env=environment, check=True, timeout=45)
    if sys.platform == "darwin":
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(output / "Umeko.app")], check=True)
    (report_dir / "result.json").write_text(json.dumps({"scope": "preview" if args.preview else "full", "gui": "passed", "pi": "passed", "terminal":"passed", "build": metadata}, indent=2), encoding="utf-8")
    print("Packaged GUI rendered; bundled Pi self-test and build provenance verified")


if __name__ == "__main__": main()
