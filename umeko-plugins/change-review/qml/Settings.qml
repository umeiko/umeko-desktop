import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    objectName: "changeReviewSettings"
    required property var sdk
    property string pending: ""
    property string error: ""
    implicitHeight: childrenRect.height
    spacing: 10

    function save(name, value) {
        error = ""
        const config = Object.assign({}, sdk.config)
        config[name] = value
        pending = sdk.saveConfig(config)
        if (!pending) error = sdk.t("保存失败，请重试")
    }

    RowLayout {
        Layout.fillWidth: true
        Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: root.sdk.t("每次变更后自动打开")
            color: root.sdk.colors.ink
            font.pixelSize: 14 * root.sdk.scale
        }
        Switch {
            objectName: "changeReviewAutoOpenSwitch"
            checked: root.sdk.config.autoOpen !== false
            enabled: root.sdk.active && !root.pending
            onToggled: root.save("autoOpen", checked)
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: root.sdk.t("保存每轮代码检查点")
            color: root.sdk.colors.ink
            font.pixelSize: 14 * root.sdk.scale
        }
        Switch {
            objectName: "changeReviewCheckpointsSwitch"
            checked: root.sdk.config.checkpoints === true
            enabled: root.sdk.active && !root.pending
            onToggled: root.save("checkpoints", checked)
        }
    }
    Label {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        text: root.sdk.t("检查点只保存在本机，默认最多 20 份、512 MiB；重启后仍可查看历史差异。恢复前必须预览并通过冲突检查。")
        color: root.sdk.colors.muted
        font.pixelSize: 12 * root.sdk.scale
    }
    Label {
        visible: !!root.error
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        text: root.error
        color: root.sdk.colors.danger
        font.pixelSize: 12 * root.sdk.scale
    }
    Connections {
        target: root.sdk
        function onConfigSaved(request, value) {
            if (request !== root.pending) return
            root.pending = ""
            if (!value.ok) root.error = value.error || root.sdk.t("保存失败，请重试")
        }
    }
}
