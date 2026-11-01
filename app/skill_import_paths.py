"""Pin approved import directories across staging, replacement and rollback.

POSIX operations use directory descriptors and never traverse a replaced path.
Windows pins ancestors with handles that deny delete/rename, rejecting reparse
points (including junctions on Python 3.10).
"""
from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path


def linked_info(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def identity(info):
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


def snapshot(paths):
    expected = {}
    for path in paths:
        for directory in reversed((path, *path.parents)):
            if directory in expected:
                continue
            try:
                info = directory.lstat()
            except FileNotFoundError:
                expected[directory] = None
                continue
            if linked_info(info) or not stat.S_ISDIR(info.st_mode):
                raise ValueError('技能目标目录不能使用符号链接或目录联接')
            expected[directory] = identity(info)
    return expected


class ImportDirectories:
    def __init__(self, expected):
        self.expected = dict(expected)
        self.opened = {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.release_below(None)

    def release_below(self, path):
        for item in list(reversed(self.opened)):
            if path is None or item == path or path in item.parents:
                handle = self.opened.pop(item)
                if os.name == 'nt':
                    self._windows_close(handle)
                else:
                    os.close(handle)

    @staticmethod
    def _windows_close(handle):
        import ctypes
        from ctypes import wintypes
        close = ctypes.windll.kernel32.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        close(handle)

    @staticmethod
    def _windows_pin(path):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        # FILE_LIST_DIRECTORY participates in share-access checks. A metadata-
        # only handle (DesiredAccess=0) does not reliably deny rename/delete.
        # READ|WRITE sharing deliberately omits FILE_SHARE_DELETE; opening the
        # reparse point itself avoids following a final junction before lstat.
        handle = create(str(path), 0x00000001, 3, None, 3, 0x02000000 | 0x00200000, None)
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def directory(self, path, create=False):
        path = Path(path)
        if path in self.opened:
            return self.opened[path]
        if path not in self.expected:
            raise OSError('Unapproved import directory')
        parent = None if path.parent == path else self.directory(path.parent, create)
        wanted = self.expected[path]
        if wanted is None:
            if not create:
                raise OSError('Import directory disappeared; preview again')
            # A previously absent directory appearing before our mkdir is a
            # changed approval boundary, even if it is an ordinary directory.
            if os.name == 'nt':
                path.mkdir(mode=0o700)
            else:
                os.mkdir(path.name, mode=0o700, dir_fd=parent)
        if os.name == 'nt':
            handle = self._windows_pin(path)
            try:
                info = path.lstat()
                if linked_info(info) or not stat.S_ISDIR(info.st_mode) or (wanted is not None and identity(info) != wanted):
                    raise OSError('Import directory changed; preview again')
            except BaseException:
                self._windows_close(handle)
                raise
        else:
            handle = os.open(str(path) if parent is None else path.name,
                             os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            info = os.fstat(handle)
            if wanted is not None and identity(info) != wanted:
                os.close(handle)
                raise OSError('Import directory changed; preview again')
        self.expected[path] = identity(info)
        self.opened[path] = handle
        return handle

    def mkdir(self, path):
        self.expected[path] = None
        self.directory(path, create=True)

    def check_target(self, path, expected):
        parent = self.directory(path.parent)
        try:
            info = path.lstat() if os.name == 'nt' else os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            if expected is None:
                return
            raise OSError('Skill target disappeared; preview again') from None
        if linked_info(info) or identity(info) != expected:
            raise OSError('Skill target changed; preview again')

    def write(self, path, content):
        if path.parent not in self.opened:
            if path.parent not in self.expected:
                self.mkdir_parents(path.parent)
            else:
                self.directory(path.parent)
        if os.name == 'nt':
            with path.open('xb') as stream:
                stream.write(content)
        else:
            fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=self.directory(path.parent))
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)

    def mkdir_parents(self, path):
        if path in self.opened:
            return
        if path in self.expected:
            self.directory(path)
            return
        self.mkdir_parents(path.parent)
        self.mkdir(path)

    def rename(self, source, target):
        source_parent, target_parent = self.directory(source.parent), self.directory(target.parent)
        # Windows must release the renamed child, keeping both parents pinned.
        self.release_below(source)
        if os.name == 'nt':
            source.rename(target)
        else:
            os.rename(source.name, target.name, src_dir_fd=source_parent, dst_dir_fd=target_parent)

    def remove(self, path):
        parent = self.directory(path.parent)
        self.release_below(path)
        if os.name == 'nt':
            # Python >=3.8 rmtree never descends into directory junctions.
            if path.is_symlink():
                path.unlink()
            else:
                shutil.rmtree(path)
            return
        self._remove_at(parent, path.name)

    @classmethod
    def _remove_at(cls, parent, name):
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode):
            os.unlink(name, dir_fd=parent)
            return
        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            if identity(os.fstat(child)) != identity(info):
                raise OSError('Import cleanup directory changed')
            with os.scandir(child) as entries:
                for entry in entries:
                    cls._remove_at(child, entry.name)
        finally:
            os.close(child)
        os.rmdir(name, dir_fd=parent)
