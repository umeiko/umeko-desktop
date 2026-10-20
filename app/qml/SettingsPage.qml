import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property int tab: 0
    signal tabSelected(int value)
    signal back()
    property bool editingProvider: false
    property string editId: ""
    property string mappingSignature: ""
    function editProvider(p) {
        editId = p ? p.id : ""
        providerName.text = p ? p.name : ""
        providerUrl.text = p ? p.baseUrl : ""
        providerKey.clear()
        providerKey.placeholderText = p && p.hasKey ? "已保存，留空保持现有密钥" : "输入 API Key"
        providerModels.load(p ? p.models : [])
        providerProtocol.currentIndex = p && p.api === "anthropic" ? 1 : 0
        editingProvider = true
    }
    function reloadMappings() {
        const signature = JSON.stringify(backend.config.providers.map(p => ({id:p.id, name:p.name, models:p.models})))
        if (signature === mappingSignature) return
        mappingSignature = signature
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
            Text { text: "设置"; font.pixelSize: 24; font.weight: Font.Medium; color: Theme.ink }
            Item { Layout.fillWidth: true }
            ActionButton { text: "返回会话"; glyph: "arrow-left"; quiet: true; onClicked: root.back() }
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
                targetX: settingsNav.selectedButton ? settingsNav.selectedButton.x : 0
                targetWidth: settingsNav.selectedButton ? settingsNav.selectedButton.width : 0
            }
            Row {
                id: tabButtons; z: 1; spacing: 8
                Repeater {
                    id: tabItems
                    model: [{id:0, title:"账号与供应商"}, {id:1, title:"API 代理服务"}, {id:3, title:"Agent"}, {id:5, title:"外观"}, {id:6, title:"关于"}]
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
                        width: parent.width
                        ColumnLayout { width: parent.width; spacing: 18
                            RowLayout { Layout.fillWidth: true
                                Text { text: "API 供应商"; color: Theme.ink; font.pixelSize: 14; font.weight: Font.DemiBold }
                                HelpButton { help: "手动配置 API 地址和密钥。一个供应商可以添加多个模型，在聊天框底部选择使用。只连接你明确保存的服务地址。" }
                                Item { Layout.fillWidth: true }
                                ActionButton { objectName: "addProviderButton"; text: "添加供应商"; glyph: "plus"; onClicked: root.editProvider(null) }
                            }
                            Text { visible: backend.config.providers.filter(p => p.api === "openai" || p.api === "anthropic").length === 0 && !root.editingProvider; text: "暂无自定义供应商"; color: Theme.muted; font.pixelSize: 11; Layout.topMargin: 8; Layout.bottomMargin: 8 }
                            Repeater {
                                model: backend.config.providers.filter(p => p.api === "openai" || p.api === "anthropic")
                                ColumnLayout {
                                    required property var modelData
                                    Layout.fillWidth: true; spacing: 12
                                    RowLayout { Layout.fillWidth: true; spacing: 12
                                    Glyph { name: "server"; width: 19; height: 19 }
                                    Column { Layout.fillWidth: true; spacing: 5
                                        Text { text: modelData.name; color: Theme.ink; font.pixelSize: 12 }
                                        Text { text: modelData.baseUrl; color: Theme.muted; font.pixelSize: 10; elide: Text.ElideRight; width: 400 }
                                    }
                                    Text { text: modelData.models.length + " 个模型"; color: Theme.muted; font.pixelSize: 10 }
                                    Text { text: modelData.api === "openai" ? "OpenAI 格式" : "Anthropic 格式"; color: Theme.muted; font.pixelSize: 10 }
                                    ActionButton { objectName: "editProvider_" + modelData.id; glyph: "edit"; quiet: true; hint: "编辑供应商与模型"; onClicked: root.editProvider(modelData) }
                                    ActionButton { glyph: "trash"; quiet: true; hint: "移除供应商"; onClicked: backend.removeProvider(modelData.id) }
                                    }
                                    Flow { Layout.fillWidth: true; spacing: 7
                                        Repeater { model: modelData.models
                                            Rectangle { required property var modelData; width: chip.implicitWidth + 18; height: 27; radius: 6; color: Theme.accentBg
                                                Text { id: chip; anchors.centerIn: parent; text: modelData.alias; color: Theme.accent; font.pixelSize: 10 }
                                            }
                                        }
                                    }
                                }
                            }
                            ColumnLayout {
                                visible: root.editingProvider; Layout.fillWidth: true; spacing: 15
                                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
                                RowLayout { Layout.fillWidth: true; spacing: 16
                                    ColumnLayout { Layout.fillWidth: true; spacing: 8
                                        Text { text: "供应商名称"; color: Theme.ink; font.pixelSize: 11 }
                                        InputField { id: providerName; objectName: "providerName"; Layout.fillWidth: true; placeholderText: "例如：我的模型服务" }
                                    }
                                    ColumnLayout { Layout.preferredWidth: 190; Layout.fillWidth: false; spacing: 8
                                        Text { text: "API 协议"; color: Theme.ink; font.pixelSize: 11 }
                                        Picker { id: providerProtocol; Layout.fillWidth: true; model: ["OpenAI 兼容", "Anthropic 兼容"] }
                                    }
                                }
                                ColumnLayout { Layout.fillWidth: true; spacing: 8
                                    RowLayout { Text { text: "Base URL"; color: Theme.ink; font.pixelSize: 11 } HelpButton { help: "OpenAI 兼容地址需包含服务的版本路径，例如 /v1；Anthropic 地址可填根路径或 /v1。" } }
                                    InputField { id: providerUrl; objectName: "providerUrl"; Layout.fillWidth: true; placeholderText: "https://你的服务地址/v1" }
                                }
                                ColumnLayout { Layout.fillWidth: true; spacing: 8
                                    RowLayout { Text { text: "API Key"; color: Theme.ink; font.pixelSize: 11 } HelpButton { help: "密钥使用系统凭据保护保存。编辑供应商时留空可保持已有密钥。" } }
                                    InputField { id: providerKey; objectName: "providerKey"; Layout.fillWidth: true; echoMode: TextInput.Password; placeholderText: "输入 API Key" }
                                }
                                ProviderModels { id: providerModels; objectName: "providerModelsEditor"; Layout.fillWidth: true }
                                RowLayout { Layout.fillWidth: true
                                    Item { Layout.fillWidth: true }
                                    ActionButton { text: "收起"; quiet: true; onClicked: root.editingProvider = false }
                                    ActionButton { objectName: "saveProviderButton"; text: "保存供应商"; primary: true; onClicked: { if (backend.saveProvider(root.editId, providerName.text, providerProtocol.currentIndex === 0 ? "openai" : "anthropic", providerUrl.text, providerKey.text, providerModels.json())) { providerKey.clear(); root.editingProvider = false } } }
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
                            RowLayout { Text { text: "模型映射"; color: Theme.ink; font.pixelSize: 14; font.weight: Font.DemiBold } HelpButton { objectName: "mappingHelp"; help: "左侧填写供应商的原始模型名称，右侧是聊天与 API 代理服务使用的别名。每个供应商可有多条映射，别名必须唯一。插件供应商的模型 ID 由模型发现提供。" } }
                            RowLayout { Layout.fillWidth: true; spacing: 14
                                Text { text: "供应商"; color: Theme.muted; font.pixelSize: 10; Layout.preferredWidth: 88 }
                                Text { text: "原始模型名称"; color: Theme.muted; font.pixelSize: 10; Layout.fillWidth: true; Layout.preferredWidth: 1 }
                                Item { Layout.preferredWidth: 24 }
                                Text { text: "对外模型别名"; color: Theme.muted; font.pixelSize: 10; Layout.fillWidth: true; Layout.preferredWidth: 1 }
                                Item { Layout.preferredWidth: 34 }
                            }
                            Repeater {
                                model: mappingRows
                                ColumnLayout {
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
                                    Layout.fillWidth: true; spacing: 4
                                    RowLayout {
                                        Layout.fillWidth: true; spacing: 14
                                        Text { text: providerName; color: Theme.ink; font.pixelSize: 11; Layout.preferredWidth: 88; elide: Text.ElideRight }
                                        InputField { objectName: "mappingModelId_" + index; readOnly: pluginModel; text: upstream; Layout.fillWidth: true; Layout.preferredWidth: 1; onTextEdited: mappingRows.setProperty(index, "upstream", text) }
                                        Glyph { name: "arrow-right"; width: 24; height: 17 }
                                        InputField { text: alias; Layout.fillWidth: true; Layout.preferredWidth: 1; onTextEdited: mappingRows.setProperty(index, "alias", text) }
                                        ActionButton { enabled: !pluginModel; glyph: "trash"; quiet: true; width: 34; hint: "删除映射"; onClicked: mappingRows.remove(index) }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true; Layout.leftMargin: 102; spacing: 8
                                        Text { text: "上下文长度"; color: Theme.muted; font.pixelSize: 11 }
                                        HelpButton { help: "自动按原始模型名匹配，未知名称使用 128000 token。输入整数、256K 或 1M 可自定义；K=1024，M=1048576。恢复自动后跟随模型名。" }
                                        ContextWindowField {
                                            objectName: "mappingContext_" + index
                                            Layout.preferredWidth: 190; Layout.fillWidth: false
                                            modelName: upstream; customText: contextWindowText; automatic: contextWindowAuto
                                            onEdited: (value, automatic) => { mappingRows.setProperty(index, "contextWindowText", value); mappingRows.setProperty(index, "contextWindowAuto", automatic) }
                                        }
                                        VisionField {
                                            objectName: "mappingVision_" + index
                                            Layout.leftMargin: 12; Layout.preferredWidth: 190; Layout.fillWidth: false
                                            modelName: upstream; visionEnabled: visionValue; automatic: visionAuto
                                            onEdited: (value, automatic) => { mappingRows.setProperty(index, "visionValue", value); mappingRows.setProperty(index, "visionAuto", automatic) }
                                        }
                                        Item { Layout.fillWidth: true }
                                    }
                                }
                            }
                            RowLayout { Layout.fillWidth: true; spacing: 10
                                Picker { id: mappingProvider; property var providers: backend.config.providers.filter(p => p.api === "openai" || p.api === "anthropic"); Layout.preferredWidth: 175; model: providers.map(p => p.name) }
                                ActionButton { text: "添加映射"; glyph: "plus"; enabled: mappingProvider.providers.length > 0; onClicked: { let p = mappingProvider.providers[mappingProvider.currentIndex]; if (p) mappingRows.append({provider:p.id, providerName:p.name, upstream:"", alias:"", contextWindowText:"", contextWindowAuto:true, visionValue:false, visionAuto:true}) } }
                                Item { Layout.fillWidth: true }
                                ActionButton { objectName: "saveMappingsButton"; text: "保存映射"; primary: true; onClicked: { let rows = []; for(let i=0;i<mappingRows.count;i++) { let m=mappingRows.get(i); rows.push({provider:m.provider,upstream:m.upstream,alias:m.alias,contextWindow:m.contextWindowText,contextWindowAuto:m.contextWindowAuto,vision:m.visionValue,visionAuto:m.visionAuto}) } backend.saveMappings(JSON.stringify(rows)) } }
                            }
                        }
                    }
                }

                AgentPage { visible: root.tab === 3; width: parent.width; availableHeight: settingsScroll.availableHeight; onNavigated: Qt.callLater(() => settingsScroll.contentItem.contentY = 0) }

                Column {
                    visible: root.tab === 5; width: parent.width; spacing: 18
                    SectionCard {
                        width: parent.width
                        ColumnLayout { width: parent.width; spacing: 20
                            Text { text: "主题"; color: Theme.ink; font.pixelSize: 14; font.weight: Font.DemiBold }
                            RowLayout { Layout.fillWidth: true; spacing: 20
                                Repeater {
                                    model: [{name:"浅色",id:"light",bg:"#fcfcfa",side:"#f2f3ef",card:"#ffffff",line:"#e5e8e1"},{name:"深色",id:"dark",bg:"#191c1b",side:"#141716",card:"#212523",line:"#343a36"},{name:"八奈见 · 海盐蓝",id:"yanami",bg:"#f4f7ff",side:"#e9effd",card:"#ffffff",line:"#d6e1f7"}]
                                    ColumnLayout { required property var modelData; Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.minimumWidth: 0; spacing: 12
                                        Rectangle { objectName: "theme_" + modelData.id; Layout.fillWidth: true; height: 160; radius: 10; color: modelData.bg; border.color: backend.config.theme === modelData.id ? Theme.accent : Theme.line; border.width: backend.config.theme === modelData.id ? 2 : 1
                                            Rectangle { x: 2; y: 2; width: parent.width * 0.22; height: parent.height - 4; radius: 8; color: modelData.side }
                                            Rectangle { x: parent.width * 0.32; y: 85; width: parent.width * 0.55; height: 40; radius: 6; color: modelData.card; border.color: modelData.line }
                                            Rectangle { visible: modelData.id !== "yanami"; x: parent.width * 0.54; y: 37; width: 24; height: 24; radius: 8; color: "#59755d" }
                                            Image { visible: modelData.id === "yanami"; source: "../icons/portraits/02.png"; x: parent.width * 0.42; y: 15; width: 65; height: 65; mipmap: true }
                                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: backend.setTheme(modelData.id) }
                                        }
                                        Row { spacing: 8
                                            Text { text: modelData.name; color: Theme.ink; font.pixelSize: 12 }
                                            Glyph { name: "check"; width: 15; height: 15; visible: backend.config.theme === modelData.id }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                AboutPage { visible: root.tab === 6; width: parent.width }
                Item { width: 1; height: 12 }
            }
        }
    }
}
