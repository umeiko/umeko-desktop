"""Exercise independent chat edges, responsive fallback and composer input."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-chat-width-')
os.environ['UMEKO_LANGUAGE'] = 'zh'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))


def find(name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name:
            return item
        stack.extend(item.childItems())
    raise AssertionError(name)


def click(name):
    item = find(name)
    assert item.isVisible() and item.isEnabled(), name
    QTest.mouseMove(window, item.mapToScene(item.boundingRect().center()).toPoint())
    QTest.qWait(150)
    if name.startswith('expandChat'):
        for _ in range(25):
            if item.opacity() > .95:
                break
            QTest.qWait(20)
        assert item.opacity() > .95, (name, item.opacity(), item.property('nearby'), item.property('hovered'))
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier,
                     item.mapToScene(item.boundingRect().center()).toPoint())
    QTest.qWait(230)


try:
    shots = ROOT / 'artifacts/screenshots'
    shots.mkdir(parents=True, exist_ok=True)
    backend.setTheme('yanami')
    window.resize(1700, 920)
    backend._view.messages = [
        {'role': 'user', 'text': '看看宽屏中的代码和表格', 'error': False},
        {'role': 'assistant', 'text': '宽屏布局示例。\n\n| 状态 | 金额 | 选择 |\n| --- | --- | --- |\n| 1 | 7 | 跳过 |\n| 2 | 11 | 偷取 |\n\n```rust\nfn rob(nums: &[i32]) -> i32 {\n    nums.iter().fold((0, 0), |(prev, best), &n| (best, best.max(prev + n))).1\n}\n```', 'error': False},
    ]
    backend.chatChanged.emit()
    QTest.qWait(300)
    layout, composer, conversation = (find(name) for name in ('chatWidthControls', 'composer', 'conversation'))
    assert layout.property('expandable')
    assert abs(composer.width() - 850) < 1
    QTest.mouseMove(window, find('promptInput').mapToScene(find('promptInput').boundingRect().center()).toPoint())
    QTest.qWait(250)
    left_button, right_button = find('expandChatLeft'), find('expandChatRight')
    assert left_button.opacity() == 0 and right_button.opacity() == 0, 'Width controls should be hidden while reading'
    zone = find('chatWidthLeftHoverZone')
    QTest.mouseMove(window, zone.mapToScene(zone.boundingRect().center()).toPoint() + QPoint(0, -55))
    QTest.qWait(160)
    assert left_button.opacity() > .95 and right_button.opacity() == 0, 'Only the nearby edge should appear'
    assert find('expandChatLeftMascot').property('loaded')
    assert window.grabWindow().save(str(shots / 'chat-width-hover-push.png'))
    QTest.mouseMove(window, find('promptInput').mapToScene(find('promptInput').boundingRect().center()).toPoint())
    QTest.qWait(250)
    assert left_button.opacity() == 0, 'Leaving the edge should hide the control'
    original_left, original_right = composer.x(), composer.x() + composer.width()
    click('expandChatLeft')
    assert composer.x() < original_left - 60
    assert abs(composer.x() + composer.width() - original_right) < 1
    assert find('expandChatLeft').property('text') == '\u25b6'
    assert 'yanami-pull.png' in find('expandChatLeftMascot').property('source').toString()
    assert find('expandChatLeftMascot').property('mirror')
    QTest.mouseMove(window, left_button.mapToScene(left_button.boundingRect().center()).toPoint())
    QTest.qWait(300)
    assert find('expandChatLeftMascot').property('loaded')
    assert window.grabWindow().save(str(shots / 'chat-width-hover-pull.png'))
    assert abs(conversation.x() - composer.x() - 10) < 1
    left_width = composer.width()
    click('expandChatRight')
    assert composer.width() > left_width + 60
    assert find('expandChatRight').property('text') == '\u25c0'
    assert abs(conversation.width() - composer.width() + 20) < 1
    shots = ROOT / 'artifacts/screenshots'
    shots.mkdir(parents=True, exist_ok=True)
    assert window.grabWindow().save(str(shots / 'chat-width-both.png'))
    click('expandChatLeft')
    assert abs(composer.x() - original_left) < 1
    assert composer.x() + composer.width() > original_right + 60
    assert window.grabWindow().save(str(shots / 'chat-width-right.png'))
    window.resize(1060, 760)
    QTest.qWait(250)
    assert not layout.property('expandable')
    assert not find('expandChatLeft').isVisible() and not find('expandChatRight').isVisible()
    assert composer.x() >= 40 and composer.x() + composer.width() <= find('chatPage').width() - 40
    assert layout.property('expandedRight'), 'Narrow mode should retain the user choice'
    window.resize(1700, 920)
    QTest.qWait(250)
    assert layout.property('expandable') and composer.width() > 850
    click('expandChatRight')
    assert abs(composer.width() - 850) < 1
    click('promptInput')
    QTest.keyClick(window, Qt.Key_A)
    assert find('promptInput').property('text').lower() == 'a'
    backend.setFontScale(2)
    QTest.qWait(250)
    click('expandChatRight')
    assert find('expandChatRight').width() == 152
    assert composer.x() + composer.width() < find('chatPage').width() - 90
    assert not warnings, '\n'.join(warnings)
    print('CHAT_WIDTH_UI_OK: four combinations, reversed arrows, both bounds, narrow fallback, restored choice, input and 200% controls')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
