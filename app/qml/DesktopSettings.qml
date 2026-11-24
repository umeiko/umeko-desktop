import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Column {
    id: root
    objectName: "umekoDesktopSettings"
    spacing: 16
    signal requestHeadersRequested()
    property bool startupSettingsReady: false
    Component.onCompleted: {
        startupSettingsReady = true
        if (visible) {
            backend.loginStartup.refresh()
            backend.refreshSshConfigHosts()
        }
    }
    onVisibleChanged: if (startupSettingsReady && visible) {
        backend.loginStartup.refresh()
        backend.refreshSshConfigHosts()
    }
    Button {
        id: customRequestsEntry
        objectName: "openRequestHeaders"
        width: parent.width
        implicitHeight: Math.max(Theme.control(64), customRequestsRow.implicitHeight + 32)
        padding: 20; hoverEnabled: true
        Accessible.name: I18n.t("自定义请求")
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        background: Rectangle { radius: 12; color: customRequestsEntry.hovered ? Theme.hover : Theme.surface; border.color: customRequestsEntry.activeFocus ? Theme.accent : Theme.line }
        contentItem: RowLayout {
            id: customRequestsRow; spacing: 12
            Glyph { name: "sliders"; color: Theme.muted; Layout.preferredWidth: Theme.icon(20); Layout.preferredHeight: Theme.icon(20) }
            Text { Layout.fillWidth: true; text: I18n.t("自定义请求"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(14); elide: Text.ElideRight }
            Glyph { name: "chevron-right"; color: Theme.muted; Layout.preferredWidth: Theme.icon(16); Layout.preferredHeight: Theme.icon(16) }
        }
        onClicked: root.requestHeadersRequested()
    }
    SectionCard {
        width: parent.width
        ColumnLayout {
            width: parent.width; spacing: 20
            Text { text: I18n.t("开机启动"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Text { text: I18n.t("开机启动 Umeko"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); wrapMode: Text.Wrap; Layout.fillWidth: true }
                HelpButton { help: I18n.t("登录系统后在托盘中启动 Umeko。"); Layout.alignment: Qt.AlignVCenter }
                Toggle {
                    objectName: "desktopLoginUmeko"
                    enabled: backend.loginStartup.state.available
                    checked: backend.loginStartup.state.umeko
                    Accessible.name: I18n.t("开机启动 Umeko")
                    onClicked: { const value = checked; checked = Qt.binding(function() { return backend.loginStartup.state.umeko }); backend.loginStartup.setEnabled(value, backend.loginStartup.state.proxy) }
                }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Text { text: I18n.t("开机启动 API 代理"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); wrapMode: Text.Wrap; Layout.fillWidth: true }
                HelpButton { help: I18n.t("登录系统后在后台启动 API 代理，无需打开 Umeko 窗口。"); Layout.alignment: Qt.AlignVCenter }
                Toggle {
                    objectName: "desktopLoginProxy"
                    enabled: backend.loginStartup.state.available
                    checked: backend.loginStartup.state.proxy
                    Accessible.name: I18n.t("开机启动 API 代理")
                    onClicked: { const value = checked; checked = Qt.binding(function() { return backend.loginStartup.state.proxy }); backend.loginStartup.setEnabled(backend.loginStartup.state.umeko, value) }
                }
            }
            Text {
                objectName: "desktopLoginStartupReason"
                Layout.fillWidth: true
                visible: !backend.loginStartup.state.available && text.length > 0
                text: I18n.t(backend.loginStartup.state.reason)
                color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12); wrapMode: Text.Wrap
            }
        }
    }
    SectionCard {
        width: parent.width
        RowLayout {
            width: parent.width; spacing: 8
            Text { text: I18n.t("聊天区域左右展开提示"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); wrapMode: Text.Wrap; Layout.fillWidth: true }
            HelpButton { help: I18n.t("鼠标移到聊天区域两侧时显示展开或收起提示。关闭后保留当前布局。"); Layout.alignment: Qt.AlignVCenter }
            Toggle {
                objectName: "desktopChatWidthHints"
                checked: backend.desktopSettings.chatWidthHints
                Accessible.name: I18n.t("聊天区域左右展开提示")
                onClicked: { const value = checked; checked = Qt.binding(function() { return backend.desktopSettings.chatWidthHints }); backend.saveDesktopSettings(JSON.stringify({chatWidthHints:value})) }
            }
        }
    }
    SectionCard {
        width: parent.width
        ColumnLayout {
            width: parent.width; spacing: 20
            Text { text: I18n.t("提交与预览"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Text { text: I18n.t("提交后自动打开预览"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); wrapMode: Text.Wrap; Layout.fillWidth: true }
                HelpButton { help: I18n.t("模型提交网页或文档后自动打开预览。关闭后，内容仍会显示在聊天中，点击时再打开。"); Layout.alignment: Qt.AlignVCenter }
                Toggle {
                    objectName: "desktopAutoOpenSubmissions"
                    checked: backend.desktopSettings.autoOpenSubmissions
                    Accessible.name: I18n.t("提交后自动打开预览")
                    onClicked: { const value = checked; checked = Qt.binding(function() { return backend.desktopSettings.autoOpenSubmissions }); backend.saveDesktopSettings(JSON.stringify({autoOpenSubmissions:value})) }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true; spacing: 10
                RowLayout {
                    Layout.fillWidth: true; spacing: 8
                    Text { text: I18n.t("网页打开方式"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); Layout.fillWidth: true }
                    HelpButton { help: I18n.t("网页链接和本地 HTML 均遵循此设置。系统默认浏览器可绕过内置 WebView 的兼容性问题。"); Layout.alignment: Qt.AlignVCenter }
                }
                ComboBox {
                    id: browserChoice
                    objectName: "desktopWebDisplay"
                    Layout.fillWidth: true
                    model: [I18n.t("内置网页预览"), I18n.t("系统默认浏览器")]
                    function syncSelection() { currentIndex = backend.desktopSettings.webDisplay === "external" ? 1 : 0 }
                    onModelChanged: Qt.callLater(syncSelection)
                    Component.onCompleted: syncSelection()
                    Connections { target: backend; function onDesktopSettingsChanged() { browserChoice.syncSelection() } }
                    font.family: Theme.fontFamily; font.pixelSize: Theme.font(13)
                    palette.text: Theme.ink; palette.buttonText: Theme.ink; palette.base: Theme.surface
                    palette.window: Theme.surface; palette.highlight: Theme.accentBg; palette.highlightedText: Theme.ink
                    implicitHeight: Theme.control(38)
                    Accessible.name: I18n.t("网页打开方式")
                    onActivated: index => { backend.saveDesktopSettings(JSON.stringify({webDisplay:index === 1 ? "external" : "embedded"})); syncSelection() }
                    background: Rectangle { radius: 8; color: Theme.surface; border.color: browserChoice.activeFocus ? Theme.accent : Theme.line }
                    contentItem: Text { text: browserChoice.displayText; font: browserChoice.font; color: Theme.ink; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; leftPadding: 12; rightPadding: 30 }
                    indicator: Glyph { name: "chevron-down"; width: Theme.icon(14); height: width; x: parent.width-width-12; y: (parent.height-height)/2; color: Theme.muted }
                }
            }
        }
    }
    SectionCard {
        width: parent.width
        ColumnLayout {
            id: remoteSettingsSection
            width: parent.width
            spacing: 12
            property bool addingRemote: false
            property string addReqId: ""
            property string remoteActionMessage: ""
            property string testingName: ""
            property string testReqId: ""

            Connections {
                target: backend
                function onRemoteAddHostFinished(reqId, result) {
                    if (reqId !== remoteSettingsSection.addReqId) return
                    remoteSettingsSection.addingRemote = false
                    remoteSettingsSection.addReqId = ""
                    if (result.ok) {
                        remoteHostInput.editText = ""
                        remoteSettingsSection.remoteActionMessage = ""
                    } else {
                        remoteSettingsSection.remoteActionMessage = result.error || I18n.t("无法添加远程机器")
                    }
                }
                function onRemoteTestFinished(reqId, result) {
                    if (reqId !== remoteSettingsSection.testReqId) return
                    remoteSettingsSection.testingName = ""
                    remoteSettingsSection.testReqId = ""
                    if (result.ok) {
                        remoteSettingsSection.remoteActionMessage = ""
                    } else {
                        remoteSettingsSection.remoteActionMessage = result.error || I18n.t("连接失败")
                    }
                }
            }

            Text {
                text: I18n.t("远程环境")
                color: Theme.ink
                font.family: Theme.fontFamily
                font.pixelSize: Theme.font(14)
                font.weight: Font.DemiBold
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                ComboBox {
                    id: remoteHostInput
                    objectName: "remoteEnvironmentHostInput"
                    Layout.fillWidth: true
                    implicitHeight: Theme.control(36)
                    editable: true
                    model: (backend.sshConfigHosts || []).map(item => item.alias)
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.font(13)
                    palette.text: Theme.ink; palette.buttonText: Theme.ink; palette.base: Theme.surface
                    palette.window: Theme.surface; palette.highlight: Theme.accentBg; palette.highlightedText: Theme.ink
                    Accessible.name: I18n.t("OpenSSH 主机别名")
                    background: Rectangle { radius: 8; color: Theme.surface; border.color: remoteHostInput.activeFocus ? Theme.accent : Theme.line }
                    contentItem: TextField {
                        text: remoteHostInput.editable ? remoteHostInput.editText : remoteHostInput.displayText
                        placeholderText: I18n.t("OpenSSH 主机别名")
                        placeholderTextColor: Theme.muted
                        font: remoteHostInput.font
                        color: Theme.ink
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 10; rightPadding: 28
                        selectByMouse: true
                        background: Item {}
                        onTextEdited: remoteHostInput.editText = text
                    }
                    indicator: Glyph { name: "chevron-down"; width: Theme.icon(13); height: width; x: parent.width - width - 10; y: (parent.height - height) / 2; color: Theme.muted }
                }
                ComboBox {
                    id: remotePlatformInput
                    objectName: "remoteEnvironmentPlatformInput"
                    Layout.preferredWidth: 112
                    implicitHeight: Theme.control(36)
                    model: [I18n.t("自动检测"), "Linux", "Windows"]
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.font(13)
                    palette.text: Theme.ink; palette.buttonText: Theme.ink; palette.base: Theme.surface
                    palette.window: Theme.surface; palette.highlight: Theme.accentBg; palette.highlightedText: Theme.ink
                    background: Rectangle { radius: 8; color: Theme.surface; border.color: remotePlatformInput.activeFocus ? Theme.accent : Theme.line }
                    contentItem: Text { text: remotePlatformInput.displayText; font: remotePlatformInput.font; color: Theme.ink; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; leftPadding: 10; rightPadding: 26 }
                    indicator: Glyph { name: "chevron-down"; width: Theme.icon(13); height: width; x: parent.width - width - 8; y: (parent.height - height) / 2; color: Theme.muted }
                }
                Button {
                    objectName: "remoteEnvironmentAddButton"
                    implicitHeight: Theme.control(36)
                    leftPadding: 14; rightPadding: 14
                    enabled: !remoteSettingsSection.addingRemote && remoteHostInput.editText.trim().length > 0
                    hoverEnabled: true
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                    background: Rectangle { radius: 8; color: parent.enabled ? Theme.button : Theme.hover; opacity: parent.enabled ? 1.0 : 0.5 }
                    contentItem: Text {
                        text: remoteSettingsSection.addingRemote ? I18n.t("添加中…") : I18n.t("添加")
                        color: parent.enabled ? Theme.buttonText : Theme.muted
                        font.family: Theme.fontFamily; font.pixelSize: Theme.font(13)
                        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        const host = remoteHostInput.editText.trim()
                        if (!host) return
                        const platform = remotePlatformInput.currentIndex === 1 ? "linux" : remotePlatformInput.currentIndex === 2 ? "windows" : ""
                        remoteSettingsSection.addingRemote = true
                        remoteSettingsSection.remoteActionMessage = ""
                        remoteSettingsSection.addReqId = backend.addRemoteEnvironment("", host, platform)
                    }
                }
            }
            Text {
                objectName: "remoteEnvironmentActionError"
                Layout.fillWidth: true
                visible: remoteSettingsSection.remoteActionMessage.length > 0
                text: remoteSettingsSection.remoteActionMessage
                textFormat: Text.PlainText
                wrapMode: Text.WrapAnywhere
                color: Theme.danger
                font.family: Theme.fontFamily
                font.pixelSize: Theme.font(12)
            }
            Text {
                Layout.fillWidth: true
                visible: remoteRows.count === 0
                text: I18n.t("可直接从 ~/.ssh/config 选择主机别名添加，或让 Agent 添加远程环境。")
                color: Theme.muted
                wrapMode: Text.Wrap
                font.family: Theme.fontFamily
                font.pixelSize: Theme.font(13)
            }
            Repeater {
                id: remoteRows
                model: backend.remoteEnvironments
                RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 10
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3
                        Text {
                            Layout.fillWidth: true
                            text: modelData.name
                            wrapMode: Text.Wrap
                            color: Theme.ink
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.font(13)
                        }
                        Text {
                            Layout.fillWidth: true
                            text: modelData.host + " · " + modelData.platform
                            wrapMode: Text.Wrap
                            color: Theme.muted
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.font(12)
                        }
                        Text {
                            objectName: "remoteEnvironmentSshClient_" + modelData.name
                            Layout.fillWidth: true
                            visible: !!modelData.sshClient
                            text: I18n.t("SSH 客户端：") + (modelData.sshClient || "")
                            color: Theme.muted
                            wrapMode: Text.WrapAnywhere
                            textFormat: Text.PlainText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.font(12)
                        }
                        Text {
                            objectName: "remoteEnvironmentRetry_" + modelData.name
                            Layout.fillWidth: true
                            visible: modelData.state === "reconnecting" && !!modelData.retryAfterMs
                            text: I18n.t("正在等待重试；重试间隔 %1 秒").arg(Math.ceil((modelData.retryAfterMs || 0) / 1000))
                                  + (modelData.attempt ? " · " + I18n.t("第 %1 次重试").arg(modelData.attempt) : "")
                            color: Theme.muted
                            wrapMode: Text.Wrap
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.font(12)
                        }
                        Text {
                            objectName: "remoteEnvironmentError_" + modelData.name
                            Layout.fillWidth: true
                            visible: (modelData.state === "reconnecting" || modelData.state === "error") && text.length > 0
                            text: modelData.message || modelData.sshError || ""
                            color: Theme.muted
                            wrapMode: Text.WrapAnywhere
                            textFormat: Text.PlainText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.font(12)
                        }
                    }
                    BusyIndicator {
                        visible: running
                        running: modelData.state === "connecting" || modelData.state === "reconnecting" || remoteSettingsSection.testingName === modelData.name
                        Layout.preferredWidth: Theme.icon(20)
                        Layout.preferredHeight: Theme.icon(20)
                    }
                    Text {
                        objectName: "remoteEnvironmentState_" + modelData.name
                        property string connectionState: modelData.state
                        text: I18n.t(({connected: "已连接", connecting: "连接中", reconnecting: "正在重新连接",
                                       disconnected: "未连接", error: "连接失败"})[modelData.state] || "未连接")
                        color: Theme.muted
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.font(13)
                    }
                    Button {
                        objectName: "remoteEnvironmentTest_" + modelData.name
                        implicitHeight: Theme.control(30)
                        leftPadding: 10; rightPadding: 10
                        enabled: remoteSettingsSection.testingName !== modelData.name
                        hoverEnabled: true
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        background: Rectangle { radius: 6; color: parent.hovered ? Theme.hover : Theme.bg; border.color: Theme.line }
                        contentItem: Text {
                            text: I18n.t("测试")
                            color: Theme.ink
                            font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                        }
                        onClicked: {
                            remoteSettingsSection.testingName = modelData.name
                            remoteSettingsSection.remoteActionMessage = ""
                            remoteSettingsSection.testReqId = backend.testRemoteEnvironment(modelData.name)
                        }
                    }
                    Button {
                        objectName: "remoteEnvironmentRemove_" + modelData.name
                        implicitHeight: Theme.control(30)
                        leftPadding: 10; rightPadding: 10
                        hoverEnabled: true
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        background: Rectangle { radius: 6; color: parent.hovered ? Theme.hover : "transparent"; border.color: Theme.line }
                        contentItem: Text {
                            text: I18n.t("移除")
                            color: Theme.muted
                            font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                        }
                        onClicked: backend.removeRemoteEnvironment(modelData.name)
                    }
                }
            }
        }
    }
}
