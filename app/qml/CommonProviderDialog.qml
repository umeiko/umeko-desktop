import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: root
    objectName: "commonProviderDialog"
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(440, parent.width - 32)
    height: Math.min(content.implicitHeight + 48, parent.height - 32)
    padding: 24; modal: true; focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    property var selected: null
    readonly property bool useInternational: !!(selected && selected.international && site.currentIndex === 1)
    readonly property var effectivePreset: useInternational ? selected.international : selected
    property bool submitting: false
    onOpened: { selected = null; site.currentIndex = 0; apiKey.clear(); accountAlias.clear(); providerScroll.contentY = 0 }
    onClosed: { apiKey.clear(); accountAlias.clear(); selected = null; site.currentIndex = 0 }
    function keyHint() {
        if (!selected || !selected.subscription) return I18n.t("填写官方 API Key，即可添加使用。")
        return useInternational ? I18n.t("填写国际站订阅 Key，即可添加使用。") : I18n.t("填写国内站订阅 Key，即可添加使用。")
    }
    function siteLabel(preset, international) {
        if (!preset || !preset.siteUrl) return I18n.t(international ? "国际站" : "国内站")
        const address = preset.siteUrl.replace(/^https?:\/\//, "").replace(/\/$/, "")
        return address + I18n.t(international ? "（国际）" : "（中国大陆）")
    }
    function choose(preset) { apiKey.clear(); accountAlias.clear(); site.currentIndex = 0; selected = preset; providerScroll.contentY = 0; apiKey.forceActiveFocus() }
    background: Rectangle { color: Theme.surface; radius: 14; border.color: Theme.line }
    Overlay.modal: Rectangle { color: "#66000000" }
    contentItem: Flickable {
        id: providerScroll
        objectName: "commonProviderScroll"
        contentHeight: content.implicitHeight; clip: true
        boundsBehavior: Flickable.StopAtBounds
        ColumnLayout {
            id: content
            width: parent.width; spacing: 20
            RowLayout {
                Layout.fillWidth: true; spacing: 10
                ActionButton { objectName: "commonProviderBack"; visible: !!root.selected; glyph: "arrow-left"; quiet: true; hint: I18n.t("返回"); onClicked: { apiKey.clear(); accountAlias.clear(); root.selected = null; site.currentIndex = 0; providerScroll.contentY = 0 } }
                Text { font.family: Theme.fontFamily; Layout.fillWidth: true; text: root.selected ? I18n.t(root.selected.label) : I18n.t("添加常见供应商"); color: Theme.ink; font.pixelSize: Theme.font(18); font.weight: Font.DemiBold }
                ActionButton { glyph: "x"; quiet: true; hint: I18n.t("关闭"); onClicked: root.close() }
            }
            ColumnLayout {
                visible: !root.selected; Layout.fillWidth: true; spacing: 8
                Repeater {
                    model: backend.commonProviders
                    ActionButton {
                        id: vendorButton
                        required property var modelData
                        objectName: "commonProvider_" + modelData.id
                        Layout.fillWidth: true; implicitHeight: Theme.control(62)
                        Accessible.name: I18n.t(modelData.label)
                        onClicked: root.choose(modelData)
                        contentItem: RowLayout {
                            anchors.fill: parent; anchors.margins: 13; spacing: 13
                            Rectangle {
                                width: 34; height: 34; radius: 8; color: "white"
                                Image { anchors.centerIn: parent; width: 24; height: 24; source: "../icons/providers/" + vendorButton.modelData.icon; fillMode: Image.PreserveAspectFit }
                            }
                            Text { font.family: Theme.fontFamily; Layout.fillWidth: true; text: I18n.t(vendorButton.modelData.label); color: Theme.ink; font.pixelSize: Theme.font(13) }
                            Glyph { name: "chevron-right"; width: Theme.icon(16); height: width }
                        }
                    }
                }
            }
            ColumnLayout {
                visible: !!root.selected; Layout.fillWidth: true; spacing: 14
                Picker {
                    id: site
                    objectName: "commonProviderRegion"
                    visible: !!(root.selected && root.selected.international)
                    Layout.fillWidth: true
                    model: [root.siteLabel(root.selected, false), root.siteLabel(root.selected ? root.selected.international : null, true)]
                    currentIndex: 0
                    Accessible.name: I18n.t("站点")
                    onCurrentIndexChanged: if (apiKey) apiKey.clear()
                    onActivated: apiKey.forceActiveFocus()
                }
                Flow {
                    Layout.fillWidth: true; spacing: 6
                    Text { font.family: Theme.fontFamily; objectName: "commonProviderKeyHint"; width: Math.min(implicitWidth, parent.width); text: root.keyHint(); color: Theme.muted; font.pixelSize: Theme.font(12); wrapMode: Text.Wrap }
                    Button {
                        id: keyLink
                        objectName: "commonProviderKeyLink"
                        readonly property string targetUrl: root.effectivePreset ? root.effectivePreset.keyUrl : ""
                        text: I18n.t("申请 API Key") + " ↗"
                        enabled: targetUrl.length > 0
                        padding: 0; implicitWidth: linkLabel.implicitWidth; implicitHeight: linkLabel.implicitHeight
                        Accessible.role: Accessible.Link
                        background: Rectangle { color: "transparent"; radius: 2; border.color: keyLink.activeFocus ? Theme.accent : "transparent" }
                        contentItem: Text { font.family: Theme.fontFamily; id: linkLabel; text: keyLink.text; color: Theme.accent; font.pixelSize: Theme.font(12); font.underline: true }
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        onClicked: Qt.openUrlExternally(targetUrl)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 7
                    Text { font.family: Theme.fontFamily; text: "API Key"; color: Theme.ink; font.pixelSize: Theme.font(12) }
                    InputField { id: apiKey; objectName: "commonProviderKey"; Layout.fillWidth: true; echoMode: TextInput.Password; placeholderText: I18n.t("输入 API Key"); onAccepted: if (addButton.enabled) addButton.clicked() }
                }
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 7
                    Text { font.family: Theme.fontFamily; text: I18n.t("账号别名（可选）"); color: Theme.ink; font.pixelSize: Theme.font(12) }
                    InputField { id: accountAlias; objectName: "commonProviderAlias"; Layout.fillWidth: true; maximumLength: 60; placeholderText: I18n.t("例如：工作号"); onAccepted: if (addButton.enabled) addButton.clicked() }
                }
                Text { font.family: Theme.fontFamily; objectName: "commonProviderNamePreview"; visible: accountAlias.text.trim().length > 0; Layout.fillWidth: true; text: root.effectivePreset ? root.effectivePreset.name + (accountAlias.text.trim() ? "(" + accountAlias.text.trim() + ")" : "") : ""; color: Theme.muted; font.pixelSize: Theme.font(11); elide: Text.ElideRight }
                RowLayout {
                    Layout.fillWidth: true; Layout.topMargin: 4
                    Item { Layout.fillWidth: true }
                    ActionButton { text: I18n.t("取消"); quiet: true; onClicked: root.close() }
                    ActionButton {
                        id: addButton; objectName: "confirmCommonProvider"; text: I18n.t("添加并使用"); primary: true
                        enabled: !root.submitting && !!root.selected && apiKey.text.trim().length > 0
                        onClicked: {
                            if (root.submitting) return
                            root.submitting = true
                            try { if (backend.addCommonProvider(root.selected.id, apiKey.text, accountAlias.text, root.useInternational ? "international" : "cn")) root.close() }
                            finally { root.submitting = false }
                        }
                    }
                }
            }
        }
    }
}
