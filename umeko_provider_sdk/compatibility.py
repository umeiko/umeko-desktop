"""Response-driven parameter recovery and bounded HTTP retries for model APIs.

The caller identifies automatically added fields. Explicit user fields retain
their values. Retry-After parsing and exponential jitter follow openai-python's
BaseClient; this transport retries 429/503 twice before returning the error.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import io
import json
import math
import os
from pathlib import Path
import random
import re
import threading
import time
import urllib.error
import urllib.request

from . import current_request_cancelled
from .errors import format_http_error
from .network import TracedResponse
from .streaming import upstream_error


def _payload(value):
    try:
        return json.loads(value) if isinstance(value, (str, bytes)) else value
    except (ValueError, TypeError):
        return None


def raise_api_error(payload):
    """Surface service error envelopes even when the HTTP status is 200."""
    error = upstream_error(payload) if isinstance(payload, dict) else None
    if error:
        raise error


def rejected_parameters(status, raw, automatic):
    """Select named automatic fields from parameter-specific client errors."""
    if not 400 <= status < 500 or status in (401, 403, 408, 425, 429):
        return set()
    payload = _payload(raw)
    detail = payload.get('error', payload) if isinstance(payload, dict) else {}
    text = json.dumps(payload, ensure_ascii=False) if payload is not None else str(raw)
    # Authentication, routing, quota and context errors are handled by the user.
    if re.search(r'authentication|unauthorized|invalid.?api.?key|insufficient_quota|context_length|context window', text, re.I):
        return set()
    explicit = set()
    if isinstance(detail, dict):
        param = detail.get('param') or detail.get('parameter')
        if isinstance(param, str): explicit.add(re.sub(r'\[(\d+)\]', r'.\1', param))
        for item in detail.get('detail', []) if isinstance(detail.get('detail'), list) else []:
            if isinstance(item, dict):
                loc = item.get('loc', [])
                if isinstance(loc, (list, tuple)):
                    explicit.add('.'.join(str(part) for part in loc if part not in ('body', 'request')))
    clear = bool(explicit) or bool(re.search(
        r'unsupported|not supported|unrecognized|unknown (?:parameter|argument|field)|'
        r'invalid (?:parameter|value|argument)|extra_forbidden|literal_error|validation_error|'
        r'not permitted|not allowed|does not support', text, re.I))
    if not clear:
        return set()
    return {name for name in automatic if name in explicit or any(
        value.startswith(name + '.') or name.startswith(value + '.') for value in explicit
    ) or (not explicit and re.search(r'(?<![\w])' + re.escape(name) + r'(?![\w])', text))}


def _adapt(body, name):
    parts = name.split('.')
    target = body
    for part in parts[:-1]:
        if isinstance(target, dict):
            target = target.get(part)
        elif isinstance(target, list) and part.isdigit() and int(part) < len(target):
            target = target[int(part)]
        else:
            return False
    if not isinstance(target, dict) or parts[-1] not in target:
        return False
    if name == 'tool_choice' and target[name] in ('required', 'auto'):
        if target[name] == 'auto':
            return False
        target[name] = 'auto'
    else:
        target.pop(parts[-1], None)
    return True


REJECTION_TTL_SECONDS = 7 * 24 * 60 * 60


class ParameterMemory:
    """Keep dated provider/model rejections for one week, with explicit refresh."""
    def __init__(self, directory=None, *, clock=None, app_version=None):
        self.path = Path(directory) / 'provider-compatibility.json' if directory else None
        self.lock = threading.RLock()
        self.clock = clock if clock is not None else lambda: time.time()
        self.app_version = app_version
        self.rejections = {}
        if self.path and self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                same_app = app_version is None or data.get('appVersion') == app_version
                if data.get('version') == 2 and same_app:
                    self.app_version = data.get('appVersion') if app_version is None else app_version
                    self.rejections = {key: {name: stamp for name, stamp in names.items()
                        if isinstance(name, str) and type(stamp) in (int, float) and math.isfinite(stamp)}
                        for key, names in data.get('rejections', {}).items() if isinstance(names, dict)}
                    if self._prune(self.clock()):
                        self._write()
                else:
                    # Old undated records and records from another app version
                    # start a new observation period on the next request.
                    self._write()
            except (OSError, ValueError, AttributeError):
                pass

    @staticmethod
    def key(scope):
        return json.dumps(list(scope), ensure_ascii=False)

    def apply(self, scope, body, automatic):
        return self.apply_with_details(scope, body, automatic)[0]

    def _prune(self, now):
        previous = sum(len(names) for names in self.rejections.values())
        self.rejections = {key: {name: stamp for name, stamp in names.items()
            if 0 <= now - stamp < REJECTION_TTL_SECONDS} for key, names in self.rejections.items()}
        self.rejections = {key: names for key, names in self.rejections.items() if names}
        return sum(len(names) for names in self.rejections.values()) != previous

    def apply_with_details(self, scope, body, automatic):
        body = copy.deepcopy(body)
        details = []
        with self.lock:
            now = self.clock()
            if self._prune(now):
                self._write()
            names = self.rejections.get(self.key(scope), {})
            for name in sorted(set(names) & set(automatic)):
                if _adapt(body, name):
                    details.append({'parameter': name, 'recordedAt': names[name],
                                    'ageDays': int((now - names[name]) // 86400),
                                    'action': 'auto' if name == 'tool_choice' and body.get(name) == 'auto' else 'omitted'})
        return body, details

    def clear_provider(self, provider_id):
        with self.lock:
            removed = []
            for key in self.rejections:
                try:
                    scope = json.loads(key)
                except ValueError:
                    continue
                if isinstance(scope, list) and scope and scope[0] == provider_id:
                    removed.append(key)
            for key in removed:
                del self.rejections[key]
            if removed:
                self._write()

    def clear_all(self):
        with self.lock:
            self.rejections.clear()
            self._write()

    def remember(self, scope, names):
        with self.lock:
            now = self.clock()
            self._prune(now)
            self.rejections.setdefault(self.key(scope), {}).update({name: now for name in names})
            self._write()

    def _write(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + '.' + str(threading.get_ident()) + '.tmp')
            try:
                temporary.write_text(json.dumps({'version': 2, 'appVersion': self.app_version,
                    'rejections': self.rejections}, ensure_ascii=False, indent=2), encoding='utf-8')
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)


def retry_delay(headers, attempt):
    """Accept seconds, HTTP dates and the SDK's millisecond header."""
    headers = {key.lower(): value for key, value in headers.items()}
    seconds = None
    for name, divisor in (('retry-after-ms', 1000), ('retry-after', 1)):
        try:
            seconds = float(headers[name]) / divisor
            break
        except (ValueError, TypeError, KeyError):
            continue
    if seconds is None:
        try:
            seconds = (parsedate_to_datetime(headers['retry-after']) - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, KeyError, OverflowError):
            seconds = .5 * 2 ** attempt * (1 - .25 * random.random())
    if not math.isfinite(seconds):
        return None
    # A longer server wait is shown to the caller; never retry ahead of it.
    return max(0, seconds) if seconds <= 30 else None


