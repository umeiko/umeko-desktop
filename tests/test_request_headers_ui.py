import os
from pathlib import Path
import subprocess
import sys
import unittest

class RequestHeadersUiTests(unittest.TestCase):
    def test_editor(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([sys.executable,str(root/'tests/request_headers_ui_smoke.py')],cwd=root,env=os.environ.copy(),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout)
        self.assertIn('REQUEST_HEADERS_UI_OK',result.stdout)
