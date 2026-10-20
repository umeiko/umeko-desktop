"""Build the two public development downloads bundled with Umeko. No private packages."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/provider-resources"


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
    archive(OUT / "umeko-provider-sdk-0.1.0.zip", [(ROOT / "umeko_provider_sdk", "umeko_provider_sdk"),
        (ROOT / "pyproject.toml", "pyproject.toml"), (ROOT / "provider_dev/README.md", "README.md"),
        (ROOT / "provider_dev/examples", "examples")])
    archive(OUT / "develop-umeko-provider.zip", [(ROOT / "provider_dev/skills/develop-umeko-provider", "develop-umeko-provider")])
    print(OUT)


if __name__ == "__main__": main()
