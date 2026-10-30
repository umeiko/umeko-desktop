import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    required property var sdk
    color: sdk.colors.surface
    property var rows: []
    property string status: ""
    property string job: ""
    property var requests: ({})
    function request(operation,args) {
        if (typeof sdk.requestHost !== "function" || !sdk.hostCapabilities || !sdk.hostCapabilities.operations[operation]) { status="请升级到支持 Widget Host API v1 的版本"; return }
        const id=sdk.requestHost(operation,args || {})
        if (id) requests[id]=operation
        else status="宿主忙碌或当前 Widget 不可用"
    }
    component HostButton: Button {
        id: control
        padding: 10
        background: Rectangle { radius: 7; color: control.hovered ? root.sdk.colors.hover : root.sdk.colors.accentBg; border.color: root.sdk.colors.line }
        contentItem: Text { text: control.text; color: root.sdk.colors.ink; font.pixelSize: 12*root.sdk.scale; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
    }
    Component.onCompleted: request("pi.status")
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 20; spacing: 14
        Text { text: "Pi 扩展管理 · SDK 示例"; color: sdk.colors.ink; font.pixelSize: 18*sdk.scale }
        RowLayout {
            HostButton { objectName: "piWidgetScan"; text: "刷新扩展列表"; enabled: !root.job; onClicked: root.request("pi.scan") }
            HostButton { text: "重新读取状态"; onClicked: root.request("pi.status") }
        }
        Text { objectName: "piWidgetSummary"; Layout.fillWidth: true; text: root.status; color: sdk.colors.muted; wrapMode: Text.Wrap; textFormat: Text.PlainText }
        ListView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true; reuseItems: true; model: root.rows; spacing: 8
            delegate: RowLayout {
                required property var modelData
                width: ListView.view.width
                Text { Layout.fillWidth: true; text: modelData.name + " · " + modelData.scope; textFormat: Text.PlainText; elide: Text.ElideRight; color: root.sdk.colors.ink }
                HostButton { text: modelData.enabled ? "停用" : "启用"; enabled: !root.job; onClicked: root.request("pi.enable",{id:modelData.id,enabled:!modelData.enabled}) }
            }
        }
    }
    Timer { interval: 400; repeat: true; running: root.sdk.active && !!root.job; onTriggered: root.request("pi.job",{id:root.job}) }
    Connections {
        ignoreUnknownSignals: true
        target: root.sdk
        function onHostResponse(id,value) {
            if (!root.requests[id]) return
            const operation=root.requests[id]; delete root.requests[id]
            if (!value.ok) { root.status=value.error || value.status; root.job=""; return }
            if (value.jobId) { root.job=value.jobId; root.status="宿主任务已接受，等待实际结果…"; return }
            if (operation==="pi.status") {
                root.rows=value.result.extensions || []
                root.status=value.result.contextCurrent ? "共 " + value.result.total + " 项，当前显示前 " + root.rows.length + " 项" : "当前工作区尚未扫描，请刷新列表"
            } else if (operation==="pi.job" && (value.jobs || []).length) {
                const job=value.jobs[0]
                if (job.status==="done" || job.status==="failed") {
                    root.job=""; root.status=job.result.error || "宿主任务已完成"
                    if (job.status==="done") root.request("pi.status")
                }
            }
        }
    }
}
