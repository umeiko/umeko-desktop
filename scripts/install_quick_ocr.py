"""Install the optional CPU OCR component into an existing Umeko profile."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv

PINS = ("rapidocr==3.10.0", "onnxruntime==1.24.3", "Pillow==13.0.0", "opencv-python-headless==5.1.0.95")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-dir", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, help="Only use wheel files from this folder; no index/network.")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        parser.error("Use Python 3.12 on the target machine.")
    profile = args.profile_dir.expanduser().resolve()
    if not profile.is_dir():
        parser.error("Use the existing profile path copied from the Umeko OCR dialog.")
    wheelhouse = None
    if args.wheelhouse:
        wheelhouse = args.wheelhouse.expanduser().resolve()
        if not wheelhouse.is_dir() or not any(wheelhouse.glob("*.whl")):
            parser.error("Wheelhouse must contain Python 3.12-compatible wheel files for this machine.")
    worker = Path(__file__).resolve().parents[1] / "app/quick_ocr_worker.py"
    if not worker.is_file():
        parser.error("Run from the Quick OCR source preview (both installer and app worker are required).")
    component = profile / "quick-ocr"
    component.mkdir(exist_ok=True)
    destination = component / "venv"
    if destination.exists():
        parser.error(f"{destination} already exists. Remove or move that optional folder before reinstalling.")
    # Create the venv at its final location: Windows and pip wrappers can embed
    # absolute paths. With a fresh directory, only our own candidate is cleaned.
    destination.mkdir()
    try:
        venv.EnvBuilder(with_pip=True).create(destination)
        python = destination / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        index = ["--no-index", "--find-links", str(wheelhouse)] if wheelhouse else []
        with tempfile.TemporaryDirectory() as cache:
            subprocess.run([str(python), "-I", "-m", "pip", "--isolated", "--disable-pip-version-check",
                            "install", "--cache-dir", cache, "--only-binary=:all:", *index, *PINS], check=True)
        result = subprocess.run([str(python), "-I", str(worker), "--check"], check=True, capture_output=True)
        if result.stdout.strip() != b'{"ok": true}':
            raise RuntimeError("Runtime/weight verification failed: " + result.stdout[:120].decode("ascii", "replace"))
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    print("Quick OCR ready. Open the dialog again or click Check again.")

if __name__ == "__main__":
    main()
