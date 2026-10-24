import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    property var accounts: []
    property bool editing: false
    property string editingId: ""
    signal editProvider(var provider)
    visible: accounts.length > 0
    spacing: 12
    Repeater {
        model: root.accounts
        ColumnLayout {
            required property var modelData
            Layout.fillWidth: true; spacing: 12
            RowLayout { Layout.fillWidth: true; spacing: 12
            Rectangle {
                readonly property var preset: {
                    const base = backend.commonProviders.filter(p => p.id === modelData.presetId)[0] || null
                    return base && modelData.presetRegion === "international" && base.international ? base.international : base
                }
                visible: !!preset; Layout.preferredWidth: Theme.icon(28); Layout.preferredHeight: Theme.icon(28); radius: 6; color: "white"
                Image { anchors.centerIn: parent; width: Theme.icon(22); height: width; source: parent.preset ? "../icons/providers/" + parent.preset.icon : ""; fillMode: Image.PreserveAspectFit }
            }
            Glyph { visible: !modelData.presetId; name: "server"; width: Theme.icon(19); height: Theme.icon(19) }
            Column { Layout.fillWidth: true; spacing: 5
                Text { text: modelData.name; color: Theme.ink; font.pixelSize: Theme.font(12) }
                Text { text: modelData.baseUrl; color: Theme.muted; font.pixelSize: Theme.font(10); elide: Text.ElideRight; width: 400 }
            }
            Text { text: modelData.models.length + I18n.t(" 个模型"); color: Theme.muted; font.pixelSize: Theme.font(10) }
            Text { text: modelData.api === "openai" ? I18n.t("OpenAI 格式") : I18n.t("Anthropic 格式"); color: Theme.muted; font.pixelSize: Theme.font(10) }
            ProviderProxy { providerId: modelData.id }
            ActionButton { objectName: "editProvider_" + modelData.id; glyph: root.editing && root.editingId === modelData.id ? "chevron-up" : "edit"; quiet: true; hint: root.editing && root.editingId === modelData.id ? I18n.t("收起供应商与模型") : I18n.t("编辑供应商与模型"); onClicked: root.editProvider(modelData) }
            ActionButton { glyph: "trash"; quiet: true; hint: I18n.t("移除供应商"); onClicked: backend.removeProvider(modelData.id) }
            }
            Flow { Layout.fillWidth: true; spacing: 7
                Repeater { model: modelData.models
                    Rectangle { required property var modelData; width: chip.implicitWidth + 18; height: 27; radius: 6; color: Theme.accentBg
                        Text { id: chip; anchors.centerIn: parent; text: modelData.alias; color: Theme.accent; font.pixelSize: Theme.font(10) }
                    }
                }
            }
        }
    }
}
