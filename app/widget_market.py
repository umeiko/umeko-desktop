"""Official public Widget catalog and inert download preparation.

Only runtime/widget-market.mjs performs network I/O. A fetcher used by local
tests accepts (url, headers={}, destination=None) and returns status/headers/body.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, parse_qs

REPOSITORY = 'umeiko/umeko-desktop-widgets'
RELEASES = 'https://api.github.com/repos/' + REPOSITORY + '/releases?per_page=100&page=1'
CACHE_SECONDS = 600
MAX_BYTES = 128 * 1024 * 1024
_VERSION = r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?'
_ASSET = re.compile(r'([a-z0-9][a-z0-9-]{0,63})-(' + _VERSION + r')\.zip', re.ASCII)


def semver_key(value):
    """SemVer precedence; build metadata does not affect version ordering."""
    match = re.fullmatch(_VERSION, value, re.ASCII) if isinstance(value, str) else None
    if not match:
        return None
    major, minor, patch, pre = match.groups()
    parts = tuple((0, int(part)) if part.isdigit() else (1, part) for part in pre.split('.')) if pre else ()
    return int(major), int(minor), int(patch), 0 if pre else 1, parts


def is_newer(candidate, installed):
    left, right = semver_key(candidate), semver_key(installed)
    return left is not None and (right is None or left > right)


class MarketError(ValueError):
    def __init__(self, message, code='network', headers=None):
        super().__init__(message)
        self.code, self.headers = code, headers or {}


def _official_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port or parsed.fragment:
        raise MarketError('Widget 市场地址无效', 'source')
    query = parse_qs(parsed.query)
    if parsed.hostname == 'api.github.com' and parsed.path == '/repos/' + REPOSITORY + '/releases':
        if set(query) == {'per_page', 'page'} and query['per_page'] == ['100'] and len(query['page']) == 1 and re.fullmatch('[1-9][0-9]*', query['page'][0]):
            return url
    elif parsed.hostname == 'raw.githubusercontent.com' and not parsed.query:
        if re.fullmatch('/' + REPOSITORY + r'/[^/]+/widgets/[a-z0-9][a-z0-9-]{0,63}/manifest\.json', parsed.path):
            return url
    elif parsed.hostname == 'github.com' and not parsed.query:
        if re.fullmatch('/' + REPOSITORY + r'/releases/download/[^/]+/[^/]+\.zip', parsed.path):
            return url
    raise MarketError('只允许从官方 Widget 仓库获取内容', 'source')


class MarketCatalog:
    def __init__(self, profile, root=None, fetcher=None):
        self.root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
        self.directory = Path(profile) / 'widget-market'
        self.cache_file = self.directory / 'catalog.json'
        self.fetcher = fetcher or self._fetch
        self._owned = {}
        self._cache = {'checkedAt': 0, 'rows': [], 'responses': {}}
        try:
            value = json.loads(self.cache_file.read_text(encoding='utf-8'))
            if isinstance(value, dict) and isinstance(value.get('rows'), list) and isinstance(value.get('responses'), dict):
                self._cache = value
        except (OSError, ValueError):
            pass

    def _fetch(self, url, headers=None, destination=None):
        from .pi_runtime import node_executable, CREATE_NO_WINDOW
        from .update import update_environment
        from .update_proxy import system_proxy
        env = update_environment()
        environment = {key: env.value(key) for key in env.keys()}
        # Empty explicit proxy preserves the host resolver's NO_PROXY decision.
        environment['UMEKO_UPDATE_PROXY'] = system_proxy(url)
        result = subprocess.run([node_executable(), str(self.root / 'runtime/widget-market.mjs')],
            input=json.dumps({'url': url, 'headers': headers or {}, 'destination': str(destination) if destination else None}),
            env=environment, capture_output=True, text=True, encoding='utf-8', timeout=180,
            creationflags=CREATE_NO_WINDOW)
        try:
            value = json.loads(result.stdout)
        except ValueError:
            raise MarketError('Widget 市场网络进程未返回有效信息') from None
        if result.returncode or value.get('error'):
            raise MarketError(value.get('error') or 'Widget 市场连接失败')
        return value

    def _request(self, url, responses, destination=None):
        _official_url(url)
        previous = responses.get(url, {}) if destination is None else {}
        headers = {'If-None-Match': previous['etag']} if previous.get('etag') else {}
        result = self.fetcher(url, headers=headers, destination=destination)
        status = result.get('status', 0)
        received = {str(key).lower(): str(value) for key, value in (result.get('headers') or {}).items()}
        if status in (403, 429):
            raise MarketError('GitHub 请求受限，请稍后刷新。', 'rate-limit', received)
        if status == 304:
            if 'body' not in previous:
                raise MarketError('GitHub 缓存响应缺少本地内容', 'response')
            merged = {**previous.get('headers', {}), **received}
            responses[url] = {**previous, 'headers': merged, 'etag': merged.get('etag', previous.get('etag', ''))}
            return previous['body'], merged
        if status != 200:
            raise MarketError('GitHub 暂时无法提供 Widget 信息（HTTP ' + str(status) + '）', 'response', received)
        if destination is not None:
            if not destination.exists() and result.get('body') is not None:
                body = result['body']
                destination.write_bytes(body.encode() if isinstance(body, str) else body)
            return None, received
        body = result.get('body', '')
        if isinstance(body, bytes):
            body = body.decode('utf-8-sig')
        if not isinstance(body, str) or len(body.encode('utf-8')) > (65536 if 'raw.githubusercontent.com' in url else 4 * 1024 * 1024):
            raise MarketError('Widget 市场信息过大或无效', 'response')
        responses[url] = {'etag': received.get('etag', ''), 'body': body, 'headers': received}
        return body, received

    def _result(self, warning=None, code=None, **extra):
        warning = self._cache.get('warning', '') if warning is None else warning
        code = self._cache.get('warningCode', '') if code is None else code
        return {'rows': copy.deepcopy(self._cache['rows']), 'warning': warning, 'warningCode': code,
                'checkedAt': self._cache.get('checkedAt', 0), 'attemptedAt': self._cache.get('attemptedAt', 0),
                'rateLimit': self._cache.get('rateLimit', {}), **extra}

    def _save_cache(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_file.with_suffix('.tmp')
        temporary.write_text(json.dumps(self._cache, ensure_ascii=False), encoding='utf-8')
        temporary.replace(self.cache_file)

    def _fallback(self, warning, code, rate=None):
        self._cache.update(warning=warning, warningCode=code, rateLimit=rate or {})
        try:
            self._save_cache()
        except OSError:
            pass
        return self._result(cached=True)

    def refresh(self, force=False):
        now = time.time()
        if not force and self._cache.get('attemptedAt', self._cache.get('checkedAt', 0)) > now - CACHE_SECONDS:
            return self._result(cached=True)
        self._cache['attemptedAt'] = now
        responses = copy.deepcopy(self._cache['responses'])
        try:
            releases, visited, url = [], set(), RELEASES
            while url:
                if url in visited or len(visited) >= 100:
                    raise MarketError('GitHub 分页信息无效', 'response')
                visited.add(url)
                body, headers = self._request(url, responses)
                page = json.loads(body)
                if not isinstance(page, list):
                    raise MarketError('GitHub 发布列表无效', 'response')
                releases.extend(page)
                url = ''
                for link in headers.get('link', '').split(','):
                    match = re.search(r'<([^>]+)>;\s*rel="next"', link)
                    if match:
                        url = _official_url(match[1])
            selected = {}
            for release in releases:
                if not isinstance(release, dict) or release.get('draft') or release.get('prerelease'):
                    continue
                tag = release.get('tag_name')
                if not isinstance(tag, str) or not tag or len(tag) > 512:
                    continue
                for asset in release.get('assets', []):
                    if not isinstance(asset, dict):
                        continue
                    match = _ASSET.fullmatch(asset.get('name', ''))
                    if not match:
                        continue
                    identifier, version = match.group(1, 2)
                    size = asset.get('size')
                    if type(size) is not int or not 0 < size <= MAX_BYTES:
                        continue
                    expected = 'https://github.com/' + REPOSITORY + '/releases/download/' + quote(tag, safe='') + '/' + quote(asset['name'], safe='')
                    actual = asset.get('browser_download_url')
                    if not isinstance(actual, str):
                        continue
                    try:
                        _official_url(actual)
                    except (MarketError, ValueError):
                        continue
                    if unquote(urlsplit(actual).path) != unquote(urlsplit(expected).path):
                        continue
                    row = {'id': identifier, 'version': version, 'name': identifier, 'description': '',
                           'icon': 'puzzle', 'readme': 'README.md',
                           'publishedAt': str(release.get('published_at') or ''), 'digest': asset.get('digest') or '',
                           'size': size, 'url': actual, 'tag': tag, 'assetName': asset['name']}
                    previous = selected.get(identifier)
                    # Filename version is authoritative; unrelated release tags may collide.
                    if previous is None or (semver_key(version), row['publishedAt'], version) > (semver_key(previous['version']), previous['publishedAt'], previous['version']):
                        selected[identifier] = row
            warning, warning_code = '', ''
            for row in selected.values():
                metadata = 'https://raw.githubusercontent.com/' + REPOSITORY + '/' + quote(row['tag'], safe='') + '/widgets/' + row['id'] + '/manifest.json'
                try:
                    body, _ = self._request(metadata, responses)
                    manifest = json.loads(body)
                    if not isinstance(manifest, dict) or manifest.get('id') != row['id'] or manifest.get('version') != row['version']:
                        raise MarketError('Widget 展示清单与发布包名称不一致', 'metadata')
                    for key in ('name', 'description', 'summary', 'lifecycle', 'readme'):
                        if isinstance(manifest.get(key), str):
                            row[key] = manifest[key][:8000]
                    icon = manifest.get('icon')
                    if isinstance(icon, str):
                        row['icon'] = icon[:8000]
                    elif isinstance(icon, dict) and isinstance(icon.get('path'), str):
                        row['icon'] = {'path': icon['path'][:8000]}
                    if isinstance(manifest.get('permissions'), list):
                        row['permissions'] = [item for item in manifest['permissions'] if isinstance(item, str)]
                except MarketError as error:
                    if error.code == 'rate-limit':
                        raise
                    warning, warning_code = '部分 Widget 简介暂时无法读取，安装前会检查完整插件包。', 'metadata'
                except (OSError, ValueError, TypeError):
                    warning, warning_code = '部分 Widget 简介暂时无法读取，安装前会检查完整插件包。', 'metadata'
            self._cache = {'checkedAt': time.time(), 'attemptedAt': now,
                           'rows': sorted(selected.values(), key=lambda row: row['id']), 'responses': responses,
                           'warning': warning, 'warningCode': warning_code, 'rateLimit': {}}
            self._save_cache()
            return self._result(warning, warning_code, cached=False)
        except MarketError as error:
            rate = {key: error.headers[key] for key in ('x-ratelimit-remaining', 'x-ratelimit-reset', 'retry-after') if key in error.headers}
            return self._fallback(str(error), error.code, rate)
        except (OSError, ValueError, TypeError, subprocess.SubprocessError):
            return self._fallback('Widget 市场暂时无法连接，已保留上次列表。', 'network')

    def prepare(self, identifier):
        row = next((row for row in self._cache['rows'] if row.get('id') == identifier), None)
        if row is None:
            raise MarketError('Widget 不在当前官方列表中，请先刷新。', 'missing')
        _official_url(row['url'])
        parent = self.directory / 'tmp'
        parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix='download-', dir=parent))
        archive = temporary / 'package.zip'
        try:
            self._request(row['url'], {}, destination=archive)
            if archive.is_symlink() or not archive.is_file() or not 0 < archive.stat().st_size <= MAX_BYTES:
                raise MarketError('Widget 下载包大小无效', 'archive')
            digest = row.get('digest')
            verified = False
            if digest:
                if not isinstance(digest, str) or not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
                    raise MarketError('发布资源的 SHA-256 信息无效', 'digest')
                value = hashlib.sha256()
                with archive.open('rb') as source:
                    for chunk in iter(lambda: source.read(65536), b''):
                        value.update(chunk)
                if value.hexdigest() != digest[7:].lower():
                    raise MarketError('Widget 下载包的 SHA-256 不匹配，已拒绝安装。', 'digest')
                verified = True
            # Reuse the installer's exact path, size, manifest and file rules.
            import sys
            sdk = str(self.root / 'plugin-runtime')
            if sdk not in sys.path:
                sys.path.insert(0, sdk)
            from umeko_plugin_sdk.packages import inspect_archive
            manifest = inspect_archive(archive, temporary_root=temporary)
            if manifest['id'] != row['id'] or manifest['version'] != row['version']:
                raise MarketError('ZIP 清单的 ID 或版本与发布资源名称不一致。', 'identity')
            result = {'path': str(archive), 'manifest': manifest, 'digestVerified': verified}
            self._owned[str(archive)] = temporary
            return result
        except BaseException:
            shutil.rmtree(temporary)
            raise

    def cleanup(self, prepared):
        archive = str(prepared.get('path', '')) if isinstance(prepared, dict) else ''
        temporary = self._owned.pop(archive, None)
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
