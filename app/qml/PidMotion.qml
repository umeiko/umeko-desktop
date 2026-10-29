import QtQuick

Item {
    id: root
    property rect targetRect: Qt.rect(0, 0, 0, 0)
    property rect value: Qt.rect(0, 0, 0, 0)
    property var velocity: [0, 0, 0, 0]
    property var integral: [0, 0, 0, 0]
    property bool moving: false
    property bool ready: false
    width: 0; height: 0
    Component.onCompleted: { ready = true; snap() }
    onTargetRectChanged: if (ready) moving = true
    function snapTo(rect) { value = rect; velocity = [0,0,0,0]; integral = [0,0,0,0]; moving = false }
    function snap() { snapTo(targetRect) }
    function clamp(value, limit) { return Math.max(-limit, Math.min(limit, value)) }
    function advance(seconds) {
        const target = [targetRect.x,targetRect.y,targetRect.width,targetRect.height]
        const current = [value.x,value.y,value.width,value.height]
        let remaining = Math.min(Math.max(seconds, 0), 0.05)
        while (remaining > 0.000001) {
            const dt = Math.min(remaining, 1/240)
            for (let i=0;i<4;i++) {
                const error = target[i]-current[i]
                integral[i] = clamp(integral[i]+error*dt,60)*Math.exp(-3*dt)
                velocity[i] = clamp(velocity[i]+clamp(280*error+60*integral[i]-20*velocity[i],30000)*dt,1800)
                current[i] += velocity[i]*dt
            }
            remaining -= dt
        }
        value = Qt.rect(current[0],current[1],Math.max(1,current[2]),Math.max(1,current[3]))
        if (current.every((position,i) => Math.abs(target[i]-position)<0.15 && Math.abs(velocity[i])<0.8)) snap()
    }
    FrameAnimation { running: root.moving; onTriggered: root.advance(frameTime) }
}
