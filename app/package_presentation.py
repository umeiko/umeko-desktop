"""Read-only presentation of structured and legacy package audit records.

Persistence stays in package_records.py. Legacy records contain Python reprs;
literal_eval reads data only, and incomplete records expose only recoverable
severity/pattern/location fields, never executable content or source contexts.
"""
import ast
import json
import re

SEVERITIES = ("critical", "high", "medium", "low", "info")


def audit_presentation(value):
    report = value if isinstance(value, dict) else {}
    raw = value if isinstance(value, str) else ""
    findings = report.get("findings", [])
    if raw:
        start = raw.find("[{")
        if start >= 0:
            encoded = raw[start:]
            for reader in (json.loads, ast.literal_eval):
                try:
                    findings = reader(encoded)
                    break
                except (ValueError, SyntaxError):
                    pass
            if not findings:
                # Historical records were bounded while being saved. Recover
                # complete display fields even if a later source context was cut.
                findings = []
                for part in re.split(r"(?=\{['\"]severity['\"]\s*:)", encoded)[1:]:
                    row = {}
                    for field in ("severity", "pattern", "file", "line"):
                        match = re.search(r"['\"]" + field + r"['\"]\s*:\s*('(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|\d+)", part)
                        if match:
                            try:
                                row[field] = ast.literal_eval(match[1])
                            except (ValueError, SyntaxError):
                                pass
                    findings.append(row)
    rows = []
    for finding in findings if isinstance(findings, list) else []:
        if not isinstance(finding, dict):
            continue
        rows.append({key: str(finding.get(key, "")) for key in ("severity", "pattern", "file", "line")})
    counts = {severity: sum(row["severity"] == severity for row in rows) for severity in SEVERITIES}
    summary = str(report.get("summary", "")) or raw.split("\n", 1)[0]
    # Keep the original total when an older stored finding list was truncated.
    for severity in SEVERITIES:
        match = re.search(r"\b(\d+) " + severity + r"\b", summary)
        if match:
            counts[severity] = max(counts[severity], int(match[1]))
    status = "findings" if any(counts.values()) else "notes"
    if report.get("scanError") or report.get("deepScanned") is False or "Metadata-only audit" in summary or any(row["pattern"] == "Source scan unavailable" for row in rows):
        status = "incomplete"
    elif summary in ("Not audited", "尚未检查", ""):
        status = "not-audited"
    elif not rows and ("No " in summary or "no " in summary) and "finding" in summary:
        status = "clear"
    return {"counts": counts, "findings": rows, "status": status,
            "note": summary if status == "notes" else ""}
