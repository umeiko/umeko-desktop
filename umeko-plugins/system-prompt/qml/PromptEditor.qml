import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../app/qml" as Umeko

Rectangle {
    id: root
    required property var sdk
    property var selected: null
    property string draft: ""
    property bool dirty: false
    property bool available: true
    property bool chinese: sdk.language.indexOf("zh") === 0
    signal edited(string value)
    signal save()
    signal restore()
    function t(zh, en) { return chinese ? zh : en }
    function characters(text) { return Array.from(text || "").length }
    color: sdk.colors.surface
    border.color: selected && !selected.enabled ? sdk.colors.muted : sdk.colors.line
    radius: 6 * sdk.scale
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10 * root.sdk.scale
        spacing: 7 * root.sdk.scale
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: root.selected ? root.selected.name : root.t("选择提示词段落", "Select a segment")
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: root.selected && (root.selected.modified || root.dirty) ? "#d7b65b" : root.sdk.colors.ink
                font.family: Umeko.Theme.fontFamily
                font.pixelSize: Umeko.Theme.font(12)
                font.bold: true
            }
            Text {
                visible: root.dirty
                text: root.t("未保存", "Unsaved")
                color: "#d7b65b"
                font.family: Umeko.Theme.fontFamily
                font.pixelSize: Umeko.Theme.font(10)
            }
        }
        Text {
            objectName: "systemPromptDisabledNotice"
            visible: !!root.selected && !root.selected.enabled
            Layout.fillWidth: true
            text: root.t("此段已停用，不会加入系统提示词。", "Disabled · excluded from the system prompt.")
            wrapMode: Text.Wrap
            color: root.sdk.colors.muted
            font.family: Umeko.Theme.fontFamily
            font.pixelSize: Umeko.Theme.font(10)
        }
        Text {
            objectName: "systemPromptShadowedNotice"
            visible: !!root.selected && !!root.selected.shadowed
            Layout.fillWidth: true
            text: root.t("此段被后续来源覆盖。停用对应的替换段落后，此段才会生效。", "A later source replaces this segment. Disable that replacement to use this segment.")
            wrapMode: Text.Wrap
            color: root.sdk.colors.muted
            font.family: Umeko.Theme.fontFamily
            font.pixelSize: Umeko.Theme.font(10)
        }
        Text {
            objectName: "systemPromptStaleNotice"
            visible: !!root.selected && !!root.selected.stale
            Layout.fillWidth: true
            text: root.t("原文已变化。当前保留你的修改；恢复原文将使用最新版本。", "The original has changed. Your edit is retained; Restore uses the latest original.")
            wrapMode: Text.Wrap
            color: "#d7b65b"
            font.family: Umeko.Theme.fontFamily
            font.pixelSize: Umeko.Theme.font(10)
        }
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            TextArea {
                id: editor
                objectName: "systemPromptEditor"
                text: root.draft
                onTextChanged: if (text !== root.draft) root.edited(text)
                readOnly: !root.selected || !root.available
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                textFormat: TextEdit.PlainText
                placeholderText: root.t("在上方选择段落，查看或编辑内容。", "Choose a segment above to read or edit it.")
                placeholderTextColor: root.sdk.colors.muted
                color: root.selected && !root.selected.enabled ? root.sdk.colors.muted : root.sdk.colors.ink
                selectionColor: root.sdk.colors.accentBg
                font.family: Umeko.Theme.fontFamily
                font.pixelSize: Umeko.Theme.font(11)
                padding: 7 * root.sdk.scale
                background: Rectangle { color: root.sdk.colors.bg; radius: 4 * root.sdk.scale }
            }
        }
        Text {
            objectName: "systemPromptCharacterCount"
            Layout.fillWidth: true
            text: root.selected ? root.t("当前 ", "Now ") + (root.selected.enabled && !root.selected.shadowed ? root.characters(root.draft) : 0) + root.t(" 字符 · 原文 ", " chars · Original ") + root.characters(root.selected.originalText) : ""
            color: root.sdk.colors.muted
            font.family: Umeko.Theme.fontFamily
            font.pixelSize: Umeko.Theme.font(10)
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 7 * root.sdk.scale
            Item { Layout.fillWidth: true }
            PromptButton {
                objectName: "systemPromptRestore"
                sdk: root.sdk
                text: root.t("恢复原文", "Restore original")
                enabled: root.available && !!root.selected && (!root.selected.enabled || !!root.selected.modified || root.dirty || !!root.selected.stale)
                onClicked: root.restore()
            }
            PromptButton {
                objectName: "systemPromptSave"
                sdk: root.sdk
                primary: true
                text: root.t("保存", "Save")
                enabled: root.available && root.dirty
                onClicked: root.save()
            }
        }
    }
}
