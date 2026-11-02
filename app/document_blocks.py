"""A virtual document: source and rendered blocks are accessed only as needed."""
import json
import subprocess
import threading
import time
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


def source_blocks(text):
    start = 0
    while start < len(text):
        end = min(start + 8192, len(text))
        line = text.find('\n', start)
        for _ in range(79):
            if line < 0 or line >= end:
                break
            following = text.find('\n', line + 1)
            if following < 0 or following >= end:
                break
            line = following
        if start < line < end:
            end = line + 1
        yield {'kind': 'source', 'text': text[start:end], 'html': '', 'anchor': ''}
        start = end


def parse_markdown(text, cancelled=lambda: False):
    from .pi_runtime import node_executable, node_environment, CREATE_NO_WINDOW, RELEASE_NAME
    root = Path(__file__).resolve().parents[1]
    script = root / 'runtime/markdown-preview.mjs'
    if not (root / 'runtime/node_modules/marked').is_dir():
        script = root / 'runtime/releases' / RELEASE_NAME / 'markdown-preview.mjs'
    process = subprocess.Popen([node_executable(), str(script)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW,
        env=node_environment())
    payload = text.encode('utf-8')
    # Retrying communicate() cannot finish a partial input on POSIX. Let the
    # writer own and close stdin while communicate() only drains the output.
    input_stream = process.stdin
    process.stdin = None
    def write_input():
        try:
            with input_stream:
                input_stream.write(payload)
        except (BrokenPipeError, OSError):
            pass
    writer = threading.Thread(target=write_input, daemon=True)
    writer.start()
    deadline = time.monotonic() + 30
    try:
        while True:
            if cancelled():
                raise InterruptedError('Document changed')
            if time.monotonic() >= deadline:
                raise TimeoutError('Markdown parsing timed out')
            try:
                output, error = process.communicate(timeout=.05)
                break
            except subprocess.TimeoutExpired:
                pass
        if process.returncode:
            raise RuntimeError(error.decode('utf-8', 'replace')[:300])
        return json.loads(output)['blocks']
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
        writer.join(timeout=1)


class DocumentBlocks(QAbstractListModel):
    BlockRole = Qt.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rendered, self.source, self.rows = [], [], []

    def roleNames(self):
        return {self.BlockRole: b'block'}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        return self.rows[index.row()] if index.isValid() and role == self.BlockRole and 0 <= index.row() < len(self.rows) else None

    def load(self, blocks, source, mode='rendered'):
        self.beginResetModel()
        self.rendered, self.source = blocks, source
        self.rows = self.source if mode == 'source' else self.rendered
        self.endResetModel()

    def set_mode(self, mode):
        rows = self.source if mode == 'source' else self.rendered
        if rows is self.rows:
            return
        self.beginResetModel(); self.rows = rows; self.endResetModel()

    def anchor(self, name):
        return next((i for i, row in enumerate(self.rows) if row.get('anchor') == name), -1)
