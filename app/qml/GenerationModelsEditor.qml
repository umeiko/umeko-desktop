import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    property var models: []
    property var catalog: []
    property bool fixedCatalog: false
    signal edited(var models)
    readonly property var available: catalog.filter(row => !models.includes(row.id))
    spacing: 8

    function load(values) {
        models = values.slice()
        newModel.clear()
    }
    function addModel() {
        const choice = root.available[modelChoices.currentIndex]
        const value = fixedCatalog ? (choice ? choice.id : "") : newModel.text.trim()
        if (!value || models.includes(value) || models.length >= 128) return
        models = models.concat([value])
        newModel.clear()
        edited(models)
    }
    function removeModel(index) {
        models = models.filter((model, row) => row !== index)
        edited(models)
    }

    Text {
        text: I18n.t("模型"); color: Theme.ink
        font.family: Theme.fontFamily; font.pixelSize: Theme.font(13, visible); font.weight: Font.DemiBold
    }
    Repeater {
        model: root.models
        RowLayout {
            required property string modelData
            required property int index
            Layout.fillWidth: true; spacing: 10
            readonly property var catalogRow: root.catalog.find(row => row.id === modelData)
            Text {
                Layout.fillWidth: true
                text: catalogRow ? catalogRow.name : modelData
                textFormat: Text.PlainText; elide: Text.ElideRight
                color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible)
            }
            ActionButton {
                objectName: "removeGenerationModel_" + index
                glyph: "trash"; quiet: true; hint: I18n.t("移除模型")
                Accessible.name: hint
                onClicked: root.removeModel(index)
            }
        }
    }
    RowLayout {
        visible: !root.fixedCatalog || root.available.length > 0
        Layout.fillWidth: true; spacing: 10
        InputField {
            id: newModel; objectName: "newGenerationModel"
            visible: !root.fixedCatalog; Layout.fillWidth: true
            maximumLength: 200; placeholderText: I18n.t("输入模型 ID")
            Accessible.name: I18n.t("模型 ID")
            onAccepted: root.addModel()
        }
        Picker {
            id: modelChoices; objectName: "generationModelCatalog"
            visible: root.fixedCatalog; Layout.fillWidth: true
            model: root.available.map(row => row.name)
            Accessible.name: I18n.t("模型")
        }
        ActionButton {
            objectName: "addGenerationModel"; glyph: "plus"; text: I18n.t("添加模型")
            enabled: root.fixedCatalog ? root.available.length > 0
                : newModel.text.trim().length > 0 && !root.models.includes(newModel.text.trim())
            onClicked: root.addModel()
        }
    }
}
