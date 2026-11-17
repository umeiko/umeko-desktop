"""Compatibility entry point: build the current revision, not retired artwork."""
import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent.parent / "kazuhiko-v2/build.py"), run_name="__main__")
