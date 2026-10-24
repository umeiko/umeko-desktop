"""Build the Linux IME against the exact Qt bundled by PySide6."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

if not sys.platform.startswith('linux'): raise SystemExit(0)
from PySide6.QtCore import qVersion
ROOT = Path(__file__).resolve().parents[1]
version = qVersion()
qt = Path(os.environ.get('QT_ROOT', ROOT/'build/qt-sdk'/version/'gcc_64'))
if not (qt/'lib/cmake/Qt6/Qt6Config.cmake').is_file():
    subprocess.run([sys.executable, '-m', 'aqt', 'install-qt', 'linux', 'desktop', version,
                    'linux_gcc_64', '--outputdir', str(ROOT/'build/qt-sdk'), '--archives', 'qtbase', 'icu'], check=True)
    qt = ROOT/'build/qt-sdk'/version/'gcc_64'
detected = subprocess.check_output([str(qt/'bin/qmake'), '-query', 'QT_VERSION'], text=True).strip()
if detected != version: raise SystemExit(f'IME SDK Qt {detected} differs from PySide Qt {version}')
cmake = shutil.which('cmake', path=str(Path(sys.executable).parent)) or shutil.which('cmake')
if not cmake: raise SystemExit('Install CMake 3.24+, extra-cmake-modules, libxkbcommon-dev, libxcb1-dev and libx11-dev.')
build = ROOT/'build/input-method'
args = [cmake, '-S', str(ROOT/'native/input-method'), '-B', str(build), '-DCMAKE_BUILD_TYPE=Release',
        '-DCMAKE_PREFIX_PATH='+str(qt), '-DPython3_EXECUTABLE='+sys.executable]
# Local SDK/dependency overrides are ordinary CMake arguments; CI uses system headers.
args.extend(sys.argv[1:])
subprocess.run(args, check=True)
subprocess.run([cmake, '--build', str(build), '--parallel', '3'], check=True)
plugin = build/'plugins/platforminputcontexts/libfcitx5platforminputcontextplugin.so'
if not plugin.is_file(): raise SystemExit('fcitx5 input context plugin was not built')
licenses = ROOT/'licenses/fcitx5-qt'
shutil.copytree(build/'source/LICENSES', licenses, dirs_exist_ok=True)
print('Linux input method:', plugin)
