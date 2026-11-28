"""Native local project picker creates a missing folder only on confirmation."""
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import monotonic
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from main import create_application


def test(screenshots=None):
    with TemporaryDirectory(prefix='umeko-project-create-') as temporary:
        base = Path(temporary).resolve()
        profile = base / 'profile'
        os.environ.update(UMEKO_DATA_DIR=str(profile), PI_CODING_AGENT_DIR=str(base / 'agent'), UMEKO_LANGUAGE='zh')
        app, engine, backend = create_application()
        window = engine.rootObjects()[0]
        window.resize(1320, 860)

        def find(name):
            pending = [window.contentItem()]
            while pending:
                item = pending.pop()
                if item.objectName() == name and item.isVisible():
                    return item
                pending.extend(item.childItems())
            return None

        def wait(check, label):
            deadline = monotonic() + 8
            while monotonic() < deadline:
                QTest.qWait(25)
                if value := check():
                    return value
            raise AssertionError(label)

        def click(name):
            item = wait(lambda: (item := find(name)) and item.isEnabled() and item, name)
            window.grabWindow()
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier,
                             item.mapToScene(item.boundingRect().center()).toPoint())
            QTest.qWait(125)

        def type_path(value):
            field = wait(lambda: find('localPathInput'), 'Missing local path field')
            field.setProperty('text', str(value))
            return field

        def projects():
            return {row['path'] for row in backend.store.data['projects']}

        def notice(expected):
            wait(lambda: (item := find('localProjectStatus')) and expected in item.property('text'), expected)

        def save(name):
            if screenshots is not None:
                QTest.qWait(180)
                assert window.grabWindow().save(str(screenshots / name))

        try:
            before = projects()
            default = profile / 'workspace'
            default_was_present = default.exists()
            click('openWorkspacePickerButton')
            assert find('localPathInput').property('text') == str(default)
            assert default.exists() == default_was_present
            missing = base / '季度报告项目'
            field = type_path(missing)
            click('localChooseButton')
            notice('目录不存在')
            assert not missing.exists() and projects() == before
            assert find('localCreateProjectButton')
            field.forceActiveFocus()
            QTest.keyClick(window, Qt.Key_Return)
            assert not missing.exists() and projects() == before
            save('271-目录不存在.png')
            click('workspacePickerClose')
            assert not missing.exists() and projects() == before and default.exists() == default_was_present

            click('openWorkspacePickerButton')
            type_path('相对路径')
            click('localChooseButton')
            notice('有效的本机绝对路径')
            assert find('localPathInput').property('text') == '相对路径'
            assert not find('localCreateProjectButton') and projects() == before
            collision = base / '已有普通文件'
            collision.write_text('合成文件', encoding='utf-8')
            type_path(collision)
            click('localChooseButton')
            notice('该路径不是目录')
            assert collision.read_text(encoding='utf-8') == '合成文件' and projects() == before
            absent_parent = base / '不存在的父目录' / '子目录'
            type_path(absent_parent)
            click('localChooseButton')
            notice('已有的父目录')
            assert not absent_parent.parent.exists() and projects() == before

            type_path(missing)
            click('localChooseButton')
            real_mkdir = Path.mkdir

            def deny_only_target(path, *args, **kwargs):
                if path == missing:
                    raise PermissionError('fixture: synthetic denied mkdir')
                return real_mkdir(path, *args, **kwargs)

            with patch.object(Path, 'mkdir', deny_only_target):
                click('localCreateProjectButton')
            notice('权限不足')
            assert find('localPathInput').property('text') == str(missing)
            assert not missing.exists() and projects() == before
            save('271-失败保留输入.png')
            click('localCreateProjectButton')
            wait(lambda: not find('localPathInput'), 'Picker did not close after successful creation')
            assert missing.is_dir() and projects() == before | {str(missing)}
            assert backend._view.workspace == str(missing)
            row = next(row for row in backend.projectRows if row.get('path') == str(missing))
            wait(lambda: find('sidebarRow_' + row['id']), 'New project is not visible in sidebar')
            wait(lambda: backend.store.path.exists() and any(
                row.get('path') == str(missing)
                for row in json.loads(backend.store.path.read_text(encoding='utf-8')).get('projects', [])),
                 'New project was not persisted')
            save('271-项目已创建.png')

            existing = base / '已有项目 #'
            existing.mkdir()
            content = existing / '原文件.txt'
            content.write_bytes(b'unchanged fixture')
            click('openWorkspacePickerButton')
            type_path(existing.as_uri())
            click('localChooseButton')
            wait(lambda: not find('localPathInput'), 'Existing directory should open directly')
            assert backend._view.workspace == str(existing)
            assert content.read_bytes() == b'unchanged fixture' and list(existing.iterdir()) == [content]
            assert projects() == before | {str(missing), str(existing)}
            print('LOCAL_PROJECT_CREATE_UI_OK: explicit creation, unchanged existing folder, retry, no writes on cancel')
        finally:
            window.hide()
            backend.close()
            app.quit()


if __name__ == '__main__':
    output = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
    if output is not None:
        output.mkdir(parents=True, exist_ok=True)
        del sys.argv[1:]
    test(output)
