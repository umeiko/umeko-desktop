import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

SectionCard {
    id: root
    objectName: "teamCollaborationSettings"
    readonly property bool collaborationEnabled: backend.desktopSettings.teamCollaborationEnabled === true

    component ModelField: RowLayout {
        id: field
        required property string label
        required property string selection
        property bool inherit: false
        signal selected(string model)
        spacing: 12
        Text {
            Layout.fillWidth: true
            text: field.label
            textFormat: Text.PlainText
            color: Theme.ink
            font.family: Theme.fontFamily
            font.pixelSize: Theme.font(13)
            wrapMode: Text.WrapAnywhere
        }
        ComboBox {
            id: picker
            objectName: field.objectName + "Picker"
            Layout.fillWidth: true
            Layout.minimumWidth: Theme.control(96)
            Layout.preferredWidth: Theme.control(240)
            Layout.maximumWidth: Theme.control(360)
            implicitHeight: Theme.control(36)
            enabled: count > (field.inherit ? 1 : 0) || field.selection.length > 0 && field.inherit
            model: {
                const choices = backend.teamModelChoices.map(row => ({
                    id: row.id, label: row.group ? I18n.t("模型组") : row.label
                }))
                if (field.inherit) choices.unshift({id: "", label: I18n.t("沿用对话模型")})
                return choices
            }
            textRole: "label"
            valueRole: "id"
            function selectedIndex() { return model.findIndex(row => row.id === field.selection) }
            currentIndex: selectedIndex()
            displayText: currentIndex >= 0 ? currentText : field.selection || I18n.t("未配置模型")
            Accessible.name: field.label
            font.family: Theme.fontFamily
            font.pixelSize: Theme.font(12)
            palette.text: Theme.ink
            palette.base: Theme.surface
            palette.buttonText: Theme.ink
            onActivated: index => {
                field.selected(valueAt(index))
                currentIndex = Qt.binding(selectedIndex)
            }
        }
    }

    ColumnLayout {
        width: parent.width
        spacing: 13
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: I18n.t("团队协作")
                color: Theme.ink
                font.family: Theme.fontFamily
                font.pixelSize: Theme.font(14)
                font.weight: Font.DemiBold
            }
            Toggle {
                objectName: "desktopTeamCollaborationEnabled"
                checked: root.collaborationEnabled
                Accessible.name: I18n.t("团队协作")
                onClicked: {
                    const value = checked
                    checked = Qt.binding(() => root.collaborationEnabled)
                    backend.saveDesktopSettings(JSON.stringify({teamCollaborationEnabled: value}))
                }
            }
        }
        Loader {
            Layout.fillWidth: true
            active: root.collaborationEnabled
            visible: active
            sourceComponent: ColumnLayout {
                spacing: 11
                Text {
                    Layout.fillWidth: true
                    text: backend.sessionModelRolesAvailable ? I18n.t("当前会话的模型分工") : I18n.t("模型分工适用于普通 Pi 会话")
                    color: Theme.muted
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.font(12)
                    wrapMode: Text.Wrap
                }
                Repeater {
                    model: backend.sessionModelRolesAvailable ? [
                        {id: "planningModel", label: I18n.t("规划模型")},
                        {id: "executionModel", label: I18n.t("执行模型")},
                        {id: "coordinatorModel", label: I18n.t("协调者模型")},
                        {id: "memberDefaultModel", label: I18n.t("成员默认模型")}
                    ] : []
                    ModelField {
                        required property var modelData
                        objectName: "teamRole_" + modelData.id
                        Layout.fillWidth: true
                        label: modelData.label
                        selection: backend.sessionModelRoles[modelData.id] || ""
                        inherit: true
                        onSelected: model => backend.selectRoleModel(modelData.id, model)
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: backend.teamMemberModels.length ? I18n.t("团队成员模型") : I18n.t("在全局子智能体 Widget 中创建成员后，可以在这里为成员选模。")
                    color: Theme.muted
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.font(12)
                    wrapMode: Text.Wrap
                }
                Repeater {
                    model: backend.teamMemberModels
                    ModelField {
                        required property var modelData
                        objectName: "teamMember_" + modelData.id
                        Layout.fillWidth: true
                        label: modelData.name
                        selection: modelData.model
                        onSelected: model => backend.selectTeamMemberModel(modelData.id, model)
                    }
                }
            }
        }
    }
}
