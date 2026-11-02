"""Filesystem boundaries for the two Skill roots, independent of chat switches."""
from pathlib import Path
import os
import stat
import uuid

from umeko_provider_sdk.packages import normalize_package_path, PackageValidationError
from .skill_import_paths import ImportDirectories, linked_info, snapshot


def preview_folder(approval):
    """Read a bounded document from the pinned, approved Skill directory."""
    directory = checked_folder(approval)
    with ImportDirectories(approval['directories']) as pinned:
        parent = pinned.directory(directory)
        path = directory / 'SKILL.md'
        info = path.lstat() if os.name == 'nt' else os.stat('SKILL.md', dir_fd=parent, follow_symlinks=False)
        if linked_info(info) or not stat.S_ISREG(info.st_mode):
            raise ValueError('Skill 文件已变化，请刷新目录')
        from .skill_import_paths import identity
        fd = os.open(path if os.name == 'nt' else 'SKILL.md',
                     os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0),
                     **({} if os.name == 'nt' else {'dir_fd': parent}))
        with os.fdopen(fd, 'rb') as stream:
            if identity(os.fstat(stream.fileno())) != identity(info):
                raise ValueError('Skill 文件已变化，请刷新目录')
            raw = stream.read(65536)
    text = raw.decode('utf-8-sig', 'replace')
    return {'path': str(path), 'markdown': text[:24000], 'truncated': info.st_size > len(raw) or len(text) > 24000}


def folder_snapshots(value, roots):
    """Native discovery supplies metadata; the host owns filesystem authority."""
    approved, rows = {}, []
    for row in value['skills']:
        root = roots.get(row.get('scope'))
        if root is None:
            continue
        directory = Path(row.get('directory', ''))
        path = Path(row.get('path', ''))
        if not directory.is_absolute() or not directory.is_relative_to(root) or directory == root or path != directory / 'SKILL.md':
            continue
        try:
            directories = snapshot([root, directory])
            info = path.lstat()
            if linked_info(info) or not stat.S_ISREG(info.st_mode):
                continue
            approved[row['id']] = {'directories': directories, 'identity': directories[directory],
                                   'root': root, 'directory': directory, 'scope': row['scope']}
            rows.append(row)
        except OSError:
            continue
        except ValueError:
            continue
    value['skills'] = rows
    return approved


def checked_folder(approval):
    if not approval:
        raise ValueError('请刷新 Skill 目录后重试')
    directory = approval['directory']
    with ImportDirectories(approval['directories']) as pinned:
        pinned.directory(directory.parent)
        pinned.check_target(directory, approval['identity'])
        info = (directory / 'SKILL.md').lstat()
        if linked_info(info) or not stat.S_ISREG(info.st_mode):
            raise ValueError('Skill 文件已变化，请刷新目录')
    return directory


def validate_folder_name(name):
    try:
        valid = isinstance(name, str) and bool(name) and len(name) <= 128 and normalize_package_path(name) == name and '/' not in name
    except PackageValidationError:
        valid = False
    if not valid:
        raise ValueError('请输入有效的 Skill 文件夹名称')


def rename_folder(approval, name):
    validate_folder_name(name)
    directory = approval['directory']
    target = directory.parent / name
    if target == directory:
        return directory
    with ImportDirectories(approval['directories']) as pinned:
        pinned.directory(directory.parent)
        pinned.check_target(directory, approval['identity'])
        pinned.check_target(target, None)
        pinned.rename(directory, target)
    return target


def delete_folder(approval):
    directory = approval['directory']
    with ImportDirectories(approval['directories']) as pinned:
        pinned.directory(directory.parent)
        pinned.check_target(directory, approval['identity'])
        # Move the approved entry before removal. Cleanup never follows links
        # in its assets, and a swapped ancestor cannot redirect the operation.
        retired = directory.parent / ('.umeko-delete-' + uuid.uuid4().hex)
        pinned.rename(directory, retired)
        try:
            pinned.remove(retired)
        except OSError as error:
            raise OSError('Skill 已移至 ' + retired.name + '，清理未完成，请在原目录检查。') from error
