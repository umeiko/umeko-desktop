pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "scheduledTasksWidget"
    required property var sdk
    readonly property var c: sdk.colors
    readonly property bool readyForInteraction: sdk.active
    readonly property var frequencies: ["once", "daily", "weekly", "weekdays"]
    property var tasks: []
    property var runs: []
    property var profiles: []
    property var selected: null
    property var selectedRun: null
    property string page: "list"
    property string pending: ""
    property string operation: ""
    property string hostRequest: ""
    property string error: ""
    color: c.surface
    clip: true

    function tr(zh, en) { return sdk.language.indexOf("zh") === 0 ? zh : en }
    function status(code) {
        return ({running:tr("运行中", "Running"), completed:tr("已运行", "Completed"),
                 failed:tr("失败", "Failed"), cancelled:tr("已停止", "Cancelled"),
                 interrupted:tr("已中断", "Interrupted"), skipped:tr("已跳过", "Skipped"),
                 missed:tr("已错过", "Missed")})[code] || code
    }
    function detail(code) {
        return ({previous_run_active:tr("上一次运行仍未结束", "The previous run is still active"),
                 outside_dispatch_window:tr("应用未能在计划时间触发", "Umeko missed the scheduled time")})[code] || code || ""
    }
    function stamp(value) { return value ? Qt.formatDateTime(new Date(value * 1000), "yyyy-MM-dd HH:mm:ss") : "—" }
    function call(method, args) {
        if (pending || !sdk.active) return
        operation = method
        pending = sdk.call(method, args || {})
        if (!pending) error = tr("服务暂不可用。", "The service is unavailable.")
    }
    function requestProfiles() { hostRequest = sdk.requestHost("scheduledTasks.profiles", {}) }
    function edit(task) {
        selected = task
        error = ""
        page = "edit"
        taskName.text = task ? task.name : ""
        message.text = task ? task.message : ""
        frequency.currentIndex = task ? frequencies.indexOf(task.schedule.frequency) : 0
        dateField.text = task ? task.schedule.first_date : new Date().toISOString().slice(0, 10)
        timeField.text = task ? task.schedule.local_time : new Date().toISOString().slice(11, 16)
        zoneField.text = task ? task.schedule.zone : "UTC"
        profileBox.currentIndex = task ? profiles.findIndex(p => p.name === task.profile) : (profiles.length ? 0 : -1)
        enabledField.checked = task ? !!task.enabled : false
    }
    function history(task) {
        selected = task
        error = ""
        page = "history"
        runs = []
        selectedRun = null
        call("history", {task_id: task.id})
    }
    Component.onCompleted: { requestProfiles(); call("list") }
    Connections {
        target: root.sdk
        function onActiveChanged() { if (root.readyForInteraction && root.page === "list") root.call("list") }
        function onResponse(id, value) {
            if (id !== root.pending) return
            root.pending = ""
            if (!value.ok) { root.error = value.error; return }
            if (root.operation === "list") {
                if (JSON.stringify(root.tasks) !== JSON.stringify(value.result.tasks)) root.tasks = value.result.tasks
            } else if (root.operation === "history") {
                if (JSON.stringify(root.runs) !== JSON.stringify(value.result.runs)) root.runs = value.result.runs
            }
            else if (root.operation === "run" || root.operation === "cancel")
                root.call("history", {task_id:root.selected.id})
            else {
                root.page = "list"
                root.call("list")
            }
        }
        function onHostResponse(id, value) {
            if (id !== root.hostRequest) return
            root.hostRequest = ""
            if (!value.ok) { root.error = value.error; return }
            if (value.result.profiles) root.profiles = value.result.profiles
        }
    }
    Timer {
        interval: 2000; repeat: true; running: root.sdk.active && root.page !== "edit"
        onTriggered: root.page === "list" ? root.call("list") : root.call("history", {task_id:root.selected.id})
    }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 18; spacing: 12
        RowLayout {
            Layout.fillWidth: true; Layout.minimumWidth: 0
            Label {
                Layout.fillWidth: true; Layout.minimumWidth: 0
                text: root.page === "edit" ? (root.selected ? root.tr("编辑定时任务", "Edit task") : root.tr("新建定时任务", "New scheduled task"))
                    : root.page === "history" ? root.selected.name : root.tr("定时任务", "Scheduled Tasks")
                textFormat: Text.PlainText; color: root.c.ink; font.pixelSize: 19; font.bold: true; elide: Text.ElideRight
            }
            Button {
                objectName: "scheduledNewOrBack"
                text: root.page === "list" ? root.tr("新建任务", "New task") : root.tr("返回", "Back")
                enabled: root.readyForInteraction && !root.pending
                onClicked: {
                    if (root.page === "list") root.edit(null)
                    else { root.error = ""; root.page = "list"; root.call("list") }
                }
            }
        }
        Label {
            Layout.fillWidth: true; Layout.minimumWidth: 0; visible: root.page === "list"
            text: root.tr("Umeko 运行时按计划启动独立 Pi 会话。", "Schedules start separate Pi conversations while Umeko is running.")
            wrapMode: Text.WordWrap; color: root.c.muted
        }
        Label { Layout.fillWidth: true; Layout.minimumWidth: 0; visible: !!root.error; text: root.error; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: root.c.danger }
        StackLayout {
            Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.fillHeight: true
            currentIndex: root.page === "edit" ? 1 : root.page === "history" ? 2 : 0
            ListView {
                model: root.tasks; spacing: 8; clip: true
                Label {
                    anchors.centerIn: parent; visible: root.tasks.length === 0
                    text: root.tr("还没有定时任务", "No scheduled tasks yet"); color: root.c.muted
                }
                delegate: Rectangle {
                    required property var modelData
                    width: ListView.view.width; height: row.implicitHeight + 24
                    color: root.c.bg; border.color: root.c.line; radius: 8
                    RowLayout {
                        id: row
                        anchors.fill: parent; anchors.margins: 12
                        ColumnLayout {
                            Layout.fillWidth: true; Layout.minimumWidth: 0
                            Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: modelData.name; textFormat: Text.PlainText; color: root.c.ink; font.bold: true; elide: Text.ElideRight }
                            Label {
                                Layout.fillWidth: true; Layout.minimumWidth: 0
                                text: modelData.enabled ? root.tr("下次运行 · ", "Next run · ") + modelData.next_label
                                    : root.tr("未启用", "Inactive")
                                color: root.c.muted; wrapMode: Text.Wrap
                            }
                        }
                        Button {
                            text: modelData.enabled ? root.tr("暂停", "Pause") : root.tr("编辑", "Edit")
                            enabled: root.readyForInteraction && !root.pending
                            onClicked: modelData.enabled ? root.call("set_enabled", {task_id:modelData.id,enabled:false}) : root.edit(modelData)
                        }
                        Button { visible: !!modelData.enabled; text: root.tr("编辑", "Edit"); enabled: root.readyForInteraction && !root.pending; onClicked: root.edit(modelData) }
                        Button { objectName: "scheduledTaskHistory"; text: root.tr("运行记录", "Runs"); enabled: root.readyForInteraction && !root.pending; onClicked: root.history(modelData) }
                    }
                }
            }
            Flickable {
                id: editor
                clip: true
                contentWidth: width
                contentHeight: form.height
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}
                ColumnLayout {
                    id: form
                    width: editor.width - 6; spacing: 9
                    Label { text: root.tr("任务名称", "Task name"); color: root.c.ink }
                    TextField { id: taskName; objectName: "scheduledTaskName"; Layout.fillWidth: true; Layout.minimumWidth: 0; maximumLength: 120 }
                    Label { text: root.tr("预写消息", "Saved prompt"); color: root.c.ink }
                    ScrollView {
                        Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredHeight: 130
                        TextArea { id: message; objectName: "scheduledTaskPrompt"; wrapMode: TextEdit.Wrap; placeholderText: root.tr("到点发送给 Pi 的完整消息", "Message to send to Pi at the scheduled time") }
                    }
                    Label { text: root.tr("会话配置", "Session profile"); color: root.c.ink }
                    ComboBox { id: profileBox; objectName: "scheduledTaskProfile"; Layout.fillWidth: true; Layout.minimumWidth: 0; model: root.profiles; textRole: "name" }
                    Label {
                        Layout.fillWidth: true; Layout.minimumWidth: 0; wrapMode: Text.WrapAnywhere; color: root.c.muted; textFormat: Text.PlainText
                        text: profileBox.currentIndex >= 0 && root.profiles[profileBox.currentIndex]
                            ? root.profiles[profileBox.currentIndex].workspace + " · " + root.profiles[profileBox.currentIndex].model
                            : root.tr("暂无可用配置。请参阅此 Widget 的说明。", "No approved profiles. See this Widget’s documentation.")
                    }
                    Label { text: root.tr("计划", "Schedule"); color: root.c.ink }
                    ComboBox {
                        id: frequency; objectName: "scheduledTaskFrequency"; Layout.fillWidth: true; Layout.minimumWidth: 0
                        model: [root.tr("单次","Once"),root.tr("每天","Daily"),root.tr("每周","Weekly"),root.tr("工作日","Weekdays")]
                    }
                    RowLayout {
                        Layout.fillWidth: true; Layout.minimumWidth: 0
                        ColumnLayout {
                            Layout.fillWidth: true; Layout.minimumWidth: 0
                            Label { text: root.tr("起始日期", "First date"); color: root.c.ink }
                            TextField { id: dateField; objectName: "scheduledTaskDate"; Layout.fillWidth: true; Layout.minimumWidth: 0; placeholderText: "YYYY-MM-DD" }
                        }
                        ColumnLayout {
                            Layout.preferredWidth: 84
                            Label { text: root.tr("时间", "Time"); color: root.c.ink }
                            TextField { id: timeField; objectName: "scheduledTaskTime"; Layout.fillWidth: true; Layout.minimumWidth: 0; placeholderText: "HH:MM" }
                        }
                    }
                    Label { text: root.tr("时区（例如 Asia/Shanghai）", "Time zone (e.g. Asia/Shanghai)"); color: root.c.ink }
                    TextField { id: zoneField; objectName: "scheduledTaskZone"; Layout.fillWidth: true; Layout.minimumWidth: 0 }
                    CheckBox { id: enabledField; objectName: "scheduledTaskEnabled"; text: root.tr("启用计划", "Enable schedule") }
                    Button {
                        objectName: "scheduledTaskSave"
                        text: root.tr("保存", "Save")
                        enabled: root.readyForInteraction && !root.pending && !!taskName.text.trim() && !!message.text.trim() && profileBox.currentIndex >= 0
                        onClicked: {
                            root.error = ""
                            root.call("save", {task_id:root.selected ? root.selected.id : null, name:taskName.text,
                                message:message.text, profile:root.profiles[profileBox.currentIndex].name,
                                schedule:{frequency:root.frequencies[frequency.currentIndex],first_date:dateField.text.trim(),
                                          local_time:timeField.text.trim(),zone:zoneField.text.trim()},
                                enabled:enabledField.checked})
                        }
                    }
                }
            }
            ColumnLayout {
                RowLayout {
                    Layout.fillWidth: true; Layout.minimumWidth: 0
                    Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: root.tr("运行记录", "Run history"); color: root.c.muted }
                    Button {
                        objectName: "scheduledTaskRunNow"
                        text: root.tr("立即运行", "Run now")
                        enabled: root.readyForInteraction && root.page === "history" && !root.pending && !root.runs.some(r => r.state === "running")
                        onClicked: { root.error = ""; root.call("run", {task_id:root.selected.id}) }
                    }
                }
                ListView {
                    Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.fillHeight: true; model: root.runs; spacing: 8; clip: true
                    delegate: Rectangle {
                        required property var modelData
                        width: ListView.view.width; height: runRow.implicitHeight + 24
                        color: root.c.bg; border.color: root.c.line; radius: 8
                        ColumnLayout {
                            id: runRow
                            anchors.fill: parent; anchors.margins: 12
                            Label { text: root.status(modelData.state) + " · "
                                   + (modelData.scheduled_at ? root.tr("按计划", "Scheduled") : root.tr("手动运行", "Manual"))
                                   + " · " + root.stamp(modelData.scheduled_at || modelData.started_at); color: root.c.ink; font.bold: true }
                            Label {
                                Layout.fillWidth: true; Layout.minimumWidth: 0; visible: !!modelData.detail; text: root.detail(modelData.detail)
                                textFormat: Text.PlainText; wrapMode: Text.Wrap; color: root.c.muted
                            }
                            Label {
                                Layout.fillWidth: true; Layout.minimumWidth: 0; text: modelData.snapshot.message; textFormat: Text.PlainText
                                maximumLineCount: 2; elide: Text.ElideRight; wrapMode: Text.Wrap; color: root.c.muted
                            }
                            RowLayout {
                                Button {
                                    text: root.tr("查看消息", "View prompt")
                                    onClicked: { root.selectedRun = modelData; promptDialog.open() }
                                }
                                Button {
                                    text: root.tr("打开会话", "Open conversation")
                                    visible: !!modelData.session_id
                                    onClicked: root.hostRequest = root.sdk.requestHost("scheduledTasks.openSession", {session_id:modelData.session_id})
                                }
                                Button {
                                    text: root.tr("停止", "Stop")
                                    visible: modelData.state === "running"; enabled: root.readyForInteraction && !root.pending
                                    onClicked: root.call("cancel", {run_id:modelData.id})
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    Dialog {
        id: promptDialog
        anchors.centerIn: parent
        width: parent.width - 30
        modal: true
        title: root.tr("本次运行的消息", "Prompt used for this run")
        standardButtons: Dialog.Close
        ScrollView {
            implicitHeight: Math.min(340, promptText.implicitHeight + 20)
            contentWidth: availableWidth
            Label {
                id: promptText
                width: parent.width
                text: root.selectedRun ? root.selectedRun.snapshot.message : ""
                textFormat: Text.PlainText; wrapMode: Text.Wrap
            }
        }
    }
}
