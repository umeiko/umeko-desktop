import QtQuick
import QtQuick.Controls

Item {
    id: root
    height: backend.queuedMessages.length ? Math.min(170, backend.queuedMessages.length * 32 + 10) : 0
    visible: height > 0
    Rectangle { x: 14; width: parent.width - 28; height: parent.height + 18; radius: 15; color: Theme.surface; border.color: Theme.line }
    Flickable {
        x: 23; y: 5; width: parent.width - 46; height: parent.height - 5
        contentHeight: rows.implicitHeight; clip: true; acceptedButtons: Qt.NoButton
        boundsBehavior: Flickable.StopAtBounds
        Column {
            id: rows; width: parent.width
            Repeater {
                model: backend.queuedMessages
                Rectangle {
                    id: row
                    required property var modelData
                    required property int index
                    width: parent.width; height: 32; radius: 5
                    color: editArea.containsMouse ? Theme.accentBg : "transparent"
                    Glyph { x: 2; width: 13; height: 13; name: "queue"; anchors.verticalCenter: parent.verticalCenter; opacity: 0.65 }
                    Text { x: 25; width: Math.max(20, parent.width - 150); anchors.verticalCenter: parent.verticalCenter; text: [row.modelData.text.replace(/\n/g, " "), ...(row.modelData.attachments || []).map(item => item.name)].filter(part => part.length).join(" · "); textFormat: Text.PlainText; elide: Text.ElideRight; font.pixelSize: Theme.font(13); color: Theme.ink }
                    MouseArea { id: editArea; objectName: "editQueued_" + row.index; x: 0; width: parent.width - 122; height: parent.height; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.editQueued(row.modelData.id) }
                    Row {
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 5
                        Item {
                            width: 62; height: 28
                            Row { anchors.centerIn: parent; spacing: 4; Glyph { name: "steer"; width: 13; height: 13; anchors.verticalCenter: parent.verticalCenter } Text { text: I18n.t("引导"); font.pixelSize: Theme.font(12); color: Theme.muted } }
                            MouseArea { objectName: "steerQueued_" + row.index; anchors.fill: parent; cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor; onClicked: backend.steerQueued(row.modelData.id) }
                        }
                        ActionButton { objectName: "removeQueued_" + row.index; glyph: "trash"; width: 24; height: 28; quiet: true; hint: I18n.t("删除排队消息"); onClicked: backend.removeQueued(row.modelData.id) }
                        Item {
                            width: 24; height: 28
                            Glyph { anchors.centerIn: parent; name: "more"; width: 15; height: 15 }
                            MouseArea { objectName: "queuedMenu_" + row.index; anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: { const point = mapToItem(row, 0, height); menu.popup(point.x, point.y) } }
                        }
                    }
                    FloatingMenu {
                        id: menu
                        ContextAction { text: I18n.t("编辑"); onTriggered: backend.editQueued(row.modelData.id) }
                        ContextAction { text: I18n.t("复制"); onTriggered: backend.copy(row.modelData.text) }
                        ContextAction { text: I18n.t("删除"); onTriggered: backend.removeQueued(row.modelData.id) }
                    }
                }
            }
        }
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; width: 4 }
    }
}
