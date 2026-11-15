import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// A transient single-question card. No history, transcript or Desktop navigation.
Popup {
    id: root
    objectName: "petTimerPrompt"
    required property var schedule
    required property var composer
    readonly property var state: schedule.state
    readonly property var question: state.question
    readonly property bool reviewing: question.key === "review" && Object.keys(state.review).length > 0
    signal answered()
    signal dismissed()
    function selectChoice(value) { const result=schedule.answer(value); if(result.ok) answered() }
    function modifyStep(value) { schedule.editStep(value); answered() }
    parent: composer.contentItem
    popupType: Popup.Window
    visible: state.opened && composer.desiredOpen
    modal: false
    focus: false
    closePolicy: Popup.NoAutoClose
    margins: -1
    implicitWidth: composer.width
    width: implicitWidth
    padding: 12
    implicitHeight: body.implicitHeight + padding * 2
    height: implicitHeight
    // Stay next to the capsule, flipping below at the top edge.
    x: 0
    y: composer.parent.Window.window.y + composer.y - height - 6 >= Screen.virtualY ? -height - 6 : composer.height + 6
    background: Rectangle { radius: 14; color: Theme.surface; border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, .25) }
    contentItem: ColumnLayout {
        id: body
        spacing: 7
        Keys.onEscapePressed: event => { root.schedule.close(); root.dismissed(); event.accepted = true }
        RowLayout {
            Layout.fillWidth: true
            Text { textFormat: Text.PlainText; text: "定时任务"; color: Theme.accent; font.pixelSize: 11 }
            Item { Layout.fillWidth: true }
            ToolButton {
                objectName: "petTimerCancel"; text: "关闭"; implicitHeight: 24
                enabled: !root.state.busy
                background: Item {}
                contentItem: Text { textFormat: Text.PlainText; text: "关闭"; color: Theme.muted; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                onClicked: { root.schedule.close(); root.dismissed() }
                ToolTip.visible: hovered; ToolTip.text: "关闭并保留已填写内容"
            }
        }
        Text {
            textFormat: Text.PlainText; Layout.fillWidth: true
            text: root.question.prompt
            color: Theme.ink; font.pixelSize: 13; wrapMode: Text.Wrap
            maximumLineCount: 3; elide: Text.ElideRight
        }
        Text {
            textFormat: Text.PlainText; Layout.fillWidth: true; visible: root.question.key === "owner" && !root.state.owners.length
            text: "暂无已有普通会话可选。请先准备一个会话；不会自动跳转或创建会话。"
            color: Theme.muted; font.pixelSize: 11; wrapMode: Text.Wrap
        }
        ListView {
            id: choices; objectName: "petTimerChoices"
            Layout.fillWidth: true; Layout.preferredHeight: Math.min(contentHeight, 100)
            visible: root.question.choices.length > 0
            model: root.question.choices; clip: true; spacing: 3
            ScrollBar.vertical: ScrollBar {}
            delegate: ItemDelegate {
                required property var modelData
                width: choices.width; height: 30
                text: modelData.name
                contentItem: Text { textFormat: Text.PlainText; text: parent.text; color: Theme.accent; font.pixelSize: 12; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { radius: 7; color: parent.hovered ? Qt.rgba(Theme.accent.r,Theme.accent.g,Theme.accent.b,.08) : "transparent" }
                onClicked: root.selectChoice(modelData.id)
                ToolTip.visible: hovered; ToolTip.text: modelData.name
            }
        }
        Text {
            textFormat: Text.PlainText; Layout.fillWidth: true; visible: root.reviewing
            text: root.reviewing ? root.state.review.ownerName + " · " + root.state.review.args.name + "\n" + root.state.review.targetName + "\n" + root.state.review.scheduleText + "\n" + root.state.review.args.message : ""
            color: Theme.ink; font.pixelSize: 12; wrapMode: Text.Wrap
            maximumLineCount: 5; elide: Text.ElideRight
            ToolTip.visible: reviewHover.hovered
            ToolTip.text: root.reviewing ? "归属："+root.state.review.owner+"\n"+root.state.review.args.message+"\n预计下次："+root.state.review.next : ""
            HoverHandler { id: reviewHover }
        }
        Text {
            textFormat: Text.PlainText; Layout.fillWidth: true; visible: root.reviewing
            text: "Umeko 需保持运行。确认后才会创建并启用。"
            color: Theme.muted; font.pixelSize: 11; wrapMode: Text.Wrap
        }
        Text {
            textFormat: Text.PlainText; Layout.fillWidth: true; visible: !!root.state.error || !!root.state.notice
            text: root.state.error || root.state.notice
            color: root.state.error ? Theme.danger : Theme.muted; font.pixelSize: 11
            wrapMode: Text.Wrap; maximumLineCount: 3; elide: Text.ElideRight
        }
        RowLayout {
            Layout.fillWidth: true
            ToolButton {
                background: Item {}
                contentItem: Text { textFormat: Text.PlainText; text: "修改"; color: Theme.accent; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                text: "修改"; visible: !!root.state.owner && !root.state.outcome; enabled: !root.state.busy
                onClicked: edits.open()
                Menu {
                    id: edits
                    Repeater {
                        model: [{key:"owner",name:"归属会话"},{key:"name",name:"名称"},{key:"message",name:"执行指令"},{key:"target",name:"执行对象"},{key:"frequency",name:"单次 / 间隔"},{key:"first_date",name:"日期"},{key:"local_time",name:"时间"},{key:"zone",name:"时区"},{key:"interval_value",name:"间隔分钟数"}]
                        MenuItem { required property var modelData; visible: !(["first_date","local_time","zone"].indexOf(modelData.key)>=0 && root.state.draft.frequency !== "once") && !(modelData.key === "interval_value" && root.state.draft.frequency !== "interval"); height: visible ? implicitHeight : 0; text: modelData.name; onTriggered: root.modifyStep(modelData.key) }
                    }
                }
            }
            Item { Layout.fillWidth: true }
            Button {
                objectName: "petTimerConfirm"; visible: root.reviewing
                background: Rectangle { radius: height/2; color: Theme.accent }
                contentItem: Text { textFormat: Text.PlainText; text: "确认创建"; color: "white"; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                text: "确认创建"; enabled: !root.state.busy
                onClicked: root.schedule.confirm()
            }
            ToolButton {
                visible: root.state.outcome.startsWith("创建结果待核对"); enabled: !root.state.busy
                text: "已核对未创建"; onClicked: { root.schedule.acknowledgeNotCreated(); root.answered() }
                background: Item {}
                contentItem: Text { textFormat: Text.PlainText; text: "已核对未创建"; color: Theme.accent; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                ToolTip.visible: hovered; ToolTip.text: "仅在你核实任务列表中没有创建此任务后使用，不会自动重试"
            }
            ToolButton {
                visible: root.state.outcome.startsWith("已创建")
                text: "新任务"; onClicked: { root.schedule.newDraft(); root.answered() }
                background: Item {}
                contentItem: Text { textFormat: Text.PlainText; text: "新任务"; color: Theme.accent; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
            }
            Button {
                visible: root.state.outcome.startsWith("已创建")
                background: Item {}
                contentItem: Text { textFormat: Text.PlainText; text: "完成"; color: Theme.accent; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                text: "完成"; onClicked: { root.schedule.close(); root.dismissed() }
            }
        }
    }
}
