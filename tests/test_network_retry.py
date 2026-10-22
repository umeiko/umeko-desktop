import subprocess
import unittest
from pathlib import Path
from app.network_retry import transient_failure
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

    def test_shared_retry_contract(self):
        subprocess.run([node_executable(), '--test', str(Path(__file__).with_name('network_retry_test.mjs'))], check=True, capture_output=True, timeout=15)
