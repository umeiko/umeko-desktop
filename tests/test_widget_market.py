"""Local public-release fixtures; no HTTP server or live GitHub dependency."""
import io
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'plugin-runtime'))
from app.widget_market import MarketCatalog, MarketError, RELEASES, semver_key, is_newer
from umeko_plugin_sdk import PluginError


def manifest(identifier='sample-widget', version='1.0.0'):
    return {'kind':'umeko-plugin','apiVersion':1,'id':identifier,'version':version,
            'name':'Sample Widget','summary':'A local fixture','description':'Fixture description',
            'entrypoint':'main.py:create','permissions':[], 'agent':{'document':'AGENT.md','methods':{}}}


def archive_bytes(value=None, extra=None):
    stream = io.BytesIO()
    files = {'manifest.json':json.dumps(value or manifest()),'main.py':'raise RuntimeError("must remain inert")',
             'README.md':'Read me','AGENT.md':'Agent instructions','config.json':'{}',
             'config.schema.json':'{"type":"object"}'}
    files.update(extra or {})
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    return stream.getvalue()


def release(version='1.0.0', identifier='sample-widget', tag='unrelated-tag', **overrides):
    from urllib.parse import quote
    name = identifier + '-' + version + '.zip'
    asset = {'name':name,'size':1000,'browser_download_url':
             'https://github.com/umeiko/umeko-desktop-widgets/releases/download/' + quote(tag, safe='') + '/' + quote(name, safe='')}
    asset.update(overrides.pop('asset', {}))
    return {'tag_name':tag,'published_at':'2026-10-01T00:00:00Z','assets':[asset], **overrides}


class StubFetcher:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, url, headers=None, destination=None):
        self.calls.append((url, dict(headers or {}), destination))
        response = self.routes[url]
        if isinstance(response, Exception):
            raise response
        if callable(response):
            return response(headers or {}, destination)
        return dict(response)


def metadata_url(identifier='sample-widget', tag='unrelated-tag'):
    from urllib.parse import quote
    return 'https://raw.githubusercontent.com/umeiko/umeko-desktop-widgets/' + quote(tag, safe='') + '/widgets/' + identifier + '/manifest.json'


class MarketCatalogTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'build/widget-market-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temporary.cleanup)
        self.profile = Path(self.temporary.name)

    def catalog(self, releases=None, payload=None):
        releases = [release()] if releases is None else releases
        routes = {RELEASES:{'status':200,'headers':{'ETag':'"page-one"'},'body':json.dumps(releases)},
                  metadata_url():{'status':200,'body':json.dumps(manifest()),'headers':{'etag':'"manifest"'}}}
        if releases:
            routes[releases[0]['assets'][0]['browser_download_url']] = {'status':200,'body':payload or archive_bytes()}
        fetcher = StubFetcher(routes)
        return MarketCatalog(self.profile, root=ROOT, fetcher=fetcher), fetcher

    def test_constructor_is_inert_and_ten_minute_cache_is_disk_backed(self):
        catalog, fetch = self.catalog()
        self.assertEqual(fetch.calls, [])
        first = catalog.refresh()
        self.assertEqual(first['rows'][0]['name'], 'Sample Widget')
        self.assertEqual(len(fetch.calls), 2, 'Catalog should fetch only release JSON and the small raw manifest')
        self.assertFalse(any(call[2] for call in fetch.calls))
        self.assertEqual(catalog.refresh()['rows'], first['rows'])
        self.assertEqual(len(fetch.calls), 2)
        restored = MarketCatalog(self.profile, fetcher=fetch)
        self.assertEqual(restored.refresh()['rows'], first['rows'])
        self.assertEqual(len(fetch.calls), 2)

    def test_semver_order_build_metadata_and_filename_identity(self):
        versions = ['1.0.0-alpha','1.0.0-alpha.1','1.0.0-alpha.beta','1.0.0-beta','1.0.0-beta.2','1.0.0-beta.11','1.0.0-rc.1','1.0.0']
        self.assertEqual(sorted(versions, key=semver_key), versions)
        self.assertEqual(semver_key('1.0.0+one'), semver_key('1.0.0+two'))
        for version in ('01.0.0','1.0.0-01','1.0','1.0.0-','1.0.0+','1.0.0-a..b'):
            self.assertIsNone(semver_key(version))
        self.assertTrue(is_newer('2.0.0', '1.0.0'))
        releases = [release('1.9.0'), release('1.10.0+build.2'), release('9.0.0', draft=True), release('10.0.0', prerelease=True), release('01.0.0')]
        catalog, fetch = self.catalog(releases)
        fetch.routes[metadata_url()] = {'status':200,'body':json.dumps(manifest(version='1.10.0+build.2'))}
        rows = catalog.refresh()['rows']
        self.assertEqual([row['version'] for row in rows], ['1.10.0+build.2'])

    def test_multiple_widgets_with_colliding_release_tags_keep_filename_identity(self):
        releases = [release('1.0.0', 'first-widget', 'shared-tag'),
                    release('2.0.0', 'second-widget', 'shared-tag'),
                    release('1.2.0', 'first-widget', 'shared-tag')]
        catalog, fetch = self.catalog(releases)
        for identifier, version in [('first-widget', '1.2.0'), ('second-widget', '2.0.0')]:
            fetch.routes[metadata_url(identifier, 'shared-tag')] = {
                'status':200, 'body':json.dumps(manifest(identifier, version))}
        result = catalog.refresh()
        self.assertEqual([(row['id'], row['version']) for row in result['rows']],
                         [('first-widget', '1.2.0'), ('second-widget', '2.0.0')])
        self.assertEqual(result['warningCode'], '')
        self.assertEqual(len(fetch.calls), 3)
        self.assertFalse(any(call[2] for call in fetch.calls))

    def test_invalid_asset_names_are_ignored_before_metadata_or_download(self):
        names = ['Sample-widget-1.0.0.zip', 'sample-widget-1.0.0.tar.gz',
                 'sample-widget.zip', 'sample-widget-1.2.zip',
                 'sample-widget-01.0.0.zip', 'sample-widget-1.0.0-01.zip',
                 'sample-widget-1.0.0-a..b.zip', 'sample-widget-1.0.0+.zip']
        for name in names:
            with self.subTest(name=name):
                catalog, fetch = self.catalog([release(asset={'name':name})])
                result = catalog.refresh(force=True)
                self.assertEqual(result['rows'], [])
                self.assertEqual(len(fetch.calls), 1)

    def test_pagination_etags_304_and_force(self):
        page2 = RELEASES.replace('&page=1', '&page=2')
        catalog, fetch = self.catalog()
        fetch.routes[RELEASES]['headers']['Link'] = '<' + page2 + '>; rel="next"'
        fetch.routes[page2] = {'status':200,'headers':{'etag':'"page-two"'},'body':'[]'}
        original = catalog.refresh()
        for url in (RELEASES, page2, metadata_url()):
            fetch.routes[url] = {'status':304,'headers':{}}
        self.assertEqual(catalog.refresh(force=True)['rows'], original['rows'])
        calls = fetch.calls[-3:]
        self.assertEqual([call[0] for call in calls], [RELEASES, page2, metadata_url()])
        self.assertEqual([call[1]['If-None-Match'] for call in calls], ['"page-one"','"page-two"','"manifest"'])

    def test_rate_limit_and_network_error_preserve_cached_list(self):
        catalog, fetch = self.catalog()
        original = catalog.refresh()['rows']
        for status in (403, 429):
            fetch.routes[RELEASES] = {'status':status,'headers':{'X-RateLimit-Remaining':'0','Retry-After':'60'},'body':'{}'}
            result = catalog.refresh(force=True)
            self.assertEqual(result['warningCode'], 'rate-limit')
            self.assertEqual(result['rows'], original)
            self.assertEqual(result['rateLimit']['retry-after'], '60')
        fetch.routes[RELEASES] = OSError('offline')
        result = catalog.refresh(force=True)
        self.assertEqual(result['warningCode'], 'network')
        self.assertEqual(result['rows'], original)

    def test_failed_automatic_attempts_are_cached_on_disk_with_warning(self):
        for status in (403, 429, None):
            with self.subTest(status=status):
                catalog, fetch = self.catalog()
                catalog.refresh(force=True)
                catalog._cache['attemptedAt'] = 0
                fetch.routes[RELEASES] = OSError('offline') if status is None else {
                    'status':status,'headers':{'Retry-After':'60','X-RateLimit-Remaining':'0'}}
                failed = catalog.refresh()
                requests = len(fetch.calls)
                cached = MarketCatalog(self.profile, root=ROOT, fetcher=fetch).refresh()
                self.assertEqual(cached['rows'], failed['rows'])
                self.assertEqual(cached['warningCode'], failed['warningCode'])
                self.assertEqual(cached['warning'], failed['warning'])
                self.assertEqual(cached['rateLimit'], failed['rateLimit'])
                self.assertEqual(len(fetch.calls), requests)
                catalog.refresh(force=True)
                self.assertEqual(len(fetch.calls), requests + 1)

    def test_unofficial_asset_and_pagination_are_rejected_without_fetch(self):
        catalog, fetch = self.catalog([release(asset={'browser_download_url':'https://example.com/plugin.zip'})])
        self.assertEqual(catalog.refresh()['rows'], [])
        self.assertEqual(len(fetch.calls), 1)
        fetch.routes[RELEASES]['headers']['link'] = '<https://example.com/releases>; rel="next"'
        self.assertEqual(catalog.refresh(force=True)['warningCode'], 'source')
        self.assertEqual(len(fetch.calls), 2)

    def test_missing_raw_manifest_uses_filename_row_without_downloading_zip(self):
        catalog, fetch = self.catalog()
        fetch.routes[metadata_url()] = {'status':404,'headers':{},'body':''}
        result = catalog.refresh()
        self.assertEqual(result['warningCode'], 'metadata')
        self.assertEqual(result['rows'][0]['name'], 'sample-widget')
        self.assertEqual(len(fetch.calls), 2)

    def test_prepare_without_digest_is_inert_and_cleanup_is_exact(self):
        catalog, fetch = self.catalog()
        catalog.refresh()
        prepared = catalog.prepare('sample-widget')
        archive = Path(prepared['path'])
        self.assertTrue(archive.is_file())
        self.assertEqual(prepared['manifest']['id'], 'sample-widget')
        self.assertFalse(prepared['digestVerified'])
        unrelated = self.profile / 'keep.txt'; unrelated.write_text('keep')
        catalog.cleanup({'path':str(unrelated)})
        self.assertTrue(unrelated.exists())
        catalog.cleanup(prepared)
        self.assertFalse(archive.parent.exists())
        self.assertTrue(unrelated.exists())

    def test_declared_digest_verified_or_mismatch_refused(self):
        payload = archive_bytes()
        declared = hashlib.sha256(payload).hexdigest()
        for expected, accepted in [(declared, True), ('0'*64, False)]:
            catalog, fetch = self.catalog([release(asset={'digest':'sha256:' + expected})], payload)
            catalog.refresh(force=True)
            if accepted:
                prepared = catalog.prepare('sample-widget')
                self.assertTrue(prepared['digestVerified'])
                catalog.cleanup(prepared)
            else:
                with self.assertRaisesRegex(MarketError, 'SHA-256'):
                    catalog.prepare('sample-widget')
            self.assertEqual(list((catalog.directory / 'tmp').iterdir()), [])

    def test_manifest_identity_zip_traversal_and_expanded_size_fail_cleanly(self):
        cases = [archive_bytes(manifest(identifier='other-widget')),
                 archive_bytes(manifest(version='2.0.0')),
                 archive_bytes(extra={'../outside.txt':'outside'})]
        for payload in cases:
            catalog, fetch = self.catalog(payload=payload)
            catalog.refresh(force=True)
            with self.assertRaises((MarketError, PluginError)):
                catalog.prepare('sample-widget')
            self.assertEqual(list((catalog.directory / 'tmp').iterdir()), [])
        catalog, fetch = self.catalog()
        catalog.refresh(force=True)
        with patch('umeko_plugin_sdk.packages.MAX_BYTES', 1):
            with self.assertRaisesRegex(PluginError, '128 MiB'):
                catalog.prepare('sample-widget')
        self.assertEqual(list((catalog.directory / 'tmp').iterdir()), [])

    def test_partial_download_failure_is_cleaned(self):
        catalog, fetch = self.catalog()
        catalog.refresh()
        def fail(headers, destination):
            destination.write_bytes(b'partial')
            raise OSError('connection lost')
        fetch.routes[release()['assets'][0]['browser_download_url']] = fail
        with self.assertRaises(OSError):
            catalog.prepare('sample-widget')
        self.assertEqual(list((catalog.directory / 'tmp').iterdir()), [])

    def test_leading_digit_id_and_build_version_pass_shared_sdk(self):
        item = release('1.2.3+build.1', identifier='1-widget')
        catalog, fetch = self.catalog([item], archive_bytes(manifest('1-widget','1.2.3+build.1')))
        fetch.routes[metadata_url('1-widget')] = {'status':200,'body':json.dumps(manifest('1-widget','1.2.3+build.1'))}
        catalog.refresh()
        prepared = catalog.prepare('1-widget')
        self.assertEqual(prepared['manifest']['version'], '1.2.3+build.1')
        catalog.cleanup(prepared)

    def test_runtime_get_bridge_suite_is_included_in_python_discovery(self):
        result = subprocess.run([shutil.which('node') or 'node', '--test', 'tests/widget-market.test.mjs'],
            cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=30,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
