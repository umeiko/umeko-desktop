"""Build public SDK downloads and default-installable Provider SDK packages."""
from pathlib import Path
import json
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/provider-resources"
sys.path.insert(0, str(ROOT))

from umeko_provider_sdk.packages import pack_package, validate_folder


def archive(target, groups):
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as stream:
        for source, prefix in groups:
            paths = sorted(source.rglob("*")) if source.is_dir() else [source]
            for path in paths:
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    name = str(Path(prefix) / path.relative_to(source)) if source.is_dir() else prefix
                    stream.write(path, name.replace("\\", "/"))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    archive(OUT / "umeko-provider-sdk-0.2.1.zip", [(ROOT / "umeko_provider_sdk", "umeko_provider_sdk"),
        (ROOT / "pyproject.toml", "pyproject.toml"), (ROOT / "provider_dev/README.md", "README.md"),
        (ROOT / "provider_dev/examples", "examples")])
    archive(OUT / "develop-umeko-provider.zip", [(ROOT / "provider_dev/skills/develop-umeko-provider", "develop-umeko-provider")])
    providers = []
    for folder in sorted((ROOT / "provider_dev/bundled").glob("*")):
        if not folder.is_dir() or folder.is_symlink():
            continue
        manifest, _, _ = validate_folder(folder)
        name = manifest["id"] + "-" + manifest["version"] + ".zip"
        pack_package(folder, OUT / name)
        providers.append({key: manifest[key] for key in ("id", "version", "name")} | {"archive": name})
    (OUT / "bundled-providers.json").write_text(
        json.dumps({"schemaVersion": 1, "providers": providers}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUT)


if __name__ == "__main__": main()
