"""Remove rejected inline images from model requests while preserving chat history."""
import hashlib
import json
import re
import threading

from umeko_provider_sdk import current_request_cancelled


_OMITTED = ('[Image omitted because the model gateway rejected the request size. '
            'The original remains in the chat. Its visual content is unavailable in this request.]')
_MAX_SESSIONS = 128
_MAX_IMAGES = 32


def _omit_inline_images(messages, omit=None):
    result, removed = [], []
    for message in messages:
        parts = message.get('content')
        if not isinstance(parts, list):
            result.append(message)
            continue
        content = []
        for part in parts:
            image = part.get('image_url') if isinstance(part, dict) and part.get('type') == 'image_url' else None
            url = image.get('url') if isinstance(image, dict) else None
            if isinstance(url, str) and url.startswith('data:image/'):
                digest = hashlib.sha256(url.encode()).hexdigest()
                if omit is None or digest in omit:
                    removed.append(digest)
                    part = {'type': 'text', 'text': _OMITTED}
            content.append(part)
        result.append({**message, 'content': content})
    return (result if removed else messages), removed


def _size_rejection(response):
    status = response.get('status')
    if status == 413:
        return True
    if status not in (400, 422):
        return False
    try:
        body = json.loads(response.get('body') or '{}')
        error = body.get('error', body)
        return error.get('code') in ('context_length_exceeded', 'context_window_exceeded')
    except (AttributeError, ValueError, TypeError):
        return False


class ContextImageRecovery:
    def __init__(self, directory):
        self.path = directory / 'cache' / 'rejected-context-images.json'
        self.lock = threading.Lock()
        try:
            if self.path.stat().st_size > 512 * 1024:
                raise ValueError('Oversized context image cache')
            saved = json.loads(self.path.read_text(encoding='utf-8'))
            self.rejected = {session: [key for key in keys[-_MAX_IMAGES:]
                                      if isinstance(key, str) and re.fullmatch(r'[a-f0-9]{64}', key)]
                             for session, keys in list(saved.items())[-_MAX_SESSIONS:] if isinstance(keys, list)}
        except (AttributeError, OSError, ValueError):
            self.rejected = {}

    def _remember(self, session, removed):
        with self.lock:
            previous = self.rejected.pop(session, [])
            self.rejected[session] = list(dict.fromkeys([*previous, *removed]))[-_MAX_IMAGES:]
            if len(self.rejected) > _MAX_SESSIONS:
                del self.rejected[next(iter(self.rejected))]
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix('.tmp')
                temporary.write_text(json.dumps(self.rejected), encoding='utf-8')
                temporary.replace(self.path)
            except OSError:
                # Continue using the in-memory suppression even on read-only profiles.
                pass

    def events(self, session, messages, records, open_events):
        with self.lock:
            omit = frozenset(self.rejected.get(session, ()))
        if omit:
            messages, _ = _omit_inline_images(messages, omit)
        events = iter(open_events(messages))
        try:
            first = next(events, None)
        except (ValueError, OSError):
            if (not records or not _size_rejection(records[-1].get('response', {}))
                    or current_request_cancelled().is_set()):
                raise
            fallback, removed = _omit_inline_images(messages)
            if not removed:
                raise
            # Retry only a rejected request, before any response or tool call
            # can have reached the chat. A second rejection propagates.
            events = iter(open_events(fallback))
            first = next(events, None)
            if first is not None:
                self._remember(session, removed)
        if first is not None:
            yield first
        yield from events
