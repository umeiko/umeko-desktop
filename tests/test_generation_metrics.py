import subprocess
import unittest
from pathlib import Path
from app.pi_runtime import node_executable


class GenerationMetricsTests(unittest.TestCase):
    def test_streaming_generation_meter(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([node_executable(), '--test', 'tests/generation_metrics_test.mjs'],
            cwd=root, capture_output=True, text=True, timeout=15, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
