import QtQuick
import QtQuick.Controls

TextArea {
    id: input
    signal submitted()

    function handleReturn(event) {
        if (inputMethodComposing) {
            event.accepted = false
            return
        }
        if (event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier)) {
            const position = selectionStart
            remove(position, selectionEnd)
            insert(position, "\n")
            cursorPosition = position + 1
        } else {
            submitted()
        }
        event.accepted = true
    }

    Keys.onReturnPressed: event => handleReturn(event)
    Keys.onEnterPressed: event => handleReturn(event)
}
