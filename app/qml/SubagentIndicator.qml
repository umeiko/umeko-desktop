import QtQuick
import QtQuick.Controls
import QtQuick.Window

ActionButton {
    id: root
    objectName: "subagentIndicator"
    visible: backend.subagents.activeCount > 0
    width: Theme.control(62); height: Theme.control(34); quiet: true
    hint: I18n.t("正在工作的子代理")
    onClicked: menu.visible ? menu.close() : menu.open()
    onVisibleChanged: if (!visible) menu.close()
    contentItem: Item {
        SubagentAvatar { x: 3; anchors.verticalCenter: parent.verticalCenter; width: 29; height: 29; slot: backend.subagents.activeAgents.length ? backend.subagents.activeAgents[0].avatarSlot || 0 : 0 }
        Rectangle { x: 26; y: 2; width: 6; height: 6; radius: 3; color: Theme.accent }
        Text { x: 38; anchors.verticalCenter: parent.verticalCenter; text: backend.subagents.activeCount; color: Theme.ink; font.pixelSize: Theme.font(11) }
        Glyph { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; name: "chevron-down"; width: 10; height: 10 }
    }
    PidPopup {
        id: menu; objectName: "subagentActiveMenu"
        x: root.width-width; y: root.height+8; width: Math.min(340,root.Window.window.width-40)
        padding: 9; modal: false; transformOrigin: Popup.TopRight
        contentItem: Column {
            spacing: 4
            Repeater {
                model: backend.subagents.activeAgents
                ActionButton {
                    id: entry
                    required property var modelData
                    objectName: "activeSubagent_" + modelData.id
                    width: menu.availableWidth; height: Theme.control(67); quiet: true
                    onClicked: { menu.close(); backend.subagents.open(modelData.id) }
                    contentItem: Item {
                        SubagentAvatar { x: 7; anchors.verticalCenter: parent.verticalCenter; width: 38; height: 38; slot: entry.modelData.avatarSlot || 0 }
                        Column { x: 56; width: Math.max(0,parent.width-x-18); anchors.verticalCenter: parent.verticalCenter; spacing: 6
                            Text { width: parent.width; text: entry.modelData.name + " · " + I18n.t(entry.modelData.status === "queued" ? "排队中" : "运行中"); color: Theme.ink; font.pixelSize: Theme.font(12); elide: Text.ElideRight }
                            Text { width: parent.width; text: entry.modelData.activity || entry.modelData.task || entry.modelData.type; textFormat: Text.PlainText; color: Theme.muted; font.pixelSize: Theme.font(10); elide: Text.ElideRight }
                        }
                    }
                }
            }
        }
    }
}
