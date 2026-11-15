import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: root
    objectName: "petTimerDialog"
    required property var schedule
    readonly property var state: schedule.state
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(620,parent ? parent.width-32 : 620)
    height: Math.min(700,parent ? parent.height-32 : 700)
    modal: true
    visible: state.opened
    closePolicy: Popup.NoAutoClose
    title: "创建定时任务"
    background: Rectangle { color: Theme.surface; radius: 12; border.color: Theme.line }
    contentItem: ScrollView {
        clip: true
        ColumnLayout {
            width: root.availableWidth; spacing: 10
            Label { text: "归属会话（必选；悬浮小助手不能作为归属）"; color: Theme.ink }
            RowLayout {
                Layout.fillWidth: true
                ComboBox {
                    objectName: "petTimerOwner"; Layout.fillWidth: true
                    model: root.state.owners; textRole: "name"; valueRole: "id"
                    enabled: !root.state.busy
                    currentIndex: root.state.owners.findIndex(r=>r.id===root.state.owner)
                    displayText: currentIndex < 0 ? "选择已有普通会话或项目会话" : currentText
                    onActivated: root.schedule.selectOwner(currentValue)
                }
                Button { text: "刷新"; onClicked: root.schedule.refresh() }
            }
            Button { text: root.state.owner ? "在 Desktop 打开归属会话的定时任务" : "去 Desktop 准备普通会话"; onClicked: root.schedule.openDesktop() }
            Text { Layout.fillWidth: true; visible: !root.state.owners.length; text: "没有可用归属。请在 Desktop 创建或打开普通会话，再回到胶囊输入 /定时任务。不会自动创建归属会话。"; wrapMode: Text.Wrap; color: Theme.muted }
            Text { Layout.fillWidth: true; visible: !!root.state.notice; text: root.state.notice; wrapMode: Text.Wrap; color: Theme.accent }
            Text { Layout.fillWidth: true; text: "仅支持单次或固定间隔；每天固定时间不等于每隔 24 小时。Umeko 需保持运行，错过触发按既有调度规则处理。"; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: 12 }
            Text { Layout.fillWidth: true; visible: !!root.state.error; text: root.state.error; wrapMode: Text.Wrap; color: "#bd4545" }
            Text { Layout.fillWidth: true; visible: !!root.state.outcome; text: root.state.outcome; wrapMode: Text.Wrap; color: Theme.accent }
            Button {
                visible: root.state.outcome.startsWith("创建结果待核对"); enabled: !root.state.busy
                text: "已在 Desktop 核对未创建，允许重新准备"
                onClicked: root.schedule.acknowledgeNotCreated()
            }
            ColumnLayout {
                Layout.fillWidth: true; visible: !Object.keys(root.state.review).length; enabled: !!root.state.owner && !root.state.busy && !root.state.outcome
                TextField { objectName: "petTimerName"; Layout.fillWidth: true; placeholderText: "任务名称（必填，最多 120 字）"; text: root.state.draft.name; onTextEdited: root.schedule.setField("name",text) }
                TextArea { objectName: "petTimerMessage"; Layout.fillWidth: true; Layout.preferredHeight: 90; placeholderText: "要执行的指令（必填）"; wrapMode: TextEdit.Wrap; text: root.state.draft.message; onTextChanged: if (activeFocus) root.schedule.setField("message",text) }
                Label { text: "执行对象（与归属会话分开）"; color: Theme.ink }
                ComboBox { objectName: "petTimerTarget"; Layout.fillWidth: true; model: root.state.targets; textRole: "name"; valueRole: "id"; displayText: currentIndex < 0 ? "选择执行对象（必选）" : currentText; currentIndex: root.state.targets.findIndex(r=>r.id===root.state.draft.target); onActivated: root.schedule.setField("target",currentValue) }
                ComboBox { objectName: "petTimerFrequency"; Layout.fillWidth: true; model: ["单次 · 日期和时间", "固定间隔 · 最短 15 秒"]; currentIndex: root.state.draft.frequency === "interval" ? 1 : 0; onActivated: root.schedule.setField("frequency",currentIndex ? "interval" : "once") }
                RowLayout {
                    visible: root.state.draft.frequency === "once"; Layout.fillWidth: true
                    TextField { objectName: "petTimerDate"; Layout.fillWidth: true; placeholderText: "日期 YYYY-MM-DD（必填）"; text: root.state.draft.first_date; onTextEdited: root.schedule.setField("first_date",text) }
                    TextField { objectName: "petTimerTime"; Layout.preferredWidth: 160; placeholderText: "时间 HH:mm（必填）"; text: root.state.draft.local_time; onTextEdited: root.schedule.setField("local_time",text) }
                }
                TextField { objectName: "petTimerZone"; visible: root.state.draft.frequency === "once"; Layout.fillWidth: true; placeholderText: "IANA 时区（必填）"; text: root.state.draft.zone; onTextEdited: root.schedule.setField("zone",text) }
                RowLayout {
                    visible: root.state.draft.frequency === "interval"; Layout.fillWidth: true
                    TextField { objectName: "petTimerInterval"; Layout.fillWidth: true; placeholderText: "间隔数值（必填）"; text: root.state.draft.interval_value; onTextEdited: root.schedule.setField("interval_value",text) }
                    ComboBox { model: ["分钟","小时","天（24 小时）"]; currentIndex: ["minutes","hours","days"].indexOf(root.state.draft.interval_unit); onActivated: root.schedule.setField("interval_unit",["minutes","hours","days"][currentIndex]) }
                }
            }
            Text {
                objectName: "petTimerConfirmation"; visible: Object.keys(root.state.review).length>0
                Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.ink; font.pixelSize: 14
                text: visible ? "请确认创建并启用\n\n归属："+root.state.review.owner+"\n名称："+root.state.review.args.name+"\n执行对象："+root.state.review.targetName+"\n指令："+root.state.review.args.message+"\n\n计划："+root.state.review.scheduleText+"\n预计下次触发："+root.state.review.next+"\n\n确认后才创建；最多 5 项（含全局），创建时重新检查名额和权限。应用必须保持运行。" : ""
            }
        }
    }
    footer: RowLayout {
        Button { text: "关闭并保留草稿"; onClicked: root.schedule.close() }
        Button { text: "新任务"; visible: root.state.outcome.startsWith("已创建"); onClicked: root.schedule.newDraft() }
        Item { Layout.fillWidth: true }
        Button { objectName: "petTimerReview"; text: "核对创建信息"; visible: !Object.keys(root.state.review).length; enabled: !root.state.busy && !root.state.outcome; onClicked: root.schedule.review() }
        Button { text: "返回修改"; visible: Object.keys(root.state.review).length>0; enabled: !root.state.busy; onClicked: root.schedule.edit() }
        Button { objectName: "petTimerConfirm"; text: root.state.busy ? "正在创建…" : "确认创建并启用"; visible: Object.keys(root.state.review).length>0; enabled: !root.state.busy; onClicked: root.schedule.confirm() }
    }
}
