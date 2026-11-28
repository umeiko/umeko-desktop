import os
import ssl
import stat
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app.network_retry import upstream_failure
from app.request_diagnostics import RequestDiagnostics, RequestFailure


class RequestDiagnosticsIoTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.diagnostics = RequestDiagnostics(Path(temp.name))
        self.provider = {'id': 'fixture'}

    def test_unwritable_report_directory_preserves_upstream_classification(self):
        self.diagnostics.directory.write_text('not a directory', encoding='utf-8')
        http = [{'timing': {'phase': 'stream_idle'}}]
        error = self.diagnostics.failure(self.provider, {}, {}, TimeoutError('upstream timeout'), http)
        self.assertIsInstance(error, RequestFailure)
        self.assertIn('超时', str(error))
        self.assertNotIn('[Umeko:', str(error))
        self.assertTrue(error.retryable)
        self.assertTrue(error.gateway_timeout)
        self.assertTrue(upstream_failure(error)['retryable'])

        http[0]['httpRetryManaged'] = True
        managed = self.diagnostics.failure(self.provider, {}, {}, TimeoutError('upstream timeout'), http)
        self.assertFalse(managed.retryable)
        self.assertEqual(upstream_failure(managed)['code'], 'umeko_http_retry_finished')

        tls = self.diagnostics.failure(self.provider, {}, {}, ssl.SSLCertVerificationError('bad CA'))
        self.assertFalse(tls.retryable)
        self.assertEqual(upstream_failure(tls)['code'], 'umeko_tls_certificate')
        self.assertNotIn('open request details', str(tls))
        self.assertNotIn('[Umeko:', str(tls))

    @unittest.skipUnless(os.name == 'nt', 'Tests Windows read-only file semantics')
    def test_windows_permission_denied_preserves_timeout(self):
        identifier = uuid.uuid4()
        self.diagnostics.directory.mkdir()
        path = self.diagnostics.directory / f'{identifier}.json'
        path.write_text('{}', encoding='utf-8')
        path.chmod(stat.S_IREAD)
        self.addCleanup(path.chmod, stat.S_IWRITE)
        with self.assertRaises(PermissionError):
            path.write_text('blocked', encoding='utf-8')
        with patch('app.request_diagnostics.uuid.uuid4', return_value=identifier):
            error = self.diagnostics.failure(self.provider, {}, {}, TimeoutError('upstream timeout'))
        self.assertTrue(error.retryable)
        self.assertIn('超时', str(error))
        self.assertNotIn('[Umeko:', str(error))
        self.assertEqual(path.read_text(encoding='utf-8'), '{}')

    def test_unwritable_compatibility_report_does_not_fail_a_success(self):
        http = [{'parameterRetry': True}]
        self.diagnostics.directory.write_text('not a directory', encoding='utf-8')
        self.assertEqual(self.diagnostics.compatibility(self.provider, {}, http), '')
        self.assertEqual(self.diagnostics.latest_compatibility('fixture')['compatibilityReportId'], '')

    def test_prune_failure_leaves_new_report_readable(self):
        self.diagnostics.directory.mkdir()
        for index in range(30):
            path = self.diagnostics.directory / f'{uuid.uuid4()}.json'
            path.write_text('{}', encoding='utf-8')
            os.utime(path, (index + 1000, index + 1000))
        original_unlink = Path.unlink

        def unlink(path, *args, **kwargs):
            if path.parent == self.diagnostics.directory:
                raise PermissionError('synthetic cleanup failure')
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, 'unlink', unlink):
            identifier = self.diagnostics.compatibility(self.provider, {}, [{'parameterRetry': True}])
        self.assertTrue(identifier)
        self.assertTrue(self.diagnostics.read(identifier))
        self.assertEqual(self.diagnostics.latest_compatibility('fixture')['compatibilityReportId'], identifier)
        self.assertEqual(len(list(self.diagnostics.directory.glob('*.json'))), 31)

        error = self.diagnostics.failure(self.provider, {}, {}, TimeoutError('upstream timeout'))
        self.assertRegex(str(error), r'\[Umeko:[a-f0-9-]{36}\]')
        self.assertEqual(len(list(self.diagnostics.directory.glob('*.json'))), 30)
