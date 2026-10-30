import QtQuick
import QtQuick.Controls

Item {
    id: root
    property var controller: backend
    property string objectPrefix: ""
    property string primaryActionText: I18n.t("引导")
    property string primaryActionGlyph: "steer"
    property bool editEnabled: true
    property bool showSourceNames: false
    signal inspected(var message)
    property real heightLimit: Theme.control(170)
    height: implicitHeight
    implicitHeight: controller.queuedMessages.length ? Math.min(heightLimit, controller.queuedMessages.length * Theme.control(32) + 10) : 0
    visible: height > 0
    Rectangle { x: 14; width: parent.width - 28; height: parent.height + 18; radius: 15; color: Theme.surface; border.color: Theme.line }
    Flickable {
        x: 23; y: 5; width: parent.width - 46; height: parent.height - 5
        contentHeight: rows.implicitHeight; clip: true; acceptedButtons: Qt.NoButton
        boundsBehavior: Flickable.StopAtBounds
        Column {
            id: rows; width: parent.width
            Repeater {
                model: root.controller.queuedMessages
                Rectangle {
                    id: row
                    required property var modelData
                    required property int index
                    width: parent.width; height: Theme.control(32); radius: 5
                    color: editArea.containsMouse ? Theme.accentBg : "transparent"
                    Glyph { x: 2; width: Theme.icon(13); height: Theme.icon(13); name: "queue"; anchors.verticalCenter: parent.verticalCenter; opacity: 0.65 }
                    Text { x: 12 + Theme.icon(13); width: Math.max(20, parent.width - Theme.control(150)); anchors.verticalCenter: parent.verticalCenter; text: [(root.showSourceNames && row.modelData.sourceTitle ? row.modelData.sourceTitle + "：" : "") + row.modelData.text.replace(/\n/g, " "), ...(row.modelData.attachments || []).map(item => item.name)].filter(part => part.length).join(" · "); textFormat: Text.PlainText; elide: Text.ElideRight; font.pixelSize: Theme.font(13); color: Theme.ink }
                    MouseArea { id: editArea; objectName: root.objectPrefix + "editQueued_" + row.index; x: 0; width: parent.width - Theme.control(122); height: parent.height; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { if(root.editEnabled) root.controller.editQueued(row.modelData.id); else root.inspected(row.modelData) } }
                    Row {
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 5
                        Item {
                            width: Theme.control(62); height: Theme.control(28)
                            Row { anchors.centerIn: parent; spacing: 4; Glyph { name: root.primaryActionGlyph; width: Theme.icon(13); height: Theme.icon(13); anchors.verticalCenter: parent.verticalCenter } Text { text: root.primaryActionText; font.pixelSize: Theme.font(12); color: Theme.muted } }
                            MouseArea { objectName: root.objectPrefix + "steerQueued_" + row.index; anchors.fill: parent; cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor; onClicked: root.controller.steerQueued(row.modelData.id) }
                        }
                        ActionButton { objectName: root.objectPrefix + "removeQueued_" + row.index; glyph: "trash"; width: Theme.control(24); height: Theme.control(28); quiet: true; hint: I18n.t("删除排队消息"); onClicked: root.controller.removeQueued(row.modelData.id) }
                        Item {
                            width: Theme.control(24); height: Theme.control(28)
                            Glyph { anchors.centerIn: parent; name: "more"; width: Theme.icon(15); height: Theme.icon(15) }
                            MouseArea { objectName: root.objectPrefix + "queuedMenu_" + row.index; anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: { const point = mapToItem(row, 0, height); menu.popup(point.x, point.y) } }
                        }
                    }
                    FloatingMenu {
                        id: menu
                        ContextAction { visible:root.editEnabled; text: I18n.t("编辑"); onTriggered: root.controller.editQueued(row.modelData.id) }
                        ContextAction { visible:!root.editEnabled; text:I18n.t("查看"); onTriggered:root.inspected(row.modelData) }
                        ContextAction { text: I18n.t("复制"); onTriggered: root.controller.copy(row.modelData.text) }
                        ContextAction { text: I18n.t("删除"); onTriggered: root.controller.removeQueued(row.modelData.id) }
                    }
                }
            }
        }
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; width: 4 }
    }
}
