"""Audit display must be readable without rewriting the stored metadata."""
import copy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from app.package_presentation import audit_presentation


class PackagePresentationTests(unittest.TestCase):
    def test_structured_audit_keeps_only_display_fields_without_mutation(self):
        value = {"summary": "3 finding(s) found (0 critical, 0 high, 3 medium, 0 low, 0 info).", "findings": [
            {"severity": "medium", "pattern": "HTTP client usage", "file": file, "line": line, "context": "PRIVATE CONTEXT"}
            for file, line in (("index.ts", 5), ("index.ts", 102), ("request.ts", 264))]}
        original = copy.deepcopy(value)
        shown = audit_presentation(value)
        self.assertEqual(shown["counts"]["medium"], 3)
        self.assertEqual(len(shown["findings"]), 3)
        self.assertNotIn("PRIVATE", json.dumps(shown))
        self.assertEqual(value, original)

    def test_legacy_python_repr_and_truncated_context_are_display_only(self):
        legacy = "3 finding(s) found (0 critical, 0 high, 3 medium, 0 low, 0 info).\n" + repr([
            {"severity": "medium", "pattern": "HTTP client usage", "file": "index.ts", "line": 5, "context": "unfinished"}])
        self.assertEqual(audit_presentation(legacy)["findings"][0]["line"], "5")
        truncated = legacy[:legacy.index("unfinished") + 4]
        result = audit_presentation(truncated)
        self.assertEqual(result["counts"]["medium"], 3)
        self.assertEqual(result["findings"][0]["file"], "index.ts")
        self.assertEqual(result["findings"][0]["line"], "5")

    def test_unscanned_audit_and_empty_notes_do_not_claim_a_clean_scan(self):
        self.assertEqual(audit_presentation({"deepScanned": False, "findings": []})["status"], "incomplete")
        self.assertEqual(audit_presentation("Not audited")["status"], "not-audited")
        self.assertEqual(audit_presentation("Metadata-only audit (no source scan).")["status"], "incomplete")

    def test_qml_summary_expansion_and_both_languages(self):
        environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software", "QT_QUICK_CONTROLS_STYLE": "Basic"}
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("package_presentation_qml.py"))],
            env=environment, capture_output=True, text=True, timeout=45,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PACKAGE_PRESENTATION_QML_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