def compatible_open(opener, request, *, timeout=20, memory=None, scope=(), automatic=(), records=None, cancelled=None):
    """Open a model request, recovering one named rejection before streaming.

    Each HTTP attempt has its own diagnostics record. A response already being
    consumed belongs to the caller and is never replayed by this helper.
    """
    cancelled = cancelled if cancelled is not None else current_request_cancelled()
    original = _payload(request.data)
    automatic = set(automatic) if isinstance(original, dict) else set()
    body, remembered = memory.apply_with_details(scope, original, automatic) if memory and isinstance(original, dict) else (copy.deepcopy(original), [])
    rejected_once, retries = False, 0
    while True:
        if cancelled.is_set():
            raise InterruptedError('供应商请求已取消')
        data = json.dumps(body, ensure_ascii=False).encode() if isinstance(body, dict) else request.data
        outgoing = urllib.request.Request(request.full_url, data=data, headers=dict(request.header_items()), method=request.get_method())
        record = {'request': {'url': request.full_url, 'method': request.get_method(),
                             'headers': dict(request.header_items()), 'body': copy.deepcopy(body) if isinstance(body, dict) else None},
                  'response': {'status': None, 'headers': {}, 'body': ''}}
        if remembered:
            record['compatibility'] = copy.deepcopy(remembered)
        if records is not None:
            records.append(record)
        try:
            response = opener.open(outgoing, timeout=timeout)
            record['response'].update(status=response.status, headers=dict(response.headers))
            return TracedResponse(response, record) if records is not None else response
        except urllib.error.HTTPError as error:
            raw = error.read()
            record['response'].update(status=error.code, headers=dict(error.headers), body=raw.decode('utf-8', 'replace'))
            names = rejected_parameters(error.code, raw, automatic) if not rejected_once else set()
            if names and isinstance(body, dict):
                changed = {name for name in names if _adapt(body, name)}
                if changed:
                    error.close()
                    if memory:
                        memory.remember(scope, changed)
                    rejected_once = True
                    continue
            if error.code in (429, 503) and retries < 2:
                delay = retry_delay(error.headers, retries)
                if delay is not None:
                    error.close()
                    retries += 1
                    if cancelled.wait(delay):
                        raise InterruptedError('供应商请求已取消') from None
                    continue
            record['httpRetryManaged'] = error.code in (429, 503)
            error.close()
            raise urllib.error.HTTPError(error.url, error.code, error.msg, error.headers, io.BytesIO(raw)) from None
        except OSError as error:
            record['exception'] = str(error)
            raise
