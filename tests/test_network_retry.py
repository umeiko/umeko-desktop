import subprocess
import ssl
import unittest
import urllib.error
from pathlib import Path
from app.network_retry import certificate_failure, transient_failure
from app.pi_runtime import node_executable


class NetworkRetryTests(unittest.TestCase):
    def test_classification(self):
        for error in ('供应商流已中断', 'ConnectionResetError(10054)', 'IncompleteRead(12 bytes)', 'RemoteDisconnected', 'timed out'):
            self.assertTrue(transient_failure(error), error)
        for status in (408,425,429,500,502,503,504):
            self.assertTrue(transient_failure('request failed', [{'response':{'status':status}}]))
        for status in (400,401,403,404,422):
            self.assertFalse(transient_failure('stream failed', [{'response':{'status':status}}]))
        self.assertFalse(transient_failure('insufficient_quota', [{'response':{'status':429}}]))
        self.assertFalse(transient_failure('CERTIFICATE_VERIFY_FAILED'))
        self.assertTrue(transient_failure('ConnectionResetError', [{'response':{'status':200,'body':'billing and quota exceeded explained'}}]))

    def test_certificate_words_and_paths_do_not_hide_timeouts(self):
        for detail in ('timed out while reading certificate request details',
                       r'timed out opening C:\certificate\CERT_HAS_EXPIRED\request.json',
                       'timed out while reading self-signed certificate notes'):
            error = TimeoutError(detail)
            self.assertEqual(certificate_failure(error), '', detail)
            self.assertTrue(transient_failure(error), detail)
        self.assertTrue(transient_failure(TimeoutError('timed out'), [
            {'response': {'status': 503, 'body': 'certificate processing timed out'}}]))

    def test_nested_ssl_verification_and_structured_tls_codes_are_terminal(self):
        error = RuntimeError('fetch failed')
        error.__cause__ = urllib.error.URLError(ssl.SSLCertVerificationError(1, 'verification failed'))
        self.assertEqual(certificate_failure(error), 'CERTIFICATE_VERIFY_FAILED')
        self.assertFalse(transient_failure(error, [{'response': {'status': 503}}]))
        error = OSError('connection failed')
        error.code = 'CERT_HAS_EXPIRED'
        self.assertEqual(certificate_failure(error), 'CERT_HAS_EXPIRED')
        self.assertFalse(transient_failure(error))

    def test_shared_retry_contract(self):
        subprocess.run([node_executable(), '--test', str(Path(__file__).with_name('network_retry_test.mjs'))], check=True, capture_output=True, timeout=15)
