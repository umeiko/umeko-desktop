import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Column {
    id: root
    spacing: 18
    property string serverSignature: ""
    property string address: "127.0.0.1"
    readonly property string currentAddress: addressPicker.currentText || "127.0.0.1"
    property string editKeyId: ""
    property string revokeKeyId: ""
    property string revokeKeyName: ""
    property bool draftKeyVisible: false
    property string createdKey: ""
    property double now: Date.now()
    Timer { interval: 30000; running: root.visible; repeat: true; onTriggered: root.now = Date.now() }
    function lastUsed(value) {
        if (!value) return "尚未使用"
        const seconds = Math.max(0, (now - new Date(value).getTime()) / 1000)
        if (seconds < 60) return "刚刚"
        if (seconds < 3600) return Math.floor(seconds / 60) + " 分钟前"
        if (seconds < 86400) return Math.floor(seconds / 3600) + " 小时前"
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
                Text { text: "API 代理服务"; color: Theme.ink; font.pixelSize: 14; font.weight: Font.DemiBold }
                HelpButton { help: "让其他客户端通过兼容 API 使用已配置的供应商和模型。默认仅本机访问，可开启局域网访问。所有请求都需要有效 Key。关闭应用后服务停止，下次需手动启动。" }
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "toggleServerButton"; text: backend.serverRunning ? "停止服务" : "启动服务"; primary: !backend.serverRunning; onClicked: { if (backend.serverRunning) backend.toggleServer(); else if (root.saveServer()) backend.toggleServer() } }
            }
            Rectangle { Layout.fillWidth: true; height: 51; radius: 8; color: Theme.accentBg
                Row { x: 16; anchors.verticalCenter: parent.verticalCenter; spacing: 9
                    Rectangle { width: 6; height: 6; radius: 3; color: backend.serverRunning ? Theme.accent : Theme.muted; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: backend.serverRunning ? "服务正在运行" : "服务尚未启动"; color: Theme.accent; font.pixelSize: 11 }
                }
                Text { anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter; text: backend.config.server.lan ? "本机及局域网" : "仅本机可访问"; color: Theme.accent; font.pixelSize: 10 }
            }
            RowLayout { Layout.fillWidth: true; spacing: 20
                ColumnLayout { spacing: 8
                    Text { text: "监听端口"; color: Theme.ink; font.pixelSize: 11 }
                    InputField { id: port; objectName: "portInput"; Layout.preferredWidth: 130; validator: IntValidator { bottom: 1024; top: 65535 } inputMethodHints: Qt.ImhDigitsOnly }
                }
                Item { Layout.fillWidth: true }
                ColumnLayout { spacing: 10
                    Text { text: "OpenAI 格式"; color: Theme.ink; font.pixelSize: 11 }
                    Toggle { id: openai; objectName: "proxyOpenaiToggle" }
                }
                ColumnLayout { Layout.leftMargin: 15; spacing: 10
                    Text { text: "Anthropic 格式"; color: Theme.ink; font.pixelSize: 11 }
                    Toggle { id: anthropic; objectName: "proxyAnthropicToggle" }
                }
            }
            RowLayout { Layout.fillWidth: true
                Text { text: "允许局域网访问"; color: Theme.ink; font.pixelSize: 12 }
                HelpButton { help: "开启后监听所有 IPv4 网卡（0.0.0.0），同一网络的设备可使用本机 IP 和有效 Key 连接。当前服务使用 HTTP，请在可信网络使用；实际连通性受本机防火墙影响。" }
                Item { Layout.fillWidth: true }
                Toggle { id: lan; objectName: "proxyLanToggle" }
            }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "saveProxyServerButton"; text: "保存设置"; primary: true; onClicked: root.saveServer() }
            }
        }
    }
    SectionCard {
        width: root.width
        ColumnLayout { width: parent.width; spacing: 16
            RowLayout { Layout.fillWidth: true
                Text { text: "连接地址"; color: Theme.ink; font.pixelSize: 14; font.weight: Font.DemiBold }
                HelpButton { help: "本机客户端使用 127.0.0.1；局域网设备选择能访问的本机网卡地址。OpenAI 使用 Bearer Key，Anthropic 使用 x-api-key，并填写下方模型映射中的别名。" }
                Item { Layout.fillWidth: true }
                ActionButton { text: "刷新地址"; quiet: true; glyph: "refresh"; onClicked: backend.refreshProxyAddresses() }
            }
            RowLayout { Layout.fillWidth: true
                Text { text: "访问地址"; color: Theme.muted; font.pixelSize: 11; Layout.preferredWidth: 135 }
                Picker { id: addressPicker; objectName: "proxyAddressPicker"; Layout.fillWidth: true; model: backend.proxyAddresses; currentIndex: Math.max(0, model.indexOf(root.address)); onActivated: index => root.address = model[index] }
            }
            Repeater {
                model: [{label:"OpenAI Base URL", suffix:"/v1", enabled:backend.config.server.openai}, {label:"Anthropic Base URL", suffix:"", enabled:backend.config.server.anthropic}]
                RowLayout {
                    required property var modelData
                    visible: modelData.enabled; Layout.fillWidth: true
                    readonly property string url: "http://" + root.currentAddress + ":" + backend.config.server.port + modelData.suffix
                    Text { text: modelData.label; color: Theme.muted; font.pixelSize: 11; Layout.preferredWidth: 135 }
                    InputField { Layout.fillWidth: true; text: parent.url; readOnly: true; font.family: "Consolas" }
                    ActionButton { glyph: "copy"; quiet: true; hint: "复制地址"; onClicked: backend.copy(parent.url) }
                }
            }
            Text { visible: backend.config.server.lan && backend.proxyAddresses.length === 1; text: "未找到其他 IPv4 网卡地址，请检查本机网络。"; color: Theme.muted; font.pixelSize: 11 }
        }
    }
    SectionCard {
        objectName: "proxyKeyManagementCard"
        width: root.width
        ColumnLayout { width: parent.width; spacing: 16
            RowLayout { Layout.fillWidth: true
                Text { text: "API Key 管理"; color: Theme.ink; font.pixelSize: 14; font.weight: Font.DemiBold }
                HelpButton { help: "可为每个客户端创建独立 Key。支持自定义、随机生成、编辑、停用和撤销。编辑时重新生成并保存会替换旧 Key；停用和撤销对新请求生效，已开始的请求可继续完成。最近活跃记录最近一次通过鉴权的时间。" }
                Text { text: backend.proxyKeys.filter(k => k.enabled).length + " 个启用"; color: Theme.muted; font.pixelSize: 11 }
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "addProxyKeyButton"; text: "新建 API Key"; glyph: "plus"; primary: true; onClicked: root.editKey(null) }
            }
            Rectangle { Layout.fillWidth: true; implicitHeight: keyNotice.implicitHeight + 26; radius: 10; color: Theme.bg
                Text { id: keyNotice; anchors.fill: parent; anchors.margins: 13; text: "完整 API Key 仅在新建或替换后显示一次，请及时复制保存。请勿与他人共享或写入客户端代码。可为不同客户端分别命名，随时停用或撤销。"; wrapMode: Text.Wrap; color: Theme.ink; font.pixelSize: 11 }
            }
            Text { visible: backend.proxyKeys.length === 0; text: "暂无 Key，创建并启用后即可启动代理服务。"; color: Theme.muted; font.pixelSize: 12 }
            ScrollView {
                id: keyScroll; objectName: "proxyKeysTable"; Layout.fillWidth: true
                Layout.preferredHeight: keyTable.implicitHeight + 14
                contentWidth: Math.max(availableWidth, 940); contentHeight: keyTable.implicitHeight; clip: true
                ScrollBar.vertical.policy: ScrollBar.AlwaysOff
                ScrollBar.horizontal.policy: contentWidth > availableWidth ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
                Column { id: keyTable; width: keyScroll.contentWidth
                    RowLayout { width: parent.width; height: 43; spacing: 12
                        Repeater { model: [{label:"API ID", w:180},{label:"Key", w:112},{label:"名称", w:136},{label:"创建时间", w:140},{label:"最近活跃", w:88},{label:"状态", w:54},{label:"操作", w:134}]
                            Text { required property var modelData; text: modelData.label; Layout.preferredWidth: modelData.w; color: Theme.ink; font.pixelSize: 11 }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.line }
                    Repeater { model: backend.proxyKeys
                        Column {
                            required property var modelData
                            width: keyTable.width
                            RowLayout { width: parent.width; height: 51; spacing: 12
                                Text { text: modelData.id; Layout.preferredWidth: 180; elide: Text.ElideMiddle; font.family: "Consolas"; font.pixelSize: 10; color: Theme.ink
                                    ToolTip.text: modelData.id; ToolTip.visible: idHover.hovered; ToolTip.delay: 600
                                    HoverHandler { id: idHover }
                                    TapHandler { onTapped: backend.copy(modelData.id) }
                                }
                                Text { objectName: "proxyKeyDisplay_" + modelData.id; text: modelData.maskedKey; Layout.preferredWidth: 112; font.family: "Consolas"; font.pixelSize: 11; color: Theme.ink }
                                Text { text: modelData.name; textFormat: Text.PlainText; Layout.preferredWidth: 136; elide: Text.ElideRight; font.pixelSize: 11; color: Theme.ink
                                    ToolTip.text: text; ToolTip.visible: nameHover.hovered; ToolTip.delay: 600; HoverHandler { id: nameHover }
                                }
                                Text { text: Qt.formatDateTime(new Date(modelData.createdAt), "yyyy-MM-dd HH:mm:ss"); Layout.preferredWidth: 140; font.pixelSize: 10; color: Theme.ink }
                                Text { objectName: "proxyKeyLastUsed_" + modelData.id; text: root.lastUsed(modelData.lastUsedAt); Layout.preferredWidth: 88; font.pixelSize: 11; color: Theme.muted
                                    ToolTip.text: modelData.lastUsedAt ? Qt.formatDateTime(new Date(modelData.lastUsedAt), "yyyy-MM-dd HH:mm:ss") : "尚未使用"; ToolTip.visible: usedHover.hovered; ToolTip.delay: 600; HoverHandler { id: usedHover }
                                }
                                Text { text: modelData.enabled ? "生效中" : "已停用"; Layout.preferredWidth: 54; font.pixelSize: 11; color: modelData.enabled ? Theme.accent : Theme.muted }
                                Row { Layout.preferredWidth: 134; spacing: 1
                                    ActionButton { objectName: "editProxyKey_" + modelData.id; glyph: "edit"; quiet: true; hint: "编辑名称或替换 Key"; onClicked: root.editKey(modelData) }
                                    ActionButton { objectName: "enableProxyKey_" + modelData.id; text: modelData.enabled ? "停用" : "启用"; implicitWidth: 50; quiet: true; onClicked: backend.setProxyKeyEnabled(modelData.id, !modelData.enabled) }
                                    ActionButton { objectName: "revokeProxyKey_" + modelData.id; glyph: "trash"; quiet: true; destructive: true; hint: "撤销 Key"; onClicked: { root.revokeKeyId = modelData.id; root.revokeKeyName = modelData.name; revokeDialog.open() } }
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
            Text { text: root.editKeyId ? "编辑 API Key" : "新增 API Key"; color: Theme.ink; font.pixelSize: 18; font.weight: Font.Medium }
            Text { text: "名称"; color: Theme.muted; font.pixelSize: 11 }
            InputField { id: keyName; objectName: "proxyKeyNameInput"; Layout.fillWidth: true; placeholderText: "例如：笔记本、内网工具"; maximumLength: 80 }
            Text { text: root.editKeyId ? "Key（留空保持原值）" : "Key（留空自动生成）"; color: Theme.muted; font.pixelSize: 11 }
            RowLayout { Layout.fillWidth: true
                InputField { id: keyValue; objectName: "proxyKeyValueInput"; Layout.fillWidth: true; maximumLength: 256; echoMode: root.draftKeyVisible ? TextInput.Normal : TextInput.Password; placeholderText: "自定义 Key 或点击生成" }
                ActionButton { glyph: root.draftKeyVisible ? "eye-off" : "eye"; quiet: true; onClicked: root.draftKeyVisible = !root.draftKeyVisible }
            }
            RowLayout { Layout.fillWidth: true
                ActionButton { objectName: "generateProxyKeyButton"; text: "生成 Key"; glyph: "refresh"; onClicked: keyValue.text = backend.generateProxyKey() }
                ActionButton { text: "复制输入值"; glyph: "copy"; quiet: true; enabled: keyValue.text.length > 0; onClicked: backend.copy(keyValue.text) }
                Item { Layout.fillWidth: true }
            }
            Text { text: "自定义 Key 支持 16–256 位字母、数字及 . _ ~ -。保存后生效。"; color: Theme.muted; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.Wrap }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { text: "取消"; quiet: true; onClicked: keyEditor.close() }
                ActionButton { objectName: "saveProxyKeyButton"; text: "保存 Key"; primary: true; onClicked: {
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
            Text { text: "保存你的 API Key"; color: Theme.ink; font.pixelSize: 18; font.weight: Font.Medium }
            Text { text: "完整 Key 只显示这一次，请复制并妥善保存。关闭后无法再次查看；遗失时可编辑此条目，生成新的 Key。"; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: 12 }
            InputField { objectName: "createdProxyKeyValue"; Layout.fillWidth: true; text: root.createdKey; readOnly: true; font.family: "Consolas"; font.pixelSize: 12 }
            RowLayout { Layout.fillWidth: true
                ActionButton { objectName: "copyCreatedProxyKeyButton"; text: "复制 Key"; glyph: "copy"; primary: true; onClicked: backend.copy(root.createdKey) }
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "closeCreatedProxyKeyButton"; text: "已保存，关闭"; onClicked: createdDialog.close() }
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
            Text { text: "撤销 Key"; color: Theme.ink; font.pixelSize: 17 }
            Text { text: "撤销“" + root.revokeKeyName + "”后，此 Key 将无法用于新的请求。"; textFormat: Text.PlainText; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: 12 }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { text: "取消"; quiet: true; onClicked: revokeDialog.close() }
                ActionButton { objectName: "confirmRevokeProxyKeyButton"; text: "撤销"; destructive: true; onClicked: { backend.revokeProxyKey(root.revokeKeyId); revokeDialog.close() } }
            }
        }
    }
}
