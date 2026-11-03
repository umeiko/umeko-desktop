import QtQuick
import "PidTrajectory.js" as Pid

Item {
    id: root
    property Item target
    readonly property real kp: Pid.kp
    readonly property real ki: Pid.ki
    readonly property real kd: Pid.kd
    readonly property bool moving: animation.running
    property real destination: 0
    property var trajectory: null
    property real startedAt: 0
    width: 0; height: 0

    function currentState() {
        return trajectory ? Pid.sample(trajectory, Date.now() - startedAt) : [destination, 0, 0]
    }
    function snapTo(value) {
        animation.stop()
        trajectory = null
        destination = value
        if (target) target.y = value
    }
    function moveTo(value) {
        if (value === destination) return
        const state = currentState()
        animation.stop()
        destination = value
        trajectory = Pid.plan(state[0], state[1], state[2], value)
        target.y = trajectory.start
        animation.from = trajectory.start
        animation.to = trajectory.end
        animation.duration = trajectory.duration
        animation.easing.bezierCurve = trajectory.curve
        startedAt = Date.now()
        animation.start()
    }
    YAnimator {
        id: animation
        objectName: "sidebarSelectionAnimator"
        target: root.target
        easing.type: Easing.BezierSpline
        onFinished: {
            root.trajectory = null
            root.target.y = root.destination
        }
    }
}
