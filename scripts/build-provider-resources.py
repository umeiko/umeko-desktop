"""Build public SDK downloads and default-installable Provider SDK packages."""
from pathlib import Path
import json
import re
import shutil
import sys
import tempfile
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


def build(output):
    policy = json.loads((ROOT / "provider_dev/default-providers.json").read_text(encoding="utf-8"))
    selected = policy.get("providers") if isinstance(policy, dict) and policy.get("schemaVersion") == 1 else None
    if (not isinstance(selected, list) or any(not isinstance(item, str)
            or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", item) for item in selected)
            or len(set(selected)) != len(selected)):
        raise ValueError("Invalid default provider allow-list")
    archive(output / "umeko-provider-sdk-0.2.1.zip", [(ROOT / "umeko_provider_sdk", "umeko_provider_sdk"),
        (ROOT / "pyproject.toml", "pyproject.toml"), (ROOT / "provider_dev/README.md", "README.md"),
        (ROOT / "provider_dev/examples", "examples")])
    archive(output / "develop-umeko-provider.zip", [(ROOT / "provider_dev/skills/develop-umeko-provider", "develop-umeko-provider")])
    providers = []
    # Adding a source directory alone must never opt users into a new provider.
    for plugin_id in selected:
        folder = ROOT / "provider_dev/bundled" / plugin_id
        if not folder.is_dir() or folder.is_symlink():
            raise ValueError("Invalid default provider directory")
        manifest, _, _ = validate_folder(folder)
        if manifest["id"] != plugin_id:
            raise ValueError("Default provider ID does not match its directory")
        name = manifest["id"] + "-" + manifest["version"] + ".zip"
        pack_package(folder, output / name)
        providers.append({key: manifest[key] for key in ("id", "version", "name")} | {"archive": name})
    (output / "bundled-providers.json").write_text(
        json.dumps({"schemaVersion": 1, "providers": providers}, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="provider-resources-", dir=OUT.parent) as temporary:
        output = Path(temporary) / "resources"
        output.mkdir()
        build(output)
        # Regenerate the whole directory so removed defaults cannot survive in packages.
        if OUT.exists(): shutil.rmtree(OUT)
        output.rename(OUT)
    print(OUT)


if __name__ == "__main__": main()
