import QtQuick

Item {
    id: root
    property var status: ({})
    property bool compact: false
    property bool unread: false
    readonly property string state: status.state || ""
    readonly property bool live: state === "running" || state === "stopping"
    readonly property string label: I18n.t(({running: "运行中", stopping: "正在停止", finished: "已完成", failed: "失败", stopped: "已停止", unread: "未读"})[state] || "")
    property double clock: Date.now()
    readonly property int seconds: Math.max(0, Math.floor(live && status.startedAt ? (clock - status.startedAt) / 1000 : status.elapsed || 0))
    readonly property string duration: seconds >= 60 ? Math.floor(seconds / 60) + "m " + seconds % 60 + "s" : seconds + "s"
    readonly property string text: label + (unread && state !== "unread" ? " · " + I18n.t("未读") : "") + (!compact && (live || typeof status.elapsed === "number") ? " · " + duration : "")
    readonly property color tint: state === "failed" ? Theme.danger : live || unread ? Theme.accent : Theme.muted
    implicitWidth: statusRow.implicitWidth
    implicitHeight: Theme.control(24)
    visible: state.length > 0
    Timer { interval: 250; repeat: true; running: root.live && root.visible; onTriggered: root.clock = Date.now() }
    onStatusChanged: clock = Date.now()
    Row {
        id: statusRow; spacing: 6; anchors.verticalCenter: parent.verticalCenter
        ActivitySpinner { objectName: "taskStatusSpinner"; visible: root.live; running: visible; width: Theme.icon(13); height: width; anchors.verticalCenter: parent.verticalCenter; color: root.tint }
        Glyph { objectName: "taskStatusIcon"; visible: !root.live; name: root.state === "finished" ? "check" : root.state === "failed" ? "x" : root.state === "unread" ? "chat" : "stop"; width: Theme.icon(13); height: width; anchors.verticalCenter: parent.verticalCenter; color: root.tint }
        Text { font.family: Theme.fontFamily; objectName: "taskStatusText"; text: root.text; color: root.tint; font.pixelSize: Theme.font(root.compact ? 10 : 12); font.weight: root.unread ? Font.DemiBold : Font.Normal }
    }
    Accessible.role: Accessible.StaticText
    Accessible.name: text
}
