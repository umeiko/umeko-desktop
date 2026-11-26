"""Private local connection shared by the desktop, terminal and ACP adapter."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

MAX_FRAME = 2 * 1024 * 1024


def endpoint(directory):
    return "umeko-terminal-v1-" + hashlib.sha256(str(Path(directory).resolve()).encode()).hexdigest()[:32]


def encode(value):
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def frames(socket):
    while socket.canReadLine():
        line = bytes(socket.readLine(MAX_FRAME + 1))
        if len(line) > MAX_FRAME or not line.endswith(b"\n"):
            raise ValueError("Terminal message is too large")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("Expected a terminal message object")
        yield value
    if socket.bytesAvailable() >= MAX_FRAME:
        raise ValueError("Terminal message is too large")
