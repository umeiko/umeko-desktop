import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

Column {
    id: root
    property var manager: backend.providerPlugins
    property string currentId: ""
    property string exportKind: "sdk"
    property var uninstallTarget: ({})
    spacing: 14
    function acceptsPackage(urls) {
        return urls.length === 1 && String(urls[0]).toLowerCase().startsWith("file:") && String(urls[0]).toLowerCase().endsWith(".zip")
    }
    function importPackage(url) {
        if (root.manager.importZip(String(url))) importDialog.close()
        else errorDialog.open()
    }
    function installBundle(pluginId) {
        // Installing updates the Repeater synchronously and destroys its button.
        importDialog.close()
        if (!root.manager.installBundled(pluginId)) importDialog.open()
    }
    function errorText() {
        const error = root.manager.importError
        if (!error.rule) return I18n.t(error.message)
        let text = I18n.t("ZIP 条目") + ": " + JSON.stringify(error.entry) + "\n"
        text += I18n.t("命中规则") + ": " + error.rule + "\n" + I18n.t(error.detail)
        if (error.conflict) text += "\n" + I18n.t("冲突条目") + ": " + JSON.stringify(error.conflict)
        return text
    }

    SectionCard {
        width: parent.width
        ColumnLayout {
            width: parent.width; spacing: 10
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    spacing: 5
                    Text { textFormat: Text.PlainText; text: I18n.t("自定义供应商"); color: Theme.ink; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold }
                    Text { textFormat: Text.PlainText; text: root.manager.rows.length ? I18n.t("登录、可用模型和连接配置") : I18n.t("导入供应商实现，接入自定义的登录与模型服务"); color: Theme.muted; font.pixelSize: Theme.font(11) }
                }
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "importCustomProviderButton"; glyph: "plus"; hint: I18n.t("导入自定义供应商实现"); onClicked: importDialog.open() }
            }
            Text { textFormat: Text.PlainText; visible: root.manager.packages.length > 0; text: I18n.t("已安装插件"); color: Theme.muted; font.pixelSize: Theme.font(11) }
            Repeater {
                model: root.manager.packages
                RowLayout {
                    required property var modelData
                    Layout.fillWidth: true; spacing: 10
                    Text { textFormat: Text.PlainText; text: modelData.name; color: Theme.ink; font.pixelSize: Theme.font(12); elide: Text.ElideRight; Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.maximumWidth: implicitWidth }
                    HelpButton { objectName: "pluginDescription_" + modelData.id + "_" + modelData.version; help: modelData.description || ""; visible: help.trim().length > 0 }
                    Item { Layout.fillWidth: true }
                    Text { textFormat: Text.PlainText; text: "v" + modelData.version + " · " + modelData.accountCount + I18n.t(" 个账号"); color: Theme.muted; font.pixelSize: Theme.font(10) }
                    ActionButton { objectName: "addPluginAccount_" + modelData.id + "_" + modelData.version; text: I18n.t("添加账号"); quiet: true; enabled: modelData.valid && !modelData.busy; onClicked: root.manager.addAccount(modelData.id, modelData.version) }
                    ActionButton { objectName: "uninstallPlugin_" + modelData.id + "_" + modelData.version; text: I18n.t("卸载插件"); quiet: true; enabled: !modelData.busy; onClicked: { root.uninstallTarget = modelData; uninstallDialog.open() } }
                }
            }
        }
    }
    Repeater {
        model: root.manager.rows
        SectionCard {
            id: card
            required property var modelData
            width: root.width
            function credentials() {
                let values = {}
                for (let i = 0; i < authFields.count; i++) {
                    const item = authFields.itemAt(i)
                    values[item.fieldKey] = item.value
                }
                return JSON.stringify(values)
            }
            function clearSecrets() {
                for (let i = 0; i < authFields.count; i++) {
                    const item = authFields.itemAt(i)
                    if (item.secret) item.clear()
                }
            }
            ColumnLayout {
                width: parent.width; spacing: 14
                RowLayout {
                    Layout.fillWidth: true; spacing: 12
                    Glyph { name: "server"; width: Theme.icon(21); height: Theme.icon(21) }
                    Text { textFormat: Text.PlainText; text: card.modelData.name; color: Theme.ink; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.maximumWidth: implicitWidth }
                    HelpButton { objectName: "providerDescription_" + card.modelData.id; help: card.modelData.description || ""; visible: help.trim().length > 0 }
                    Text { textFormat: Text.PlainText; text: "v" + card.modelData.version; color: Theme.muted; font.pixelSize: Theme.font(10) }
                    Item { Layout.fillWidth: true }
                    ProviderProxy { providerId: card.modelData.id; enabled: !card.modelData.busy }
                    ActionButton { objectName: "removePluginAccount_" + card.modelData.id; glyph: "trash"; quiet: true; hint: I18n.t("删除账号，保留已安装插件"); enabled: !card.modelData.busy; onClicked: root.manager.remove(card.modelData.id) }
                }
                GridLayout {
                    Layout.fillWidth: true; columns: width > 550 ? 2 : 1; columnSpacing: 16; rowSpacing: 10
                    Repeater {
                        id: authFields
                        model: card.modelData.fields
                        ColumnLayout {
                            required property var modelData
                            property string fieldKey: modelData.key
                            property bool secret: modelData.secret
                            property alias value: field.text
                            function clear() { field.clear() }
                            Layout.fillWidth: true; spacing: 7
                            Text { textFormat: Text.PlainText; text: I18n.t(modelData.label); color: Theme.ink; font.pixelSize: Theme.font(11) }
                            InputField {
                                id: field; objectName: "pluginAuth_" + card.modelData.id + "_" + fieldKey
                                Layout.fillWidth: true; enabled: !card.modelData.busy
                                text: modelData.value; echoMode: secret ? TextInput.Password : TextInput.Normal
                                placeholderText: secret && modelData.hasValue ? I18n.t("已保存，账号未变时留空可继续使用") : I18n.t("输入") + I18n.t(modelData.label)
                            }
                        }
                    }
                }
                Text { textFormat: Text.PlainText; text: I18n.t(card.modelData.status); color: Theme.muted; font.pixelSize: Theme.font(11); wrapMode: Text.Wrap; Layout.fillWidth: true }
                Repeater {
                    model: card.modelData.cardActions || []
                    ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true; spacing: 5
                        ActionButton {
                            objectName: "pluginCardAction_" + card.modelData.id + "_" + modelData.key
                            text: modelData.label; enabled: !card.modelData.busy
                            onClicked: root.manager.cardAction(card.modelData.id, modelData.key)
                        }
                        Text { textFormat: Text.PlainText; visible: !!modelData.hint; text: modelData.hint; color: Theme.muted; font.pixelSize: Theme.font(11); wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
                Text { textFormat: Text.PlainText; visible: !!card.modelData.cardStatus; text: card.modelData.cardStatus || ""; color: Theme.muted; font.pixelSize: Theme.font(11); wrapMode: Text.Wrap; Layout.fillWidth: true }
                RowLayout {
                    Layout.fillWidth: true; spacing: 8
                    ActionButton { text: I18n.t("连接配置"); quiet: true; enabled: !card.modelData.busy; onClicked: { root.currentId = card.modelData.id; configEditor.text = root.manager.configJson(root.currentId); configDialog.open() } }
                    ActionButton { objectName: "refreshPluginModels_" + card.modelData.id; text: I18n.t("刷新模型"); quiet: true; enabled: !card.modelData.busy; onClicked: root.manager.refreshModels(card.modelData.id) }
                    Item { Layout.fillWidth: true }
                    ActionButton { objectName: "loginPlugin_" + card.modelData.id; text: card.modelData.busy ? I18n.t("连接中…") : I18n.t("登录并刷新模型"); primary: true; enabled: !card.modelData.busy; onClicked: { const id = card.modelData.id; const values = card.credentials(); card.clearSecrets(); root.manager.login(id, values) } }
                }
                Repeater {
                    model: card.modelData.cardFields || []
                    ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true; spacing: 7
                        Text { textFormat: Text.PlainText; text: modelData.label; color: Theme.ink; font.pixelSize: Theme.font(12); font.weight: Font.DemiBold; Layout.fillWidth: true; wrapMode: Text.Wrap }
                        Text { textFormat: Text.PlainText; visible: !!modelData.hint; text: modelData.hint; color: Theme.muted; font.pixelSize: Theme.font(11); Layout.fillWidth: true; wrapMode: Text.Wrap }
                        RowLayout {
                            Layout.fillWidth: true; spacing: 8
                            InputField {
                                id: extraSecret; objectName: "pluginCardSecret_" + card.modelData.id + "_" + modelData.key
                                Layout.fillWidth: true; echoMode: TextInput.Password; enabled: !card.modelData.busy
                                placeholderText: modelData.hasValue ? I18n.t("密钥已保存，输入可替换") : I18n.t("输入密钥")
                            }
                            ActionButton {
                                objectName: "savePluginCardSecret_" + card.modelData.id + "_" + modelData.key
                                text: I18n.t("保存密钥"); enabled: !card.modelData.busy && extraSecret.text.trim().length > 0
                                onClicked: { const value = extraSecret.text; extraSecret.clear(); root.manager.saveCardSecret(card.modelData.id, modelData.key, value) }
                            }
                            ActionButton { visible: !!modelData.link; text: I18n.t("申请密钥"); quiet: true; onClicked: Qt.openUrlExternally(modelData.link) }
                        }
                        Text { textFormat: Text.PlainText; visible: !!modelData.message; text: modelData.message; color: Theme.muted; font.pixelSize: Theme.font(11); Layout.fillWidth: true; wrapMode: Text.Wrap }
                    }
                }
                Rectangle { visible: card.modelData.models.length > 0; Layout.fillWidth: true; implicitHeight: 1; color: Theme.line }
                RowLayout {
                    visible: card.modelData.models.length > 0; Layout.fillWidth: true
                    Text { textFormat: Text.PlainText; text: I18n.t("可用模型 · ") + card.modelData.models.length; color: Theme.ink; font.pixelSize: Theme.font(12) }
                    Item { Layout.fillWidth: true }
                    ActionButton { objectName: "managePluginModels_" + card.modelData.id; text: I18n.t("模型设置"); quiet: true; enabled: !card.modelData.busy; onClicked: { root.currentId = card.modelData.id; modelsEditor.load(card.modelData.models); modelsDialog.open() } }
                }
                Text {
                    visible: card.modelData.models.length > 0; Layout.fillWidth: true
                    text: card.modelData.models.slice(0, 8).map(m => m.alias).join("  ·  ") + (card.modelData.models.length > 8 ? "  …" : "")
                    color: Theme.muted; font.pixelSize: Theme.font(11); wrapMode: Text.Wrap
                }
            }
        }
    }
    Popup {
        id: uninstallDialog; objectName: "uninstallProviderDialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(480, parent.width - 48); padding: 24; modal: true; focus: true
        background: Rectangle { radius: 14; color: Theme.surface; border.color: Theme.line }
        contentItem: ColumnLayout {
            spacing: 14
            Text { textFormat: Text.PlainText; text: I18n.t("卸载插件") + " · " + (root.uninstallTarget.name || ""); color: Theme.ink; font.pixelSize: Theme.font(16); Layout.fillWidth: true; wrapMode: Text.Wrap }
            Text { textFormat: Text.PlainText; text: I18n.t("卸载此版本的插件及其关联账号和登录凭据。其他插件和版本不受影响，卸载后可重新安装同版本修正版。"); color: Theme.muted; font.pixelSize: Theme.font(12); Layout.fillWidth: true; wrapMode: Text.Wrap }
            RowLayout {
                Layout.fillWidth: true; Item { Layout.fillWidth: true }
                ActionButton { text: I18n.t("取消"); quiet: true; onClicked: uninstallDialog.close() }
                ActionButton { objectName: "confirmUninstallProviderButton"; text: I18n.t("卸载插件"); primary: true; onClicked: { if (root.manager.uninstall(root.uninstallTarget.id, root.uninstallTarget.version)) uninstallDialog.close() } }
            }
        }
    }
    Popup {
        id: errorDialog; objectName: "providerImportErrorDialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(650, parent.width - 48); height: Math.min(360, parent.height - 64)
        padding: 24; modal: true; focus: true
        background: Rectangle { radius: 14; color: Theme.surface; border.color: Theme.line }
        contentItem: ColumnLayout {
            spacing: 14
            Text { textFormat: Text.PlainText; text: I18n.t("供应商导入失败"); color: Theme.ink; font.pixelSize: Theme.font(17) }
            ScrollView {
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                TextArea { objectName: "providerImportErrorText"; text: root.errorText(); readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; color: Theme.ink; font.pixelSize: Theme.font(12); selectionColor: Theme.selectionBg; selectedTextColor: Theme.selectionText; background: Rectangle { radius: 8; color: Theme.bg } }
            }
            RowLayout {
                Layout.fillWidth: true; Item { Layout.fillWidth: true }
                ActionButton { text: I18n.t("复制错误详情"); quiet: true; onClicked: backend.copy(root.errorText()) }
                ActionButton { objectName: "closeProviderImportErrorButton"; text: I18n.t("关闭"); onClicked: errorDialog.close() }
            }
        }
    }
    Popup {
        id: importDialog; objectName: "customProviderImportDialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(580, parent.width - 48); padding: 24; modal: true; focus: true
        background: Rectangle { radius: 14; color: Theme.surface; border.color: Theme.line }
        contentItem: ColumnLayout {
            spacing: 18
            RowLayout {
                Layout.fillWidth: true
                Text { textFormat: Text.PlainText; text: I18n.t("导入自定义供应商实现"); color: Theme.ink; font.pixelSize: Theme.font(18); font.weight: Font.Medium }
                Item { Layout.fillWidth: true }
                ActionButton { glyph: "x"; quiet: true; onClicked: importDialog.close() }
            }
            Text { textFormat: Text.PlainText; text: I18n.t("选择包含 manifest.json 的供应商 ZIP 包。导入后即可在本页登录、查看和配置可用模型。"); Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.ink; font.pixelSize: Theme.font(12) }
            Text { textFormat: Text.PlainText; visible: root.manager.availableBundles.length > 0; text: I18n.t("随应用提供的供应商"); color: Theme.ink; font.pixelSize: Theme.font(12) }
            Repeater {
                model: root.manager.availableBundles
                RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    Text { textFormat: Text.PlainText; text: modelData.name; color: Theme.ink; font.pixelSize: Theme.font(12); Layout.fillWidth: true }
                    ActionButton { objectName: "installBundledProvider_" + modelData.id; text: I18n.t("安装供应商"); onClicked: root.installBundle(modelData.id) }
                }
            }
            Rectangle {
                Layout.fillWidth: true; implicitHeight: 104; radius: 10
                color: packageDrop.containsDrag ? Theme.accentBg : Theme.bg
                border.color: packageDrop.containsDrag ? Theme.accent : Theme.line
                border.width: packageDrop.containsDrag ? 2 : 1
                ColumnLayout {
                    anchors.centerIn: parent; spacing: 9
                    Text { textFormat: Text.PlainText; text: packageDrop.containsDrag ? I18n.t("松开鼠标，导入供应商") : I18n.t("将供应商 ZIP 拖到这里"); color: Theme.ink; font.pixelSize: Theme.font(12); Layout.alignment: Qt.AlignHCenter }
                    ActionButton { objectName: "chooseProviderZipButton"; text: I18n.t("选择供应商 ZIP"); glyph: "plus"; primary: true; Layout.alignment: Qt.AlignHCenter; onClicked: packagePicker.open() }
                }
                DropArea {
                    id: packageDrop; objectName: "providerPackageDropArea"; anchors.fill: parent
                    onEntered: drag => { drag.accepted = drag.hasUrls && root.acceptsPackage(drag.urls) }
                    onDropped: drop => {
                        if (!drop.hasUrls || !root.acceptsPackage(drop.urls)) { drop.accepted = false; return }
                        const url = drop.urls[0]
                        drop.acceptProposedAction()
                        root.importPackage(url)
                    }
                }
            }
            Text { textFormat: Text.PlainText; text: I18n.t("供应商实现会在本机执行代码，请使用可信来源的包。"); color: Theme.muted; font.pixelSize: Theme.font(11); wrapMode: Text.Wrap; Layout.fillWidth: true }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.line }
            Text { textFormat: Text.PlainText; text: I18n.t("开发自定义供应商"); color: Theme.ink; font.pixelSize: Theme.font(13); font.weight: Font.DemiBold }
            Text { textFormat: Text.PlainText; text: I18n.t("SDK 包含公共接口、示例与打包工具；开发 Skill 可交给你的 AI，协助编写、验证和打包供应商。"); Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(11) }
            RowLayout {
                ActionButton { objectName: "exportProviderSdkButton"; text: I18n.t("导出 Provider SDK"); onClicked: { root.exportKind = "sdk"; resourcePicker.selectedFile = root.manager.resourceFile("sdk"); resourcePicker.open() } }
                ActionButton { objectName: "exportProviderSkillButton"; text: I18n.t("导出开发 Skill"); onClicked: { root.exportKind = "skill"; resourcePicker.selectedFile = root.manager.resourceFile("skill"); resourcePicker.open() } }
            }
        }
    }
    FileDialog {
        id: packagePicker; title: I18n.t("导入自定义供应商实现"); nameFilters: ["Provider packages (*.zip)"]
        onAccepted: root.importPackage(selectedFile)
    }
    FileDialog {
        id: resourcePicker; title: I18n.t("保存开发资源"); fileMode: FileDialog.SaveFile; nameFilters: ["ZIP archives (*.zip)"]
        onAccepted: root.manager.exportResource(root.exportKind, selectedFile.toString())
    }
    Popup {
        id: configDialog; parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(750, parent.width - 48); height: Math.min(580, parent.height - 64); padding: 24; modal: true; focus: true
        background: Rectangle { radius: 14; color: Theme.surface; border.color: Theme.line }
        contentItem: ColumnLayout {
            spacing: 12
            Text { textFormat: Text.PlainText; text: I18n.t("供应商连接配置"); color: Theme.ink; font.pixelSize: Theme.font(17) }
            Text { textFormat: Text.PlainText; text: I18n.t("由插件定义的非秘密配置。账号、密码和令牌由系统凭据保护单独保存。"); color: Theme.muted; font.pixelSize: Theme.font(11); Layout.fillWidth: true; wrapMode: Text.Wrap }
            ScrollView {
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                TextArea { id: configEditor; objectName: "pluginConfigEditor"; color: Theme.ink; selectionColor: Theme.selectionBg; selectedTextColor: Theme.selectionText; selectByMouse: true; font.family: "Consolas"; wrapMode: TextEdit.Wrap; background: Rectangle { color: Theme.bg; radius: 8 } }
            }
            RowLayout { Layout.fillWidth: true; Item { Layout.fillWidth: true } ActionButton { text: I18n.t("取消"); quiet: true; onClicked: configDialog.close() } ActionButton { text: I18n.t("保存配置"); primary: true; onClicked: { if (root.manager.saveConfig(root.currentId, configEditor.text)) configDialog.close() } } }
        }
    }
    Popup {
        id: modelsDialog; objectName: "pluginModelsDialog"; parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(820, parent.width - 48); height: Math.min(600, parent.height - 64); padding: 24; modal: true; focus: true
        background: Rectangle { radius: 14; color: Theme.surface; border.color: Theme.line }
        contentItem: ColumnLayout {
            spacing: 16
            Text { textFormat: Text.PlainText; text: I18n.t("模型设置"); color: Theme.ink; font.pixelSize: Theme.font(17) }
            ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth; clip: true
                ProviderModels { id: modelsEditor; width: parent.width; fixedModels: true }
            }
            RowLayout { Layout.fillWidth: true; Item { Layout.fillWidth: true } ActionButton { text: I18n.t("取消"); quiet: true; onClicked: modelsDialog.close() } ActionButton { objectName: "savePluginModelsButton"; text: I18n.t("保存模型设置"); primary: true; onClicked: { if (root.manager.saveModels(root.currentId, modelsEditor.json())) modelsDialog.close() } } }
        }
    }
}
