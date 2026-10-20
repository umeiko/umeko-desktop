"""Write public build metadata consumed by the packaged About page."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.project_info import build_metadata

if __name__ == "__main__":
    target = ROOT / "build/build-info.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build_metadata(ROOT), ensure_ascii=False, indent=2), encoding="utf-8")
    print("Build metadata:", target)
