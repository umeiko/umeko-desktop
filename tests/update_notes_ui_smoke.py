"""Progress updates must preserve the rendered release document and reading state."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
profile = tempfile.TemporaryDirectory(prefix="umeko-update-notes-")
os.environ["UMEKO_DATA_DIR"] = profile.name
os.environ["PI_CODING_AGENT_DIR"] = str(Path(profile.name) / "agent")
os.environ.setdefault("UMEKO_LANGUAGE", "zh")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import Q_ARG, QMetaObject
from PySide6.QtQuick import QQuickTextDocument
from PySide6.QtTest import QSignalSpy, QTest
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))


def find(name):
    pending = [window.contentItem()]
    while pending:
        item = pending.pop()
        if item.objectName() == name:
            return item
        pending.extend(item.childItems())
    raise AssertionError(name)


try:
    about = backend.appAbout
    window.setProperty("page", "settings")
    window.setProperty("settingsTab", 6)
    notes = "# Release overview\n\n**Stable selection** with [release details](https://example.invalid/release).\n\n"
    notes += "| Feature | Result |\n| --- | --- |\n| Download | Stable<br>progress |\n\n"
    notes += "```python\nprint('release notes')\n```\n\n"
    notes += "\n\n".join(f"## Change {i}\n\nReading paragraph {i}." for i in range(30))
    about._release = {"state": "available", "version": "v99.0.0", "notes": notes}
    about.changed.emit()
    QTest.qWait(200)
    editor = find("appReleaseNotes")
    text_document = editor.property("textDocument")
    document = text_document.textDocument()
    plain = document.toPlainText()
    assert "Stable selection" in plain and "print('release notes')" in plain
    flick = editor.parentItem()
    while flick is not None and flick.property("contentY") is None:
        flick = flick.parentItem()
    assert flick is not None and flick.property("contentHeight") > flick.height()
    start = plain.index("Stable selection")
    assert QMetaObject.invokeMethod(editor, "select", Q_ARG(int, start), Q_ARG(int, start + len("Stable selection")))
    flick.setProperty("contentY", 120)
    QTest.qWait(50)
    selected, y = editor.property("selectedText"), flick.property("contentY")
    assert selected == "Stable selection" and y > 0
    changed = QSignalSpy(document.contentsChanged)
    for i in range(60):
        about._progress({"state": "downloading", "progress": i / 100, "received": i * 1024,
                         "total": 100 * 1024, "speed": 2048, "eta": 50 - i / 2})
        QTest.qWait(5)
    for state in ("paused", "downloading", "verifying", "ready", "error"):
        about._progress({"state": state, "message": state})
        QTest.qWait(10)
    about._install_changed({"state": "preparing", "message": "Preparing", "busy": True})
    QTest.qWait(10)
    about._install_changed({"busy": False})
    QTest.qWait(50)
    print(f"RELEASE_DOCUMENT_REBUILDS:{changed.count()} selection={editor.property('selectedText')!r} scroll={flick.property('contentY')}", flush=True)
    assert changed.count() == 0, "Download progress rebuilt the Markdown document"
    assert editor.property("selectedText") == selected
    assert abs(flick.property("contentY") - y) < 0.5
    assert document.toPlainText() == plain
    assert find("appDownloadStatus").property("text") == "error"
    # New release content must still replace the document, and empty notes hide it.
    about._release = {**about._release, "notes": "# New release\n\nUpdated **overview**."}
    about.changed.emit()
    QTest.qWait(50)
    assert "New release" in document.toPlainText() and "Change 29" not in document.toPlainText()
    assert changed.count() > 0
    about._release = {**about._release, "notes": ""}
    about.changed.emit()
    QTest.qWait(30)
    assert not editor.isVisible()
    assert not warnings, "\n".join(warnings)
    print("UPDATE_NOTES_UI_OK: progress, pause/resume, verification, ready/error and installer preserve Markdown; new notes refresh")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
    profile.cleanup()
