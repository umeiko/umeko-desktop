"""Initialize the shared Qt WebView2 profile before the frozen-app CI check.

The former Windows interaction smoke incidentally did this. Qt 6.10.2 stores
WebView2 data in QStandardPaths.AppLocalDataLocation/WebView2, independently of
UMEKO_DATA_DIR. Keep this first-run preparation without pointer interactions.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if sys.platform != "win32":
    raise SystemExit("This CI preparation is Windows-only")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["QT_QPA_PLATFORM"] = "windows"

from PySide6.QtCore import QStandardPaths, QTimer
from main import create_application


def main():
    ready = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/ready":
                ready.set()
            body = b'<title>Browser initialization</title><script>requestAnimationFrame(()=>fetch("/ready"))</script>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html;charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with tempfile.TemporaryDirectory(prefix="umeko-ci-webview-") as temporary:
        os.environ["UMEKO_DATA_DIR"] = str(Path(temporary) / "profile")
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        app, engine, controller = create_application()
        window = engine.rootObjects()[0]
        window.raise_()
        window.requestActivate()
        profile = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)) / "WebView2"
        print("WebView2 profile:", profile, flush=True)
        poll = QTimer()
        poll.setInterval(50)
        poll.timeout.connect(lambda: app.quit() if ready.is_set() else None)
        poll.start()
        # Bound first-run preparation; the packaged-app check retains its own
        # existing startup deadline and verifies the actual frozen browser.
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(app.quit)
        deadline.start(30_000)
        QTimer.singleShot(0, lambda: controller.webRequested.emit(
            f"http://127.0.0.1:{server.server_port}/", "Browser initialization"))
        try:
            result = app.exec()
        finally:
            poll.stop()
            deadline.stop()
            controller.close()
            import shiboken6
            shiboken6.delete(engine)
            server.shutdown()
        if result or not ready.is_set():
            raise RuntimeError("Windows browser profile initialization did not render the local page within 30 seconds")
        print("Windows browser profile initialized; no pointer interactions", flush=True)


if __name__ == "__main__":
    main()
