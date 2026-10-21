"""Exercise the real npm/Pi CLI against a local registry, without public services."""
import hashlib
import io
import json
import os
import tarfile
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from app.npm_config import npm_environment, probe_npm, validate_npm_config
from app.pi_install import install_package
from app.pi_management import resource_command
from app.pi_runtime import RELEASE_NAME

ROOT = Path(__file__).resolve().parents[1]


class NpmConfigTests(unittest.TestCase):
    def test_validation_and_process_overrides_preserve_global_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / '.npmrc'; config.write_text('# fixture\n', encoding='utf-8')
            values = validate_npm_config({'npmRegistry': 'https://npm.example.invalid/repository/npm/', 'npmUserconfig': str(config)})
            with patch.dict(os.environ, {'NPM_CONFIG_REGISTRY': 'https://inherited.invalid/'}):
                env = npm_environment(values)
                self.assertNotIn('NPM_CONFIG_REGISTRY', env)
                self.assertEqual(env['npm_config_registry'], values['npmRegistry'])
                self.assertEqual(os.environ['NPM_CONFIG_REGISTRY'], 'https://inherited.invalid/')
            self.assertEqual(config.read_text(), '# fixture\n')
        for value in ('ftp://example.invalid', 'https://user:secret@example.invalid/', 'https://example.invalid/?token=secret', 'https://example.invalid/\ninvalid'):
            with self.assertRaises(ValueError): validate_npm_config({'npmRegistry': value})
        with self.assertRaises(ValueError): validate_npm_config([])

    def test_registry_probe_and_real_pi_npm_install_use_application_mirror(self):
        package = {'name': 'umeko-registry-fixture', 'version': '1.0.0', 'pi': {'extensions': ['./extension.js']}}
        content = io.BytesIO()
        with tarfile.open(fileobj=content, mode='w:gz') as archive:
            for name, data in {'package.json': json.dumps(package).encode(), 'extension.js': b'export default () => {};\n'}.items():
                entry = tarfile.TarInfo('package/' + name); entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
        tarball = content.getvalue(); requests = []
        class Registry(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                if self.path.startswith('/fixture.tgz'):
                    body = tarball
                elif self.path.startswith('/-/ping'):
                    body = b'{}'
                elif self.path.startswith('/umeko-registry-fixture'):
                    manifest = {**package, 'dist': {'tarball': f'http://127.0.0.1:{self.server.server_port}/fixture.tgz', 'shasum': hashlib.sha1(tarball).hexdigest()}}
                    body = json.dumps({'name': package['name'], 'dist-tags': {'latest': '1.0.0'}, 'versions': {'1.0.0': manifest}}).encode()
                else:
                    self.send_error(404); return
                self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
            def log_message(self, *_): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Registry)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                folder = Path(temp); cwd = folder / 'project'; cwd.mkdir()
                agent = folder / 'agent'; agent.mkdir()
                config = folder / '.npmrc'; config.write_text('', encoding='utf-8')
                values = validate_npm_config({'npmRegistry': f'http://127.0.0.1:{server.server_port}/', 'npmUserconfig': str(config)})
                self.assertIn('连接正常', probe_npm(values, cwd))
                install_package(ROOT / 'runtime/releases' / RELEASE_NAME, cwd, agent, 'npm:umeko-registry-fixture@1.0.0', timeout=45, npm_config=values)
                rows = resource_command(ROOT / 'runtime/releases' / RELEASE_NAME, cwd, agent, {}, action='scan')
                self.assertTrue(any('umeko-registry-fixture' in row['path'] for row in rows), rows)
                self.assertTrue(any(path.startswith('/fixture.tgz') for path in requests), requests)
        finally:
            server.shutdown(); server.server_close()


if __name__ == '__main__': unittest.main()
