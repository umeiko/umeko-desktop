"""Exercise both mode destinations and the experimental badge at the real sidebar minimum."""
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from main import create_application


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="umeko-cowork-mode-") as temporary:
        base = Path(temporary).resolve()
        os.environ.update(UMEKO_DATA_DIR=str(base / "profile"), PI_CODING_AGENT_DIR=str(base / "agent"))
        app, engine, backend = create_application()
        window = engine.rootObjects()[0]
        window.resize(1180, 760)
        warnings = []
        engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))

        def wait(test, detail):
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                QTest.qWait(25)
                if test():
                    return
            raise AssertionError((detail, warnings[-10:]))

        def item(name):
            stack = [window.contentItem()]
            while stack:
                row = stack.pop()
                if row.objectName() == name:
                    return row
                stack.extend(row.childItems())
            raise AssertionError(f"Missing UI item: {name}")

        button = item("openCoworkButton")
        badge = item("coworkSidebarExperimentalBadge")
        label = item("coworkSidebarModeLabel")
        sidebar = item("sidebar")
        settings = item("settingsButton")

        def click():
            assert button.isVisible() and button.isEnabled()
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier,
                             button.mapToScene(button.boundingRect().center()).toPoint())

        def capture(name):
            QTest.mouseMove(window, QPoint(360, 120))
            QTest.qWait(200)
            assert window.grabWindow().save(str(output / name)), name

        def width(pixels):
            assert backend.saveSidebarLayout(pixels, False)
            wait(lambda: abs(sidebar.width() - pixels) <= 0.75 and button.isEnabled(), pixels)

        def incoming(text, mark, wrapped):
            wait(lambda: label.property("text") == text and badge.isVisible(), text)
            assert button.property("text") == text and button.property("hint").endswith(mark)
            assert badge.property("text") == mark
            assert not label.property("truncated")
            outer = button.mapRectToScene(button.boundingRect())
            words = label.mapRectToScene(label.boundingRect())
            experiment = badge.mapRectToScene(badge.boundingRect())
            assert outer.contains(words) and outer.contains(experiment), (outer, words, experiment)
            assert not words.intersects(experiment), (words, experiment)
            assert button.mapRectToScene(button.boundingRect()).bottom() < settings.mapRectToScene(settings.boundingRect()).top()
            if wrapped:
                assert experiment.top() >= words.bottom(), (words, experiment)
            elif wrapped is False:
                assert experiment.left() > words.right() and experiment.top() < words.bottom(), (words, experiment)
            print(f"entry {text}, sidebar={sidebar.width():.2f}, label={words}, badge={experiment}", flush=True)

        try:
            backend.setLanguage("zh")
            wait(lambda: backend.language == "zh", "Chinese locale")
            assert not button.isVisible(), "Cowork disabled by default"
            assert backend.saveDesktopSettings('{"coworkEnabled":true}')
            encoding = backend._view
            width(300)
            incoming("协同办公（CoWork）", "实验版", wrapped=False)
            capture("238-zh-enter-cowork.png")
            click()
            wait(lambda: backend.cowork.active and label.property("text") == "编码（AICoding）", "enter")
            assert not badge.isVisible() and button.property("hint") == "编码（AICoding）"
            capture("238-zh-return-coding.png")
            click()
            wait(lambda: not backend.cowork.active and backend._view is encoding, "return same session")
            width(200)
            incoming("协同办公（CoWork）", "实验版", wrapped=True)
            assert label.property("lineCount") == 1, (label.width(), label.property("contentWidth"), label.parentItem().parentItem().width())
            capture("238-zh-narrow-experimental.png")
            click()
            wait(lambda: backend.cowork.active and label.property("text") == "编码（AICoding）", "narrow enter")
            assert not badge.isVisible()
            click()
            wait(lambda: not backend.cowork.active and backend._view is encoding, "narrow return")
            backend.setLanguage("en")
            incoming("CoWork", "Experimental", wrapped=None)
            assert label.property("lineCount") == 1
            click()
            wait(lambda: backend.cowork.active and label.property("text") == "AICoding", "English enter")
            assert not badge.isVisible()
            click()
            wait(lambda: not backend.cowork.active and backend._view is encoding, "English return")
            assert backend.saveDesktopSettings('{"coworkEnabled":false}')
            wait(lambda: not button.isVisible(), "disabled again")
            assert settings.isVisible()
            assert not [warning for warning in warnings if "Binding loop" in warning], warnings
            print("PASS: same Qt button, zh/en, default disabled, 300/200px, badge containment and session restore.")
        finally:
            backend.close()
            window.close()
            QTest.qWait(125)


if __name__ == "__main__":
    run(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build/cowork-mode-switch")
