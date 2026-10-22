import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ActionButton {
    id: root
    property string providerId: ""
    readonly property var record: backend.config.providers.find(p => p.id === providerId) || ({})
    objectName: "providerProxy_" + providerId
    glyph: "settings"; quiet: true; hint: I18n.t("供应商网络代理")
    onClicked: {
        const network = record.proxy || {mode:"system",url:""}
        mode.currentIndex = Math.max(0, ["system","direct","custom"].indexOf(network.mode))
        address.text = network.url || ""
        dialog.open()
    }
    Popup {
        id: dialog; objectName: "providerProxyDialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(510, parent.width - 40); padding: 24; modal: true; focus: true
        background: Rectangle { radius: 14; color: Theme.surface; border.color: Theme.line }
        contentItem: ColumnLayout {
            spacing: 16
            Text { text: I18n.t("供应商网络代理"); color: Theme.ink; font.pixelSize: Theme.font(17); font.weight: Font.DemiBold }
            Text { text: root.record.name || ""; color: Theme.muted; font.pixelSize: Theme.font(12); textFormat: Text.PlainText; Layout.fillWidth: true; elide: Text.ElideRight }
            Picker { id: mode; objectName: "providerProxyMode"; Layout.fillWidth: true; model: [I18n.t("跟随系统代理"), I18n.t("不使用代理"), I18n.t("使用自定义代理")] }
            InputField { id: address; objectName: "providerProxyAddress"; Layout.fillWidth: true; visible: mode.currentIndex === 2; placeholderText: "http://127.0.0.1:7890" }
            Text { text: I18n.t("仅影响此供应商的模型请求，以及插件的登录和模型发现。自定义代理支持 HTTP / HTTPS。"); color: Theme.muted; font.pixelSize: Theme.font(12); wrapMode: Text.Wrap; Layout.fillWidth: true }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { text: I18n.t("取消"); quiet: true; onClicked: dialog.close() }
                ActionButton { objectName: "saveProviderProxy"; text: I18n.t("保存"); primary: true; onClicked: if (backend.setProviderProxy(root.providerId, ["system","direct","custom"][mode.currentIndex], address.text)) dialog.close() }
            }
        }
    }
}
