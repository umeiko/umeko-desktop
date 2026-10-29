import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: root
    objectName: "extensionDetailsPopup"
    parent: Overlay.overlay
    property var manager
    property string extensionId: ""
    readonly property var extension: manager.extensions.find(row => row.id === extensionId) || ({})
    readonly property var info: extension.info || ({})
    readonly property var tools: (backend.agentResources.allTools || []).filter(tool => tool.source === extension.path)
    readonly property var update: manager.extensionUpdate.id === extensionId ? manager.extensionUpdate : ({})
    readonly property bool desktop: info.updateKind === "desktop"
    readonly property bool checking: desktop ? backend.appAbout.busy : update.status === "checking"
    width: Math.min(760,parent.width-40); height: Math.min(750,parent.height-40)
    x: (parent.width-width)/2; y: (parent.height-height)/2
    padding: 24; modal: true; focus: true
    background: Rectangle { radius: 13; color: Theme.surface; border.color: Theme.line }
    Overlay.modal: Rectangle { color: "#50000000" }
    ColumnLayout {
        anchors.fill: parent; spacing: 14
        RowLayout {
            Layout.fillWidth: true
            Text { objectName: "extensionDetailsName"; Layout.fillWidth: true; text: root.extension.name || ""; textFormat: Text.PlainText; elide: Text.ElideMiddle; color: Theme.ink; font.pixelSize: Theme.font(19); font.weight: Font.DemiBold }
            ActionButton { objectName: "closeExtensionDetailsButton"; quiet: true; glyph: "x"; width: Theme.control(30); height: width; hint: I18n.t("关闭"); onClicked: root.close() }
        }
        Text {
            Layout.fillWidth: true; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(11)
            text: I18n.t(({community:"社区扩展",pi:"Pi 内置扩展",desktop:"Umeko 内置扩展",local:"本地扩展"})[root.info.origin] || "扩展")
                + (root.info.bundled ? " · " + I18n.t("随软件捆绑") : "")
                + " · " + (root.extension.scope === "project" ? I18n.t("项目") : I18n.t("全局"))
                + (root.info.version ? " · v" + root.info.version : "")
                + (root.info.package ? "\n" + root.info.package : "")
        }
        Text { Layout.fillWidth: true; visible: !!root.info.description; text: root.info.description || ""; textFormat: Text.PlainText; color: Theme.ink; wrapMode: Text.Wrap; maximumLineCount: 4; elide: Text.ElideRight; font.pixelSize: Theme.font(12) }
        TextEdit { Layout.fillWidth: true; text: root.extension.path || ""; textFormat: TextEdit.PlainText; color: Theme.muted; readOnly: true; selectByMouse: true; wrapMode: TextEdit.WrapAnywhere; font.pixelSize: Theme.font(10) }
        Flow {
            Layout.fillWidth: true; spacing: 8
            ActionButton { objectName: "extensionHomepageButton"; visible: !!root.info.homepage; text: I18n.t("扩展主页"); glyph: "external-link"; quiet: true; hint: root.info.homepage || ""; onClicked: Qt.openUrlExternally(root.info.homepage) }
            ActionButton { objectName: "extensionRepositoryButton"; visible: !!root.info.repository; text: (root.info.repository || "").indexOf("github.com/") >= 0 ? "GitHub" : I18n.t("源代码"); glyph: "external-link"; quiet: true; hint: root.info.repository || ""; onClicked: Qt.openUrlExternally(root.info.repository) }
            ActionButton { objectName: "extensionNpmButton"; visible: !!root.info.npmUrl; text: "npm"; glyph: "external-link"; quiet: true; hint: root.info.npmUrl || ""; onClicked: Qt.openUrlExternally(root.info.npmUrl) }
        }
        RowLayout {
            Layout.fillWidth: true
            ActionButton {
                objectName: "checkExtensionUpdateButton"; text: root.checking ? I18n.t("检查中…") : root.desktop ? I18n.t("检查软件更新") : I18n.t("检查扩展更新"); glyph: "refresh"
                enabled: !root.manager.busy && !backend.appAbout.busy && !backend.kernelBusy && ["npm","git","desktop"].includes(root.info.updateKind)
                onClicked: root.desktop ? backend.appAbout.checkUpdates() : root.manager.checkExtensionUpdate(root.extensionId)
            }
            Text {
                objectName: "extensionUpdateResult"; Layout.fillWidth: true; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: root.update.status === "error" ? Theme.danger : Theme.muted; font.pixelSize: Theme.font(11)
                text: root.desktop ? I18n.t(backend.appAbout.release.message || "此扩展随 Umeko 更新") : I18n.t(root.update.message || (root.info.updateKind === "none" ? "本地扩展没有可检查的更新源" : "仅在点击时检查更新"))
                    + (root.update.latest ? " · " + (root.update.current || "?") + " → " + root.update.latest : "")
            }
        }
        Text { Layout.fillWidth: true; visible: !!root.info.bundled && !root.desktop; text: I18n.t(root.info.origin === "community" ? "此社区扩展由 Umeko 集成，版本升级随 Umeko 更新提供。" : "此扩展随 Pi 内核更新。可在 Pi 配置中更新内核。"); wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(11) }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
        RowLayout {
            Layout.fillWidth: true
            Text { text: I18n.t("已加载的工具") + " · " + root.tools.length; color: Theme.ink; font.pixelSize: Theme.font(13); font.weight: Font.Medium }
            Item { Layout.fillWidth: true }
            ActionButton { objectName: "refreshExtensionToolsButton"; text: I18n.t("刷新"); quiet: true; glyph: "refresh"; enabled: !backend.busy && !backend.kernelBusy; onClicked: backend.loadCapabilities() }
        }
        ListView {
            id: toolList; objectName: "extensionDetailsToolList"
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 10; model: root.tools; reuseItems: true
            ScrollBar.vertical: ScrollBar { }
            delegate: Rectangle {
                required property var modelData
                width: toolList.width; height: content.implicitHeight+24; radius: 8; color: Theme.bg
                Column {
                    id: content; x: 12; y: 12; width: parent.width-24; spacing: 7
                    Text { width: parent.width; text: modelData.name; textFormat: Text.PlainText; color: Theme.ink; font.pixelSize: Theme.font(12); font.family: "monospace"; wrapMode: Text.WrapAnywhere }
                    TextEdit { width: parent.width; text: (modelData.description || I18n.t("暂无说明")).slice(0,4096); textFormat: TextEdit.PlainText; color: Theme.muted; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; font.pixelSize: Theme.font(11) }
                }
            }
            Text { anchors.centerIn: parent; width: parent.width-30; visible: !root.tools.length; text: backend.busy ? I18n.t("正在读取 Pi 能力…") : I18n.t("此扩展尚无已加载的工具。启用扩展后刷新，或查看扩展主页。扩展也可能只提供命令或界面能力。"); color: Theme.muted; font.pixelSize: Theme.font(12); wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter }
        }
    }
}
