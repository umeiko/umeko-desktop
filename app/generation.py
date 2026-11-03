"""Bounded OpenAI-compatible media generation using existing provider accounts.

Successful binary/base64 bodies are deliberately excluded from HTTP diagnostics.
No retries are performed here: request failures use the shared classification.
"""
from __future__ import annotations

import base64
import binascii
import errno
import http.client
import json
import select
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from umeko_provider_sdk import ProviderError, current_request_cancelled
from umeko_provider_sdk.network import network_scope, proxy_handler, tls_context
from .multimodal_settings import normalize
from .provider_errors import format_http_error, safe_text

MAX_RESPONSE = 48 * 1024 * 1024
MAX_MEDIA = 32 * 1024 * 1024
TIMEOUT = 90
FORMATS = {'mp3': 'audio/mpeg', 'opus': 'audio/ogg', 'aac': 'audio/aac',
           'flac': 'audio/flac', 'wav': 'audio/wav', 'pcm': 'audio/pcm'}


class GenerationCancelled(ConnectionError):
    """A caller cancellation is not a provider failure or a retry request."""


class VideoJobFailed(ProviderError):
    """A terminal remote job failure carries a public, sanitized reason."""


def capabilities(provider):
    if provider.get('api') == 'openai':
        return ['image', 'speech', 'video']
    return provider.get('generationCapabilities', []) if provider.get('api') == 'plugin' else []


def selection(data, kind):
    if kind not in ('image', 'speech', 'video'):
        raise ValueError('生成类型必须是 image、speech 或 video')
    settings = normalize(data.get('multimodal'))[kind]
    provider = next((p for p in data.get('providers', []) if p.get('id') == settings['providerId']), None)
    if not provider or kind not in capabilities(provider):
        raise ValueError('请先在设置中选择支持此生成类型的供应商')
    model = settings.get('model', '').strip()
    if not model:
        raise ValueError('请先配置生成模型 ID')
    if provider.get('api') == 'openai' and not provider.get('key'):
        raise ValueError('请先配置供应商 API Key')
    if provider.get('api') == 'openai':
        from .gateway import validate_base_url
        validate_base_url(provider.get('baseUrl', ''))
    if kind == 'speech' and not settings.get('voice', '').strip():
        raise ValueError('请先配置语音 voice')
    return provider, model, settings


def generation_config(data):
    """Public tool descriptions only; selections are resolved again per request."""
    result = {}
    for kind in ('image', 'speech', 'video'):
        try:
            provider, model, _ = selection(data, kind)
            result[kind] = {'provider': provider.get('name', ''), 'model': model}
        except (ValueError, TypeError, KeyError):
            result[kind] = None
    return result


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('供应商返回重定向；请使用最终服务地址')


