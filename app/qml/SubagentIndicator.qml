import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ActionButton {
    id: root
    objectName: "subagentIndicator"
    readonly property bool popupVisible: menu.visible && (menu.desiredOpen || menu.animating)
    visible: backend.subagents.activeCount > 0
    width: Math.max(Theme.control(70), count.implicitWidth + Theme.icon(45) + Theme.control(16))
    height: Theme.control(34); quiet: true
    hint: I18n.t("正在工作的子代理")
    onClicked: menu.toggle()
    onVisibleChanged: if (!visible) menu.close()
    contentItem: RowLayout {
        spacing: 5
        SubagentAvatar { Layout.preferredWidth: Theme.icon(27); Layout.preferredHeight: Theme.icon(27); slot: backend.subagents.activeAgents.length ? backend.subagents.activeAgents[0].avatarSlot || 0 : 0 }
        Text { font.family: Theme.fontFamily; id: count; text: backend.subagents.activeCount; color: Theme.ink; font.pixelSize: Theme.font(11) }
        Glyph { name: "chevron-down"; Layout.preferredWidth: Theme.icon(10); Layout.preferredHeight: Theme.icon(10) }
    }
    AnchoredPidPopup {
        id: menu; objectName: "subagentActiveMenu"
        openBelow: true; alignRight: true
        fullWidth: Theme.control(340)
        fullHeight: Math.min(Theme.control(520), backend.subagents.activeCount*(Theme.control(74)+4)-4+padding*2)
        padding: 9
        contentItem: Item {
            clip: true
            ListView {
                id: list; objectName: "activeSubagentList"
                width: menu.expandedWidth-menu.padding*2; height: menu.expandedHeight-menu.padding*2
                opacity: menu.contentOpacity; clip: true; spacing: 4
                model: backend.subagents.activeAgents; reuseItems: true; cacheBuffer: 100
                ScrollBar.vertical: ScrollBar {}
                delegate: SubagentTile {
                    required property var modelData
                    objectName: "activeSubagent_" + modelData.id
                    width: list.width; height: Theme.control(74); agent: modelData; showStatus: true
                    onActivated: { menu.close(); backend.subagents.open(modelData.id) }
                }
            }
        }
    }
}
