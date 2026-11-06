import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Readable body of a confirm request; see approval-view.js for the parsing.
ColumnLayout {
    id: root
    property var view: ({})
    property bool rawOpen: false
    spacing: 14

    Text {
        objectName: "approvalAction"
        Layout.fillWidth: true
        visible: text.length > 0
        text: root.view.action ? I18n.t(root.view.action) : ""
        textFormat: Text.PlainText; wrapMode: Text.Wrap
        color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(14, visible); font.weight: Font.DemiBold
    }
    Text {
        objectName: "approvalDescription"
        Layout.fillWidth: true; Layout.topMargin: -8
        visible: text.length > 0
        text: root.view.description || ""
        textFormat: Text.PlainText; wrapMode: Text.Wrap
        color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible)
    }
    Repeater {
        model: root.view.sections || []
        delegate: ColumnLayout {
            id: section
            required property var modelData
            required property int index
            objectName: "approvalSection_" + index
            Layout.fillWidth: true; spacing: 6
            Text {
                visible: !!section.modelData.label
                text: I18n.t(section.modelData.label || "")
                color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible)
            }
            TextArea {
                objectName: "approvalSectionText_" + section.index
                Layout.fillWidth: true
                text: section.modelData.text
                readOnly: true; selectByMouse: true; wrapMode: TextArea.Wrap
                textFormat: TextEdit.PlainText
                color: Theme.ink
                font.family: section.modelData.mono ? "Consolas" : Theme.fontFamily
                font.pixelSize: Theme.font(section.modelData.mono ? 12 : 13, visible)
                padding: section.modelData.mono ? 12 : 0
                leftPadding: padding; rightPadding: padding; topPadding: padding; bottomPadding: padding
                background: Rectangle { visible: section.modelData.mono; color: Theme.bg; radius: 7; border.color: Theme.line }
            }
        }
    }
    RowLayout {
        objectName: "approvalPermission"
        Layout.fillWidth: true; spacing: 8
        visible: !!root.view.permission || !!root.view.permissionValue
        Glyph {
            name: "lock"; Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: Theme.icon(15); Layout.preferredHeight: Theme.icon(15)
            color: root.view.permissionLevel === "danger-full-access" ? Theme.danger : Theme.muted
        }
        Text {
            objectName: "approvalPermissionText"
            Layout.fillWidth: true
            text: root.view.permission ? I18n.t(root.view.permission) : root.view.permissionValue ? I18n.t("请求的权限：") + root.view.permissionValue : ""
            textFormat: Text.PlainText; wrapMode: Text.Wrap
            color: root.view.permissionLevel === "danger-full-access" ? Theme.danger : Theme.ink
            font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible)
        }
    }
    ActionButton {
        objectName: "approvalRawToggle"
        visible: !!root.view.raw
        quiet: true
        text: root.rawOpen ? I18n.t("收起原始参数") : I18n.t("查看原始参数")
        glyph: root.rawOpen ? "chevron-up" : "chevron-down"
        onClicked: root.rawOpen = !root.rawOpen
    }
    TextArea {
        objectName: "approvalRawText"
        Layout.fillWidth: true; Layout.topMargin: -8
        visible: root.rawOpen && !!root.view.raw
        text: root.view.raw || ""
        readOnly: true; selectByMouse: true; wrapMode: TextArea.Wrap
        textFormat: TextEdit.PlainText
        color: Theme.muted; font.family: "Consolas"; font.pixelSize: Theme.font(11, visible); padding: 12
        leftPadding: padding; rightPadding: padding
        background: Rectangle { color: Theme.bg; radius: 7; border.color: Theme.line }
    }
}
