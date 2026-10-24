"""Build the small OS notification adapter; installed apps need no build tools."""
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
output = ROOT/'build/notification-runtime'
output.mkdir(parents=True, exist_ok=True)
if sys.platform not in ('win32', 'darwin'):
    (output/'README.txt').write_text('Linux notifications use the desktop D-Bus notification service.\n')
    raise SystemExit(0)
cmake = Path(sys.executable).parent/('cmake.exe' if os.name == 'nt' else 'cmake')
program = str(cmake) if cmake.is_file() else shutil.which('cmake')
if not program: raise SystemExit('Packaging native notifications requires CMake 3.24+ and the platform C++ SDK.')
build = ROOT/'build/notifications-native'
args = [program, '-S', str(ROOT/'native/notifications'), '-B', str(build), '-DUMEKO_NOTIFY_SHARED=ON', '-DCMAKE_BUILD_TYPE=Release']
if os.name == 'nt': args += ['-G', 'Visual Studio 17 2022', '-A', 'x64']
else: args += ['-DCMAKE_OSX_ARCHITECTURES='+platform.machine(), '-DCMAKE_OSX_DEPLOYMENT_TARGET=13.0']
subprocess.run(args, check=True)
subprocess.run([program, '--build', str(build), '--config', 'Release', '--parallel', '2'], check=True)
name = 'umeko_notifications.dll' if os.name == 'nt' else 'libumeko_notifications.dylib'
source = next(build.rglob(name), None)
if not source: raise SystemExit('Native notification library was not generated.')
shutil.copy2(source, output/name)
print('Native notification adapter:', output/name)
