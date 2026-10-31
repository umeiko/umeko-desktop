import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Column {
    id: root
    spacing: 18
    property string serverSignature: ""
    readonly property string currentAddress: backend.config.server.lan ? (backend.proxyAddresses.find(ip => ip !== "127.0.0.1") || "") : "127.0.0.1"
    property string editKeyId: ""
    property string revokeKeyId: ""
    property string revokeKeyName: ""
    property bool draftKeyVisible: false
    property string createdKey: ""
    property double now: Date.now()
    TextMetrics { id: addressLabelMetrics; text: "Anthropic Base URL"; font.pixelSize: Theme.font(11, visible) }
    Timer { interval: 30000; running: root.visible; repeat: true; onTriggered: { root.now = Date.now(); backend.refreshProxyAddresses() } }
    function lastUsed(value) {
        if (!value) return I18n.t("尚未使用")
        const seconds = Math.max(0, (now - new Date(value).getTime()) / 1000)
        if (seconds < 60) return I18n.t("刚刚")
        if (seconds < 3600) return Math.floor(seconds / 60) + I18n.t(" 分钟前")
        if (seconds < 86400) return Math.floor(seconds / 3600) + I18n.t(" 小时前")
        return Qt.formatDateTime(new Date(value), "yyyy-MM-dd")
    }
    function reloadServer() {
        const s = backend.config.server, signature = JSON.stringify(s)
        if (signature === serverSignature) return
        serverSignature = signature
        port.text = s.port.toString()
        openai.checked = s.openai; anthropic.checked = s.anthropic; lan.checked = s.lan
    }
    function saveServer() { return backend.saveServer(Number(port.text), openai.checked, anthropic.checked, lan.checked) }
    function editKey(row) {
        editKeyId = row ? row.id : ""
        keyName.text = row ? row.name : ""
        keyValue.clear(); draftKeyVisible = false
        keyEditor.open()
    }
    Component.onCompleted: reloadServer()
    Connections { target: backend; function onChanged() { root.reloadServer() } }

    SectionCard {
        width: root.width
        ColumnLayout { width: parent.width; spacing: 20
            RowLayout { Layout.fillWidth: true
                Text { font.family: Theme.fontFamily; text: I18n.t("API 代理服务"); color: Theme.ink; font.pixelSize: Theme.font(14, visible); font.weight: Font.DemiBold }
                HelpButton { help: I18n.t("将本软件可用的供应商和模型，变为本地服务供你的其他 Agent 软件使用。") }
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "toggleServerButton"; text: backend.serverRunning ? I18n.t("停止服务") : I18n.t("启动服务"); primary: !backend.serverRunning; onClicked: { if (backend.serverRunning) backend.toggleServer(); else if (root.saveServer()) backend.toggleServer() } }
            }
            Rectangle { Layout.fillWidth: true; height: 51; radius: 8; color: Theme.accentBg
                Row { x: 16; anchors.verticalCenter: parent.verticalCenter; spacing: 9
                    Rectangle { width: 6; height: 6; radius: 3; color: backend.serverRunning ? Theme.accent : Theme.muted; anchors.verticalCenter: parent.verticalCenter }
                    Text { font.family: Theme.fontFamily; text: backend.serverRunning ? I18n.t("服务正在运行") : I18n.t("服务尚未启动"); color: Theme.accent; font.pixelSize: Theme.font(11, visible) }
                }
                Text { font.family: Theme.fontFamily; anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter; text: backend.config.server.lan ? I18n.t("本机及局域网") : I18n.t("仅本机可访问"); color: Theme.accent; font.pixelSize: Theme.font(10, visible) }
            }
            RowLayout { Layout.fillWidth: true; spacing: 20
                ColumnLayout { spacing: 8
                    Text { font.family: Theme.fontFamily; text: I18n.t("监听端口"); color: Theme.ink; font.pixelSize: Theme.font(11, visible) }
                    InputField { id: port; objectName: "portInput"; Layout.preferredWidth: 130; validator: IntValidator { bottom: 1024; top: 65535 } inputMethodHints: Qt.ImhDigitsOnly }
                }
                Item { Layout.fillWidth: true }
                ColumnLayout { spacing: 10
                    Text { font.family: Theme.fontFamily; text: I18n.t("OpenAI 格式"); color: Theme.ink; font.pixelSize: Theme.font(11, visible) }
                    Toggle { id: openai; objectName: "proxyOpenaiToggle" }
                }
                ColumnLayout { Layout.leftMargin: 15; spacing: 10
                    Text { font.family: Theme.fontFamily; text: I18n.t("Anthropic 格式"); color: Theme.ink; font.pixelSize: Theme.font(11, visible) }
                    Toggle { id: anthropic; objectName: "proxyAnthropicToggle" }
                }
            }
            RowLayout { Layout.fillWidth: true
                Text { font.family: Theme.fontFamily; text: I18n.t("允许局域网访问"); color: Theme.ink; font.pixelSize: Theme.font(12, visible) }
                HelpButton { help: I18n.t("开启后监听所有 IPv4 网卡（0.0.0.0），同一网络的设备可使用本机 IP 和有效 Key 连接。当前服务使用 HTTP，请在可信网络使用；实际连通性受本机防火墙影响。") }
                Item { Layout.fillWidth: true }
                Toggle { id: lan; objectName: "proxyLanToggle" }
            }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "saveProxyServerButton"; text: I18n.t("保存设置"); primary: true; onClicked: root.saveServer() }
            }
        }
    }
    SectionCard {
        objectName: "proxyAddressesCard"
        width: root.width
        ColumnLayout { width: parent.width; spacing: 16
            RowLayout { Layout.fillWidth: true
                Text { font.family: Theme.fontFamily; text: I18n.t("连接地址"); color: Theme.ink; font.pixelSize: Theme.font(14, visible); font.weight: Font.DemiBold }
                HelpButton { help: I18n.t("本机模式显示 127.0.0.1；局域网模式自动显示本机网卡 IP。复制对应协议的 Base URL，并使用下方模型别名和有效 API Key 连接。") }
                Item { Layout.fillWidth: true }
                ActionButton { text: I18n.t("刷新地址"); quiet: true; glyph: "refresh"; onClicked: backend.refreshProxyAddresses() }
            }
            Repeater {
                model: [{label:"OpenAI Base URL", suffix:"/v1", enabled:backend.config.server.openai}, {label:"Anthropic Base URL", suffix:"", enabled:backend.config.server.anthropic}]
                GridLayout {
                    id: addressRow
                    required property var modelData
                    visible: modelData.enabled; Layout.fillWidth: true
                    objectName: modelData.suffix ? "proxyOpenaiAddressRow" : "proxyAnthropicAddressRow"
                    readonly property bool stacked: width < addressLabelMetrics.advanceWidth + 12 + 220 * Theme.fontScale + copyAddress.implicitWidth + 8
                    columns: stacked ? 1 : 2; columnSpacing: 12; rowSpacing: 8
                    readonly property string url: root.currentAddress ? "http://" + root.currentAddress + ":" + backend.config.server.port + modelData.suffix : ""
                    Text { font.family: Theme.fontFamily; objectName: modelData.suffix ? "proxyOpenaiAddressLabel" : "proxyAnthropicAddressLabel"; text: modelData.label; color: Theme.muted; font.pixelSize: Theme.font(11, visible); Layout.minimumWidth: implicitWidth; Layout.preferredWidth: Math.ceil(addressLabelMetrics.advanceWidth); Layout.fillWidth: addressRow.stacked }
                    RowLayout {
                        Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 8
                        InputField { objectName: modelData.suffix ? "proxyOpenaiBaseUrl" : "proxyAnthropicBaseUrl"; Layout.fillWidth: true; Layout.minimumWidth: 0; text: addressRow.url; readOnly: true; placeholderText: I18n.t("未找到局域网 IP"); font.family: "Consolas" }
                        ActionButton { id: copyAddress; objectName: modelData.suffix ? "copyProxyOpenaiBaseUrl" : "copyProxyAnthropicBaseUrl"; glyph: "copy"; quiet: true; enabled: !!addressRow.url; hint: I18n.t("复制地址"); onClicked: backend.copy(addressRow.url) }
                    }
                }
            }
            Text { font.family: Theme.fontFamily; visible: backend.config.server.lan && backend.proxyAddresses.length === 1; text: I18n.t("未找到其他 IPv4 网卡地址，请检查本机网络。"); color: Theme.muted; font.pixelSize: Theme.font(11, visible) }
        }
    }
    SectionCard {
        objectName: "proxyKeyManagementCard"
        width: root.width
        ColumnLayout { width: parent.width; spacing: 16
            RowLayout { Layout.fillWidth: true
                Text { font.family: Theme.fontFamily; text: I18n.t("API Key 管理"); color: Theme.ink; font.pixelSize: Theme.font(14, visible); font.weight: Font.DemiBold }
                HelpButton { help: I18n.t("可为每个客户端创建独立 Key。支持自定义、随机生成、编辑、停用和撤销。编辑时重新生成并保存会替换旧 Key；停用和撤销对新请求生效，已开始的请求可继续完成。最近活跃记录最近一次通过鉴权的时间。") }
                Text { font.family: Theme.fontFamily; text: backend.proxyKeys.filter(k => k.enabled).length + I18n.t(" 个启用"); color: Theme.muted; font.pixelSize: Theme.font(11, visible) }
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "addProxyKeyButton"; text: I18n.t("新建 API Key"); glyph: "plus"; primary: true; onClicked: root.editKey(null) }
            }
            Rectangle { Layout.fillWidth: true; implicitHeight: keyNotice.implicitHeight + 26; radius: 10; color: Theme.bg
                Text { font.family: Theme.fontFamily; id: keyNotice; anchors.fill: parent; anchors.margins: 13; text: I18n.t("完整 API Key 仅在新建或替换后显示一次，请及时复制保存。请勿与他人共享或写入客户端代码。可为不同客户端分别命名，随时停用或撤销。"); wrapMode: Text.Wrap; color: Theme.ink; font.pixelSize: Theme.font(11, visible) }
            }
            Text { font.family: Theme.fontFamily; visible: backend.proxyKeys.length === 0; text: I18n.t("暂无 Key，创建并启用后即可启动代理服务。"); color: Theme.muted; font.pixelSize: Theme.font(12, visible) }
            InlineScrollView {
                id: keyScroll; objectName: "proxyKeysTable"; Layout.fillWidth: true
                Layout.preferredHeight: keyTable.implicitHeight + 14
                contentWidth: Math.max(availableWidth, 940); contentHeight: keyTable.implicitHeight; clip: true
                ScrollBar.vertical.policy: ScrollBar.AlwaysOff
                ScrollBar.horizontal.policy: contentWidth > availableWidth ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
                Column { id: keyTable; width: keyScroll.contentWidth
                    RowLayout { width: parent.width; height: 43; spacing: 12
                        Repeater { model: [{label:"API ID", w:180},{label:"Key", w:112},{label:I18n.t("名称"), w:136},{label:I18n.t("创建时间"), w:140},{label:I18n.t("最近活跃"), w:88},{label:I18n.t("状态"), w:54},{label:I18n.t("操作"), w:134}]
                            Text { font.family: Theme.fontFamily; required property var modelData; text: modelData.label; Layout.preferredWidth: modelData.w; color: Theme.ink; font.pixelSize: Theme.font(11, visible) }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.line }
                    Repeater { model: backend.proxyKeys
                        Column {
                            required property var modelData
                            width: keyTable.width
                            RowLayout { width: parent.width; height: 51; spacing: 12
                                Text { text: modelData.id; Layout.preferredWidth: 180; elide: Text.ElideMiddle; font.family: "Consolas"; font.pixelSize: Theme.font(10, visible); color: Theme.ink
                                    HoverTip { active: idHover.hovered; text: modelData.id }
                                    HoverHandler { id: idHover; cursorShape: Qt.PointingHandCursor }
                                    TapHandler { onTapped: backend.copy(modelData.id) }
                                }
                                Text { objectName: "proxyKeyDisplay_" + modelData.id; text: modelData.maskedKey; Layout.preferredWidth: 112; font.family: "Consolas"; font.pixelSize: Theme.font(11, visible); color: Theme.ink }
                                Text { font.family: Theme.fontFamily; text: modelData.name; textFormat: Text.PlainText; Layout.preferredWidth: 136; elide: Text.ElideRight; font.pixelSize: Theme.font(11, visible); color: Theme.ink
                                    HoverTip { active: nameHover.hovered; text: modelData.name } HoverHandler { id: nameHover }
                                }
                                Text { font.family: Theme.fontFamily; text: Qt.formatDateTime(new Date(modelData.createdAt), "yyyy-MM-dd HH:mm:ss"); Layout.preferredWidth: 140; font.pixelSize: Theme.font(10, visible); color: Theme.ink }
                                Text { font.family: Theme.fontFamily; objectName: "proxyKeyLastUsed_" + modelData.id; text: root.lastUsed(modelData.lastUsedAt); Layout.preferredWidth: 88; font.pixelSize: Theme.font(11, visible); color: Theme.muted
                                    HoverTip { active: usedHover.hovered; text: modelData.lastUsedAt ? Qt.formatDateTime(new Date(modelData.lastUsedAt), "yyyy-MM-dd HH:mm:ss") : I18n.t("尚未使用") } HoverHandler { id: usedHover }
                                }
                                Text { font.family: Theme.fontFamily; text: modelData.enabled ? I18n.t("生效中") : I18n.t("已停用"); Layout.preferredWidth: 54; font.pixelSize: Theme.font(11, visible); color: modelData.enabled ? Theme.accent : Theme.muted }
                                Row { Layout.preferredWidth: 134; spacing: 1
                                    ActionButton { objectName: "editProxyKey_" + modelData.id; glyph: "edit"; quiet: true; hint: I18n.t("编辑名称或替换 Key"); onClicked: root.editKey(modelData) }
                                    ActionButton { objectName: "enableProxyKey_" + modelData.id; text: modelData.enabled ? I18n.t("停用") : I18n.t("启用"); implicitWidth: 50; quiet: true; onClicked: backend.setProxyKeyEnabled(modelData.id, !modelData.enabled) }
                                    ActionButton { objectName: "revokeProxyKey_" + modelData.id; glyph: "trash"; quiet: true; destructive: true; hint: I18n.t("撤销 Key"); onClicked: { root.revokeKeyId = modelData.id; root.revokeKeyName = modelData.name; revokeDialog.open() } }
                                }
                            }
                            Rectangle { width: parent.width; height: 1; color: Theme.line }
                        }
                    }
                }
            }
        }
    }
    Popup {
        id: keyEditor; objectName: "proxyKeyEditor"; parent: Overlay.overlay
        modal: true; focus: true; padding: 24
        width: Math.min(560, parent.width - 48); height: editorColumn.implicitHeight + 48
        x: (parent.width - width) / 2; y: (parent.height - height) / 2
        closePolicy: Popup.CloseOnEscape
        onClosed: { keyValue.clear(); keyName.clear(); root.draftKeyVisible = false }
        background: Rectangle { radius: 13; color: Theme.surface; border.color: Theme.line }
        Overlay.modal: Rectangle { color: "#50000000" }
        ColumnLayout { id: editorColumn; width: parent.width; spacing: 16
            Text { font.family: Theme.fontFamily; text: root.editKeyId ? I18n.t("编辑 API Key") : I18n.t("新增 API Key"); color: Theme.ink; font.pixelSize: Theme.font(18, visible); font.weight: Font.Medium }
            Text { font.family: Theme.fontFamily; text: I18n.t("名称"); color: Theme.muted; font.pixelSize: Theme.font(11, visible) }
            InputField { id: keyName; objectName: "proxyKeyNameInput"; Layout.fillWidth: true; placeholderText: I18n.t("例如：笔记本、内网工具"); maximumLength: 80 }
            Text { font.family: Theme.fontFamily; text: root.editKeyId ? I18n.t("Key（留空保持原值）") : I18n.t("Key（留空自动生成）"); color: Theme.muted; font.pixelSize: Theme.font(11, visible) }
            RowLayout { Layout.fillWidth: true
                InputField { id: keyValue; objectName: "proxyKeyValueInput"; Layout.fillWidth: true; maximumLength: 256; echoMode: root.draftKeyVisible ? TextInput.Normal : TextInput.Password; placeholderText: I18n.t("自定义 Key 或点击生成") }
                ActionButton { glyph: root.draftKeyVisible ? "eye-off" : "eye"; quiet: true; onClicked: root.draftKeyVisible = !root.draftKeyVisible }
            }
            RowLayout { Layout.fillWidth: true
                ActionButton { objectName: "generateProxyKeyButton"; text: I18n.t("生成 Key"); glyph: "refresh"; onClicked: keyValue.text = backend.generateProxyKey() }
                ActionButton { text: I18n.t("复制输入值"); glyph: "copy"; quiet: true; enabled: keyValue.text.length > 0; onClicked: backend.copy(keyValue.text) }
                Item { Layout.fillWidth: true }
            }
            Text { font.family: Theme.fontFamily; text: I18n.t("自定义 Key 支持 16–256 位字母、数字及 . _ ~ -。保存后生效。"); color: Theme.muted; font.pixelSize: Theme.font(11, visible); Layout.fillWidth: true; wrapMode: Text.Wrap }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { text: I18n.t("取消"); quiet: true; onClicked: keyEditor.close() }
                ActionButton { objectName: "saveProxyKeyButton"; text: I18n.t("保存 Key"); primary: true; onClicked: {
                    if (!backend.saveProxyKey(root.editKeyId, keyName.text, keyValue.text)) return
                    const result = backend.takeCreatedProxyKey()
                    keyEditor.close()
                    if (result.key) { root.createdKey = result.key; createdDialog.open() }
                } }
            }
        }
    }
    Popup {
        id: createdDialog; objectName: "createdProxyKeyDialog"; parent: Overlay.overlay
        modal: true; focus: true; padding: 24; width: Math.min(560, parent.width - 48); height: createdColumn.implicitHeight + 48
        x: (parent.width - width) / 2; y: (parent.height - height) / 2
        closePolicy: Popup.CloseOnEscape
        onClosed: root.createdKey = ""
        background: Rectangle { radius: 13; color: Theme.surface; border.color: Theme.line }
        Overlay.modal: Rectangle { color: "#50000000" }
        ColumnLayout { id: createdColumn; width: parent.width; spacing: 18
            Text { font.family: Theme.fontFamily; text: I18n.t("保存你的 API Key"); color: Theme.ink; font.pixelSize: Theme.font(18, visible); font.weight: Font.Medium }
            Text { font.family: Theme.fontFamily; text: I18n.t("完整 Key 只显示这一次，请复制并妥善保存。关闭后无法再次查看；遗失时可编辑此条目，生成新的 Key。"); Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(12, visible) }
            InputField { objectName: "createdProxyKeyValue"; Layout.fillWidth: true; text: root.createdKey; readOnly: true; font.family: "Consolas"; font.pixelSize: Theme.font(12, visible) }
            RowLayout { Layout.fillWidth: true
                ActionButton { objectName: "copyCreatedProxyKeyButton"; text: I18n.t("复制 Key"); glyph: "copy"; primary: true; onClicked: backend.copy(root.createdKey) }
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "closeCreatedProxyKeyButton"; text: I18n.t("已保存，关闭"); onClicked: createdDialog.close() }
            }
        }
    }
    Popup {
        id: revokeDialog; objectName: "revokeProxyKeyDialog"; parent: Overlay.overlay
        modal: true; focus: true; padding: 24; width: Math.min(440, parent.width - 48); height: revokeColumn.implicitHeight + 48
        x: (parent.width - width) / 2; y: (parent.height - height) / 2
        background: Rectangle { radius: 13; color: Theme.surface; border.color: Theme.line }
        Overlay.modal: Rectangle { color: "#50000000" }
        ColumnLayout { id: revokeColumn; width: parent.width; spacing: 20
            Text { font.family: Theme.fontFamily; text: I18n.t("撤销 Key"); color: Theme.ink; font.pixelSize: Theme.font(17, visible) }
            Text { font.family: Theme.fontFamily; text: I18n.t("撤销“") + root.revokeKeyName + I18n.t("”后，此 Key 将无法用于新的请求。"); textFormat: Text.PlainText; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(12, visible) }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { text: I18n.t("取消"); quiet: true; onClicked: revokeDialog.close() }
                ActionButton { objectName: "confirmRevokeProxyKeyButton"; text: I18n.t("撤销"); destructive: true; onClicked: { backend.revokeProxyKey(root.revokeKeyId); revokeDialog.close() } }
            }
        }
    }
}