class _Transport:
    """Retain duplicate socket handles so cancellation also interrupts header waits.

    urllib closes the connection's socket wrapper after constructing a response;
    a duplicate still permits shutdown while that response's file is being read.
    DNS is resolved by the OS, then cancellation is checked before connecting.
    """
    def __init__(self, settings, cancelled, timeout=TIMEOUT):
        self.cancelled = cancelled
        self.timeout = timeout
        self.done = threading.Event()
        self.lock = threading.Lock()
        self.handles = []
        owner = self

        class HTTP(http.client.HTTPConnection):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._create_connection = owner.connect

        class HTTPS(http.client.HTTPSConnection):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._create_connection = owner.connect

        class HTTPHandler(urllib.request.HTTPHandler):
            def http_open(self, request):
                return self.do_open(HTTP, request)

        class HTTPSHandler(urllib.request.HTTPSHandler):
            def https_open(self, request):
                return self.do_open(HTTPS, request, context=self._context)

        self.opener = urllib.request.build_opener(proxy_handler(settings),
            HTTPHandler(), HTTPSHandler(context=tls_context(settings)), _NoRedirect())
        self.watcher = threading.Thread(target=self._watch, daemon=True)

    def check(self):
        if self.cancelled.is_set():
            raise GenerationCancelled('生成已取消')

    def connect(self, address, timeout=TIMEOUT, source_address=None, **kwargs):
        self.check()
        deadline = time.monotonic() + timeout
        failure = None
        for family, kind, protocol, _, sockaddr in socket.getaddrinfo(address[0], address[1], 0, socket.SOCK_STREAM):
            self.check()
            sock = socket.socket(family, kind, protocol)
            try:
                if source_address:
                    sock.bind(source_address)
                sock.setblocking(False)
                status = sock.connect_ex(sockaddr)
                pending = (errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, 10035, 10036, 10037)
                while status:
                    if status not in pending:
                        raise OSError(status, '供应商连接失败')
                    self.check()
                    if time.monotonic() >= deadline:
                        raise TimeoutError('供应商连接超时')
                    _, ready, errors = select.select([], [sock], [sock], .05)
                    if ready or errors:
                        status = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                self.check()
                sock.settimeout(timeout)
                handle = sock.dup()
                with self.lock:
                    self.handles.append(handle)
                self.check()
                return sock
            except BaseException as exc:
                sock.close()
                if isinstance(exc, GenerationCancelled):
                    raise
                failure = exc
        raise failure or OSError('供应商地址不可用')

    def _watch(self):
        while not self.done.wait(.025):
            if self.cancelled.is_set():
                with self.lock:
                    for handle in self.handles:
                        try:
                            handle.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                return

    def __enter__(self):
        self.check()
        self.watcher.start()
        return self

    def __exit__(self, *_):
        self.done.set()
        self.watcher.join(timeout=1)
        with self.lock:
            for handle in self.handles:
                handle.close()

    def request(self, url, headers, records, data=None, method=None):
        self.check()
        method = method or ('POST' if data is not None else 'GET')
        record = {'request': {'url': urllib.parse.urlunsplit(urllib.parse.urlsplit(url)._replace(query='')),
                              'method': method, 'headers': headers},
                  'response': {'status': None, 'headers': {}, 'body': ''}}
        records.append(record)
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                record['response'].update(status=response.status, headers=dict(response.headers))
                raw = self.read(response, MAX_RESPONSE)
                record['response']['bytes'] = len(raw)
                return raw, response.headers
        except urllib.error.HTTPError as exc:
            try:
                record['response'].update(status=exc.code, headers=dict(exc.headers))
                record['response']['body'] = self.read(exc, 64 * 1024, truncate=True).decode('utf-8', 'replace')
            finally:
                exc.close()
            raise ValueError(format_http_error(exc.code, record['response']['body'], exc.headers,
                                              list(headers.values()))) from None
        except Exception:
            self.check()
            raise

    def read(self, response, limit, truncate=False):
        declared = response.headers.get('Content-Length')
        if not truncate and declared and int(declared) > limit:
            raise ValueError('生成结果超过大小限制')
        chunks, size = [], 0
        while size <= limit:
            self.check()
            chunk = response.read(min(64 * 1024, limit + 1 - size))
            self.check()
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > limit:
            if not truncate:
                raise ValueError('生成结果超过大小限制')
        return b''.join(chunks)[:limit]


def _media(data, kind, format='', content_type=''):
    if not isinstance(data, bytes) or not data or len(data) > MAX_MEDIA:
        raise ValueError('供应商返回空白、无效或过大的媒体结果')
    if kind == 'image':
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            mime, extension = 'image/png', 'png'
        elif data.startswith(b'\xff\xd8\xff'):
            mime, extension = 'image/jpeg', 'jpg'
        elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            mime, extension = 'image/webp', 'webp'
        elif data[:6] in (b'GIF87a', b'GIF89a'):
            mime, extension = 'image/gif', 'gif'
        else:
            raise ValueError('供应商返回的图片格式不受支持')
    elif kind == 'video':
        if data[4:8] != b'ftyp' or (content_type and content_type not in ('video/mp4', 'application/octet-stream')):
            raise ValueError('供应商返回的响应不是 MP4 视频')
        mime, extension = 'video/mp4', 'mp4'
    else:
        extension = format or 'mp3'
        mime = FORMATS[extension]
        if content_type and not (content_type.startswith('audio/') or content_type == 'application/octet-stream'):
            raise ValueError('供应商返回的响应不是音频')
    return {'data': base64.b64encode(data).decode('ascii'), 'mimeType': mime, 'extension': extension}


def _video_progress(value, on_progress, transport):
    transport.check()
    if not isinstance(value, dict):
        raise ValueError('供应商返回的视频任务无效')
    job_id, status, progress = value.get('id'), value.get('status'), value.get('progress', 0)
    if (not isinstance(job_id, str) or not job_id or len(job_id) > 200
            or status not in ('queued', 'in_progress', 'completed', 'failed')
            or type(progress) is not int or not 0 <= progress <= 100):
        raise ValueError('供应商返回的视频任务状态无效')
    if on_progress:
        on_progress({'id': job_id, 'status': status, 'progress': progress})
    transport.check()
    return job_id, status


