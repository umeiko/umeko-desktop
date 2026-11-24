"""Package the patched PortableGit using solid LZMA2, like the official release.

See git-for-windows/build-extra/portable/release.sh at f48a694d.
"""
import lzma
from pathlib import Path
import shutil
import stat
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.sandbox_git_bash import ARCHIVE_NAME, REQUIRED_FILES


def main():
    bundle = ROOT / "build/sandbox-git"
    if not all((bundle / name).is_file() for name in REQUIRED_FILES):
        raise RuntimeError("Build the patched PortableGit bundle before archiving it")
    output = ROOT / "runtime/releases/coding-1.5.2/bin/windows-sandbox"
    output.mkdir(parents=True, exist_ok=True)
    legacy = output / "git"
    if legacy.is_symlink() or legacy.is_junction():
        raise RuntimeError("The old sandbox Git bundle must be an ordinary directory")
    if legacy.is_dir():
        shutil.rmtree(legacy)
    archive = output / ARCHIVE_NAME
    temporary = archive.with_suffix(".tmp")
    # Group similar file types, as the upstream solid 7-Zip build does.
    entries = sorted(bundle.rglob("*"), key=lambda path: (path.suffix.lower(), path.as_posix().lower()))
    try:
        with lzma.open(temporary, "wb", filters=[
            {"id": lzma.FILTER_LZMA2, "preset": 9, "dict_size": 128 * 1024 * 1024},
        ]) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", dereference=True) as tar:
                for path in entries:
                    relative = path.relative_to(bundle).as_posix()
                    attributes = path.lstat()
                    if attributes.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                        raise RuntimeError(f"Unexpected reparse point in PortableGit: {relative}")
                    tar.add(path, arcname=relative, recursive=False)
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"{archive.name}: {archive.stat().st_size:,} bytes", flush=True)


if __name__ == "__main__":
    main()
