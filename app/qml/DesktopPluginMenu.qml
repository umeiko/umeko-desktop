import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Item {
    id: root
    objectName: "desktopPluginLauncher"
    property var manager: backend.desktopPlugins
    readonly property var recent: manager.recentPlugin
    readonly property bool recentOpen: !!recent.id && manager.page.id === recent.id
    readonly property bool popupVisible: menu.visible
    signal manageRequested()
    implicitWidth: Theme.control(66)
    implicitHeight: Theme.control(30)
    function openRecent() {
        menu.close()
        if (recentOpen) manager.closePage()
        else if (recent.id) manager.openPage(recent.id)
        else manageRequested()
    }
    onVisibleChanged: if (!visible) menu.close()
    Connections { target: backend; function onViewChanged() { menu.close() } }
    Rectangle {
        anchors.fill: parent; radius: 7
        color: root.manager.page.id ? Theme.accentBg : Theme.surface
        border.color: menu.desiredOpen ? Theme.accent : Theme.line
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }
    Button {
        id: recentButton
        objectName: "desktopPluginRecentButton"
        x: 2; y: 2; width: parent.width - moreButton.width - 4; height: parent.height - 4
        hoverEnabled: true
        Accessible.name: I18n.t(root.recentOpen ? "收起插件" : "打开最近使用的插件") + (root.recent.name ? " · " + I18n.widgetText(root.recent, root.recent.name) : "")
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        background: Rectangle { radius: 5; color: recentButton.down ? Theme.accentBg : recentButton.hovered ? Theme.hover : "transparent" }
        contentItem: Item { WidgetIcon { plugin:root.recent; color: root.manager.page.id ? Theme.accent : Theme.muted; anchors.centerIn: parent; width: Theme.icon(17); height: Theme.icon(17) } }
        HoverTip { active: recentButton.hovered && !recentButton.down; text: root.recent.name ? I18n.t(root.recentOpen ? "收起插件" : "打开最近使用的插件") + " · " + I18n.widgetText(root.recent, root.recent.name) : I18n.t("插件管理") }
        onClicked: root.openRecent()
    }
    Rectangle { width: 1; height: parent.height - 12; x: moreButton.x - 1; anchors.verticalCenter: parent.verticalCenter; color: Theme.line }
    Button {
        id: moreButton
        objectName: "desktopPluginMenuButton"
        x: parent.width - width - 2; y: 2; width: Theme.control(22); height: parent.height - 4
        hoverEnabled: true
        Accessible.name: I18n.t("选择插件")
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        background: Rectangle { radius: 5; color: moreButton.down || menu.desiredOpen ? Theme.accentBg : moreButton.hovered ? Theme.hover : "transparent" }
        contentItem: Item { Glyph { name: menu.desiredOpen ? "chevron-up" : "chevron-down"; color: menu.desiredOpen ? Theme.accent : Theme.muted; anchors.centerIn: parent; width: Theme.icon(13); height: Theme.icon(13) } }
        HoverTip { active: moreButton.hovered && !menu.visible; text: I18n.t("选择插件") }
        onClicked: menu.toggle()
    }
    MouseArea { anchors.fill: parent; z: 3; acceptedButtons: Qt.RightButton; cursorShape: Qt.PointingHandCursor; onClicked: menu.toggle() }
    AnchoredPidPopup {
        id: menu
        objectName: "desktopPluginSessionMenu"
        parent: root; alignRight: true; padding: 6
        fullWidth: Theme.control(240)
        fullHeight: Math.min(Theme.control(330), Math.max(1, root.manager.sessionPlugins.length) * Theme.control(34) + Theme.control(48) + 12)
        contentItem: Item {
            clip: true; opacity: menu.contentOpacity
            ColumnLayout {
                anchors.fill: parent; spacing: 4
                ListView {
                    id: pluginList
                    objectName: "desktopPluginQuickList"
                    Layout.fillWidth: true; Layout.fillHeight: true
                    clip: true; boundsBehavior: Flickable.StopAtBounds
                    model: root.manager.sessionPlugins
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    delegate: ItemDelegate {
                        id: entry
                        required property var modelData
                        objectName: "openDesktopPlugin_" + modelData.id
                        width: pluginList.width; height: Theme.control(34); padding: 8
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        background: Rectangle { radius: 6; color: root.manager.page.id === entry.modelData.id ? Theme.accentBg : entry.hovered ? Theme.hover : "transparent" }
                        contentItem: RowLayout {
                            spacing: 9
                            WidgetIcon { plugin:entry.modelData; width: Theme.icon(16); height: Theme.icon(16); color: Theme.muted }
                            Text { text: I18n.widgetText(entry.modelData, entry.modelData.name); textFormat: Text.PlainText; font.pixelSize: Theme.font(12); color: Theme.ink; elide: Text.ElideRight; Layout.fillWidth: true }
                            Glyph { name: "check"; visible: root.manager.page.id === entry.modelData.id; width: Theme.icon(14); height: Theme.icon(14); color: Theme.accent }
                        }
                        onClicked: { const id = modelData.id; menu.close(); root.manager.openPage(id) }
                    }
                    Text { anchors.centerIn: parent; visible: pluginList.count === 0; text: I18n.t("暂无已启用的插件"); color: Theme.muted; font.pixelSize: Theme.font(11) }
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
                ItemDelegate {
                    id: settingsEntry
                    objectName: "desktopPluginSettingsButton"
                    Layout.fillWidth: true; implicitHeight: Theme.control(34); padding: 8
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                    background: Rectangle { radius: 6; color: settingsEntry.hovered ? Theme.hover : "transparent" }
                    contentItem: RowLayout {
                        spacing: 9
                        Glyph { name: "settings"; width: Theme.icon(16); height: Theme.icon(16) }
                        Text { text: I18n.t("设置"); font.pixelSize: Theme.font(12); color: Theme.ink; Layout.fillWidth: true }
                    }
                    onClicked: { menu.close(); root.manageRequested() }
                }
            }
        }
    }
}
