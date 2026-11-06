import QtQuick
import QtQuick.Layouts
import "../../../app/qml" as Umeko

Rectangle {
    id: root
    required property var sdk
    property string segmentName: ""
    property bool available: true
    signal cancelled()
    signal confirmed()
    function t(zh, en) { return sdk.language.indexOf("zh") === 0 ? zh : en }
    objectName: "systemPromptRestoreConfirmation"
    color: "#80000000"
    z: 20
    focus: visible
    Keys.onEscapePressed: root.cancelled()
    MouseArea { anchors.fill: parent; onClicked: {} }
    Rectangle {
        anchors.centerIn: parent
        width: Math.min(parent.width - 24 * root.sdk.scale, 360 * root.sdk.scale)
        height: body.implicitHeight + 28 * root.sdk.scale
        radius: 8 * root.sdk.scale
        color: root.sdk.colors.surface
        border.color: root.sdk.colors.line
        ColumnLayout {
            id: body
            anchors.fill: parent
            anchors.margins: 14 * root.sdk.scale
            spacing: 12 * root.sdk.scale
            Text {
                Layout.fillWidth: true
                text: root.t("恢复原文？", "Restore original?")
                color: root.sdk.colors.ink
                font.family: Umeko.Theme.fontFamily
                font.pixelSize: Umeko.Theme.font(14)
                font.bold: true
            }
            Text {
                Layout.fillWidth: true
                text: root.t("将恢复「", "Restore “") + root.segmentName + root.t("」的最新原文，移除已保存的修改和未保存草稿。", "” to its latest original, removing saved edits and the unsaved draft.")
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: root.sdk.colors.muted
                font.family: Umeko.Theme.fontFamily
                font.pixelSize: Umeko.Theme.font(11)
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                PromptButton { objectName: "systemPromptRestoreCancel"; sdk: root.sdk; text: root.t("取消", "Cancel"); onClicked: root.cancelled() }
                PromptButton { objectName: "systemPromptRestoreConfirm"; sdk: root.sdk; primary: true; text: root.t("恢复原文", "Restore original"); enabled: root.available; onClicked: root.confirmed() }
            }
        }
    }
}
