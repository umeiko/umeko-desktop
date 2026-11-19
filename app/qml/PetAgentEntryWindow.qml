import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

Window {
    id: root
    objectName: "petAgentEntryWindow"
    required property var pet
    required property var petWindow
    readonly property var entry: pet.agentEntry
    readonly property var state: entry.state
    visible: state.opened && pet.visible
    flags: Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowTitleHint | Qt.WindowCloseButtonHint
    title: I18n.t("发送给已有全局智能体")
    width: 560; height: 560
    color: Theme.surface
    onClosing: event => { event.accepted = false; entry.close() }
    onVisibleChanged: {
        if (visible) {
            const area = petWindow.screen
            x = Math.max(area.virtualX, Math.min(petWindow.x, area.virtualX + area.width - width))
            y = Math.max(area.virtualY, Math.min(petWindow.y, area.virtualY + area.height - height))
            requestActivate()
        }
    }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 16; spacing: 10
        Label {
            Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted
            text: I18n.t("仅向已有、已初始化且闲置的目标发送。不创建智能体或连接，不打断任务。回复、审批与停止保留在 Desktop 原会话。")
        }
        RowLayout {
            Layout.fillWidth: true
            ComboBox {
                id: targets; objectName: "petAgentTargets"
                Layout.fillWidth: true
                model: root.state.options; textRole: "name"; valueRole: "id"
                currentIndex: model.findIndex(row => row.id === root.state.selected)
                displayText: currentIndex < 0 ? I18n.t("请选择目标") : currentText
                onActivated: index => root.entry.select(model[index].id)
                delegate: ItemDelegate {
                    required property var modelData
                    width: targets.width
                    text: modelData.name + (modelData.available ? "" : " · " + I18n.t(modelData.reason))
                    enabled: modelData.available
                }
            }
            Button { text: I18n.t("刷新"); onClicked: root.entry.refresh() }
        }
        Label {
            objectName: "petAgentTargetDetails"
            Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.ink
            text: root.state.selected ? root.state.name + "\n" + I18n.t("模型：") + root.state.model + "\n" + I18n.t("目录：") + root.state.workspace : I18n.t("未选择目标；不会使用默认助手代替。")
        }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true
            TextArea {
                id: body; objectName: "petAgentDraft"
                wrapMode: TextEdit.Wrap; selectByMouse: true
                text: root.state.body
                enabled: !!root.state.selected && !root.state.attempted
                placeholderText: I18n.t("给所选目标的指令。Enter 换行；点击预览后确认发送。")
                onTextChanged: if (text !== root.state.body) root.entry.setBody(text)
                Keys.onEscapePressed: event => {
                    if (!inputMethodComposing) { root.entry.close(); event.accepted = true }
                    else event.accepted = false
                }
            }
        }
        Label {
            objectName: "petAgentNotice"
            Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.ink
            text: root.state.preview ? I18n.t("请核对以上目标、模型、目录与全文。确认后仅尝试提交一次；不代表执行完成。") : I18n.t(root.state.notice)
        }
        RowLayout {
            Layout.fillWidth: true
            Button { objectName: "petAgentOpenDesktop"; text: I18n.t("打开所选会话"); enabled: !!root.state.selected; onClicked: root.entry.openDesktop() }
            Item { Layout.fillWidth: true }
            Button { text: I18n.t("关闭并保留草稿"); onClicked: root.entry.close() }
            Button {
                objectName: "petAgentSubmit"
                text: root.state.preview ? I18n.t("确认发送") : I18n.t("预览发送")
                enabled: !!root.state.selected && !root.state.attempted && !body.inputMethodComposing
                onClicked: root.state.preview ? root.entry.confirm() : root.entry.prepare()
            }
        }
    }
}
