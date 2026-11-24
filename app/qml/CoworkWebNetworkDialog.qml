import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

Popup {
    id: root
    objectName: "coworkWebNetworkDialog"
    required property var network
    parent: Overlay.overlay; anchors.centerIn: parent
    modal: true; focus: true; padding: 21
    width: Math.min(560, parent.width - 40)
    height: Math.min(610, parent.height - 46)
    background: Rectangle { radius: 14; color: Theme.surface; border.color: Theme.line }
    readonly property var modes: ["system", "custom", "direct"]
    property bool saveFailed: false
    function draft() {
        return JSON.stringify({mode:modes[mode.currentIndex], proxy:address.text, caFile:caPath.text,
            username:username.text, password:password.text, clearPassword:forget.checked, proxyDns:proxyDns.checked})
    }
    onAboutToShow: {
        const value = network.settings
        mode.currentIndex = Math.max(0, modes.indexOf(value.mode))
        address.text = value.proxy || ""
        caPath.text = value.caFile || ""
        username.text = value.username || ""
        password.text = ""
        forget.checked = false
        proxyDns.checked = value.proxyDns
        saveFailed = false
        probe.reset()
    }
    onClosed: password.clear()

    FileDialog {
        id: certificate
        title: I18n.t("选择 CA 证书")
        nameFilters: [I18n.t("PEM 证书 (*.pem *.crt *.cer)"), I18n.t("所有文件 (*)")]
        onAccepted: caPath.text = String(selectedFile)
    }
    contentItem: ColumnLayout {
        spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true; text: I18n.t("Cowork 网络设置")
                color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(19); font.weight: Font.DemiBold
            }
            ActionButton { glyph: "x"; quiet: true; hint: I18n.t("关闭"); onClicked: root.close() }
        }
        ScrollView {
            id: scroll
            Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth; clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ColumnLayout {
                width: scroll.availableWidth - 8
                spacing: 9
                Text {
                    text: I18n.t("代理模式")
                    color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); font.weight: Font.DemiBold
                }
                Picker {
                    id: mode; objectName: "coworkWebProxyMode"
                    Layout.fillWidth: true
                    model: [I18n.t("跟随系统"), I18n.t("手动代理"), I18n.t("直连")]
                    Accessible.name: I18n.t("代理模式")
                }
                ColumnLayout {
                    visible: mode.currentIndex === 1
                    Layout.fillWidth: true; spacing: 7
                    InputField {
                        id: address; objectName: "coworkWebProxyAddress"
                        Layout.fillWidth: true; maximumLength: 2048
                        placeholderText: "http://proxy.example.com:8080"
                        Accessible.name: I18n.t("代理地址")
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        InputField {
                            id: username
                            Layout.fillWidth: true; maximumLength: 255
                            placeholderText: I18n.t("代理用户名（可选）")
                        }
                        InputField {
                            id: password
                            Layout.fillWidth: true; maximumLength: 1024; echoMode: TextInput.Password
                            placeholderText: root.network.settings.hasPassword && !forget.checked ? I18n.t("密码已存入系统凭据库") : I18n.t("代理密码（可选）")
                        }
                    }
                    CheckBox { id: forget; visible: root.network.settings.hasPassword; text: I18n.t("清除已保存的代理密码") }
                }
                CheckBox {
                    id: proxyDns; objectName: "coworkWebProxyDns"
                    Layout.fillWidth: true; visible: mode.currentIndex !== 2
                    text: I18n.t("本机 DNS 无可用地址时，交由代理解析")
                }
                Text {
                    visible: proxyDns.visible && proxyDns.checked; Layout.fillWidth: true; wrapMode: Text.Wrap
                    text: I18n.t("适用于无法本机解析的 HTTPS 地址。请使用受信任的代理。")
                    color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                }
                Text {
                    text: I18n.t("额外 CA 证书")
                    color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); font.weight: Font.DemiBold
                }
                Text {
                    Layout.fillWidth: true; wrapMode: Text.Wrap
                    text: I18n.t("网页工具使用系统信任的证书。可为 Cowork 追加企业 PEM 证书。")
                    color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                }
                RowLayout {
                    Layout.fillWidth: true
                    InputField {
                        id: caPath; objectName: "coworkWebCaPath"
                        Layout.fillWidth: true
                        placeholderText: I18n.t("PEM 证书路径（可选）")
                    }
                    ActionButton { text: I18n.t("选择文件"); glyph: "folder"; onClicked: certificate.open() }
                }
                CoworkWebProbe {
                    id: probe
                    Layout.fillWidth: true; Layout.topMargin: 8
                    network: root.network
                    settingsJson: root.visible ? root.draft() : ""
                }
            }
        }
        Text {
            visible: root.saveFailed; Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText
            text: root.network.result.message || ""
            color: Theme.danger; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
        }
        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            ActionButton { text: I18n.t("取消"); quiet: true; onClicked: root.close() }
            ActionButton {
                objectName: "coworkWebSave"
                text: I18n.t("保存"); primary: true
                enabled: !root.network.testing
                onClicked: {
                    root.saveFailed = !root.network.save(root.draft())
                    if (!root.saveFailed) root.close()
                }
            }
        }
    }
}
