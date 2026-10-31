"""Compatibility entry point: package the latest selected portraits."""
import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent.parent / "v5/build.py"),
                   run_name="__main__")
