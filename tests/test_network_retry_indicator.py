"""Run the real bridge/Pi retry lifecycle in shared unittest discovery."""
import subprocess
import unittest
from pathlib import Path

from app.pi_runtime import CREATE_NO_WINDOW, node_executable


class RetryIndicatorTests(unittest.TestCase):
    def test_bridge_retry_lifecycle(self):
        result = subprocess.run(
            [node_executable(), '--test', str(Path(__file__).with_name('network-retry-bridge.test.mjs'))],
            capture_output=True, text=True, encoding='utf-8', timeout=180,
            creationflags=CREATE_NO_WINDOW,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
