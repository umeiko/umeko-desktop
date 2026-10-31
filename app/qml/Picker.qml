import QtQuick
import QtQuick.Controls
ComboBox {
    id: control
    implicitHeight: Math.max(40, font.pixelSize + 20)
    font.pixelSize: Theme.font(12, visible)
    leftPadding: 12; rightPadding: Theme.control(30)
    background: Rectangle { color: Theme.surface; border.color: control.activeFocus ? Theme.accent : Theme.line; radius: 8 }
    contentItem: Text { text: control.displayText; color: Theme.ink; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; font: control.font }
    indicator: Glyph { name: "chevron-down"; width: Theme.icon(14); height: Theme.icon(14); x: control.width - width - 9; y: (control.height - height) / 2 }
    popup: Popup {
        y: control.height + 4; width: control.width; padding: 5
        implicitHeight: Math.min(280, contentItem.implicitHeight + 10)
        background: Rectangle { color: Theme.surface; border.color: Theme.line; radius: 8 }
        contentItem: ListView { clip: true; implicitHeight: contentHeight; model: control.popup.visible ? control.delegateModel : null; currentIndex: control.highlightedIndex }
    }
    delegate: ItemDelegate { width: control.width - 10; height: Math.max(36, font.pixelSize + 14); text: modelData; font.pixelSize: Theme.font(12, visible)
        contentItem: Text { text: modelData; color: Theme.ink; font: parent.font; verticalAlignment: Text.AlignVCenter }
        background: Rectangle { radius: 5; color: parent.highlighted ? Theme.accentBg : "transparent" }
        highlighted: control.highlightedIndex === index }
}
