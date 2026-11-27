import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../app/qml" as Umeko

Popup {
    id: picker
    objectName: "groupChatMemberPicker"
    required property var candidates
    required property bool english
    property bool submitting: false
    property string errorText: ""
    signal memberSelected(string sessionId)

    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(Umeko.Theme.control(492), parent.width - 32)
    height: Math.min(parent.height - 32, content.implicitHeight + padding * 2)
    padding: Umeko.Theme.control(20)
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    background: Rectangle {
        color: Umeko.Theme.surface
        border.color: Umeko.Theme.line
        radius: 15
    }
    Overlay.modal: Rectangle { color: Qt.rgba(0.055, 0.08, 0.13, Umeko.Theme.dark ? 0.55 : 0.25) }

    readonly property var workspaces: [...new Set(candidates.map(row => row.workspace).filter(Boolean))].sort()
    readonly property string selectedWorkspace: workspaces[workspaceChoice.currentIndex - 1] || ""
    readonly property string query: search.text.trim().toLowerCase()
    readonly property var results: candidates.filter(row =>
        (!selectedWorkspace || row.workspace === selectedWorkspace) &&
        (row.name + "\n" + row.workspace).toLowerCase().includes(query))
    readonly property real rowHeight: Umeko.Theme.control(54)

    function tr(zh, en) { return english ? en : zh }
    function workspaceLabel(path) {
        if (!path) return tr("默认工作区", "Default workspace")
        const name = path.split(/[\\/]/).filter(Boolean).pop() || path
        return workspaces.filter(row => row.split(/[\\/]/).filter(Boolean).pop() === name).length > 1 ? path : name
    }
    function begin() {
        search.clear()
        workspaceChoice.currentIndex = 0
        errorText = ""
        open()
    }
    onOpened: search.forceActiveFocus()

    contentItem: ColumnLayout {
        id: content
        spacing: Umeko.Theme.control(12)

        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: picker.tr("添加会话", "Add a conversation")
                font.family: Umeko.Theme.fontFamily
                font.pixelSize: Umeko.Theme.font(19)
                font.weight: Font.DemiBold
                color: Umeko.Theme.ink
            }
            Umeko.ActionButton {
                glyph: "x"; quiet: true
                Layout.preferredWidth: Umeko.Theme.control(32)
                Layout.preferredHeight: Umeko.Theme.control(32)
                hint: picker.tr("关闭", "Close")
                Accessible.name: hint
                onClicked: picker.close()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Umeko.Theme.control(8)
            Umeko.InputField {
                id: search
                objectName: "groupChatMemberFilter"
                Layout.fillWidth: true
                Layout.preferredHeight: Umeko.Theme.control(40)
                leftPadding: Umeko.Theme.control(34)
                placeholderText: picker.tr("搜索会话", "Search conversations")
                Accessible.name: placeholderText
                Umeko.Glyph {
                    name: "search"
                    width: Umeko.Theme.icon(15); height: width
                    anchors.left: parent.left
                    anchors.leftMargin: Umeko.Theme.control(11)
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
            Umeko.Picker {
                id: workspaceChoice
                objectName: "groupChatMemberWorkspace"
                Layout.preferredWidth: Math.min(Umeko.Theme.control(155), content.width * 0.4)
                Layout.preferredHeight: search.Layout.preferredHeight
                font.family: Umeko.Theme.fontFamily
                model: [picker.tr("所有工作区", "All workspaces")].concat(picker.workspaces.map(picker.workspaceLabel))
                Accessible.name: picker.tr("工作区", "Workspace")
            }
        }

        Text {
            Layout.fillWidth: true
            visible: picker.errorText !== ""
            text: picker.errorText
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            font.family: Umeko.Theme.fontFamily
            font.pixelSize: Umeko.Theme.font(12)
            color: Umeko.Theme.danger
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredHeight: Math.min(5, Math.max(2, picker.results.length)) * picker.rowHeight + 8
            radius: 10
            color: Umeko.Theme.bg
            border.color: Umeko.Theme.line
            clip: true

            ListView {
                id: resultList
                anchors.fill: parent
                anchors.margins: 4
                clip: true
                model: picker.results
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}

                delegate: ItemDelegate {
                    id: row
                    required property var modelData
                    readonly property string workspaceName: picker.workspaceLabel(modelData.workspace)
                    objectName: "groupChatMemberCandidate_" + modelData.id
                    Accessible.name: modelData.name
                    width: resultList.width
                    height: picker.rowHeight
                    leftPadding: 9; rightPadding: 9
                    enabled: !picker.submitting
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                    background: Rectangle {
                        radius: 7
                        color: row.hovered || row.visualFocus ? Umeko.Theme.hover : "transparent"
                    }
                    contentItem: RowLayout {
                        spacing: Umeko.Theme.control(9)
                        Rectangle {
                            implicitWidth: Umeko.Theme.control(32)
                            implicitHeight: implicitWidth
                            radius: 8; color: Umeko.Theme.accentBg
                            Umeko.Glyph {
                                anchors.centerIn: parent
                                name: "chat"; color: Umeko.Theme.accent
                                width: Umeko.Theme.icon(16); height: width
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Text {
                                Layout.fillWidth: true
                                text: row.modelData.name
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                                font.family: Umeko.Theme.fontFamily
                                font.pixelSize: Umeko.Theme.font(13)
                                font.weight: Font.Medium
                                color: Umeko.Theme.ink
                            }
                            Text {
                                Layout.fillWidth: true
                                text: row.workspaceName
                                textFormat: Text.PlainText
                                elide: Text.ElideMiddle
                                font.family: Umeko.Theme.fontFamily
                                font.pixelSize: Umeko.Theme.font(10)
                                color: Umeko.Theme.muted
                            }
                        }
                        Umeko.Glyph {
                            name: "plus"
                            width: Umeko.Theme.icon(15); height: width
                            color: row.hovered ? Umeko.Theme.accent : Umeko.Theme.muted
                        }
                    }
                    Umeko.HoverTip {
                        active: row.hovered && !!row.modelData.workspace && row.modelData.workspace !== row.workspaceName
                        text: row.modelData.workspace
                    }
                    onClicked: picker.memberSelected(modelData.id)
                }
            }

            Text {
                anchors.centerIn: parent
                visible: !picker.results.length
                text: picker.candidates.length ? picker.tr("没有匹配的会话", "No matching conversations")
                                               : picker.tr("暂无可添加的会话", "No conversations to add")
                font.family: Umeko.Theme.fontFamily
                font.pixelSize: Umeko.Theme.font(12)
                color: Umeko.Theme.muted
            }
        }
    }
}
