"""Loopback-only static HTML preview, confined to one document directory."""
import mimetypes
import os
import secrets
import stat
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

HTML_LIMIT = 4 * 1024 * 1024
ASSET_LIMIT = 32 * 1024 * 1024
STATIC_SUFFIXES = set("html htm css js mjs json map svg png jpg jpeg gif webp avif ico bmp woff woff2 ttf otf eot wasm csv tsv txt mp4 webm mp3 ogg wav pdf".split())


class StaticPreview:
    def __init__(self):
        self._lock = threading.Lock()
        self._root, self._token = None, ""
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.serve(True)

            def do_HEAD(self):
                self.serve(False)

            def serve(self, body):
                path = unquote(urlsplit(self.path).path)
                with owner._lock:
                    root, token = owner._root, owner._token
                parts = path.split("/")
                if root is None or len(parts) < 3 or not secrets.compare_digest(parts[1], token):
                    self.send_error(404)
                    return
                relative = parts[2:]
                if any(not part or part.startswith(".") or "\\" in part or "\0" in part for part in relative):
                    self.send_error(404)
                    return
                try:
                    target = root.joinpath(*relative).resolve(strict=True)
                    if not target.is_relative_to(root) or target.suffix.lower().lstrip(".") not in STATIC_SUFFIXES:
                        raise OSError("Not a static asset")
                    fd = os.open(target, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0) | getattr(os,"O_NOFOLLOW",0))
                    with os.fdopen(fd, "rb") as stream:
                        info = os.fstat(stream.fileno())
                        if not stat.S_ISREG(info.st_mode):
                            raise OSError("Not a regular file")
                        limit = HTML_LIMIT if target.suffix.lower() in (".html", ".htm") else ASSET_LIMIT
                        if info.st_size > limit:
                            self.send_error(413)
                            return
                        self.send_response(200)
                        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
                        self.send_header("Content-Length", str(info.st_size))
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Referrer-Policy", "no-referrer")
                        self.send_header("X-Content-Type-Options", "nosniff")
                        self.end_headers()
                        if body:
                            remaining = info.st_size
                            while remaining:
                                chunk = stream.read(min(65536, remaining))
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                remaining -= len(chunk)
                except (OSError, ValueError):
                    if not self.wfile.closed:
                        try:
                            self.send_error(404)
                        except OSError:
                            pass

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, name="html-preview", daemon=True).start()

    def open(self, file):
        file = Path(file).resolve(strict=True)
        with self._lock:
            if self._root != file.parent or not self._token:
                self._token = secrets.token_urlsafe(32)
                self._root = file.parent
            token = self._token
        return f"http://127.0.0.1:{self.server.server_port}/{token}/{quote(file.name)}"

    def revoke(self):
        with self._lock:
            self._root, self._token = None, ""

    def close(self):
        self.revoke()
        self.server.shutdown()
        self.server.server_close()
