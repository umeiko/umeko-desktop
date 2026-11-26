"""Incremental transcript delivery over the terminal's bounded local frames."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator


TEXT_FIELDS = ("text", "thinking")
CHUNK_CHARS = 16_384


def text_updates(field, text):
    for start in range(0, len(text), CHUNK_CHARS):
        yield {"event": "transcript", "field": field, "append": text[start:start + CHUNK_CHARS]}


def row_metadata(row):
    return {key: value for key, value in row.items() if key not in TEXT_FIELDS}


def updates(previous, current):
    unchanged = 0
    for old, new in zip(previous, current):
        if old != new:
            break
        unchanged += 1
    if unchanged == len(current) == len(previous):
        return
    if unchanged + 1 == len(current) == len(previous):
        old, new = previous[-1], current[-1]
        if row_metadata(old) == row_metadata(new) and all(new[key].startswith(old[key]) for key in TEXT_FIELDS):
            for key in TEXT_FIELDS:
                yield from text_updates(key, new[key][len(old[key]):])
            yield {"event": "transcript", "complete": True}
            return
    yield {"event": "transcript", "keep": unchanged}
    for row in current[unchanged:]:
        yield {"event": "transcript", "row": row_metadata(row)}
        for key in TEXT_FIELDS:
            yield from text_updates(key, row[key])
    yield {"event": "transcript", "complete": True}


@dataclass
class TranscriptFeed:
    sent: list[dict] = field(default_factory=list)
    latest: list[dict] | None = None
    state: dict | None = None
    sending: Iterator[dict] | None = None

    def next_frame(self):
        if self.sending is None:
            if self.latest is None:
                return None
            self.sending = updates(self.sent, self.latest)
            self.sent, self.latest = self.latest, None
        frame = next(self.sending, None)
        if frame is None:
            self.sending = None
            return self.next_frame()
        return frame
