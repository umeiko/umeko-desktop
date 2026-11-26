"""Real Qt interaction against an isolated profile and installed Quick OCR engine."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def check(args):
    profile = args.profile.resolve()
    os.environ.update(UMEKO_DATA_DIR=str(profile), PI_CODING_AGENT_DIR=str(profile.parent / "agent"),
                      UMEKO_LANGUAGE="zh", QT_QUICK_BACKEND="software")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QObject, QUrl, Qt
    from PySide6.QtQml import QQmlEngine, QQmlExpression
    from PySide6.QtTest import QTest
    from main import create_application
    app, engine, backend = create_application()
    window = engine.rootObjects()[0]
    window.resize(1320, 850)
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    def find(name):
        queue = [window.contentItem()]
        while queue:
            item = queue.pop(0)
            if item.objectName() == name and item.isVisible():
                return item
            queue.extend(item.childItems())
        return None
    def wait(condition, message):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            QTest.qWait(30)
            if result := condition():
                return result
        raise AssertionError((message, backend.quickOcr.state, backend.quickOcr.error, warnings[-20:]))
    def click(name):
        item = wait(lambda: find(name), name)
        assert item.isEnabled(), name
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())
        QTest.qWait(160)
    def choose(path):
        dialog = window.findChild(QObject, "quickOcrDialog")
        assert dialog
        # Trigger the exact QML FileDialog accepted handler; desktop-native chooser
        # cannot be automated portably by offscreen Qt.
        source = "chooseFile(" + json.dumps(QUrl.fromLocalFile(str(path.resolve())).toString()) + ")"
        exp = QQmlExpression(QQmlEngine.contextForObject(dialog), dialog, source)
        value = exp.evaluate()
        assert not exp.hasError(), exp.error().toString()
        return value
    def save(name):
        if args.screenshots:
            args.screenshots.mkdir(parents=True, exist_ok=True)
            assert window.grabWindow().save(str(args.screenshots / name))
    before = hashlib.sha256(args.image.read_bytes()).hexdigest()
    try:
        assert backend.saveDesktopSettings('{"coworkEnabled":true}')
        assert not find("openQuickOcr")
        click("openCoworkButton")
        if backend.cowork.role.get("typeId") != "ocr":
            if backend.cowork.activeRole:
                click("coworkHeaderOverview")
            click("coworkCard_ocr")
            click("coworkInstanceConfirm")
        assert backend.cowork.role["typeId"] == "ocr"
        save("01-ocr-entry.png")
        with patch.object(backend, "_send", side_effect=AssertionError("OCR must not send chat")), \
             patch.object(backend, "_command_pi", side_effect=AssertionError("OCR must not use Pi or a provider")):
            click("openQuickOcr")
            wait(lambda: find("quickOcrChoose"), "Open OCR dialog")
            if args.missing:
                assert backend.quickOcr.state == "missing"
                assert not find("quickOcrRun").isEnabled()
                assert "未安装" in find("quickOcrStatus").property("text")
                save("02-ocr-missing.png")
            else:
                wait(lambda: backend.quickOcr.ready, "Engine ready")
                choose(args.image)
                assert find("quickOcrFileName").property("text") == args.image.name
                start = time.perf_counter()
                click("quickOcrRun")
                wait(lambda: backend.quickOcr.state == "done", "Actual OCR result")
                took = time.perf_counter() - start
                result = backend.quickOcr.result
                for expected in ("ZX-8041-A", "1234.56", "任务进度"):
                    assert expected in result, result
                click("quickOcrCopy")
                assert app.clipboard().text() == result
                assert hashlib.sha256(args.image.read_bytes()).hexdigest() == before
                save("03-ocr-result.png")
                # Truncated/invalid input is rejected by the worker, not handed to chat.
                bad = profile.parent / "invalid.png"
                bad.write_bytes(b"not an image")
                choose(bad)
                click("quickOcrRun")
                wait(lambda: backend.quickOcr.state == "error", "Decode error")
                assert backend.quickOcr.error == "decode"
                assert not backend.quickOcr.result
                choose(args.image)
                backend.quickOcr.recognize()
                assert backend.quickOcr.state == "running"
                backend.quickOcr.cancel()
                assert backend.quickOcr.state == "idle" and not backend.quickOcr.result
                print(f"Actual local OCR with QML entrypoint: {took:.2f}s; clipboard, invalid image, cancel, original unchanged, no chat/Pi")
            click("quickOcrClose")
            assert not backend.quickOcr.result
        assert not [w for w in warnings if "QuickOcrDialog.qml" in w], warnings
    finally:
        window.hide()
        app.quit()
        backend.close()

if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--profile", type=Path, required=True)
    cli.add_argument("--image", type=Path, required=True)
    cli.add_argument("--screenshots", type=Path)
    cli.add_argument("--missing", action="store_true")
    check(cli.parse_args())