def _delete_video(provider, url, headers):
    """Cancellation cleanup has its own bounded lifetime and no caller stop event.

    A daemon also bounds OS DNS waits, which socket shutdown cannot interrupt.
    Deletion is best effort: some providers only delete terminal jobs.
    """
    stop = threading.Event()
    def delete():
        try:
            with _Transport(provider.get('proxy'), stop, timeout=2) as cleanup:
                cleanup.request(url, headers, [], method='DELETE')
        except Exception:
            pass
    worker = threading.Thread(target=delete, daemon=True)
    worker.start()
    worker.join(timeout=2)
    stop.set()


def _openai_video(provider, base, payload, transport, records, on_progress, poll_interval):
    headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + provider['key'],
               'User-Agent': 'Umeko-Desktop'}
    job_id = None
    try:
        raw, _ = transport.request(base + '/videos', headers, records, json.dumps(payload).encode())
        value = json.loads(raw)
        # Keep a known ID even if the progress callback cancels this request.
        if isinstance(value, dict) and isinstance(value.get('id'), str) and value['id']:
            job_id = value['id']
        while True:
            received_id, status = _video_progress(value, on_progress, transport)
            if received_id != job_id:
                raise ValueError('供应商返回的视频任务 ID 不匹配')
            url = base + '/videos/' + urllib.parse.quote(job_id, safe='')
            if status == 'failed':
                error = value.get('error')
                reason = error.get('message') if isinstance(error, dict) else None
                raise VideoJobFailed('视频生成失败：' + (reason if isinstance(reason, str) and reason.strip() else '供应商未提供原因'))
            if status == 'completed':
                raw, response_headers = transport.request(url + '/content', headers, records)
                transport.check()
                return [_media(raw, 'video', content_type=response_headers.get_content_type())]
            if transport.cancelled.wait(poll_interval):
                transport.check()
            raw, _ = transport.request(url, headers, records)
            value = json.loads(raw)
    except Exception:
        if transport.cancelled.is_set():
            if job_id:
                _delete_video(provider, base + '/videos/' + urllib.parse.quote(job_id, safe=''), headers)
            raise GenerationCancelled('生成已取消') from None
        raise


