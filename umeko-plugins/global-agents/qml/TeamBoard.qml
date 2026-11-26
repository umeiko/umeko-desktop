import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../app/qml" as Umeko

ColumnLayout {
    id: board
    objectName: "globalTeamBoard"
    required property var sdk
    required property bool active
    required property bool collaborationEnabled
    readonly property var colors: sdk.colors
    readonly property int pageSize: 20
    readonly property color indigo: colors.dark ? "#a8b6ff" : "#344fc0"
    readonly property color cyan: colors.dark ? "#67d9ee" : "#006a87"
    readonly property color green: colors.dark ? "#67d9b2" : "#086d53"
    readonly property color amber: colors.dark ? "#f1c982" : "#845900"
    property var teams: []
    property var members: []
    property var tasks: []
    property var events: []
    property string teamId: ""
    property string listRequest: ""
    property string memberRequest: ""
    property string boardRequest: ""
    property string errorMessage: ""
    property var cursors: [0]
    property var requestedCursors: [0]
    property double nextAfter: 0
    property bool hasMore: false
    property bool detailReady: false
    readonly property bool loading: !!(listRequest || memberRequest || boardRequest)
    readonly property int activeCount: members.filter(row => row.status === "running").length
    readonly property int waitingCount: members.filter(row => row.status === "waiting").length
    readonly property int doneCount: tasks.filter(row => row.status === "completed").length
    spacing: 9

    function clearDetail() {
        memberRequest = ""
        boardRequest = ""
        members = []
        tasks = []
        events = []
        detailReady = false
        cursors = [0]
        requestedCursors = cursors
        nextAfter = 0
        hasMore = false
    }

    function syncVisibility() {
        if (!active || !collaborationEnabled) {
            listRequest = ""
            clearDetail()
            teams = []
            errorMessage = ""
        } else {
            reload()
        }
    }
    onActiveChanged: syncVisibility()
    onCollaborationEnabledChanged: syncVisibility()

    function request(method, args) {
        const id = sdk.call(method, args)
        if (!id)
            errorMessage = Umeko.I18n.t("服务忙，请稍后重试")
        return id || ""
    }

    function reload() {
        if (!active || !collaborationEnabled || listRequest)
            return
        memberRequest = ""
        boardRequest = ""
        errorMessage = ""
        listRequest = request("team_members", {})
    }

    function selectTeam(id) {
        if (id === teamId || !id)
            return
        teamId = id
        clearDetail()
        errorMessage = ""
        if (!listRequest)
            memberRequest = request("team_members", { teamId: teamId })
    }

    function loadPage(path) {
        errorMessage = ""
        requestedCursors = path
        boardRequest = request("team_board", {
            teamId: teamId, after: path[path.length - 1], limit: pageSize
        })
    }

    function failure() {
        // A failed refresh doesn't erase the last good view of the same team.
        errorMessage = Umeko.I18n.t("团队看板读取失败，请重试")
    }

    Connections {
        target: board.sdk
        function onResponse(id, value) {
            if (!board.active || !board.collaborationEnabled || !id)
                return
            if (id === board.listRequest) {
                board.listRequest = ""
                if (!value.ok) {
                    board.failure()
                    return
                }
                board.teams = value.result.teams || []
                if (!board.teams.some(team => team.id === board.teamId)) {
                    board.clearDetail()
                    board.teamId = board.teams[0]?.id || ""
                }
                if (board.teamId)
                    board.memberRequest = board.request("team_members", { teamId: board.teamId })
            } else if (id === board.memberRequest) {
                board.memberRequest = ""
                if (!value.ok || value.result.id !== board.teamId) {
                    board.failure()
                    return
                }
                board.members = value.result.members || []
                board.loadPage(board.cursors)
            } else if (id === board.boardRequest) {
                board.boardRequest = ""
                if (!value.ok || value.result.teamId !== board.teamId) {
                    board.failure()
                    return
                }
                board.cursors = board.requestedCursors
                board.tasks = value.result.tasks || []
                board.events = value.result.events || []
                board.hasMore = !!value.result.hasMore
                board.nextAfter = value.result.nextAfter
                board.detailReady = true
            }
        }
    }

    function memberStatus(status) {
        switch (status) {
        case "running": return Umeko.I18n.t("运行中")
        case "waiting": return Umeko.I18n.t("等待点名")
        case "not_started": return Umeko.I18n.t("尚未启动")
        default: return Umeko.I18n.t("不可用")
        }
    }
    function taskKey(task) {
        return task.status === "pending" ? (task.ready ? "ready" : "blocked") : task.status
    }
    function taskStatus(key) {
        switch (key) {
        case "completed": return Umeko.I18n.t("已完成")
        case "in_progress": return Umeko.I18n.t("执行中")
        case "ready": return Umeko.I18n.t("待认领")
        case "blocked": return Umeko.I18n.t("等待依赖")
        default: return Umeko.I18n.t("未知状态")
        }
    }
    function stateColor(key) {
        switch (key) {
        case "running":
        case "in_progress": return cyan
        case "waiting":
        case "handoff": return indigo
        case "completed":
        case "result": return green
        case "blocked": return amber
        case "unavailable": return colors.danger
        default: return colors.muted
        }
    }
    function eventKind(kind) {
        switch (kind) {
        case "message": return Umeko.I18n.t("消息")
        case "task": return Umeko.I18n.t("创建任务")
        case "claim": return Umeko.I18n.t("认领任务")
        case "dependencies": return Umeko.I18n.t("更新依赖")
        case "progress": return Umeko.I18n.t("汇报进度")
        case "handoff": return Umeko.I18n.t("交接任务")
        case "result": return Umeko.I18n.t("提交结果")
        default: return Umeko.I18n.t("协作事件")
        }
    }

    readonly property var rows: {
        if (!teamId || !collaborationEnabled || !detailReady)
            return []
        const list = [{key: "members", type: "heading", title: Umeko.I18n.t("团队成员"),
                       meta: Umeko.I18n.t("%1 人").arg(members.length)}]
        for (let i = 0; i < members.length; ++i) {
            const member = members[i]
            list.push({key: "member-" + member.targetId, type: "member", title: member.name,
                       meta: member.role === "coordinator" ? Umeko.I18n.t("协调者") : Umeko.I18n.t("成员"),
                       state: member.status, status: memberStatus(member.status),
                       last: i === members.length - 1})
        }
        list.push({key: "tasks", type: "heading", title: Umeko.I18n.t("团队任务"),
                   meta: Umeko.I18n.t("%1 项").arg(tasks.length)})
        if (!tasks.length)
            list.push({key: "no-tasks", type: "empty", title: Umeko.I18n.t("暂无团队任务")})
        for (const task of tasks) {
            const key = taskKey(task)
            list.push({key: "task-" + task.id, type: "task", title: task.title,
                       meta: task.owner || Umeko.I18n.t("未分配"), body: task.result || task.description || "",
                       state: key, status: taskStatus(key)})
        }
        list.push({key: "events", type: "heading", title: Umeko.I18n.t("协作时间线"),
                   meta: events.length ? Umeko.I18n.t("按发生顺序") : ""})
        if (!events.length)
            list.push({key: "no-events", type: "empty", title: Umeko.I18n.t("暂无协作记录")})
        for (let i = 0; i < events.length; ++i) {
            const event = events[i]
            const task = event.task
            list.push({key: "event-" + event.sequence, type: "event", state: event.kind,
                       title: eventKind(event.kind) + (task ? " · " + task.title : ""),
                       meta: event.actor + (event.kind === "handoff" && task?.owner ? " → " + task.owner : ""),
                       body: event.text || "", time: event.created || "", last: i === events.length - 1})
        }
        return list
    }

    ListModel { id: rowModel; dynamicRoles: true }
    function syncRows() {
        for (let i = 0; i < rows.length; ++i) {
            let existing = i
            while (existing < rowModel.count && rowModel.get(existing).row.key !== rows[i].key)
                ++existing
            if (existing === rowModel.count) {
                rowModel.insert(i, { row: rows[i] })
            } else {
                if (existing !== i)
                    rowModel.move(existing, i, 1)
                if (JSON.stringify(rowModel.get(i).row) !== JSON.stringify(rows[i]))
                    rowModel.setProperty(i, "row", rows[i])
            }
        }
        if (rowModel.count > rows.length)
            rowModel.remove(rows.length, rowModel.count - rows.length)
    }
    onRowsChanged: syncRows()

    component BoardText: Text {
        font.family: Umeko.Theme.fontFamily
        font.pixelSize: 12 * board.sdk.scale
        color: board.colors.ink
        textFormat: Text.PlainText
    }
    component Metric: ColumnLayout {
        required property int value
        required property string label
        required property color tone
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        spacing: 3
        BoardText {
            Layout.fillWidth: true
            text: String(parent.value)
            color: parent.tone
            font.pixelSize: 28 * board.sdk.scale
            font.weight: Font.Medium
        }
        BoardText {
            Layout.fillWidth: true
            text: parent.label
            color: board.colors.muted
            font.pixelSize: 11 * board.sdk.scale
            elide: Text.ElideRight
        }
    }

    RowLayout {
        Layout.fillWidth: true
        visible: board.collaborationEnabled
        spacing: 6
        ComboBox {
            id: selector
            objectName: "globalTeamBoardPicker"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            implicitHeight: 36
            enabled: count > 1 && !board.listRequest
            model: board.teams
            textRole: "name"
            valueRole: "id"
            currentIndex: board.teams.findIndex(row => row.id === board.teamId)
            displayText: currentIndex >= 0 ? currentText : Umeko.I18n.t("选择团队")
            Accessible.name: Umeko.I18n.t("选择团队")
            palette.text: board.colors.ink
            palette.buttonText: board.colors.ink
            palette.base: board.colors.surface
            leftPadding: 9
            rightPadding: 26
            background: Rectangle {
                radius: 8
                color: board.colors.bg
                border.color: selector.activeFocus ? board.indigo : board.colors.line
            }
            contentItem: BoardText {
                verticalAlignment: Text.AlignVCenter
                text: selector.displayText
                elide: Text.ElideRight
            }
            indicator: Umeko.Glyph {
                name: "chevron-down"
                x: selector.width - width - 9
                y: (selector.height - height) / 2
                width: 14; height: 14
                color: board.colors.muted
            }
            onActivated: index => {
                board.selectTeam(valueAt(index))
                currentIndex = Qt.binding(() => board.teams.findIndex(row => row.id === board.teamId))
            }
        }
        Umeko.ActionButton {
            objectName: "globalTeamBoardReload"
            text: Umeko.I18n.t("刷新")
            enabled: !board.loading
            onClicked: board.reload()
        }
    }
    BoardText {
        objectName: "globalTeamBoardStatus"
        Layout.fillWidth: true
        visible: !!text
        text: !board.collaborationEnabled ? Umeko.I18n.t("请先在「设置 → Agent → Umeko Desktop」开启团队协作。")
              : board.errorMessage || (board.loading ? Umeko.I18n.t("正在读取团队看板…")
              : !board.teams.length ? Umeko.I18n.t("还没有团队。由全局子智能体创建团队后，可在这里查看。") : "")
        color: board.errorMessage ? board.colors.danger : board.colors.muted
        wrapMode: Text.Wrap
    }

    ListView {
        id: list
        objectName: "globalTeamBoardRows"
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: board.collaborationEnabled && board.detailReady
        clip: true
        model: rowModel
        ScrollBar.vertical: ScrollBar { }
        header: Item {
            width: list.width - 8
            height: overview.implicitHeight + 24
            Rectangle {
                anchors { left: parent.left; right: parent.right; top: parent.top }
                height: overview.implicitHeight + 24
                radius: 12
                border.color: board.colors.dark ? "#435081" : "#c8d3f7"
                gradient: Gradient {
                    GradientStop { position: 0; color: board.colors.dark ? "#202b4d" : "#edf3ff" }
                    GradientStop { position: 1; color: board.colors.dark ? "#141d36" : "#f5f7ff" }
                }
                // A quiet grid is decoration, not a synthetic trend or metric.
                Item {
                    anchors { top: parent.top; right: parent.right; margins: 7 }
                    width: 65; height: 43
                    opacity: board.colors.dark ? 0.17 : 0.10
                    Repeater {
                        model: 6
                        Rectangle { required property int index; x: index * 10; width: 1; height: 41; color: board.indigo }
                    }
                    Repeater {
                        model: 5
                        Rectangle { required property int index; y: index * 10; width: 51; height: 1; color: board.indigo }
                    }
                }
                ColumnLayout {
                    id: overview
                    objectName: "teamDashboardOverview"
                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
                    spacing: 8
                    RowLayout {
                        Layout.fillWidth: true
                        BoardText {
                            text: Umeko.I18n.t("团队概览")
                            font.weight: Font.DemiBold
                            font.pixelSize: 13 * board.sdk.scale
                            Layout.fillWidth: true
                        }
                        Rectangle {
                            implicitWidth: readonlyTag.implicitWidth + 14
                            implicitHeight: readonlyTag.implicitHeight + 6
                            radius: 4
                            color: board.colors.dark ? "#273455" : "#e0e9fb"
                            BoardText {
                                id: readonlyTag
                                anchors.centerIn: parent
                                text: Umeko.I18n.t("只读")
                                color: board.indigo
                                font.pixelSize: 10 * board.sdk.scale
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        uniformCellSizes: true
                        spacing: 6
                        Metric { objectName: "teamMetricMembers"; value: board.members.length; label: Umeko.I18n.t("成员"); tone: board.colors.ink }
                        Metric { objectName: "teamMetricRunning"; value: board.activeCount; label: Umeko.I18n.t("运行中"); tone: board.cyan }
                        Metric { objectName: "teamMetricWaiting"; value: board.waitingCount; label: Umeko.I18n.t("等待点名"); tone: board.indigo }
                    }
                    Rectangle { Layout.fillWidth: true; height: 1; color: board.colors.dark ? "#384467" : "#d7e0f4" }
                    RowLayout {
                        Layout.fillWidth: true
                        BoardText { Layout.fillWidth: true; text: Umeko.I18n.t("任务完成度"); color: board.colors.muted; font.pixelSize: 10 * board.sdk.scale }
                        BoardText {
                            objectName: "teamMetricDone"
                            text: board.doneCount + " / " + board.tasks.length
                            Accessible.name: Umeko.I18n.t("已完成 %1 / %2 项").arg(board.doneCount).arg(board.tasks.length)
                            font.weight: Font.DemiBold
                            color: board.colors.ink
                            font.pixelSize: 11 * board.sdk.scale
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        height: 5; radius: 2
                        clip: true
                        color: board.colors.dark ? "#3c496c" : "#cad5ef"
                        Rectangle {
                            objectName: "teamProgressCompletedSegment"
                            width: board.tasks.length ? parent.width * board.doneCount / board.tasks.length : 0
                            height: parent.height; color: board.green
                        }
                    }
                }
            }
        }
        delegate: Item {
            id: entry
            required property var row
            property bool expanded: false
            readonly property bool heading: row.type === "heading"
            readonly property bool member: row.type === "member"
            readonly property bool task: row.type === "task"
            readonly property bool event: row.type === "event"
            objectName: "teamBoardRow_" + row.key
            width: list.width - 8
            height: content.implicitHeight + (heading ? 27 : member ? 12 : 13)
            Rectangle {
                anchors.fill: parent
                visible: entry.member
                color: board.colors.bg
            }
            Rectangle {
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 8; bottomMargin: 0 }
                height: 1
                visible: entry.member || entry.task
                color: board.colors.line
            }
            Rectangle {
                visible: entry.event && !entry.row.last
                x: 6; y: 15; width: 1; height: entry.height
                color: board.colors.line
            }
            Rectangle {
                visible: entry.event
                x: 3; y: 11; width: 7; height: 7; radius: 4
                color: board.stateColor(entry.row.state)
            }
            ColumnLayout {
                id: content
                anchors {
                    left: parent.left; right: parent.right; top: parent.top
                    leftMargin: entry.event ? 18 : entry.member ? 8 : 1
                    rightMargin: entry.member ? 8 : 1
                    topMargin: entry.heading ? 16 : 6
                }
                spacing: 4
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Rectangle {
                        visible: entry.member
                        implicitWidth: 22; implicitHeight: 22; radius: 5
                        color: board.colors.dark ? "#273455" : "#e8edfb"
                        BoardText {
                            anchors.centerIn: parent
                            text: entry.row.title ? entry.row.title.slice(0, 1).toUpperCase() : ""
                            color: board.indigo
                            font.weight: Font.DemiBold
                            font.pixelSize: 10 * board.sdk.scale
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        BoardText {
                            Layout.fillWidth: true
                            text: entry.row.title
                            elide: Text.ElideRight
                            color: entry.row.type === "empty" ? board.colors.muted : board.colors.ink
                            font.pixelSize: (entry.heading ? 14 : 12) * board.sdk.scale
                            font.weight: entry.heading || entry.member ? Font.DemiBold : Font.Normal
                        }
                        BoardText {
                            Layout.fillWidth: true
                            visible: !entry.heading && !!text
                            text: entry.row.meta || ""
                            elide: Text.ElideRight
                            color: board.colors.muted
                            font.pixelSize: 10 * board.sdk.scale
                        }
                    }
                    Rectangle {
                        visible: (entry.member || entry.task) && !!entry.row.status
                        implicitWidth: 5; implicitHeight: 5; radius: 3
                        color: board.stateColor(entry.row.state)
                    }
                    BoardText {
                        visible: !!text
                        text: entry.heading ? entry.row.meta || ""
                              : entry.row.status || (entry.row.time ? Qt.formatDateTime(new Date(entry.row.time), "MM-dd HH:mm") : "")
                        color: entry.row.status ? board.stateColor(entry.row.state) : board.colors.muted
                        font.pixelSize: 10 * board.sdk.scale
                    }
                }
                BoardText {
                    id: description
                    Layout.fillWidth: true
                    visible: !!text
                    text: entry.row.body || ""
                    color: board.colors.muted
                    wrapMode: Text.Wrap
                    maximumLineCount: entry.expanded ? 10000 : 2
                    elide: Text.ElideRight
                    font.pixelSize: 11 * board.sdk.scale
                }
                Umeko.ActionButton {
                    objectName: "teamBoardExpand_" + entry.row.key
                    visible: description.visible && (description.truncated || entry.expanded)
                    quiet: true
                    implicitHeight: 26
                    text: Umeko.I18n.t(entry.expanded ? "收起团队记录" : "展开团队记录")
                    onClicked: entry.expanded = !entry.expanded
                }
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        visible: board.collaborationEnabled && board.detailReady && (board.cursors.length > 1 || board.hasMore)
        Umeko.ActionButton {
            objectName: "globalTeamBoardPrevious"; text: Umeko.I18n.t("上一页"); quiet: true
            enabled: !board.loading && board.cursors.length > 1
            onClicked: board.loadPage(board.cursors.slice(0, -1))
        }
        BoardText {
            text: Umeko.I18n.t("第 %1 页").arg(board.cursors.length)
            color: board.colors.muted
            font.pixelSize: 10 * board.sdk.scale
        }
        Umeko.ActionButton {
            objectName: "globalTeamBoardNext"; text: Umeko.I18n.t("下一页"); quiet: true
            enabled: !board.loading && board.hasMore
            onClicked: board.loadPage(board.cursors.concat(board.nextAfter))
        }
    }
}
