"""Build the optional CodeArts Provider ZIP separately from desktop resources."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "provider_dev/plugins/codearts"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "build/optional-providers",
        help="ZIP output directory (default: build/optional-providers)",
    )
    args = parser.parse_args()
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

    def sdk(command, *arguments):
        subprocess.run(
            [sys.executable, "-m", "umeko_provider_sdk", command, str(PLUGIN), *arguments],
            cwd=ROOT, env=environment, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    sdk("validate")
    manifest = json.loads((PLUGIN / "manifest.json").read_text(encoding="utf-8-sig"))
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"umeko-codearts-provider-{manifest['version']}.zip"
    sdk("pack", str(archive))
    print(archive)


if __name__ == "__main__":
    main()
