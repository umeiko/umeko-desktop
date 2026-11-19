"""Qt event checks shared by the real composer and Widget smoke tests."""

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QSignalSpy, QTest


def check_newline_and_ime(window, field):
    field.forceActiveFocus()
    submitted = QSignalSpy(field.submitted)
    for key in (Qt.Key_Return, Qt.Key_Enter):
        for modifier in (Qt.ControlModifier, Qt.AltModifier, Qt.ShiftModifier):
            for selection in (False, True):
                field.setProperty("text", "甲乙丙丁")
                field.setProperty("cursorPosition", 2)
                if selection:
                    QTest.keyClick(window, Qt.Key_Left, Qt.ShiftModifier)
                    assert field.property("selectedText") == "乙"
                QTest.keyClick(window, key, modifier)
                expected = "甲\n丙丁" if selection else "甲乙\n丙丁"
                assert field.property("text") == expected, (field.objectName(), key, modifier, selection)
                assert field.property("cursorPosition") == (2 if selection else 3)
                assert submitted.count() == 0

    field.setProperty("text", "")
    QCoreApplication.sendEvent(window, QInputMethodEvent("中文预编辑", []))
    assert field.property("inputMethodComposing")
    QTest.keyClick(window, Qt.Key_Return)
    assert submitted.count() == 0, field.objectName()
    # A synthetic key reaches the editor after the platform input method.
    # Qt may apply its ordinary paragraph separator before the explicit commit.
    assert field.property("inputMethodComposing")
    before_commit = field.property("text")
    cursor = field.property("cursorPosition")
    commit = QInputMethodEvent()
    commit.setCommitString("中文")
    QCoreApplication.sendEvent(window, commit)
    assert not field.property("inputMethodComposing")
    assert field.property("text") == before_commit[:cursor] + "中文" + before_commit[cursor:]
    field.setProperty("text", "")
