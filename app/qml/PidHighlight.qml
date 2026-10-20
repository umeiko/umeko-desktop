import QtQuick

Rectangle {
    id: root
    objectName: "settingsTabHighlight"
    property real targetX: 0
    property real targetWidth: 0
    property real velocityX: 0
    property real velocityWidth: 0
    property real integralX: 0
    property real integralWidth: 0
    property bool moving: false
    property bool ready: false
    readonly property real kp: 280
    readonly property real ki: 60
    readonly property real kd: 20
    height: 38; radius: 7; color: Theme.accentBg; antialiasing: true
    visible: targetWidth > 0
    Component.onCompleted: { ready = true; snap() }
    onTargetXChanged: if (ready) follow()
    onTargetWidthChanged: if (ready) follow()
    onVisibleChanged: if (ready) snap()

    function snap() {
        moving = false
        x = targetX; width = Math.max(0, targetWidth)
        velocityX = 0; velocityWidth = 0; integralX = 0; integralWidth = 0
    }
    function follow() {
        if (!visible || targetWidth <= 0) { snap(); return }
        // Retarget only the setpoint: preserve position, velocity and integral.
        moving = true
    }
    function clamp(value, limit) { return Math.max(-limit, Math.min(limit, value)) }
    function advance(seconds) {
        // Small integration steps keep the controller stable across refresh rates
        // and dropped frames. Discard long pauses rather than replaying them.
        let remaining = Math.min(Math.max(seconds, 0), 0.05)
        while (remaining > 0.000001) {
            const dt = Math.min(remaining, 1 / 240)
            const errorX = targetX - x, errorWidth = targetWidth - width
            // Bounded, leaky integrals avoid windup and a long idle correction tail.
            integralX = clamp(integralX + errorX * dt, 60) * Math.exp(-3 * dt)
            integralWidth = clamp(integralWidth + errorWidth * dt, 30) * Math.exp(-3 * dt)
            // Derivative on measured velocity avoids a kick when the target changes.
            const accelerationX = clamp(kp * errorX + ki * integralX - kd * velocityX, 30000)
            const accelerationWidth = clamp(kp * errorWidth + ki * integralWidth - kd * velocityWidth, 18000)
            velocityX = clamp(velocityX + accelerationX * dt, 1800)
            velocityWidth = clamp(velocityWidth + accelerationWidth * dt, 700)
            x += velocityX * dt
            width = Math.max(16, width + velocityWidth * dt)
            remaining -= dt
        }
        if (Math.abs(targetX - x) < 0.12 && Math.abs(targetWidth - width) < 0.12
                && Math.abs(velocityX) < 0.8 && Math.abs(velocityWidth) < 0.8) snap()
    }
    FrameAnimation {
        running: root.visible && root.moving
        onTriggered: root.advance(frameTime)
    }
}
