import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Column {
    id: root
    objectName: "umekoDesktopSettings"
    spacing: 16
    SectionCard {
        width: parent.width
        RowLayout {
            width: parent.width; spacing: 8
            Text { text: I18n.t("聊天区域左右展开提示"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); wrapMode: Text.Wrap; Layout.fillWidth: true }
            HelpButton { help: I18n.t("鼠标移到聊天区域两侧时显示展开或收起提示。关闭后保留当前布局。"); Layout.alignment: Qt.AlignVCenter }
            Toggle {
                objectName: "desktopChatWidthHints"
                checked: backend.config.desktop.chatWidthHints
                Accessible.name: I18n.t("聊天区域左右展开提示")
                onClicked: { const value = checked; checked = Qt.binding(function() { return backend.config.desktop.chatWidthHints }); backend.saveDesktopSettings(JSON.stringify({chatWidthHints:value})) }
            }
        }
    }
    SectionCard {
        width: parent.width
        ColumnLayout {
            width: parent.width; spacing: 20
            Text { text: I18n.t("提交与预览"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Text { text: I18n.t("提交后自动打开预览"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); wrapMode: Text.Wrap; Layout.fillWidth: true }
                HelpButton { help: I18n.t("模型提交网页或文档后自动打开预览。关闭后，内容仍会显示在聊天中，点击时再打开。"); Layout.alignment: Qt.AlignVCenter }
                Toggle {
                    objectName: "desktopAutoOpenSubmissions"
                    checked: backend.config.desktop.autoOpenSubmissions
                    Accessible.name: I18n.t("提交后自动打开预览")
                    onClicked: { const value = checked; checked = Qt.binding(function() { return backend.config.desktop.autoOpenSubmissions }); backend.saveDesktopSettings(JSON.stringify({autoOpenSubmissions:value})) }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true; spacing: 10
                RowLayout {
                    Layout.fillWidth: true; spacing: 8
                    Text { text: I18n.t("网页打开方式"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); Layout.fillWidth: true }
                    HelpButton { help: I18n.t("网页链接和本地 HTML 均遵循此设置。系统默认浏览器可绕过内置 WebView 的兼容性问题。"); Layout.alignment: Qt.AlignVCenter }
                }
                ComboBox {
                    id: browserChoice
                    objectName: "desktopWebDisplay"
                    Layout.fillWidth: true
                    model: [I18n.t("内置网页预览"), I18n.t("系统默认浏览器")]
                    function syncSelection() { currentIndex = backend.config.desktop.webDisplay === "external" ? 1 : 0 }
                    onModelChanged: Qt.callLater(syncSelection)
                    Component.onCompleted: syncSelection()
                    Connections { target: backend; function onChanged() { browserChoice.syncSelection() } }
                    font.family: Theme.fontFamily; font.pixelSize: Theme.font(13)
                    palette.text: Theme.ink; palette.buttonText: Theme.ink; palette.base: Theme.surface
                    palette.window: Theme.surface; palette.highlight: Theme.accentBg; palette.highlightedText: Theme.ink
                    implicitHeight: Theme.control(38)
                    Accessible.name: I18n.t("网页打开方式")
                    onActivated: index => { backend.saveDesktopSettings(JSON.stringify({webDisplay:index === 1 ? "external" : "embedded"})); syncSelection() }
                    background: Rectangle { radius: 8; color: Theme.surface; border.color: browserChoice.activeFocus ? Theme.accent : Theme.line }
                    contentItem: Text { text: browserChoice.displayText; font: browserChoice.font; color: Theme.ink; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; leftPadding: 12; rightPadding: 30 }
                    indicator: Glyph { name: "chevron-down"; width: Theme.icon(14); height: width; x: parent.width-width-12; y: (parent.height-height)/2; color: Theme.muted }
                }
            }
        }
    }
}
