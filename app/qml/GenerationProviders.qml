import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

SectionCard {
    id: root
    required property string kind
    required property var accounts
    readonly property var manager: backend.providerPlugins

    function editProvider(account) {
        if (account.api === "plugin") pluginEditor.begin(account.id)
        else nativeEditor.openFor(kind, account)
    }

    ColumnLayout {
        width: parent.width; spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: I18n.t("供应商"); color: Theme.ink
                font.family: Theme.fontFamily; font.pixelSize: Theme.font(14, visible); font.weight: Font.DemiBold
            }
            ActionButton {
                objectName: "addGenerationProvider"
                text: I18n.t("添加供应商"); glyph: "plus"
                onClicked: nativeEditor.openFor(root.kind)
            }
        }
        Text {
            visible: !root.accounts.length; Layout.fillWidth: true
            text: I18n.t("暂无供应商"); color: Theme.muted
            font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible)
        }
        Repeater {
            model: root.accounts
            ItemDelegate {
                id: row
                required property var modelData
                objectName: "editGenerationProvider_" + modelData.id
                Layout.fillWidth: true
                padding: 12; implicitHeight: Math.max(46, nameLabel.implicitHeight + 24)
                Accessible.name: nameLabel.text
                background: Rectangle {
                    color: row.hovered ? Theme.hover : Theme.bg; radius: 8
                    border.color: row.activeFocus ? Theme.accent : Theme.line
                }
                contentItem: RowLayout {
                    spacing: 10
                    Text {
                        id: nameLabel; Layout.fillWidth: true
                        text: I18n.t(row.modelData.name) + (row.modelData.accountLabel ? " · " + row.modelData.accountLabel : "")
                        textFormat: Text.PlainText; elide: Text.ElideRight
                        font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible); color: Theme.ink
                    }
                    Text {
                        text: I18n.modelCount(row.modelData.models[root.kind].length); color: Theme.muted
                        font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible)
                    }
                    Glyph { name: "chevron-right"; width: Theme.icon(16); height: width; color: Theme.muted }
                }
                onClicked: root.editProvider(modelData)
            }
        }
    }
    ImageProviderDialog {
        id: nativeEditor
        onZipRequested: zipPicker.open()
    }
    FileDialog {
        id: zipPicker
        objectName: "generationZipPicker"
        title: I18n.t("导入供应商 ZIP"); nameFilters: ["Provider packages (*.zip)"]
        onAccepted: {
            const identifier = root.manager.importGenerationZip(String(selectedFile), root.kind)
            if (identifier) pluginEditor.begin(identifier)
            else importError.open()
        }
    }
    PidPopup {
        id: importError
        objectName: "generationZipError"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(440, parent.width - 32)
        height: errorBody.implicitHeight + padding * 2
        contentItem: ColumnLayout {
            id: errorBody
            spacing: 12
            Text {
                Layout.fillWidth: true
                text: I18n.t("供应商导入失败"); color: Theme.ink
                font.family: Theme.fontFamily; font.pixelSize: Theme.font(15, visible); font.weight: Font.DemiBold
            }
            Text {
                Layout.fillWidth: true; wrapMode: Text.WrapAnywhere; textFormat: Text.PlainText
                text: I18n.t(root.manager.importError.message); color: Theme.muted
                font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible)
            }
            ActionButton {
                Layout.alignment: Qt.AlignRight
                text: I18n.t("关闭"); onClicked: importError.close()
            }
        }
    }
    PidPopup {
        id: pluginEditor
        objectName: "generationPluginEditor"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(668, parent.width - 32)
        height: Math.min(pluginBody.implicitHeight + pluginEditor.padding * 2, parent.height - 32)
        property string providerId: ""
        property bool modelsEdited: false
        readonly property var account: root.accounts.find(p => p.id === providerId)
        readonly property string modelSignature: JSON.stringify(account ? account.models[root.kind] : [])
        function begin(identifier) {
            providerId = identifier
            modelsEdited = false
            modelEditor.load(account ? account.models[root.kind] : [])
            pluginScroll.contentItem.contentY = 0
            open()
        }
        onModelSignatureChanged: {
            if (visible && !account) close()
            if (visible && account && !modelsEdited) modelEditor.load(account.models[root.kind])
        }
        contentItem: Item {
            ColumnLayout {
                id: pluginBody
                anchors.fill: parent; spacing: 12
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        text: I18n.t("编辑供应商"); color: Theme.ink
                        font.family: Theme.fontFamily; font.pixelSize: Theme.font(16, visible); font.weight: Font.DemiBold
                    }
                    ActionButton {
                        glyph: "x"; hint: I18n.t("关闭"); quiet: true; Accessible.name: hint
                        onClicked: pluginEditor.close()
                    }
                }
                ScrollView {
                    id: pluginScroll
                    Layout.fillWidth: true; Layout.fillHeight: true
                    contentWidth: availableWidth; contentHeight: editContent.implicitHeight
                    implicitHeight: editContent.implicitHeight; clip: true
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                    Column {
                        id: editContent
                        width: pluginScroll.availableWidth; spacing: 12
                        Loader {
                            width: parent.width; active: pluginEditor.visible && !!pluginEditor.account
                            sourceComponent: ProviderPluginsSection {
                                onlyProviderId: pluginEditor.providerId
                            }
                        }
                        SectionCard {
                            width: parent.width
                            GenerationModelsEditor {
                                id: modelEditor; width: parent.width
                                onEdited: pluginEditor.modelsEdited = true
                            }
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }
                    ActionButton { text: I18n.t("关闭"); quiet: true; onClicked: pluginEditor.close() }
                    ActionButton {
                        objectName: "saveGenerationPluginModels"
                        text: I18n.t("保存模型"); primary: true; enabled: pluginEditor.modelsEdited
                        onClicked: {
                            if (root.manager.saveGenerationModels(pluginEditor.providerId, root.kind, JSON.stringify(modelEditor.models)))
                                pluginEditor.modelsEdited = false
                        }
                    }
                }
            }
        }
    }
}
