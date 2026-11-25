import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    required property var network
    property string settingsJson: ""
    property bool requested: false
    spacing: 8

    function reset() { requested = false; url.text = "" }
    function stageLabel(stage) {
        return ({settings:I18n.t("设置"), policy:I18n.t("访问范围"), dns:"DNS", proxy:I18n.t("代理"), tls:"TLS", http:"HTTP"})[stage] || ""
    }

    Text {
        text: I18n.t("连接测试")
        color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); font.weight: Font.DemiBold
    }
    RowLayout {
        Layout.fillWidth: true
        InputField {
            id: url
            objectName: "coworkWebProbeUrl"
            Layout.fillWidth: true; maximumLength: 2048
            placeholderText: "https://example.com"
            Accessible.name: I18n.t("测试网址")
            onAccepted: if (run.enabled) run.clicked()
        }
        ActionButton {
            id: run
            objectName: "coworkWebProbeRun"
            enabled: !root.network.testing && !!url.text.trim()
            text: root.network.testing && root.requested ? I18n.t("测试中…") : I18n.t("测试连接")
            onClicked: {
                root.requested = true
                root.network.test(root.settingsJson, url.text.trim())
            }
        }
    }
    ColumnLayout {
        Layout.fillWidth: true
        visible: root.requested && !root.network.testing && root.network.result.ok !== undefined
        spacing: 4
        Repeater {
            model: parent.visible ? (root.network.result.steps || []) : []
            delegate: Text {
                required property var modelData
                Layout.fillWidth: true
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                text: root.stageLabel(modelData.stage) + " · " +
                    (modelData.status === "ok" ? I18n.t("通过") : I18n.t("失败")) +
                    (modelData.viaProxy ? " · " + I18n.t("由代理解析") : "") +
                    (modelData.route ? " · " + ({system:I18n.t("系统代理"), custom:I18n.t("手动代理"), direct:I18n.t("直连")})[modelData.route] : "") +
                    (modelData.httpStatus ? " · " + modelData.httpStatus : "")
                color: modelData.status === "ok" ? Theme.muted : Theme.danger
                font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
            }
        }
        Text {
            objectName: "coworkWebProbeResult"
            Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText
            text: root.network.result.ok ? I18n.t("连接成功") :
                root.stageLabel(root.network.result.stage) + " · " + (root.network.result.message || "")
            color: root.network.result.ok ? Theme.ink : Theme.danger
            font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
        }
    }
}
