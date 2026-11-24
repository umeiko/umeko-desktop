#!/usr/bin/env bash
# Adapted from git-for-windows/msys2-runtime .github/workflows/build.yaml
# at d25c02bd8bbfef7da4b42eab6f0834bcb9d9343e.
set -euo pipefail

revision=d25c02bd8bbfef7da4b42eab6f0834bcb9d9343e
git_release=2.56.1
root=$(cd -- "$(dirname -- "$0")/.." && pwd)
build="$root/build"
mkdir -p -- "$build"
staging=$(mktemp -d -- "$build/sandbox-git.XXXXXXXX")
cleanup() { rm -rf -- "$staging"; }
trap cleanup EXIT

git -c core.autocrlf=false init "$staging/runtime"
git -c core.autocrlf=false -C "$staging/runtime" fetch --depth=1 https://github.com/git-for-windows/msys2-runtime.git "$revision"
git -c core.autocrlf=false -C "$staging/runtime" checkout --detach FETCH_HEAD
git -c core.autocrlf=false -C "$staging/runtime" apply --whitespace=error "$root/scripts/windows-sandbox-msys-signal.patch"
(
    cd -- "$staging/runtime"
    (cd winsup && ./autogen.sh)
    ./configure --disable-dependency-tracking --with-msys2-runtime-commit="$revision"
    make -j4
    make DESTDIR="$staging/install" install
)

archive="$staging/portable.7z.exe"
curl --fail --location --silent --show-error --output "$archive" \
    "https://github.com/git-for-windows/git/releases/download/v${git_release}.windows.1/PortableGit-${git_release}-64-bit.7z.exe"
bundle="$staging/git"
'/c/Program Files/7-Zip/7z.exe' x -y "-o$(cygpath -w "$bundle")" "$(cygpath -w "$archive")"
runtime=$(find "$staging/install" -type f -name msys-2.0.dll)
test -f "$runtime" && test -f "$bundle/bin/bash.exe" && test -f "$bundle/usr/bin/msys-2.0.dll"
cp -- "$runtime" "$bundle/usr/bin/msys-2.0.dll"
cp -- "$staging/runtime/winsup/CYGWIN_LICENSE" "$bundle/CYGWIN_LICENSE"
cp -- "$root/scripts/windows-sandbox-msys-signal.patch" "$bundle/umeko-signal-pipe.patch"
test ! -e "$build/sandbox-git"
mv -- "$bundle" "$build/sandbox-git"
