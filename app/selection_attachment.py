"""Store a selected passage without overwriting an earlier attachment."""
import re
from pathlib import Path


def write_selection(workspace, text):
    if not text.strip():
        return None
    project = Path(workspace).resolve(strict=True)
    if not project.is_dir():
        raise OSError('当前会话目录不存在')
    folder = project / '.umeko'
    if folder.is_symlink():
        raise OSError('.umeko 不能是符号链接')
    folder.mkdir(exist_ok=True)
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f-\x9f]', '_', ' '.join(text.split())[:20]).strip(' .') or '选中文本'
    if re.fullmatch(r'(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', stem):
        stem = '选文-' + stem
    for index in range(1, 10001):
        path = folder / (stem + (f' ({index})' if index > 1 else '') + '.md')
        try:
            stream = path.open('x', encoding='utf-8', newline='')
        except FileExistsError:
            continue
        try:
            with stream:
                stream.write(text)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return {'id': path.name, 'name': path.name, 'path': str(path), 'kind': 'file'}
    raise OSError('同名临时文件过多')
