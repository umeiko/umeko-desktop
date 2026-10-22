import QtQuick
import QtQuick.Controls

Item {
    id: root
    height: backend.queuedMessages.length ? Math.min(Theme.control(170), backend.queuedMessages.length * Theme.control(32) + 10) : 0
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
                    width: parent.width; height: Theme.control(32); radius: 5
                    color: editArea.containsMouse ? Theme.accentBg : "transparent"
                    Glyph { x: 2; width: Theme.icon(13); height: Theme.icon(13); name: "queue"; anchors.verticalCenter: parent.verticalCenter; opacity: 0.65 }
                    Text { x: 12 + Theme.icon(13); width: Math.max(20, parent.width - Theme.control(150)); anchors.verticalCenter: parent.verticalCenter; text: [row.modelData.text.replace(/\n/g, " "), ...(row.modelData.attachments || []).map(item => item.name)].filter(part => part.length).join(" · "); textFormat: Text.PlainText; elide: Text.ElideRight; font.pixelSize: Theme.font(13); color: Theme.ink }
                    MouseArea { id: editArea; objectName: "editQueued_" + row.index; x: 0; width: parent.width - Theme.control(122); height: parent.height; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.editQueued(row.modelData.id) }
                    Row {
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 5
                        Item {
                            width: Theme.control(62); height: Theme.control(28)
                            Row { anchors.centerIn: parent; spacing: 4; Glyph { name: "steer"; width: Theme.icon(13); height: Theme.icon(13); anchors.verticalCenter: parent.verticalCenter } Text { text: I18n.t("引导"); font.pixelSize: Theme.font(12); color: Theme.muted } }
                            MouseArea { objectName: "steerQueued_" + row.index; anchors.fill: parent; cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor; onClicked: backend.steerQueued(row.modelData.id) }
                        }
                        ActionButton { objectName: "removeQueued_" + row.index; glyph: "trash"; width: Theme.control(24); height: Theme.control(28); quiet: true; hint: I18n.t("删除排队消息"); onClicked: backend.removeQueued(row.modelData.id) }
                        Item {
                            width: Theme.control(24); height: Theme.control(28)
                            Glyph { anchors.centerIn: parent; name: "more"; width: Theme.icon(15); height: Theme.icon(15) }
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
