import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property int tab: 0
    signal tabSelected(int value)
    signal back()
    property bool editingProvider: false
    property bool editingCommon: false
    property string editId: ""
    CommonProviderDialog { id: commonProviders }
    property string mappingSignature: ""
    property string mappingProviderId: ""
    readonly property var mappingAccount: backend.config.providers.find(p => p.id === mappingProviderId) || null
    property var activeInlineScroll: null
    function activateInlineScroll(item) { activeInlineScroll = item }
    function scrollSettings(delta) {
        const flick = settingsScroll.contentItem
        flick.cancelFlick()
        flick.contentY = Math.max(0, Math.min(Math.max(0, flick.contentHeight - flick.height), flick.contentY - delta))
    }
    onTabChanged: activeInlineScroll = null
    onVisibleChanged: if (!visible) activeInlineScroll = null
    TapHandler {
        onPressedChanged: if (pressed && root.activeInlineScroll) {
            const target = root.activeInlineScroll
            const p = root.mapToItem(target, point.position.x, point.position.y)
            if (p.x < 0 || p.y < 0 || p.x > target.width || p.y > target.height) {
                root.activeInlineScroll = null
                root.forceActiveFocus()
            }
        }
    }
    function editProvider(p) {
        editingCommon = !!(p && p.presetId)
        editId = p ? p.id : ""
        providerName.text = p ? p.name : ""
        providerUrl.text = p ? p.baseUrl : ""
        providerKey.clear()
        providerKey.placeholderText = p && p.hasKey ? I18n.t("已保存，留空保持现有密钥") : I18n.t("输入 API Key")
        providerModels.load(p ? p.models : [])
        providerProtocol.currentIndex = p && p.api === "anthropic" ? 1 : 0
        editingProvider = true
    }
    function toggleProvider(p) {
        if (editingProvider && editId === p.id) {
            editingProvider = false
            providerKey.clear()
        } else editProvider(p)
    }
    function openMappingProvider(identifier) {
        mappingProviderId = identifier
        Qt.callLater(() => {
            const flick = settingsScroll.contentItem
            const top = flick.contentY + mappingsSection.mapToItem(flick, Qt.point(0, 0)).y
            flick.contentY = Math.max(0, Math.min(top, flick.contentHeight - flick.height))
        })
    }
    function reloadMappings() {
        const signature = JSON.stringify(backend.config.providers.map(p => ({id:p.id, name:p.name, models:p.models})))
        if (signature === mappingSignature) return
        mappingSignature = signature
        if (mappingProviderId && !backend.config.providers.some(p => p.id === mappingProviderId)) mappingProviderId = ""
        mappingRows.clear()
        backend.config.providers.forEach(p => p.models.forEach(m => mappingRows.append({provider:p.id, providerName:p.name, upstream:m.upstream, alias:m.alias, contextWindowText:String(m.contextWindow), contextWindowAuto:m.contextWindowAuto, visionValue:m.vision, visionAuto:m.visionAuto})))
    }
    Component.onCompleted: reloadMappings()
    Connections { target: backend; function onChanged() { root.reloadMappings() } }
    ListModel { id: mappingRows }
    ColumnLayout {
        anchors.fill: parent; anchors.leftMargin: 40; anchors.rightMargin: 40; anchors.topMargin: 19; anchors.bottomMargin: 24; spacing: 0
        RowLayout {
            Layout.fillWidth: true
            Text { text: I18n.t("设置"); font.pixelSize: Theme.font(24); font.weight: Font.Medium; color: Theme.ink }
            Item { Layout.fillWidth: true }
            ActionButton { text: I18n.t("返回会话"); glyph: "arrow-left"; quiet: true; onClicked: root.back() }
        }
        Item {
            id: settingsNav
            Layout.topMargin: 30; Layout.alignment: Qt.AlignLeft
            implicitWidth: tabButtons.implicitWidth; implicitHeight: tabButtons.implicitHeight
            property Item selectedButton: null
            function syncTarget() {
                let selected = null
                for (let i = 0; i < tabItems.count; i++) {
                    const button = tabItems.itemAt(i)
                    if (button && button.modelData.id === root.tab) { selected = button; break }
                }
                selectedButton = selected
            }
            Component.onCompleted: Qt.callLater(syncTarget)
            Connections { target: root; function onTabChanged() { settingsNav.syncTarget() } }
            PidHighlight {
                height: settingsNav.selectedButton ? settingsNav.selectedButton.height : 38
                targetX: settingsNav.selectedButton ? settingsNav.selectedButton.x : 0
                targetWidth: settingsNav.selectedButton ? settingsNav.selectedButton.width : 0
            }
            Row {
                id: tabButtons; z: 1; spacing: 8
                Repeater {
                    id: tabItems
                    model: [{id:0, title:I18n.t("账号与供应商")}, {id:1, title:I18n.t("API 代理服务")}, {id:3, title:"Agent"}, {id:5, title:I18n.t("外观")}, {id:6, title:I18n.t("关于")}]
                    onItemAdded: Qt.callLater(settingsNav.syncTarget)
                    ActionButton {
                        required property var modelData
                        objectName: "settingsTab_" + modelData.id
                        text: modelData.title; quiet: true
                        onClicked: root.tabSelected(modelData.id)
                        background: Rectangle { radius: 7; color: parent.hovered && root.tab !== modelData.id ? Theme.hover : "transparent" }
                    }
                }
            }
        }
        Rectangle { Layout.fillWidth: true; Layout.topMargin: 15; height: 1; color: Theme.line }
        ScrollView {
            id: settingsScroll; objectName: "settingsScroll"; Layout.fillWidth: true; Layout.fillHeight: true; Layout.topMargin: 23
            Connections { target: root; function onTabChanged() { settingsScroll.contentItem.contentY = 0 } }
            contentWidth: availableWidth; clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            Column {
                id: settingsContent
                width: settingsScroll.availableWidth; spacing: 18

                Column {
                    visible: root.tab === 0; width: parent.width; spacing: 18
                    ProviderPluginsSection { width: parent.width }
                    SectionCard {
                        objectName: "commonProvidersSection"
                        width: parent.width
                        ColumnLayout {
                            id: commonProviderContent
                            width: parent.width; spacing: 18
                            RowLayout {
                                Layout.fillWidth: true; spacing: 16
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 5
                                    Text { text: I18n.t("常见供应商"); color: Theme.ink; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold }
                                    Text { Layout.fillWidth: true; text: I18n.t("填写 API Key，快速接入常见模型服务"); color: Theme.muted; font.pixelSize: Theme.font(11); wrapMode: Text.Wrap }
                                }
                                ActionButton { objectName: "addCommonProviderButton"; glyph: "plus"; hint: I18n.t("添加常见供应商"); onClicked: commonProviders.open() }
                            }
                            ProviderAccountList {
                                objectName: "commonProviderAccounts"; Layout.fillWidth: true
                                accounts: backend.config.providers.filter(p => (p.api === "openai" || p.api === "anthropic") && !!p.presetId)
                                editing: root.editingProvider; editingId: root.editId
                                onEditProvider: provider => root.toggleProvider(provider)
                            }
                        }
                    }
                    SectionCard {
                        objectName: "apiProvidersSection"
                        width: parent.width
                        ColumnLayout { id: apiProviderContent; width: parent.width; spacing: 18
                            RowLayout { Layout.fillWidth: true
                                Text { text: I18n.t("API 供应商"); color: Theme.ink; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold }
                                HelpButton { help: I18n.t("手动配置 API 地址和密钥。一个供应商可以添加多个模型，在聊天框底部选择使用。只连接你明确保存的服务地址。") }
                                Item { Layout.fillWidth: true }
                                ActionButton { objectName: "addProviderButton"; text: I18n.t("添加供应商"); glyph: "plus"; onClicked: root.editProvider(null) }
                            }
                            Text { visible: backend.config.providers.filter(p => (p.api === "openai" || p.api === "anthropic") && !p.presetId).length === 0 && (!root.editingProvider || root.editingCommon); text: I18n.t("暂无 API 供应商"); color: Theme.muted; font.pixelSize: Theme.font(11); Layout.topMargin: 8; Layout.bottomMargin: 8 }
                            ProviderAccountList {
                                objectName: "apiProviderAccounts"; Layout.fillWidth: true
                                accounts: backend.config.providers.filter(p => (p.api === "openai" || p.api === "anthropic") && !p.presetId)
                                editing: root.editingProvider; editingId: root.editId
                                onEditProvider: provider => root.toggleProvider(provider)
                            }
                            ColumnLayout {
                                id: providerEditor; objectName: "providerEditor"
                                parent: root.editingCommon ? commonProviderContent : apiProviderContent
                                visible: root.editingProvider; Layout.fillWidth: true; spacing: 15
                                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
                                RowLayout { Layout.fillWidth: true; spacing: 16
                                    ColumnLayout { Layout.fillWidth: true; spacing: 8
                                        Text { text: I18n.t("供应商名称"); color: Theme.ink; font.pixelSize: Theme.font(11) }
                                        InputField { id: providerName; objectName: "providerName"; Layout.fillWidth: true; placeholderText: I18n.t("例如：我的模型服务") }
                                    }
                                    ColumnLayout { Layout.preferredWidth: 190; Layout.fillWidth: false; spacing: 8
                                        Text { text: I18n.t("API 协议"); color: Theme.ink; font.pixelSize: Theme.font(11) }
                                        Picker { id: providerProtocol; Layout.fillWidth: true; model: [I18n.t("OpenAI 兼容"), I18n.t("Anthropic 兼容")] }
                                    }
                                }
                                ColumnLayout { Layout.fillWidth: true; spacing: 8
                                    RowLayout { Text { text: "Base URL"; color: Theme.ink; font.pixelSize: Theme.font(11) } HelpButton { help: I18n.t("OpenAI 兼容地址需包含服务的版本路径，例如 /v1；Anthropic 地址可填根路径或 /v1。") } }
                                    InputField { id: providerUrl; objectName: "providerUrl"; Layout.fillWidth: true; placeholderText: I18n.t("https://你的服务地址/v1") }
                                }
                                ColumnLayout { Layout.fillWidth: true; spacing: 8
                                    RowLayout { Text { text: "API Key"; color: Theme.ink; font.pixelSize: Theme.font(11) } HelpButton { help: I18n.t("密钥使用系统凭据保护保存。编辑供应商时留空可保持已有密钥。") } }
                                    InputField { id: providerKey; objectName: "providerKey"; Layout.fillWidth: true; echoMode: TextInput.Password; placeholderText: I18n.t("输入 API Key") }
                                }
                                ProviderModels { id: providerModels; objectName: "providerModelsEditor"; Layout.fillWidth: true }
                                RowLayout { Layout.fillWidth: true
                                    Item { Layout.fillWidth: true }
                                    ActionButton { text: I18n.t("收起"); quiet: true; onClicked: root.editingProvider = false }
                                    ActionButton { objectName: "saveProviderButton"; text: I18n.t("保存供应商"); primary: true; onClicked: { if (backend.saveProvider(root.editId, providerName.text, providerProtocol.currentIndex === 0 ? "openai" : "anthropic", providerUrl.text, providerKey.text, providerModels.json())) { providerKey.clear(); root.editingProvider = false } } }
                                }
                            }
                        }
                    }
                }

                ApiProxySettings { visible: root.tab === 1; width: parent.width }

                Column {
                    id: mappingsSection; objectName: "proxyMappingsSection"
                    visible: root.tab === 1; width: parent.width; spacing: 18
                    SectionCard {
                        width: parent.width
                        ColumnLayout { width: parent.width; spacing: 20
                            RowLayout { Layout.fillWidth: true
                                ActionButton { objectName: "backToMappingProviders"; visible: !!root.mappingAccount; glyph: "arrow-left"; quiet: true; hint: I18n.t("返回供应商"); onClicked: root.openMappingProvider("") }
                                Text { text: root.mappingAccount ? root.mappingAccount.name : I18n.t("模型映射"); textFormat: Text.PlainText; color: Theme.ink; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold; Layout.fillWidth: true; elide: Text.ElideRight }
                                HelpButton { objectName: "mappingHelp"; help: I18n.t("左侧填写供应商的原始模型名称，右侧是聊天与 API 代理服务使用的别名。每个供应商可有多条映射，别名必须唯一。插件供应商的模型 ID 由模型发现提供。") }
                            }
                            ColumnLayout { visible: !root.mappingAccount; Layout.fillWidth: true; spacing: 8
                                Text { visible: backend.config.providers.length === 0; text: I18n.t("添加供应商后设置模型别名"); color: Theme.muted; font.pixelSize: Theme.font(11) }
                                Repeater { model: backend.config.providers
                                    ItemDelegate {
                                        required property var modelData
                                        objectName: "mappingProvider_" + modelData.id
                                        Layout.fillWidth: true; implicitHeight: Math.max(64, providerLabel.implicitHeight + 28)
                                        background: Rectangle { radius: 9; color: parent.hovered ? Theme.accentBg : Theme.bg }
                                        contentItem: RowLayout { spacing: 12
                                            ColumnLayout { id: providerLabel; Layout.fillWidth: true; spacing: 3
                                                Text { text: modelData.name; textFormat: Text.PlainText; color: Theme.ink; font.pixelSize: Theme.font(12); Layout.fillWidth: true; elide: Text.ElideRight }
                                                Text { text: modelData.models.length + I18n.t(" 个模型"); color: Theme.muted; font.pixelSize: Theme.font(10) }
                                            }
                                            Glyph { name: "chevron-right"; width: Theme.icon(18); height: Theme.icon(18); color: Theme.muted }
                                        }
                                        onClicked: root.openMappingProvider(modelData.id)
                                    }
                                }
                            }
                            ColumnLayout { visible: !!root.mappingAccount; Layout.fillWidth: true; spacing: 20
                            RowLayout { Layout.fillWidth: true; spacing: 14
                                Text { text: I18n.t("原始模型名称"); color: Theme.muted; font.pixelSize: Theme.font(10); Layout.fillWidth: true; Layout.preferredWidth: 1 }
                                Item { Layout.preferredWidth: 24 }
                                Text { text: I18n.t("对外模型别名"); color: Theme.muted; font.pixelSize: Theme.font(10); Layout.fillWidth: true; Layout.preferredWidth: 1 }
                                Item { Layout.preferredWidth: 34 }
                            }
                            Repeater {
                                model: mappingRows
                                Loader {
                                    id: mappingDelegate
                                    required property int index
                                    required property string provider
                                    readonly property bool pluginModel: { const p = backend.config.providers.find(p => p.id === provider); return p ? p.api === "plugin" : false }
                                    required property string providerName
                                    required property string upstream
                                    required property string alias
                                    required property string contextWindowText
                                    required property bool contextWindowAuto
                                    required property bool visionValue
                                    required property bool visionAuto
                                    active: provider === root.mappingProviderId
                                    visible: active; Layout.fillWidth: true
                                    sourceComponent: ColumnLayout {
                                    width: parent ? parent.width : 0; spacing: 4
                                    RowLayout {
                                        Layout.fillWidth: true; spacing: 14
                                        InputField { objectName: "mappingModelId_" + mappingDelegate.index; readOnly: mappingDelegate.pluginModel; text: mappingDelegate.upstream; Layout.fillWidth: true; Layout.preferredWidth: 1; onTextEdited: mappingRows.setProperty(mappingDelegate.index, "upstream", text) }
                                        Glyph { name: "arrow-right"; width: Theme.icon(24); height: Theme.icon(17) }
                                        InputField { objectName: "mappingAlias_" + mappingDelegate.index; text: mappingDelegate.alias; Layout.fillWidth: true; Layout.preferredWidth: 1; onTextEdited: mappingRows.setProperty(mappingDelegate.index, "alias", text) }
                                        ActionButton { enabled: !mappingDelegate.pluginModel; glyph: "trash"; quiet: true; width: Theme.control(34); hint: I18n.t("删除映射"); onClicked: mappingRows.remove(mappingDelegate.index) }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true; spacing: 8
                                        Text { text: I18n.t("上下文长度"); color: Theme.muted; font.pixelSize: Theme.font(11) }
                                        HelpButton { help: I18n.t("自动按原始模型名匹配，未知名称使用 128000 token。输入整数、256K 或 1M 可自定义；K=1024，M=1048576。恢复自动后跟随模型名。") }
                                        ContextWindowField {
                                            objectName: "mappingContext_" + mappingDelegate.index
                                            Layout.preferredWidth: 190; Layout.fillWidth: false
                                            modelName: mappingDelegate.upstream; customText: mappingDelegate.contextWindowText; automatic: mappingDelegate.contextWindowAuto
                                            onEdited: (value, automatic) => { mappingRows.setProperty(mappingDelegate.index, "contextWindowText", value); mappingRows.setProperty(mappingDelegate.index, "contextWindowAuto", automatic) }
                                        }
                                        VisionField {
                                            objectName: "mappingVision_" + mappingDelegate.index
                                            Layout.leftMargin: 12; Layout.preferredWidth: 190; Layout.fillWidth: false
                                            modelName: mappingDelegate.upstream; visionEnabled: mappingDelegate.visionValue; automatic: mappingDelegate.visionAuto
                                            onEdited: (value, automatic) => { mappingRows.setProperty(mappingDelegate.index, "visionValue", value); mappingRows.setProperty(mappingDelegate.index, "visionAuto", automatic) }
                                        }
                                        Item { Layout.fillWidth: true }
                                    }
                                    }
                                }
                            }
                            RowLayout { Layout.fillWidth: true; spacing: 10
                                ActionButton { objectName: "addMappingButton"; text: I18n.t("添加映射"); glyph: "plus"; enabled: !!root.mappingAccount && (root.mappingAccount.api === "openai" || root.mappingAccount.api === "anthropic"); onClicked: { const p = root.mappingAccount; if (p) mappingRows.append({provider:p.id, providerName:p.name, upstream:"", alias:"", contextWindowText:"", contextWindowAuto:true, visionValue:false, visionAuto:true}) } }
                                Item { Layout.fillWidth: true }
                                ActionButton { objectName: "saveMappingsButton"; text: I18n.t("保存映射"); primary: true; onClicked: { let rows = []; for(let i=0;i<mappingRows.count;i++) { let m=mappingRows.get(i); rows.push({provider:m.provider,upstream:m.upstream,alias:m.alias,contextWindow:m.contextWindowText,contextWindowAuto:m.contextWindowAuto,vision:m.visionValue,visionAuto:m.visionAuto}) } backend.saveMappings(JSON.stringify(rows)) } }
                            }
                            }
                        }
                    }
                }

                AgentPage { visible: root.tab === 3; width: parent.width; availableHeight: settingsScroll.availableHeight; onNavigated: Qt.callLater(() => settingsScroll.contentItem.contentY = 0) }

                AppearanceSettings { visible: root.tab === 5; width: parent.width }
                AboutPage { visible: root.tab === 6; width: parent.width }
                Item { width: 1; height: 12 }
            }
        }
    }
}
