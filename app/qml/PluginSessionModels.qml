import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "ReasoningLevels.js" as Reasoning

// Model route and reasoning effort of each application plugin session profile.
SectionCard {
    id: root
    objectName: "pluginSessionModels"
    readonly property var profiles: backend.pluginSessionProfiles
    readonly property var choices: backend.pluginSessionModels
    visible: profiles.length > 0
    ColumnLayout {
        width: parent.width; spacing: 14
        RowLayout {
            Layout.fillWidth: true; spacing: 8
            Text { text: I18n.t("插件会话模型"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(14, visible); font.weight: Font.DemiBold; Layout.fillWidth: true; wrapMode: Text.Wrap }
            HelpButton { help: I18n.t("应用级插件取得的独立会话使用这里的模型。更换后在下一次输入时生效；工作区、工具和权限保持不变。") }
        }
        Repeater {
            model: root.profiles
            RowLayout {
                id: row
                required property var modelData
                readonly property string savedEffort: modelData.reasoningEffort || ""
                Layout.fillWidth: true; spacing: 12
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 2
                    Text { text: row.modelData.pluginName; color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13, visible); elide: Text.ElideRight; Layout.fillWidth: true }
                    Text { text: I18n.t("会话配置：%1").arg(row.modelData.profile); color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible); elide: Text.ElideRight; Layout.fillWidth: true }
                }
                ColumnLayout {
                    Layout.preferredWidth: Math.min(Theme.control(280), root.width * 0.4)
                    spacing: 4
                    Text { text: I18n.t("模型"); color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible) }
                    Picker {
                        id: picker
                        objectName: "pluginSessionModel_" + row.modelData.plugin + "_" + row.modelData.profile
                        Layout.fillWidth: true
                        readonly property int selectedIndex: root.choices.findIndex(choice => choice.model === row.modelData.model
                            && (!row.modelData.provider || choice.providerId === row.modelData.provider))
                        model: root.choices.map(choice => choice.label)
                        displayText: currentIndex < 0 ? (row.modelData.model || I18n.t("未选择模型")) : currentText
                        Accessible.name: I18n.t("插件会话模型") + " " + row.modelData.pluginName + " " + row.modelData.profile
                        function sync() { currentIndex = selectedIndex }
                        Component.onCompleted: Qt.callLater(sync)
                        onModelChanged: Qt.callLater(sync)
                        onSelectedIndexChanged: Qt.callLater(sync)
                        onActivated: index => {
                            const choice = root.choices[index]
                            if (!backend.savePluginSessionModel(row.modelData.plugin, row.modelData.profile, choice.model, choice.providerId)) sync()
                        }
                    }
                }
                ColumnLayout {
                    Layout.preferredWidth: Theme.control(144)
                    spacing: 4
                    Text { text: I18n.t("思考强度"); color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible) }
                    Picker {
                        id: reasoningPicker
                        objectName: "pluginSessionReasoning_" + row.modelData.plugin + "_" + row.modelData.profile
                        Layout.fillWidth: true
                        enabled: picker.selectedIndex >= 0
                        // Empty means leave unchanged in the save API, so inheritance is
                        // offered only while the profile already inherits desktop settings.
                        readonly property var values: (row.savedEffort ? [] : [""]).concat(["off"],
                            (picker.selectedIndex >= 0 ? root.choices[picker.selectedIndex].reasoningLevels || [] : [])
                                .filter(level => level !== "off"))
                        readonly property int selectedIndex: values.indexOf(row.savedEffort)
                        model: values.map(level => level === "" ? I18n.t("沿用桌面")
                            : level === "off" ? I18n.t("关闭") : Reasoning.label(level))
                        displayText: currentIndex < 0 ? Reasoning.label(row.savedEffort) : currentText
                        Accessible.name: I18n.t("思考强度") + " " + row.modelData.pluginName + " " + row.modelData.profile
                        function sync() { currentIndex = selectedIndex }
                        Component.onCompleted: Qt.callLater(sync)
                        onModelChanged: Qt.callLater(sync)
                        onSelectedIndexChanged: Qt.callLater(sync)
                        onActivated: index => {
                            const choice = root.choices[picker.selectedIndex]
                            if (!choice || !backend.savePluginSessionModel(row.modelData.plugin, row.modelData.profile,
                                    choice.model, choice.providerId, values[index])) sync()
                        }
                    }
                }
            }
        }
    }
}
