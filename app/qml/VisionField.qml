import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

RowLayout {
    id: root
    spacing: 5
    property string modelName: ""
    property bool visionEnabled: false
    property bool automatic: true
    property var suggestion: backend.visionSuggestion(modelName)
    signal edited(bool value, bool automatic)

    CheckBox {
        id: check
        objectName: root.objectName + "_checkbox"
        text: "视觉"
        checked: root.automatic ? root.suggestion.vision : root.visionEnabled
        implicitHeight: 42; leftPadding: 0; rightPadding: 0
        onToggled: root.edited(checked, false)
        indicator: Rectangle {
            width: 18; height: 18; radius: 4; y: (check.height - height) / 2
            color: check.checked ? Theme.accent : Theme.surface
            border.color: check.checked || check.activeFocus ? Theme.accent : Theme.line
            Canvas {
                anchors.fill: parent; visible: check.checked
                property color stroke: Theme.buttonText
                onStrokeChanged: requestPaint()
                onPaint: {
                    const ctx = getContext("2d")
                    ctx.reset(); ctx.lineWidth = 1.7; ctx.strokeStyle = stroke; ctx.lineCap = "round"; ctx.lineJoin = "round"
                    ctx.beginPath(); ctx.moveTo(4, 9); ctx.lineTo(7, 12); ctx.lineTo(14, 5); ctx.stroke()
                }
            }
        }
        contentItem: Text { text: check.text; leftPadding: 25; color: Theme.ink; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
    }
    HelpButton { help: "启用后可向模型发送图片。默认按原始模型名识别，未知型号不启用；手动勾选或取消会保留，恢复自动后重新识别。请按供应商实际部署的能力设置。此选项只代表图片输入，不代表音视频或生成图片。" }
    ActionButton {
        objectName: root.objectName + "_reset"
        Layout.preferredWidth: 66
        text: root.automatic ? "自动" : "恢复自动"
        quiet: true
        hint: root.automatic ? (root.suggestion.matched ? "按原始模型名识别；可手动勾选或取消" : "未识别模型名，默认不启用图片输入；可手动勾选") : "恢复按原始模型名识别视觉能力"
        onClicked: root.edited(root.suggestion.vision, true)
    }
    Item { Layout.fillWidth: true }
}
