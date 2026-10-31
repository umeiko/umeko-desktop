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
            onToggled: {
                root.error = ""
                root.pending = root.sdk.saveConfig(Object.assign({},root.sdk.config,{autoOpen:checked}))
                if (!root.pending) root.error = root.sdk.t("保存失败，请重试")
            }
        }
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
        function onConfigSaved(request,value) {
            if (request !== root.pending) return
            root.pending = ""
            if (!value.ok) root.error = value.error || root.sdk.t("保存失败，请重试")
        }
    }
}
