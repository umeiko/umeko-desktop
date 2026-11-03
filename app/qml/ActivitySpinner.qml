import QtQuick

Item {
    id: root
    property bool running: true
    property color color: Theme.muted
    implicitWidth: Theme.icon(15); implicitHeight: Theme.icon(15)
    Canvas {
        id: wheel
        anchors.fill: parent
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        Connections { target: root; function onColorChanged() { wheel.requestPaint() } }
        onPaint: {
            const ctx = getContext("2d"), radius = Math.min(width, height) / 2
            ctx.reset(); ctx.translate(width / 2, height / 2)
            ctx.strokeStyle = root.color; ctx.lineWidth = Math.max(1, radius * 0.2); ctx.lineCap = "round"
            for (let i = 0; i < 12; ++i) {
                ctx.save(); ctx.rotate(i * Math.PI / 6); ctx.globalAlpha = 0.16 + i / 11 * 0.84
                ctx.beginPath(); ctx.moveTo(0, -radius * 0.5); ctx.lineTo(0, -radius * 0.85); ctx.stroke(); ctx.restore()
            }
        }
        RotationAnimator on rotation { from: 0; to: 360; duration: 960; loops: Animation.Infinite; running: root.running && root.visible }
    }
}
