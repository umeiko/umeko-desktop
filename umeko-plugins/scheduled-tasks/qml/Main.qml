pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../app/qml" as Umeko

Rectangle {
    id: root
    objectName: "scheduledTasksWidget"
    required property var sdk
    readonly property var c: sdk.colors
    readonly property bool readyForInteraction: sdk.active
    readonly property var frequencies: ["once", "interval"]
    readonly property var units: ["days", "hours", "minutes"]
    readonly property var taskColors: c.dark
        ? ["#82b4ff", "#56d3b6", "#f2ac63", "#c9a4fc", "#ed91b5", "#b5ce6f"]
        : ["#245eb5", "#00796b", "#a54f00", "#7745a8", "#a73868", "#546c14"]
    property var tasks: []
    property var runs: []
    property var targets: []
    property string systemZone: ""
    readonly property var targetOptions: {
        const rows = targets.slice()
        if (selected && selected.global && !rows.some(row => row.id === selected.target))
            rows.push({id:selected.target, name:selected.target_missing ? tr("无", "None") : selected.target_name})
        return rows
    }
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
        return ({running:tr("投递中", "Delivering"), delivered:tr("已投递", "Delivered"), completed:tr("已运行", "Completed"),
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
    function requestTargets() { if (!hostRequest) hostRequest = sdk.requestHost("scheduledTasks.targets", {}) }
    function edit(task) {
        requestTargets()
        selected = task
        error = ""
        page = "edit"
        taskName.text = task ? task.name : ""
        message.text = task ? task.message : ""
        frequency.currentIndex = task ? Math.max(0, frequencies.indexOf(task.schedule.frequency)) : 0
        const now = new Date()
        dateField.text = task && task.schedule.frequency !== "interval" ? task.schedule.first_date : Qt.formatDateTime(now, "yyyy-MM-dd")
        timeField.text = task && task.schedule.frequency !== "interval" ? task.schedule.local_time : Qt.formatDateTime(now, "HH:mm")
        zoneField.text = task ? task.schedule.zone : root.systemZone || "UTC"
        targetBox.currentIndex = task ? targetOptions.findIndex(p => p.id === task.target) : 0
        intervalValue.text = task && task.schedule.frequency === "interval" ? String(task.schedule.interval_value) : "1"
        intervalUnit.currentIndex = task && task.schedule.frequency === "interval" ? units.indexOf(task.schedule.interval_unit) : 1
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
    Component.onCompleted: { requestTargets(); call("list") }
    Connections {
        target: root.sdk
        function onActiveChanged() { if (root.readyForInteraction && root.page === "list") root.call("list") }
        function onResponse(id, value) {
            if (id !== root.pending) return
            root.pending = ""
            if (!value.ok) { root.error = value.error; root.requestTargets(); return }
            if (root.operation === "list") {
                if (value.result.time_zone) root.systemZone = value.result.time_zone
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
            if (value.result.targets) {
                const previous = root.targetOptions[targetBox.currentIndex]
                root.targets = value.result.targets
                if (value.result.time_zone) root.systemZone = value.result.time_zone
                targetBox.currentIndex = previous ? root.targetOptions.findIndex(p => p.id === previous.id) : root.selected ? root.targetOptions.findIndex(p => p.id === root.selected.target) : 0
            }
        }
    }
    Timer {
        interval: 2000; repeat: true; running: root.sdk.active && root.page !== "edit"
        onTriggered: root.page === "list" ? root.call("list") : root.call("history", {task_id:root.selected.id})
    }
    function frequencyLabel(task) {
        if (task.schedule.frequency === "once") return tr("单次定时", "One time")
        if (task.schedule.frequency !== "interval") return tr("旧版计划", "Legacy schedule")
        const label = [tr("天", "days"), tr("小时", "hours"), tr("分钟", "minutes")][units.indexOf(task.schedule.interval_unit)]
        return tr("每隔 ", "Every ") + task.schedule.interval_value + " " + label
    }
    readonly property real intervalSeconds: Number(intervalValue.text) * [86400, 3600, 60][intervalUnit.currentIndex]
    readonly property bool validInterval: intervalValue.text.trim().length > 0 && isFinite(intervalSeconds) && intervalSeconds >= 15
    function stateColor(code) {
        return code === "failed" || code === "interrupted" ? c.danger : code === "running" || code === "completed" || code === "delivered" ? c.accent : c.muted
    }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 16; spacing: 12
        RowLayout {
            Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 10
            Rectangle {
                width: Umeko.Theme.control(34); height: width; radius: 10; color: root.c.accentBg
                Umeko.Glyph { anchors.centerIn: parent; name: "clock"; color: root.c.accent; width: Umeko.Theme.icon(18); height: width }
            }
            ScheduleLabel {
                Layout.fillWidth: true; Layout.minimumWidth: 0
                text: root.page === "edit" ? (root.selected ? root.tr("编辑任务", "Edit task") : root.tr("新建任务", "New task"))
                    : root.page === "history" ? root.selected.name : root.tr("定时任务", "Scheduled tasks")
                font.pixelSize: Umeko.Theme.font(16); font.weight: Font.DemiBold
                wrapMode: Text.NoWrap; elide: Text.ElideRight
            }
            Umeko.ActionButton {
                objectName: "scheduledNewOrBack"
                text: root.page === "list" ? root.tr("新建任务", "New task") : root.tr("返回", "Back")
                primary: root.page === "list"; quiet: root.page !== "list"
                enabled: root.readyForInteraction && !root.pending && !root.hostRequest && (root.page !== "list" || root.tasks.length < 5)
                hint: root.page === "list" && root.tasks.length >= 5 ? root.tr("最多 5 个定时器（含全局），请先删除一个。", "Maximum 5 timers, including global timers. Delete one first.") : ""
                onClicked: {
                    if (root.page === "list") root.edit(null)
                    else { root.error = ""; root.page = "list"; root.call("list") }
                }
            }
        }
        ScheduleLabel {
            Layout.fillWidth: true; Layout.minimumWidth: 0; visible: root.page === "list"; color: root.c.muted
            text: root.tr("本会话（含全局） ", "This conversation (incl. global): ") + root.tasks.length + "/5 · " + root.tr("到点发送给选定 Agent，Umeko 需保持运行。", "Sends to the selected Agent. Keep Umeko running.")
        }
        Rectangle {
            Layout.fillWidth: true; Layout.minimumWidth: 0; implicitHeight: notice.implicitHeight + 20; radius: 8
            visible: !!root.error; color: root.c.accentBg; border.color: root.c.line
            ScheduleLabel { id: notice; anchors.fill: parent; anchors.margins: 10; text: root.error; color: root.c.danger }
        }
        StackLayout {
            Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.fillHeight: true
            currentIndex: root.page === "edit" ? 1 : root.page === "history" ? 2 : 0
            ListView {
                id: taskList
                model: root.tasks; spacing: 10; clip: true
                ScrollBar.vertical: ScheduleScrollBar {}
                Column {
                    anchors.centerIn: parent; width: parent.width - 32; spacing: 10; visible: !root.tasks.length
                    Umeko.Glyph { anchors.horizontalCenter: parent.horizontalCenter; name: "clock"; width: 28; height: 28; color: root.c.muted }
                    ScheduleLabel { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: root.tr("还没有定时任务", "No scheduled tasks yet"); font.pixelSize: Umeko.Theme.font(13); font.weight: Font.DemiBold }
                    ScheduleLabel { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: root.tr("新建任务，写好消息并设置运行时间。", "Create a task, write a prompt and choose when to run it."); color: root.c.muted }
                }
                delegate: Rectangle {
                    required property var modelData
                    width: taskList.width; height: taskCard.implicitHeight + 28
                    color: root.c.surface; border.color: root.c.line; radius: 12
                    ColumnLayout {
                        id: taskCard
                        anchors.fill: parent; anchors.margins: 14; spacing: 10
                        RowLayout {
                            Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 9
                            Rectangle {
                                objectName: "scheduledTaskAccent_" + modelData.id
                                width: 8; height: 20; radius: 4
                                color: root.taskColors[modelData.color_index % root.taskColors.length]
                            }
                            Umeko.Glyph {
                                objectName: "scheduledTaskGlobal_" + modelData.id
                                name: "globe"; visible: !!modelData.global
                                width: Umeko.Theme.icon(16); height: width; color: root.c.accent
                                Accessible.name: root.tr("全局计时器", "Global timer")
                                HoverHandler { id: globalHover }
                                Umeko.HoverTip { active: globalHover.hovered; text: root.tr("全局计时器", "Global timer") }
                            }
                            ScheduleLabel { Layout.fillWidth: true; Layout.minimumWidth: 0; text: modelData.name; font.pixelSize: Umeko.Theme.font(13); font.weight: Font.DemiBold; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                            Umeko.Toggle {
                                objectName: "scheduledTaskToggle_" + modelData.id
                                checked: !!modelData.enabled; enabled: root.readyForInteraction && !root.pending && !modelData.target_missing
                                Accessible.name: modelData.name + " · " + root.tr("启用计划", "Enable schedule")
                                onToggled: root.call("set_enabled", {task_id: modelData.id, enabled: checked})
                            }
                        }
                        ScheduleLabel { objectName: "scheduledTaskNext_" + modelData.id; Layout.fillWidth: true; Layout.minimumWidth: 0; text: root.frequencyLabel(modelData) + " · " + (modelData.enabled ? root.tr("下次运行 ", "Next run ") + root.stamp(modelData.next_at) : root.tr("未启用", "Inactive")); color: root.c.muted }
                        ScheduleLabel {
                            objectName: "scheduledTaskModelSlot_" + modelData.id
                            Layout.fillWidth: true; Layout.minimumWidth: 0
                            visible: !!modelData.model_oneshot
                            text: modelData.enabled ? root.tr("模型单次计时 · 到期后复用", "Agent one-shot · reusable after expiry") : root.tr("模型计时槽 · 可复用", "Agent timer slot · ready to reuse")
                            color: root.c.accent; font.pixelSize: Umeko.Theme.font(10)
                        }
                        ScheduleLabel { Layout.fillWidth: true; Layout.minimumWidth: 0; text: modelData.message; maximumLineCount: 2; elide: Text.ElideRight; color: root.c.muted }
                        RowLayout {
                            Layout.fillWidth: true
                            ScheduleLabel { objectName: "scheduledTaskTargetName_" + modelData.id; Layout.fillWidth: true; Layout.minimumWidth: 0; text: modelData.target_missing ? root.tr("无", "None") : modelData.target === "main" ? root.tr("本会话主 Agent", "This conversation’s main Agent") : modelData.target_name; color: root.c.muted; font.pixelSize: Umeko.Theme.font(10); wrapMode: Text.NoWrap; elide: Text.ElideMiddle }
                            Umeko.ActionButton { objectName: "scheduledTaskEdit_" + modelData.id; text: root.tr("编辑", "Edit"); quiet: true; glyph: "edit"; enabled: root.readyForInteraction && !root.pending; onClicked: root.edit(modelData) }
                            Umeko.ActionButton { objectName: "scheduledTaskHistory_" + modelData.id; text: root.tr("运行记录", "Runs"); quiet: true; enabled: root.readyForInteraction && !root.pending; onClicked: root.history(modelData) }
                        }
                    }
                }
            }
            ColumnLayout {
                Layout.minimumWidth: 0
                spacing: 12
                Flickable {
                    id: editor
                    objectName: "scheduledTaskEditor"
                    Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.fillHeight: true
                    clip: true; contentWidth: width; contentHeight: form.height; boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScheduleScrollBar {}
                    ColumnLayout {
                        id: form
                        width: editor.width - 10; spacing: 10
                        ScheduleLabel { text: root.tr("任务内容", "Task details"); color: root.c.muted; font.weight: Font.DemiBold }
                        ScheduleLabel { text: root.tr("任务名称", "Task name") }
                        Umeko.InputField { id: taskName; objectName: "scheduledTaskName"; Layout.fillWidth: true; Layout.minimumWidth: 0; maximumLength: 120; placeholderText: root.tr("例如：每日项目进度整理", "e.g. Daily project digest") }
                        ScheduleLabel { text: root.tr("预写消息", "Saved prompt") }
                        ScrollView {
                            Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredHeight: Umeko.Theme.control(120); clip: true
                            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                            ScrollBar.vertical: ScheduleScrollBar {}
                            TextArea {
                                id: message; objectName: "scheduledTaskPrompt"
                                wrapMode: TextEdit.Wrap; selectByMouse: true; textFormat: TextEdit.PlainText
                                font.family: Umeko.Theme.fontFamily; font.pixelSize: Umeko.Theme.font(13)
                                color: root.c.ink; placeholderTextColor: root.c.muted; selectionColor: root.c.accentBg; selectedTextColor: root.c.ink
                                padding: 12; placeholderText: root.tr("到点发送给 Pi 的完整消息", "Message to send to Pi at the scheduled time")
                                background: Rectangle { radius: 8; color: root.c.surface; border.color: message.activeFocus ? root.c.accent : root.c.line }
                            }
                        }
                        ScheduleLabel { text: root.tr("触发对象", "Send to") }
                        Umeko.Picker { id: targetBox; objectName: "scheduledTaskTarget"; Layout.fillWidth: true; Layout.minimumWidth: 0; model: root.targetOptions.map(p => p.id === "main" ? root.tr("本会话主 Agent", "This conversation’s main Agent") : p.name); font.family: Umeko.Theme.fontFamily }
                        ScheduleLabel {
                            Layout.fillWidth: true; Layout.minimumWidth: 0; color: root.c.muted; font.pixelSize: Umeko.Theme.font(10)
                            text: root.tr("沿用目标的模型与权限；仅显示本会话已关联的全局智能体。", "Uses the target’s model and permissions. Only connected global Agents are listed.")
                        }
                        Rectangle { Layout.fillWidth: true; Layout.minimumWidth: 0; height: 1; color: root.c.line; Layout.topMargin: 8; Layout.bottomMargin: 4 }
                        ScheduleLabel { text: root.tr("计划时间", "Schedule"); color: root.c.muted; font.weight: Font.DemiBold }
                        Umeko.Picker {
                            id: frequency; objectName: "scheduledTaskFrequency"; Layout.fillWidth: true; Layout.minimumWidth: 0; font.family: Umeko.Theme.fontFamily
                            model: [root.tr("单次定时", "One time"), root.tr("周期触发", "Repeat")]
                        }
                        RowLayout {
                            Layout.fillWidth: true; visible: frequency.currentIndex === 1
                            ScheduleLabel { text: root.tr("每隔", "Every") }
                            Umeko.InputField { id: intervalValue; objectName: "scheduledTaskInterval"; Layout.fillWidth: true; Layout.minimumWidth: 0; text: "1"; placeholderText: "0.5"; inputMethodHints: Qt.ImhFormattedNumbersOnly }
                            Umeko.Picker { id: intervalUnit; objectName: "scheduledTaskIntervalUnit"; Layout.preferredWidth: Umeko.Theme.control(100); model: [root.tr("天", "days"), root.tr("小时", "hours"), root.tr("分钟", "minutes")] }
                        }
                        ScheduleLabel {
                            visible: frequency.currentIndex === 1; Layout.fillWidth: true; Layout.minimumWidth: 0
                            color: root.validInterval ? root.c.muted : root.c.danger
                            text: root.tr("支持小数，最短 15 秒（0.25 分钟）；启用后等待一个周期首次触发。", "Decimals supported; minimum 15 seconds (0.25 minutes). First trigger is one interval after enabling.")
                        }
                        GridLayout {
                            Layout.fillWidth: true; Layout.minimumWidth: 0; visible: frequency.currentIndex === 0; columns: editor.width >= Umeko.Theme.control(340) ? 2 : 1; columnSpacing: 10; rowSpacing: 10
                            ColumnLayout {
                                Layout.fillWidth: true; Layout.minimumWidth: 0
                                ScheduleLabel { text: root.tr("起始日期", "First date") }
                                Umeko.InputField { id: dateField; objectName: "scheduledTaskDate"; Layout.fillWidth: true; Layout.minimumWidth: 0; placeholderText: "YYYY-MM-DD" }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true; Layout.minimumWidth: 0
                                ScheduleLabel { text: root.tr("时间", "Time") }
                                Umeko.InputField { id: timeField; objectName: "scheduledTaskTime"; Layout.fillWidth: true; Layout.minimumWidth: 0; placeholderText: "HH:MM" }
                            }
                        }
                        ScheduleLabel { visible: frequency.currentIndex === 0; text: root.tr("时区", "Time zone") }
                        Umeko.InputField { id: zoneField; objectName: "scheduledTaskZone"; visible: frequency.currentIndex === 0; Layout.fillWidth: true; Layout.minimumWidth: 0; placeholderText: "Asia/Shanghai" }
                    }
                }
                Rectangle { Layout.fillWidth: true; Layout.minimumWidth: 0; height: 1; color: root.c.line }
                RowLayout {
                    Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 10
                    Umeko.ActionButton { objectName: "scheduledTaskDelete"; visible: !!root.selected; quiet: true; destructive: true; glyph: "trash"; hint: root.tr("删除定时器；已投递消息不会撤回", "Delete timer; delivered messages are not retracted"); enabled: root.readyForInteraction && !root.pending; onClicked: root.call("delete", {task_id: root.selected.id}) }
                    Umeko.Toggle { id: enabledField; objectName: "scheduledTaskEnabled"; Accessible.name: root.tr("启用计划", "Enable schedule") }
                    ScheduleLabel { Layout.fillWidth: true; Layout.minimumWidth: 0; text: root.tr("启用计划", "Enable schedule") }
                    Umeko.ActionButton {
                        objectName: "scheduledTaskSave"; text: root.tr("保存", "Save"); primary: true
                        enabled: root.readyForInteraction && !root.pending && !!taskName.text.trim() && !!message.text.trim() && targetBox.currentIndex >= 0 && (frequency.currentIndex === 0 || root.validInterval)
                        onClicked: {
                            root.error = ""
                            root.call("save", {task_id: root.selected ? root.selected.id : null, name: taskName.text,
                                message: message.text, target: root.targetOptions[targetBox.currentIndex].id,
                                schedule: frequency.currentIndex === 0 ? {frequency: "once", first_date: dateField.text.trim(), local_time: timeField.text.trim(), zone: zoneField.text.trim()} : {frequency: "interval", interval_value: intervalValue.text.trim(), interval_unit: root.units[intervalUnit.currentIndex]},
                                enabled: enabledField.checked})
                        }
                    }
                }
            }
            ColumnLayout {
                Layout.minimumWidth: 0
                spacing: 12
                RowLayout {
                    Layout.fillWidth: true
                    ScheduleLabel { Layout.fillWidth: true; Layout.minimumWidth: 0; text: root.tr("运行记录", "Run history"); color: root.c.muted }
                    Umeko.ActionButton {
                        objectName: "scheduledTaskRunNow"; text: root.tr("立即运行", "Run now"); primary: true
                        enabled: root.readyForInteraction && root.page === "history" && !root.pending && !root.selected.target_missing && !root.runs.some(r => r.state === "running")
                        onClicked: { root.error = ""; root.call("run", {task_id: root.selected.id}) }
                    }
                }
                ListView {
                    id: runList
                    Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.fillHeight: true; model: root.runs; spacing: 10; clip: true
                    ScrollBar.vertical: ScheduleScrollBar {}
                    ScheduleLabel { anchors.centerIn: parent; width: parent.width - 32; horizontalAlignment: Text.AlignHCenter; visible: !root.runs.length; text: root.tr("还没有运行记录", "No runs yet"); color: root.c.muted }
                    delegate: Rectangle {
                        required property var modelData
                        width: runList.width; height: runCard.implicitHeight + 28; radius: 12; color: root.c.surface; border.color: root.c.line
                        ColumnLayout {
                            id: runCard
                            anchors.fill: parent; anchors.margins: 14; spacing: 10
                            RowLayout {
                                Layout.fillWidth: true
                                Rectangle {
                                    color: root.c.accentBg; radius: 5; implicitWidth: stateLabel.implicitWidth + 14; implicitHeight: stateLabel.implicitHeight + 8
                                    ScheduleLabel { id: stateLabel; anchors.centerIn: parent; text: root.status(modelData.state); color: root.stateColor(modelData.state); font.pixelSize: Umeko.Theme.font(10); font.weight: Font.DemiBold }
                                }
                                ScheduleLabel { Layout.fillWidth: true; Layout.minimumWidth: 0; text: modelData.scheduled_at ? root.tr("按计划", "Scheduled") : root.tr("手动运行", "Manual"); color: root.c.muted; font.pixelSize: Umeko.Theme.font(10) }
                            }
                            ScheduleLabel { Layout.fillWidth: true; Layout.minimumWidth: 0; text: root.stamp(modelData.scheduled_at || modelData.started_at); color: root.c.muted; font.pixelSize: Umeko.Theme.font(10) }
                            ScheduleLabel { Layout.fillWidth: true; Layout.minimumWidth: 0; visible: !!modelData.detail; text: root.detail(modelData.detail); color: modelData.state === "failed" ? root.c.danger : root.c.muted }
                            ScheduleLabel { Layout.fillWidth: true; Layout.minimumWidth: 0; text: modelData.snapshot.message; maximumLineCount: 2; elide: Text.ElideRight }
                            Flow {
                                Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 6
                                Umeko.ActionButton { objectName: "scheduledRunPrompt_" + modelData.id; text: root.tr("查看消息", "View prompt"); quiet: true; onClicked: { root.selectedRun = modelData; promptDialog.open() } }
                                Umeko.ActionButton { text: root.tr("打开对象", "Open target"); quiet: true; onClicked: root.hostRequest = root.sdk.requestHost("scheduledTasks.openTarget", {target: modelData.snapshot.target || "main"}) }
                            }
                        }
                    }
                }
            }
        }
    }
    Umeko.PidPopup {
        id: promptDialog
        objectName: "scheduledPromptDialog"
        anchors.centerIn: parent
        width: Math.min(560, root.width - 24); height: Math.min(root.height - 24, Umeko.Theme.control(420))
        ColumnLayout {
            anchors.fill: parent; spacing: 16
            RowLayout {
                Layout.fillWidth: true
                ScheduleLabel { Layout.fillWidth: true; Layout.minimumWidth: 0; text: root.tr("本次运行的消息", "Prompt used for this run"); font.pixelSize: Umeko.Theme.font(14); font.weight: Font.DemiBold }
                Umeko.ActionButton { objectName: "scheduledPromptClose"; text: root.tr("关闭", "Close"); quiet: true; onClicked: promptDialog.close() }
            }
            ScrollView {
                Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.fillHeight: true; clip: true
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ScrollBar.vertical: ScheduleScrollBar {}
                TextArea {
                    text: root.selectedRun ? root.selectedRun.snapshot.message : ""
                    readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText
                    font.family: Umeko.Theme.fontFamily; font.pixelSize: Umeko.Theme.font(12); color: root.c.ink
                    selectionColor: root.c.accentBg; selectedTextColor: root.c.ink; padding: 0; background: null
                }
            }
        }
    }
}
