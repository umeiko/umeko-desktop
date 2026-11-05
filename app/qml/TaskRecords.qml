import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: panel
    objectName: "taskRecordsPanel"
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(1040, parent.width - 36)
    height: Math.min(690, parent.height - 36)
    padding: 20
    modal: true
    focus: true
    background: Rectangle { radius: 14; color: Theme.surface; border.color: Theme.line }

    readonly property var records: backend.taskRecords
    property var tasks: []
    property string taskId: ""
    readonly property var task: tasks.find(row => row.id === taskId) || null
    property var attempts: []
    property int attemptId: 0
    readonly property var attempt: attempts.find(row => row.id === attemptId) || null
    property var detail: null
    property int request: 0
    property bool loading: false
    property bool creating: false
    property bool confirmingDelete: false

    function state(code) {
        return ({
            draft: I18n.t("未开始"), running: I18n.t("执行中"), pending: I18n.t("待恢复"),
            failed: I18n.t("失败"), finished: I18n.t("执行结束"), accepted: I18n.t("已验收"),
            available: I18n.t("可用"), missing: I18n.t("已移动或缺失"), changed: I18n.t("已变化"),
            unavailable: I18n.t("不可用"), unsupported: I18n.t("无法核验此类型"), unverified: I18n.t("未记录版本")
        })[code] || code || ""
    }

    function refresh() {
        tasks = records.listTasks()
        selectTask(task ? taskId : tasks.length ? tasks[0].id : "", false)
    }

    function selectTask(id, resetAttempt) {
        taskId = id
        confirmingDelete = false
        attempts = id ? records.listAttempts(id) : []
        if (resetAttempt || !attempts.some(row => row.id === attemptId))
            attemptId = attempts.length ? attempts[0].id : 0
        loadAttempt(false)
    }

    function loadAttempt(verify) {
        if (!verify)
            detail = null
        ++request
        loading = attemptId > 0
        if (loading)
            records.inspect(request, taskId, attemptId, verify)
    }

    function show() {
        creating = false
        attemptId = 0
        refresh()
        open()
    }

    function detailsText(data) {
        const lines = [
            I18n.t("实际工作目录") + "\n" + data.cwd,
            I18n.t("会话引用") + "\n" + (data.session_id || "—") + " · " + state(data.session_state)
                + (data.session_file ? "\n" + data.session_file : ""),
            I18n.t("尝试开始时间") + " · " + data.started
        ]
        if (data.ended) lines.push(I18n.t("尝试结束时间") + " · " + data.ended)
        if (data.reason) lines.push(I18n.t(data.reason))
        if (data.accepted) lines.push(I18n.t("用户已验收") + " · " + data.accepted)
        for (const item of data.files) {
            const kind = item.source === "input" ? I18n.t("输入文件") :
                item.source === "generated" ? I18n.t("生成并交付") : I18n.t("已投递")
            lines.push(kind + " · " + state(item.state) + "\n" + item.path
                + (item.version ? "\n" + I18n.t("版本") + " · " + item.version : "")
                + (item.checked ? "\n" + I18n.t("上次核验") + " · " + state(item.check_result) + " · " + item.checked : ""))
        }
        if (data.steps.length) {
            lines.push(data.steps.map(step => {
                if (step.kind === "message")
                    return I18n.t("消息引用") + " · " + step.detail + " · " + step.key
                if (step.kind === "session")
                    return I18n.t("会话引用") + " · " + step.key + " · " + state(step.state) + " · " + step.detail
                if (step.kind === "delivery_error")
                    return I18n.t("未能交付的条目") + " · " + step.detail + " · " + step.key
                return I18n.t("工具步骤") + " · " + step.detail + " · " + step.key
            }).join("\n"))
        }
        return lines.join("\n\n")
    }

    Connections {
        target: panel.records
        function onChanged() { if (panel.opened) panel.refresh() }
        function onDetailsReady(token, value) {
            if (token !== panel.request) return
            panel.loading = false
            panel.detail = value.id ? value : null
        }
    }

    component DetailText: TextArea {
        textFormat: TextEdit.PlainText
        readOnly: true
        selectByMouse: true
        wrapMode: TextEdit.Wrap
        color: Theme.ink
        font.family: Theme.fontFamily
        background: Rectangle { radius: 8; color: Theme.bg }
    }

    contentItem: ColumnLayout {
        spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Text { text: I18n.t("任务记录"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(18, visible); font.weight: Font.DemiBold }
            Item { Layout.fillWidth: true }
            ActionButton {
                text: I18n.t("解除下条消息关联")
                visible: panel.records.selected !== ""
                onClicked: panel.records.clear()
            }
            ActionButton {
                objectName: "newTaskRecord"
                text: I18n.t("新建任务")
                onClicked: { panel.creating = true; objective.forceActiveFocus() }
            }
            ActionButton { glyph: "x"; quiet: true; hint: I18n.t("关闭"); onClicked: panel.close() }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 14

            ListView {
                Layout.preferredWidth: Math.min(240, panel.availableWidth * 0.31)
                Layout.fillHeight: true
                clip: true
                spacing: 4
                model: panel.tasks
                ScrollBar.vertical: ScrollBar {}
                delegate: ItemDelegate {
                    id: taskRow
                    required property var modelData
                    width: ListView.view.width
                    highlighted: modelData.id === panel.taskId && !panel.creating
                    onClicked: { panel.creating = false; panel.selectTask(modelData.id, true) }
                    background: Rectangle { radius: 8; color: taskRow.highlighted ? Theme.accentBg : taskRow.hovered ? Theme.hover : Theme.bg }
                    contentItem: Column {
                        spacing: 4
                        Text { width: parent.width; text: taskRow.modelData.objective; textFormat: Text.PlainText; color: Theme.ink; font.family: Theme.fontFamily; elide: Text.ElideRight }
                        Text { text: panel.state(taskRow.modelData.state); color: Theme.muted; font.family: Theme.fontFamily }
                    }
                }
            }

            ColumnLayout {
                visible: panel.creating
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 10
                TextField {
                    id: objective
                    objectName: "taskObjective"
                    Layout.fillWidth: true
                    maximumLength: 1000
                    placeholderText: I18n.t("任务目标")
                    selectByMouse: true
                }
                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    TextArea {
                        id: scope
                        objectName: "taskScope"
                        placeholderText: I18n.t("用户授权的范围")
                        wrapMode: TextEdit.Wrap
                        selectByMouse: true
                    }
                }
                ActionButton {
                    text: I18n.t("保存任务")
                    objectName: "saveTaskRecord"
                    primary: true
                    enabled: objective.text.trim().length > 0 && scope.text.trim().length > 0 && scope.length <= 4000
                    onClicked: {
                        const id = panel.records.create(objective.text, scope.text)
                        if (id) {
                            objective.clear()
                            scope.clear()
                            panel.creating = false
                            panel.selectTask(id, true)
                        }
                    }
                }
            }

            ColumnLayout {
                visible: !panel.creating
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 8
                Text { visible: !panel.task; text: I18n.t("暂无任务记录"); color: Theme.muted; font.family: Theme.fontFamily }
                ScrollView {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(160, taskSummary.implicitHeight)
                    visible: panel.task !== null
                    clip: true
                    DetailText {
                        id: taskSummary
                        text: panel.task ? [
                            panel.task.objective, panel.state(panel.task.state) + " · " + panel.task.id,
                            I18n.t("用户授权的范围") + "\n" + panel.task.scope,
                            I18n.t("项目目录") + " · " + panel.task.project,
                            I18n.t("创建时间") + " · " + panel.task.created,
                            I18n.t("更新时间") + " · " + panel.task.updated
                        ].join("\n") : ""
                    }
                }
                ComboBox {
                    objectName: "taskAttemptSelector"
                    visible: panel.attempts.length > 0
                    Layout.fillWidth: true
                    model: panel.attempts.map(row => row.started + " · " + panel.state(row.accepted ? "accepted" : row.state))
                    currentIndex: panel.attempts.findIndex(row => row.id === panel.attemptId)
                    onActivated: index => { panel.attemptId = panel.attempts[index].id; panel.loadAttempt(false) }
                }
                ScrollView {
                    visible: panel.attempt !== null
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    DetailText {
                        objectName: "taskAttemptDetails"
                        text: panel.detail ? panel.detailsText(panel.detail) : panel.loading ? I18n.t("正在读取任务详情") : ""
                    }
                }
                Item { visible: !panel.attempt; Layout.fillHeight: true }
                Text {
                    visible: panel.task !== null
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    color: Theme.muted
                    font.family: Theme.fontFamily
                    text: panel.confirmingDelete ? I18n.t("删除任务记录？会话和项目文件将保留。")
                        : I18n.t("关联后，发送下一条消息才会开始一次新尝试。请在对应项目的空闲会话中操作。")
                }
                Flow {
                    visible: panel.task !== null
                    Layout.fillWidth: true
                    spacing: 6
                    ActionButton {
                        objectName: "prepareTaskAttempt"
                        text: I18n.t("关联下条消息")
                        enabled: panel.task !== null && panel.task.state !== "running" && !backend.busy && panel.records.canPrepare(panel.taskId)
                        onClicked: { if (panel.records.prepare(panel.taskId)) panel.close() }
                    }
                    ActionButton { text: I18n.t("刷新"); enabled: !panel.loading && panel.attempt !== null; onClicked: panel.loadAttempt(false) }
                    ActionButton {
                        objectName: "verifyTaskArtifacts"
                        text: I18n.t("核验文件版本")
                        enabled: !panel.loading && panel.detail !== null && panel.detail.files.some(row => row.source !== "input")
                        onClicked: panel.loadAttempt(true)
                    }
                    ActionButton {
                        objectName: "acceptTaskAttempt"
                        text: I18n.t("验收尝试")
                        enabled: !panel.loading && panel.detail !== null && panel.attempt !== null
                                 && panel.attempt.state === "finished" && !panel.attempt.accepted && panel.attempts[0].id === panel.attemptId
                        onClicked: panel.records.accept(panel.taskId, panel.attemptId)
                    }
                    ActionButton {
                        text: panel.confirmingDelete ? I18n.t("确认删除") : I18n.t("删除任务记录")
                        destructive: true
                        enabled: panel.task !== null && panel.task.state !== "running"
                        onClicked: {
                            if (panel.confirmingDelete) panel.records.remove(panel.taskId)
                            else panel.confirmingDelete = true
                        }
                    }
                    ActionButton { text: I18n.t("取消"); visible: panel.confirmingDelete; onClicked: panel.confirmingDelete = false }
                }
            }
        }
    }
}
