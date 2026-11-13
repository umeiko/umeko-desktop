"""Build history indexes for recently modified conversations while the app is idle.

The first visit to a long conversation otherwise parses its whole transcript
before anything is shown. Indexes persist on disk, so later visits read them
in milliseconds; this module moves that first parse ahead of the visit.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from .transcript_index import Cancelled, LARGE_FILE

WARM_SESSIONS = 3
WARM_DELAY_MS = 3000


def recent_transcripts(sessions, limit=WARM_SESSIONS):
    """The most recently modified transcripts that open through the index."""
    found = []
    for session in sessions:
        file = session.get('file') if isinstance(session, dict) else None
        if not file:
            continue
        try:
            stat = Path(file).stat()
        except OSError:
            continue
        if stat.st_size >= LARGE_FILE:
            found.append((stat.st_mtime_ns, file))
    found.sort(reverse=True)
    return [file for _, file in dict.fromkeys(found)][:limit]


def warm(repository, files, cancelled, paused=lambda: False):
    """Index each file in turn; a user's own read goes first."""
    built = []
    for file in files:
        while paused() and not cancelled():
            time.sleep(0.05)
        if cancelled():
            break
        try:
            repository.open(file, cancelled=cancelled)
            built.append(file)
        except Cancelled:
            break
        except Exception:
            continue  # A transcript being rewritten is indexed on its next visit.
    return built


def start(repository, files, cancelled, paused=lambda: False, finished=lambda built: None):
    def run():
        finished(warm(repository, files, cancelled, paused))
    thread = threading.Thread(target=run, daemon=True, name='transcript-warmup')
    thread.start()
    return thread
