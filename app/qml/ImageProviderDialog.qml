import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: root
    objectName: "imageProviderDialog"
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(Theme.control(460), parent.width - 32)
    height: Math.min(content.implicitHeight + 48, parent.height - 32)
    padding: 24; modal: true; focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    property var selected: null
    property string editingId: ""
    property bool submitting: false
    readonly property bool custom: !!selected && !!selected.custom
    readonly property var customAccounts: backend.imageProviders.filter(p => p.presetId === "openai-image")
    readonly property var account: selected ? backend.imageProviders.find(p => custom ? p.id === editingId : p.presetId === selected.id) || null : null
    function choose(preset, identifier) {
        apiKey.clear(); selected = preset; editingId = identifier || ""
        accountName.text = account ? account.name : ""
        baseUrl.text = account ? account.baseUrl : ""
        modelId.text = account ? account.model : ""
        providerScroll.contentY = 0
        if (custom) accountName.forceActiveFocus(); else apiKey.forceActiveFocus()
    }
    function clearSelection() { apiKey.clear(); selected = null; editingId = ""; providerScroll.contentY = 0 }
    onOpened: clearSelection()
    onClosed: clearSelection()
    background: Rectangle { color: Theme.surface; radius: 14; border.color: Theme.line }
    Overlay.modal: Rectangle { color: "#66000000" }
    contentItem: Flickable {
        id: providerScroll
        objectName: "imageProviderScroll"
        contentHeight: content.implicitHeight; clip: true
        boundsBehavior: Flickable.StopAtBounds
        ColumnLayout {
            id: content
            width: parent.width; spacing: 20
            RowLayout {
                Layout.fillWidth: true; spacing: 10
                ActionButton {
                    objectName: "imageProviderBack"; visible: !!root.selected
                    glyph: "arrow-left"; quiet: true; hint: I18n.t("返回")
                    onClicked: root.clearSelection()
                }
                Text {
                    Layout.fillWidth: true; text: root.selected ? I18n.t(root.selected.name) : I18n.t("图片供应商")
                    color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(18, visible); font.weight: Font.DemiBold; elide: Text.ElideRight
                }
                ActionButton { objectName: "closeImageProviderDialog"; glyph: "x"; quiet: true; hint: I18n.t("关闭"); onClicked: root.close() }
            }
            ColumnLayout {
                visible: !root.selected; Layout.fillWidth: true; spacing: 10
                Repeater {
                    model: backend.imageProviderPresets
                    Button {
                        id: vendorButton
                        required property var modelData
                        readonly property bool configured: !modelData.custom && backend.imageProviders.some(p => p.presetId === modelData.id && p.hasKey)
                        objectName: "imageProvider_" + modelData.id
                        Layout.fillWidth: true; implicitHeight: Math.max(Theme.control(62), vendorContent.implicitHeight + 24)
                        padding: 14; hoverEnabled: true
                        Accessible.name: I18n.t(modelData.label)
                        background: Rectangle { radius: 10; color: vendorButton.hovered ? Theme.hover : Theme.surface; border.color: vendorButton.activeFocus ? Theme.accent : Theme.line }
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        contentItem: RowLayout {
                            id: vendorContent; spacing: 12
                            Rectangle {
                                Layout.preferredWidth: Theme.icon(36); Layout.preferredHeight: Theme.icon(36); radius: 9; color: vendorButton.modelData.icon ? "white" : Theme.accentBg
                                Image { objectName: "imageProviderLogo_" + vendorButton.modelData.id; anchors.centerIn: parent; width: Theme.icon(25); height: width; source: vendorButton.modelData.icon ? "../icons/providers/" + vendorButton.modelData.icon : ""; fillMode: Image.PreserveAspectFit }
                                Glyph { visible: !vendorButton.modelData.icon; anchors.centerIn: parent; name: "settings"; width: Theme.icon(20); height: width; color: Theme.accent }
                            }
                            Text { objectName: "imageProviderName_" + vendorButton.modelData.id; Layout.fillWidth: true; text: I18n.t(vendorButton.modelData.name); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(14, visible); elide: Text.ElideRight }
                            Text { visible: vendorButton.configured; text: I18n.t("已配置"); color: Theme.accent; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible) }
                            Glyph { name: "chevron-right"; width: Theme.icon(16); height: width; color: Theme.muted }
                        }
                        onClicked: root.choose(modelData)
                    }
                }
                Text { visible: root.customAccounts.length > 0; Layout.topMargin: 8; text: I18n.t("已添加的自定义供应商"); color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible) }
                Repeater {
                    model: root.customAccounts
                    ActionButton {
                        required property var modelData
                        objectName: "editImageProvider_" + modelData.id
                        Layout.fillWidth: true; text: modelData.name; glyph: "settings"; quiet: true
                        onClicked: root.choose(backend.imageProviderPresets.find(p => p.custom), modelData.id)
                    }
                }
            }
            ColumnLayout {
                visible: !!root.selected; Layout.fillWidth: true; spacing: 14
                RowLayout {
                    Layout.fillWidth: true; spacing: 8
                    visible: !root.custom
                    Image { Layout.preferredWidth: Theme.icon(30); Layout.preferredHeight: Theme.icon(30); source: root.selected && root.selected.icon ? "../icons/providers/" + root.selected.icon : ""; fillMode: Image.PreserveAspectFit }
                    Item { Layout.fillWidth: true }
                    ProviderProxy { visible: !!root.account; providerId: root.account ? root.account.id : "" }
                }
                ColumnLayout {
                    visible: root.custom; Layout.fillWidth: true; spacing: 7
                    RowLayout {
                        Layout.fillWidth: true
                        Text { Layout.fillWidth: true; text: I18n.t("供应商名称"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible) }
                        ProviderProxy { visible: !!root.account; providerId: root.account ? root.account.id : "" }
                    }
                    InputField { id: accountName; objectName: "imageProviderCustomName"; Layout.fillWidth: true; maximumLength: 60; placeholderText: I18n.t("例如：我的生图服务") }
                    Text { text: "Base URL"; color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible); Layout.topMargin: 7 }
                    InputField { id: baseUrl; objectName: "imageProviderCustomUrl"; Layout.fillWidth: true; maximumLength: 2048; placeholderText: "https://example.com/v1" }
                    Text { text: I18n.t("模型 ID"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible); Layout.topMargin: 7 }
                    InputField { id: modelId; objectName: "imageProviderCustomModel"; Layout.fillWidth: true; maximumLength: 200; placeholderText: I18n.t("填写供应商的生图模型 ID") }
                    Text { Layout.fillWidth: true; text: "POST /images/generations"; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible) }
                }
                Flow {
                    Layout.fillWidth: true; spacing: 8
                    Text { width: Math.min(implicitWidth, parent.width); text: root.custom ? "API Key" : I18n.t("北京地域 API Key"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible); wrapMode: Text.Wrap }
                    Button {
                        id: keyLink
                        objectName: "imageProviderKeyLink"
                        readonly property string targetUrl: root.selected ? root.selected.keyUrl : ""
                        visible: !root.custom
                        text: I18n.t("申请 API Key") + " ↗"; enabled: targetUrl.length > 0
                        padding: 0; implicitWidth: linkLabel.implicitWidth; implicitHeight: linkLabel.implicitHeight
                        Accessible.role: Accessible.Link
                        background: Rectangle { color: "transparent"; radius: 2; border.color: keyLink.activeFocus ? Theme.accent : "transparent" }
                        contentItem: Text { id: linkLabel; text: keyLink.text; color: Theme.accent; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible); font.underline: true }
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        onClicked: Qt.openUrlExternally(targetUrl)
                    }
                }
                InputField {
                    id: apiKey; objectName: "imageProviderKey"; Layout.fillWidth: true
                    echoMode: TextInput.Password; maximumLength: 4096
                    placeholderText: root.account && root.account.hasKey ? I18n.t("已保存，留空保持现有密钥") : I18n.t("输入 API Key")
                    Accessible.name: "API Key"
                    onAccepted: if (saveButton.enabled) saveButton.clicked()
                }
                RowLayout {
                    Layout.fillWidth: true; Layout.topMargin: 4
                    ActionButton {
                        objectName: "removeImageProvider"; visible: !!root.account
                        text: I18n.t("移除"); quiet: true; glyph: "trash"
                        enabled: !root.submitting
                        onClicked: if (backend.removeImageProvider(root.account.id)) root.clearSelection()
                    }
                    Item { Layout.fillWidth: true }
                    ActionButton { text: I18n.t("取消"); quiet: true; onClicked: root.close() }
                    ActionButton {
                        id: saveButton; objectName: "saveImageProvider"; text: I18n.t("保存并使用"); primary: true
                        enabled: !root.submitting && !!root.selected && (apiKey.text.trim().length > 0 || !!root.account && root.account.hasKey) && (!root.custom || accountName.text.trim().length > 0 && baseUrl.text.trim().length > 0 && modelId.text.trim().length > 0)
                        onClicked: {
                            root.submitting = true
                            try {
                                const saved = root.custom ? backend.saveCustomImageProvider(JSON.stringify({id: root.editingId, name: accountName.text, baseUrl: baseUrl.text, model: modelId.text, key: apiKey.text})) : backend.saveImageProvider(root.selected.id, apiKey.text)
                                if (saved) root.close()
                            }
                            finally { root.submitting = false }
                        }
                    }
                }
            }
        }
    }
}
