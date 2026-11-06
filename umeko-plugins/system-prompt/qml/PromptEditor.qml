import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../app/qml" as Umeko

// Lower pane: location, notices, editable text, counts and actions for one segment.
Rectangle {
    id: root
    required property var sdk
    property var selected: null
    property string title: ""
    property string breadcrumb: ""
    property color changedColor: "#d7b65b"
    property string draft: ""
    property bool dirty: false
    property bool available: true
    property bool chinese: sdk.language.indexOf("zh") === 0
    readonly property bool active: !!selected && selected.enabled && !selected.shadowed
    signal edited(string value)
    signal save()
    signal restore()
    function t(zh, en) { return chinese ? zh : en }
    function characters(text) { return Array.from(text || "").length }
    function count(value) { return Number(value || 0).toLocaleString(Qt.locale("en_US"), "f", 0) }
    color: sdk.colors.surface
    border.color: selected && (selected.modified || dirty) ? changedColor : sdk.colors.line
    radius: 6 * sdk.scale
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10 * root.sdk.scale
        spacing: 6 * root.sdk.scale
        Text {
            objectName: "systemPromptBreadcrumb"
            visible: !!root.selected && root.breadcrumb !== ""
            Layout.fillWidth: true
            text: root.breadcrumb
            textFormat: Text.PlainText
            elide: Text.ElideMiddle
            color: root.sdk.colors.muted
            font.family: Umeko.Theme.fontFamily
            font.pixelSize: Umeko.Theme.font(10)
        }
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: root.selected ? root.title : root.t("选择提示词段落", "Select a segment")
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: root.selected && (root.selected.modified || root.dirty) ? root.changedColor : root.sdk.colors.ink
                font.family: Umeko.Theme.fontFamily
                font.pixelSize: Umeko.Theme.font(12)
                font.bold: true
            }
            Text {
                visible: root.dirty || (!!root.selected && !!root.selected.modified)
                text: root.dirty ? root.t("未保存", "Unsaved") : root.t("已编辑", "Edited")
                color: root.changedColor
                font.family: Umeko.Theme.fontFamily
                font.pixelSize: Umeko.Theme.font(10)
            }
        }
        PromptNotice {
            objectName: "systemPromptDisabledNotice"
            sdk: root.sdk
            visible: !!root.selected && !root.selected.enabled
            text: root.t("此段已停用，不会注入系统提示词。勾选上方复选框可重新启用。", "Disabled · not injected into the system prompt. Tick its checkbox above to enable it again.")
        }
        PromptNotice {
            objectName: "systemPromptShadowedNotice"
            sdk: root.sdk
            visible: !!root.selected && !!root.selected.shadowed
            text: root.t("此段被后面的来源整段替换。停用那个替换段后，此段才会生效。", "A later source replaces this segment. Disable that replacement to use this segment.")
        }
        PromptNotice {
            objectName: "systemPromptStaleNotice"
            sdk: root.sdk
            visible: !!root.selected && !!root.selected.stale
            accent: root.changedColor
            text: root.t("原文已更新。当前仍使用你的修改；恢复初始会使用最新原文。", "The original has changed. Your edit is kept; Restore original uses the latest original.")
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
                color: root.active ? root.sdk.colors.ink : root.sdk.colors.muted
                selectionColor: root.sdk.colors.accentBg
                selectedTextColor: root.sdk.colors.ink
                font.family: Umeko.Theme.fontFamily
                font.pixelSize: Umeko.Theme.font(11)
                padding: 8 * root.sdk.scale
                background: Rectangle {
                    color: root.sdk.colors.bg
                    radius: 4 * root.sdk.scale
                    border.color: editor.activeFocus ? root.sdk.colors.accent : "transparent"
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 7 * root.sdk.scale
            Text {
                objectName: "systemPromptCharacterCount"
                Layout.fillWidth: true
                text: !root.selected ? ""
                    : root.active ? root.t("本段注入 " + root.count(root.characters(root.draft)) + " 字 · 原文 " + root.count(root.characters(root.selected.originalText)) + " 字",
                                           "Injected " + root.count(root.characters(root.draft)) + " chars · Original " + root.count(root.characters(root.selected.originalText)) + " chars")
                    : root.t("本段未注入 · 原文 " + root.count(root.characters(root.selected.originalText)) + " 字",
                             "Not injected · Original " + root.count(root.characters(root.selected.originalText)) + " chars")
                elide: Text.ElideRight
                color: root.sdk.colors.muted
                font.family: Umeko.Theme.fontFamily
                font.pixelSize: Umeko.Theme.font(10)
            }
            PromptButton {
                objectName: "systemPromptRestore"
                sdk: root.sdk
                text: root.t("恢复初始", "Restore original")
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