def generate(gateway, body, on_progress=None, *, poll_interval=2.0):
    if not isinstance(body, dict):
        raise ValueError('生成请求必须是对象')
    kind = body.get('kind')
    provider, model, defaults = selection(gateway.store.data, kind)
    text = body.get('text' if kind == 'speech' else 'prompt')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('生成内容不能为空')
    if len(text) > 100_000:
        raise ValueError('生成内容过长')
    fields = {'image': ('size', 'quality', 'count', 'format'),
              'speech': ('voice', 'format', 'speed'), 'video': ('seconds', 'size')}
    options = {key: body.get(key, defaults.get(key)) for key in fields[kind]}
    options = {key: value for key, value in options.items() if value is not None and value != ''}
    if kind == 'image':
        if type(options.get('count', 1)) is not int or not 1 <= options.get('count', 1) <= 10:
            raise ValueError('图片数量必须为 1 到 10')
        if options.get('format', '') not in ('', 'png', 'jpeg', 'webp'):
            raise ValueError('图片格式必须为 png、jpeg 或 webp')
    elif kind == 'speech':
        if options.get('format', 'mp3') not in FORMATS:
            raise ValueError('不支持此音频格式')
        if not isinstance(options.get('voice'), str) or not options['voice'].strip():
            raise ValueError('请先配置语音 voice')
        speed = options.get('speed', 1)
        if type(speed) not in (int, float) or not .25 <= speed <= 4:
            raise ValueError('语速必须在 0.25 到 4 之间')
    else:
        if type(poll_interval) not in (int, float) or not 0 <= poll_interval <= 60:
            raise ValueError('视频轮询间隔无效')
        if 'seconds' in options and (not isinstance(options['seconds'], str) or not options['seconds'].isdigit()
                                     or len(options['seconds']) > 4 or int(options['seconds']) <= 0):
            raise ValueError('视频 seconds 必须为正整数字符串')
        if 'size' in options:
            size = options['size']
            if (not isinstance(size, str) or len(size) > 30 or len(size.split('x')) != 2
                    or any(not part.isdigit() or int(part) <= 0 for part in size.split('x'))):
                raise ValueError('视频 size 必须为 WIDTHxHEIGHT')
    for key in ('size', 'quality', 'voice'):
        if key in options and (not isinstance(options[key], str) or len(options[key]) > 200):
            raise ValueError('生成参数无效：' + key)
    cancelled = current_request_cancelled()
    records = []
    request = {'transport': provider['api'], 'model': model, 'kind': kind,
               'parameters': options, 'input': text}
    try:
        with network_scope(provider.get('proxy'), records):
            if cancelled.is_set():
                raise GenerationCancelled('生成已取消')
            if provider['api'] == 'plugin':
                if gateway.plugins is None:
                    raise ProviderError('供应商插件不可用')
                if kind == 'video':
                    def plugin_progress(value):
                        if cancelled.is_set():
                            raise GenerationCancelled('生成已取消')
                        if on_progress:
                            on_progress(value)
                    values = gateway.plugins.generate(provider['id'], kind, model, text, options, on_progress=plugin_progress)
                else:
                    values = gateway.plugins.generate(provider['id'], kind, model, text, options)
                if not isinstance(values, list) or not 1 <= len(values) <= (options.get('count', 1) if kind == 'image' else 1):
                    raise ValueError('供应商返回的媒体列表无效')
                items = [_media(value['data'], kind, options.get('format', ''), value.get('mimeType', '')) for value in values]
            else:
                from .gateway import validate_base_url
                base = validate_base_url(provider['baseUrl'])
                payload = {'model': model}
                if kind == 'image':
                    payload.update(prompt=text, n=options.get('count', 1))
                    payload.update({k: options[k] for k in ('size', 'quality') if k in options})
                    if options.get('format'):
                        payload['output_format'] = options['format']
                elif kind == 'speech':
                    payload.update(input=text, voice=options['voice'], response_format=options.get('format', 'mp3'), speed=options.get('speed', 1))
                else:
                    payload.update(prompt=text, **options)
                with _Transport(provider.get('proxy'), cancelled) as transport:
                    if kind == 'video':
                        items = _openai_video(provider, base, payload, transport, records, on_progress, poll_interval)
                    else:
                        raw, headers = transport.request(base + ('/images/generations' if kind == 'image' else '/audio/speech'),
                            {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + provider['key'], 'User-Agent': 'Umeko-Desktop'},
                            records, json.dumps(payload).encode())
                    if kind == 'speech':
                        items = [_media(raw, kind, options.get('format', 'mp3'), headers.get_content_type())]
                    elif kind == 'image':
                        result = json.loads(raw)
                        values = result.get('data') if isinstance(result, dict) else None
                        if not isinstance(values, list) or not 1 <= len(values) <= options.get('count', 1):
                            raise ValueError('供应商返回的图片列表无效')
                        items = []
                        for value in values:
                            if not isinstance(value, dict):
                                raise ValueError('供应商返回的图片条目无效')
                            if value.get('b64_json'):
                                try:
                                    data = base64.b64decode(value['b64_json'], validate=True)
                                except (ValueError, TypeError, binascii.Error):
                                    raise ValueError('供应商返回的图片 base64 无效') from None
                            else:
                                url = value.get('url', '')
                                parsed = urllib.parse.urlsplit(url)
                                if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                                    raise ValueError('供应商返回的图片 URL 无效')
                                data, _ = transport.request(url, {'User-Agent': 'Umeko-Desktop'}, records)
                            transport.check()
                            items.append(_media(data, kind))
                            if sum(len(item['data']) for item in items) > MAX_RESPONSE * 4 // 3:
                                raise ValueError('生成结果总大小超过限制')
            if sum(len(item['data']) for item in items) > MAX_RESPONSE * 4 // 3:
                raise ValueError('生成结果总大小超过限制')
            if cancelled.is_set():
                raise GenerationCancelled('生成已取消')
            return {'items': items, 'provider': provider.get('name', ''), 'model': model}
    except GenerationCancelled:
        raise
    except Exception as exc:
        if cancelled.is_set():
            raise GenerationCancelled('生成已取消') from None
        failure = gateway.diagnostics.failure(provider, request, records[-1]['response'] if records else {}, exc, records)
        if isinstance(exc, VideoJobFailed):
            failure.args = (safe_text(str(exc), [provider.get('key', '')]) + ' ' + str(failure),)
        raise failure from None
