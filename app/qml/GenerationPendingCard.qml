import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root
    required property string toolName
    required property string toolId
    property var selectionController: null
    property bool sessionActive: true
    readonly property bool voice: toolName === "voice_gen"
    readonly property string label: backend.language === "en"
        ? (voice ? "Generating audio…" : "Generating image…")
        : (voice ? "正在生成语音…" : "正在生成图片…")
    objectName: "chatboxGenerating_" + toolId
    implicitWidth: Math.max(Theme.control(180), body.implicitWidth + 24)
    implicitHeight: Math.max(Theme.control(40), body.implicitHeight + 14)
    height: implicitHeight
    radius: 7
    color: Theme.surface
    border.color: Theme.line
    Accessible.role: Accessible.StaticText
    Accessible.name: label

    RowLayout {
        id: body
        anchors.fill: parent
        anchors.leftMargin: 12; anchors.rightMargin: 12
        spacing: 9
        ActivitySpinner {
            objectName: "chatboxGeneratingSpinner_" + root.toolId
            Layout.preferredWidth: Theme.icon(15)
            Layout.preferredHeight: Theme.icon(15)
            running: root.sessionActive
            color: Theme.accent
        }
        Text {
            Layout.fillWidth: true
            text: root.label
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: Theme.ink
            font.family: Theme.fontFamily
            font.pixelSize: Theme.font(12, visible, root.selectionController)
        }
    }
}
