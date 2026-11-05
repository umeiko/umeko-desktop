import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "taskRecordsWidget"
    required property var sdk
    readonly property var c: sdk.colors
    readonly property bool sessionBusy: !!sdk.session.busy
    color: c.surface
    clip: true

    property string view: "list"
    property string request: ""
    property string error: ""
    property bool refreshPending: false
    property bool loaded: false
    property string linked: ""
    property var tasks: []
    property bool tasksMore: false
    property int taskOffset: 0
    property string taskId: ""
    property var task: null
    property bool canLink: false
    property var attempts: []
    property bool attemptsMore: false
    property int attemptOffset: 0
    property int attemptIndex: -1
    readonly property var attempt: attempts[attemptIndex] || null
    property int detailOffset: 0
    property var detail: null
    property bool confirmingDelete: false

    function t(zh, en) { return sdk.language.indexOf("zh") === 0 ? zh : en }

    function status(code) {
        return ({
            draft: t("未开始", "Draft"), running: t("执行中", "Running"), pending: t("待恢复", "Needs recovery"),
            failed: t("失败", "Failed"), finished: t("执行结束", "Execution finished"), accepted: t("已验收", "Accepted"),
            available: t("可用", "Available"), missing: t("已移动或缺失", "Moved or missing"), changed: t("已变化", "Changed"),
            unavailable: t("不可用", "Unavailable"), unsupported: t("无法核验此类型", "Unsupported file type"),
            unverified: t("未记录版本", "Version unavailable")
        })[code] || code || ""
    }

    function reason(code) {
        return ({
            "应用已重启": t("应用已重启", "App restarted"), "应用已退出": t("应用已退出", "App exited"),
            "Pi 未能启动尝试": t("Pi 未能启动尝试", "Pi could not start the attempt"),
            "Pi 进程已退出": t("Pi 进程已退出", "Pi process exited"),
            "用户已停止尝试": t("用户已停止尝试", "User stopped the attempt"),
            "Pi 执行失败": t("Pi 执行失败", "Pi execution failed"),
            "输出达到长度上限": t("输出达到长度上限", "Output length limit reached"),
            "部分交付失败": t("部分交付失败", "Delivery had failures"),
            "任务记录写入不完整": t("任务记录写入不完整", "Task record was only partially saved")
        })[code] || code || ""
    }

    function call(operation, args) {
        if (!sdk.active || request) return
        error = ""
        request = sdk.requestHost("tasks." + operation, args || {})
        if (!request) error = t("任务记录暂不可用，请重试。", "Task records are unavailable. Please retry.")
    }

    function showList(offset) {
        view = "list"
        taskOffset = offset
        call("list", {offset: offset})
    }

    function showTask(id, offset) {
        view = "task"
        taskId = id
        attemptOffset = offset
        confirmingDelete = false
        call("get", {taskId: id, offset: offset})
    }

    function showAttempt(index, offset) {
        attemptIndex = index
        detailOffset = offset
        detail = null
        if (attempt)
            call("detail", {taskId: taskId, attemptId: attempt.id, offset: offset})
    }

    function refresh() {
        if (!sdk.active || request || view === "create") return
        refreshPending = false
        if (view === "task") showTask(taskId, attemptOffset)
        else showList(taskOffset)
    }

    function detailsText(data) {
        const lines = [
            t("实际工作目录", "Actual working directory") + "\n" + data.cwd,
            t("会话引用", "Session reference") + " · " + status(data.session_state) + "\n"
                + (data.session_id || "—") + (data.session_file ? "\n" + data.session_file : ""),
            t("尝试开始时间", "Attempt started") + " · " + data.started
        ]
        if (data.ended) lines.push(t("尝试结束时间", "Attempt ended") + " · " + data.ended)
        if (data.reason) lines.push(reason(data.reason))
        if (data.accepted) lines.push(t("用户已验收", "Accepted by user") + " · " + data.accepted)
        for (const item of data.files) {
            const kind = item.source === "input" ? t("输入文件", "Input file") :
                item.source === "generated" ? t("生成并交付", "Generated and delivered") : t("已投递", "Submitted")
            lines.push(kind + " · " + status(item.state) + "\n" + item.path
                + (item.version ? "\n" + t("版本", "Version") + " · " + item.version : "")
                + (item.checked ? "\n" + t("上次核验", "Last check") + " · " + status(item.check_result) + " · " + item.checked : ""))
        }
        for (const step of data.steps) {
            if (step.kind === "message")
                lines.push(t("消息引用", "Message reference") + " · " + step.detail + " · " + step.key)
            else if (step.kind === "session")
                lines.push(t("会话引用", "Session reference") + " · " + status(step.state) + "\n" + step.key + "\n" + step.detail)
            else if (step.kind === "delivery_error")
                lines.push(t("未能交付的条目", "Undelivered items") + " · " + step.detail + " · " + step.key)
            else
                lines.push(t("工具步骤", "Tool step") + " · " + step.detail + " · " + step.key)
        }
        return lines.join("\n\n")
    }

    onSessionBusyChanged: {
        if (view === "task") {
            refreshPending = true
            refresh()
        }
    }
    Component.onCompleted: refresh()
    Connections {
        target: root.sdk
        function onActiveChanged() { if (root.sdk.active) root.refresh() }
        function onEvent(topic, data) {
            if (topic === "tasks.changed") {
                root.refreshPending = true
                root.refresh()
            }
        }
        function onHostResponse(token, response) {
            if (token !== root.request) return
            root.request = ""
            if (!response.ok) {
                root.error = response.error || root.t("读取任务记录失败", "Could not load task records")
                return
            }
            const result = response.result
            switch (response.operation) {
            case "tasks.list":
                root.loaded = true
                root.tasks = result.tasks
                root.tasksMore = result.hasMore
                root.linked = result.linked
                break
            case "tasks.get": {
                const previous = root.attempt ? root.attempt.id : 0
                root.task = result.task
                root.attempts = result.attempts
                root.attemptsMore = result.hasMore
                root.canLink = result.canLink
                root.linked = result.linked
                const index = root.attempts.findIndex(item => item.id === previous)
                root.showAttempt(index >= 0 ? index : root.attempts.length ? 0 : -1, 0)
                break
            }
            case "tasks.detail":
                root.detail = result.id ? result : null
                break
            case "tasks.create":
                objective.clear()
                scope.clear()
                root.refreshPending = false
                root.showTask(result.taskId, 0)
                break
            case "tasks.verify":
                root.showAttempt(root.attemptIndex, root.detailOffset)
                break
            case "tasks.delete":
                root.refreshPending = false
                root.showList(0)
                break
            default:
                root.refreshPending = true
                break
            }
            if (root.refreshPending && !root.request) root.refresh()
        }
    }

    component LabelText: Text {
        textFormat: Text.PlainText
        color: root.c.ink
        font.pixelSize: 12 * root.sdk.scale
        wrapMode: Text.Wrap
    }

    component WidgetButton: Button {
        id: button
        padding: 7
        contentItem: LabelText {
            text: button.text
            color: button.enabled ? root.c.ink : root.c.muted
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 7
            color: button.down ? root.c.accentBg : button.hovered ? root.c.hover : root.c.surface
            border.color: root.c.line
        }
    }

    component DetailText: TextArea {
        textFormat: TextEdit.PlainText
        readOnly: true
        selectByMouse: true
        wrapMode: TextEdit.Wrap
        color: root.c.ink
        font.pixelSize: 12 * root.sdk.scale
        background: Rectangle { radius: 8; color: root.c.bg }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        enabled: root.sdk.active
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            WidgetButton {
                visible: root.view !== "list"
                enabled: !root.request
                text: root.t("返回", "Back")
                onClicked: root.showList(root.taskOffset)
            }
            LabelText { Layout.fillWidth: true; text: root.t("任务记录", "Task records"); font.bold: true }
            WidgetButton {
                objectName: "newTaskRecord"
                visible: root.view === "list"
                enabled: !root.request
                text: root.t("新建任务", "New task")
                onClicked: { root.error = ""; root.view = "create"; objective.forceActiveFocus() }
            }
            WidgetButton {
                enabled: !root.request
                visible: root.view !== "create"
                text: root.t("刷新", "Refresh")
                onClicked: root.refresh()
            }
        }
        RowLayout {
            visible: root.linked !== ""
            LabelText {
                objectName: "linkedTaskNotice"
                Layout.fillWidth: true
                text: root.t("下条手动发送的消息已关联任务", "The next message you send is linked to a task")
            }
            WidgetButton {
                enabled: !root.request
                text: root.t("解除关联", "Unlink")
                onClicked: root.call("unlink")
            }
        }
        LabelText { visible: text !== ""; Layout.fillWidth: true; text: root.error; color: root.c.danger }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.view === "list"
            LabelText { visible: !root.request && !root.tasks.length; text: root.t("暂无任务记录", "No tasks yet"); color: root.c.muted }
            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: root.tasks
                ScrollBar.vertical: ScrollBar {}
                delegate: ItemDelegate {
                    id: entry
                    required property var modelData
                    objectName: "openTask_" + modelData.id
                    width: ListView.view.width
                    enabled: !root.request
                    onClicked: {
                        root.task = null
                        root.attempts = []
                        root.detail = null
                        root.showTask(modelData.id, 0)
                    }
                    background: Rectangle { radius: 7; color: entry.hovered ? root.c.hover : root.c.surface }
                    contentItem: Column {
                        spacing: 3
                        LabelText { width: parent.width; text: entry.modelData.objective; maximumLineCount: 2; elide: Text.ElideRight }
                        LabelText { text: root.status(entry.modelData.state); color: root.c.muted }
                    }
                }
            }
            RowLayout {
                visible: root.taskOffset > 0 || root.tasksMore
                WidgetButton { text: root.t("上一页", "Previous"); enabled: !root.request && root.taskOffset > 0; onClicked: root.showList(root.taskOffset - 12) }
                WidgetButton { text: root.t("下一页", "Next"); enabled: !root.request && root.tasksMore; onClicked: root.showList(root.taskOffset + 12) }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.view === "create"
            TextField {
                id: objective
                objectName: "taskObjective"
                Layout.fillWidth: true
                maximumLength: 1000
                placeholderText: root.t("任务目标", "Task objective")
                selectByMouse: true
                color: root.c.ink
            }
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                TextArea {
                    id: scope
                    objectName: "taskScope"
                    placeholderText: root.t("用户授权的范围", "User-authorized scope")
                    color: root.c.ink
                    wrapMode: TextEdit.Wrap
                    selectByMouse: true
                }
            }
            WidgetButton {
                objectName: "saveTaskRecord"
                enabled: !root.request && objective.text.trim().length > 0 && scope.text.trim().length > 0 && scope.length <= 4000
                text: root.t("保存任务", "Save task")
                onClicked: root.call("create", {objective: objective.text, scope: scope.text})
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.view === "task"
            ScrollView {
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(120, taskSummary.implicitHeight)
                clip: true
                visible: root.task !== null
                DetailText {
                    id: taskSummary
                    text: root.task ? [
                        root.task.objective, root.task.id,
                        root.t("用户授权的范围", "User-authorized scope") + "\n" + root.task.scope,
                        root.t("项目目录", "Project directory") + " · " + root.task.project,
                        root.t("创建时间", "Created") + " · " + root.task.created,
                        root.t("更新时间", "Updated") + " · " + root.task.updated
                    ].join("\n") : ""
                }
            }
            ComboBox {
                objectName: "taskAttemptSelector"
                Layout.fillWidth: true
                visible: root.attempts.length > 0
                enabled: !root.request
                palette.buttonText: root.c.ink
                palette.button: root.c.surface
                palette.base: root.c.surface
                palette.text: root.c.ink
                model: root.attempts.map(row => row.started + " · " + root.status(row.accepted ? "accepted" : row.state))
                currentIndex: root.attemptIndex
                onActivated: index => root.showAttempt(index, 0)
            }
            RowLayout {
                visible: root.attemptOffset > 0 || root.attemptsMore
                WidgetButton { text: root.t("较新尝试", "Newer attempts"); enabled: !root.request && root.attemptOffset > 0; onClicked: root.showTask(root.taskId, root.attemptOffset - 12) }
                WidgetButton { text: root.t("较早尝试", "Older attempts"); enabled: !root.request && root.attemptsMore; onClicked: root.showTask(root.taskId, root.attemptOffset + 12) }
            }
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                DetailText {
                    objectName: "taskAttemptDetails"
                    text: root.detail ? root.detailsText(root.detail) : root.request ? root.t("正在读取任务记录", "Loading task records") : ""
                }
            }
            RowLayout {
                visible: root.detailOffset > 0 || !!(root.detail && root.detail.hasMore)
                WidgetButton { text: root.t("上一页详情", "Previous details"); enabled: !root.request && root.detailOffset > 0; onClicked: root.showAttempt(root.attemptIndex, root.detailOffset - 8) }
                WidgetButton { text: root.t("下一页详情", "More details"); enabled: !root.request && !!(root.detail && root.detail.hasMore); onClicked: root.showAttempt(root.attemptIndex, root.detailOffset + 8) }
            }
            LabelText {
                Layout.fillWidth: true
                visible: root.task !== null
                color: root.c.muted
                text: root.confirmingDelete ? root.t("删除任务记录？会话和项目文件将保留。", "Delete the task record? Chats and project files will be kept.")
                    : root.t("在同一项目的空闲聊天中关联任务，手动发送后才会开始尝试。", "Link a task from an idle chat in the same project. The attempt starts when you send a message.")
            }
            Flow {
                Layout.fillWidth: true
                spacing: 6
                visible: root.task !== null
                WidgetButton {
                    objectName: "prepareTaskAttempt"
                    enabled: !root.request && !root.sessionBusy && root.canLink && root.linked !== root.taskId
                    text: root.t("关联下条消息", "Link next message")
                    onClicked: root.call("link", {taskId: root.taskId})
                }
                WidgetButton {
                    objectName: "verifyTaskArtifacts"
                    enabled: !root.request && !!(root.detail && root.detail.hasDeliveries)
                    text: root.t("核验文件版本", "Check file versions")
                    onClicked: root.call("verify", {taskId: root.taskId, attemptId: root.attempt.id})
                }
                WidgetButton {
                    objectName: "acceptTaskAttempt"
                    enabled: !root.request && !!root.detail && !!root.attempt && root.attemptOffset === 0
                             && root.attemptIndex === 0 && root.attempt.state === "finished" && !root.attempt.accepted
                    text: root.t("验收尝试", "Accept attempt")
                    onClicked: root.call("accept", {taskId: root.taskId, attemptId: root.attempt.id})
                }
                WidgetButton {
                    enabled: !root.request && !(root.attemptOffset === 0 && root.attempts.length && root.attempts[0].state === "running")
                    text: root.confirmingDelete ? root.t("确认删除", "Confirm deletion") : root.t("删除任务记录", "Delete task record")
                    onClicked: {
                        if (root.confirmingDelete) root.call("delete", {taskId: root.taskId})
                        else root.confirmingDelete = true
                    }
                }
                WidgetButton { visible: root.confirmingDelete; text: root.t("取消", "Cancel"); onClicked: root.confirmingDelete = false }
            }
        }
    }
}
