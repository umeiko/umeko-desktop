import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "ReasoningLevels.js" as Reasoning

Column {
    id: root
    objectName: "modelGroupSettings"
    signal backRequested()
    readonly property var group: backend.modelGroup
    readonly property var members: group.members
    readonly property var addable: group.choices.filter(choice =>
        !members.some(member => member.provider === choice.provider && member.model === choice.model))
    property bool adding: false
    spacing: 18

    function save(enabled, rows) {
        return backend.saveModelGroup(enabled, JSON.stringify(rows.map(row =>
            ({provider: row.provider, model: row.model, effort: row.effort}))))
    }
    function move(index, offset) {
        const rows = members.slice()
        const member = rows.splice(index, 1)[0]
        rows.splice(index + offset, 0, member)
        save(group.enabled, rows)
    }
    function edit(index, effort) {
        const rows = members.slice()
        rows[index] = {provider: rows[index].provider, model: rows[index].model, effort: effort}
        save(group.enabled, rows)
    }
    function remove(index) {
        const rows = members.slice()
        rows.splice(index, 1)
        save(group.enabled, rows)
    }

    RowLayout {
        width: parent.width; spacing: 8
        ActionButton {
            objectName: "backModelGroupSettings"; glyph: "arrow-left"; quiet: true
            hint: I18n.t("返回"); onClicked: root.backRequested()
        }
        Text {
            text: I18n.t("模型组"); color: Theme.ink; font.family: Theme.fontFamily
            font.pixelSize: Theme.font(14, visible); font.weight: Font.DemiBold; Layout.fillWidth: true
        }
    }

    SectionCard {
        width: parent.width
        RowLayout {
            width: parent.width; spacing: 12
            Text {
                text: I18n.t("启用模型组"); color: Theme.ink; font.family: Theme.fontFamily
                font.pixelSize: Theme.font(13, visible); Layout.fillWidth: true; wrapMode: Text.Wrap
            }
            Toggle {
                objectName: "enableModelGroup"; checked: root.group.enabled
                Accessible.name: I18n.t("启用模型组")
                onClicked: {
                    const value = checked
                    checked = Qt.binding(() => root.group.enabled)
                    root.save(value, root.members)
                }
            }
        }
    }

    SectionCard {
        width: parent.width
        ColumnLayout {
            width: parent.width; spacing: 14
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Text {
                    text: I18n.t("模型顺序"); color: Theme.ink; font.family: Theme.fontFamily
                    font.pixelSize: Theme.font(13, visible); font.weight: Font.DemiBold
                }
                HelpButton { help: I18n.t("从上到下尝试模型。遇到网络故障、限流或额度用尽时，本轮上下文会发送给组内的下一个可用模型。") }
                Item { Layout.fillWidth: true }
                ActionButton {
                    objectName: "addModelGroupMember"; text: I18n.t("添加模型"); glyph: "plus"
                    enabled: root.addable.length > 0 && root.members.length < root.group.limit
                    onClicked: {
                        root.adding = !root.adding
                        if (root.adding) addPicker.forceActiveFocus()
                    }
                }
            }
            Picker {
                id: addPicker; objectName: "modelGroupAddPicker"
                Layout.fillWidth: true; visible: root.adding
                currentIndex: -1
                model: root.adding ? root.addable.map(row => row.model + "  ·  " + row.providerName) : []
                displayText: currentIndex < 0 ? I18n.t("选择要加入的模型") : currentText
                Accessible.name: I18n.t("选择要加入的模型")
                onActivated: index => {
                    const choice = root.addable[index]
                    if (choice && root.save(root.group.enabled, root.members.concat(
                        [{provider: choice.provider, model: choice.model, effort: "off"}])))
                        root.adding = false
                    currentIndex = -1
                }
            }
            Text {
                visible: root.members.length === 0
                text: I18n.t("添加模型后，即可在 Pi 聊天中选择模型组。")
                font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible); color: Theme.muted
                Layout.fillWidth: true; wrapMode: Text.Wrap
            }
            Repeater {
                model: root.members
                delegate: Frame {
                    id: memberCard
                    required property var modelData
                    required property int index
                    objectName: "modelGroupMember_" + index
                    Layout.fillWidth: true; padding: 12
                    implicitHeight: memberLayout.implicitHeight + topPadding + bottomPadding
                    background: Rectangle { radius: 8; color: Theme.bg }
                    ColumnLayout {
                        id: memberLayout
                        anchors.fill: parent; spacing: 8
                        RowLayout {
                            Layout.fillWidth: true; spacing: 8
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 3
                                Text {
                                    Layout.fillWidth: true; text: memberCard.modelData.model
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible)
                                    color: Theme.ink; textFormat: Text.PlainText; elide: Text.ElideRight
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: memberCard.modelData.available ? memberCard.modelData.providerName : I18n.t("模型不可用")
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.font(10, visible)
                                    color: memberCard.modelData.available ? Theme.muted : Theme.danger
                                    textFormat: Text.PlainText; elide: Text.ElideRight
                                }
                            }
                            ActionButton {
                                objectName: "moveModelGroupMemberUp_" + memberCard.index
                                glyph: "chevron-down"; rotation: 180; quiet: true
                                hint: I18n.t("上移"); enabled: memberCard.index > 0
                                onClicked: root.move(memberCard.index, -1)
                            }
                            ActionButton {
                                objectName: "moveModelGroupMemberDown_" + memberCard.index
                                glyph: "chevron-down"; quiet: true; hint: I18n.t("下移")
                                enabled: memberCard.index < root.members.length - 1
                                onClicked: root.move(memberCard.index, 1)
                            }
                            ActionButton {
                                objectName: "removeModelGroupMember_" + memberCard.index
                                glyph: "trash"; quiet: true; hint: I18n.t("移除模型")
                                onClicked: root.remove(memberCard.index)
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true; spacing: 8
                            visible: memberCard.modelData.available
                            Text {
                                text: I18n.t("思考强度"); color: Theme.muted; font.family: Theme.fontFamily
                                font.pixelSize: Theme.font(11, visible)
                            }
                            Item { Layout.fillWidth: true }
                            Picker {
                                id: effortPicker; objectName: "modelGroupEffort_" + memberCard.index
                                readonly property var levels: ["off"].concat(memberCard.modelData.levels || [])
                                readonly property int selectedIndex: Math.max(0, levels.indexOf(memberCard.modelData.effort))
                                Layout.preferredWidth: Theme.control(140)
                                Layout.minimumWidth: Theme.control(86)
                                model: levels.map(level => level === "off" ? I18n.t("关闭") : Reasoning.label(level))
                                currentIndex: selectedIndex
                                enabled: levels.length > 1
                                Accessible.name: I18n.t("思考强度")
                                onActivated: index => {
                                    root.edit(memberCard.index, levels[index])
                                    currentIndex = Qt.binding(() => effortPicker.selectedIndex)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
