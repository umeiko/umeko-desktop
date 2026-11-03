"""Route the retained release entry point to its managed source checkout."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .platform_support import data_directory


def profile_directory():
    return Path(os.environ.get('UMEKO_DATA_DIR') or data_directory())


def channel_state(directory):
    try:
        value = json.loads((Path(directory) / 'preview-channel.json').read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def launch_command(directory, state):
    """Use the venv directly: Start-Umeko prefers dist and would select release."""
    if state.get('channel') == 'preview':
        source = Path(directory) / 'preview/source'
        python = source / ('.venv/Scripts/pythonw.exe' if os.name == 'nt' else '.venv/bin/python')
        if state.get('dependencyPending'):
            raise OSError('预览版依赖尚未安装完成，请重试更新或切回正式版。')
        if not python.is_file() or not (source / 'main.py').is_file():
            raise OSError('预览版启动文件缺失，请切回正式版后重试。')
        return [str(python), str(source / 'main.py')], source
    release = Path(state.get('releaseExecutable', ''))
    if not release.is_file():
        raise OSError('找不到保留的正式版，请从原安装目录启动正式版。')
    return [str(release)], release.parent


def start_channel(directory, state, arguments=()):
    command, working = launch_command(directory, state)
    environment = os.environ.copy()
    # A source Python must not inherit the frozen application's library paths.
    for key in ('QT_PLUGIN_PATH', 'QML2_IMPORT_PATH', 'QML_IMPORT_PATH', 'PYTHONHOME', 'PYTHONPATH'):
        environment.pop(key, None)
    if getattr(sys, 'frozen', False):
        original = environment.pop('LD_LIBRARY_PATH_ORIG', None)
        if original is None:
            environment.pop('LD_LIBRARY_PATH', None)
        else:
            environment['LD_LIBRARY_PATH'] = original
    environment['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    environment['UMEKO_DATA_DIR'] = str(directory)
    return subprocess.Popen(command + list(arguments), cwd=working, env=environment,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                            start_new_session=os.name != 'nt')


def wait_for_previous_process(pid):
    """Allow Windows to release the source venv executable before removing it."""
    if not pid: return
    if not isinstance(pid, int) or pid <= 0 or pid == os.getpid():
        raise OSError('预览版仍在运行，暂时保留源码。')
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87: return  # Process already exited.
            raise OSError('无法确认预览版已退出，暂时保留源码。')
        try:
            if kernel.WaitForSingleObject(handle, 30000) != 0:
                raise OSError('预览版仍在运行，暂时保留源码。')
        finally:
            kernel.CloseHandle(handle)
        return
    deadline = time.monotonic() + 30
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        if time.monotonic() >= deadline:
            raise OSError('预览版仍在运行，暂时保留源码。')
        time.sleep(.1)


def route_start(root):
    """Run before loading Qt; helper/worker invocations keep their own entry point."""
    if any(flag in sys.argv for flag in ('--install-update', '--umeko-plugin-worker')):
        return False
    directory = profile_directory()
    state = channel_state(directory)
    if '--release-channel' in sys.argv and getattr(sys, 'frozen', False):
        # Recovery remains available even when Preview cannot load its GUI.
        state['channel'] = 'release'
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / 'preview-channel.json.tmp'
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(directory / 'preview-channel.json')
        sys.argv.remove('--release-channel')
        return False
    managed = Path(root).resolve() == (directory / 'preview/source').resolve()
    preview = state.get('channel') == 'preview'
    if not ((getattr(sys, 'frozen', False) and preview) or (managed and not preview)):
        return False
    try:
        start_channel(directory, state, sys.argv[1:])
        return True
    except OSError as error:
        # A damaged preview must never prevent opening the retained release.
        os.environ['UMEKO_PREVIEW_LAUNCH_ERROR'] = str(error)
        return False
