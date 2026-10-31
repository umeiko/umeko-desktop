import QtQuick
import QtQuick.Controls

Rectangle {
    id: pane
    objectName: "webPane"
    property bool opened: false
    property bool blocked: false
    property bool resizing: false
    property bool surfaceReady: false
    onOpenedChanged: if (!opened) surfaceReady = false
    property string pageUrl: ""
    property string pageTitle: ""
    property string mode: "web"
    readonly property bool subagentInputFocused: !!agentSurface.item && agentSurface.item.inputFocused
    readonly property bool pluginInputFocused: !!pluginSurface.item && pluginSurface.item.activeFocus
    property string documentPath: ""
    property real preferredWidth: 480
    readonly property real animatedWidth: Math.max(0, motion.value.width - 1)
    readonly property bool moving: motion.moving && !resizing
    readonly property bool live: opened && !moving && !blocked && visible
    width: animatedWidth
    visible: animatedWidth > 0.5
    color: Theme.surface
    clip: true
    // Opened by fresh Agent deliveries or an explicit click on a delivered URL card.
    function submit(url, title) {
        backend.desktopPlugins.closePage()
        const clean = backend.normalizeWebUrl(url)
        if (!clean || !backend.webviewAvailable) return
        if (mode === "subagent") backend.subagents.closeView()
        backend.documentPreview.cancel()
        pageTitle = title || ""
        if (mode === "web" && surface.item && pageUrl === clean) surface.item.reload()
        else { pageUrl = clean; if (surface.item) surface.item.url = clean }
        mode = "web"
        opened = true
    }
    function showDocument(item) {
        backend.desktopPlugins.closePage()
        if (mode === "subagent") backend.subagents.closeView()
        address.focus = false
        documentPath = item.path; pageTitle = item.title || item.name || item.path.split(/[\\/]/).pop()
        mode = "document"; opened = true
        backend.documentPreview.load(documentPath, item.kind || "file")
    }
    function showSubagent() { backend.desktopPlugins.closePage(); address.focus = false; backend.documentPreview.cancel(); mode = "subagent"; opened = true }
    function showPlugin() { if (mode === "subagent") backend.subagents.closeView(); address.focus = false; backend.documentPreview.cancel(); mode = "plugin"; opened = true }
    function dismiss() { backend.desktopPlugins.closePage(); address.focus = false; opened = false; backend.documentPreview.cancel(); if (mode === "subagent") backend.subagents.closeView() }
    function snapWidth() { motion.snap() }
    function navigate() {
        const url = backend.normalizeWebUrl(address.text)
        if (!opened || !url) { address.text = pageUrl; return }
        pageUrl = url
        if (surface.item) surface.item.url = url
    }
    PidMotion { id: motion; objectName: "webPaneMotion"; targetRect: Qt.rect(0, 0, pane.opened ? pane.preferredWidth + 1 : 1, 1) }
    Rectangle { width: 1; height: parent.height; color: Theme.line }
    Item {
        id: heading
        visible: pane.mode !== "subagent"
        width: parent.width; height: Theme.control(pane.mode === "plugin" ? 35 : 44)
        WidgetIcon {visible:pane.mode==="plugin";plugin:backend.desktopPlugins.page;x:16;anchors.verticalCenter:parent.verticalCenter;width:Theme.icon(15);height:width}
        Glyph {visible:pane.mode!=="plugin";x:16;anchors.verticalCenter:parent.verticalCenter;name:pane.mode==="web"?"globe":backend.documentPreview.state.kind==="code"?"code":"file";width:Theme.icon(15);height:width}
        Text { font.family: Theme.fontFamily; x: 40; width: Math.max(0, parent.width - 88); anchors.verticalCenter: parent.verticalCenter; textFormat: Text.PlainText; text: pane.mode === "web" && surface.item && surface.item.title ? surface.item.title : pane.mode === "plugin" ? I18n.widgetText(backend.desktopPlugins.page, backend.desktopPlugins.page.title || "") : pane.pageTitle || pane.pageUrl; elide: Text.ElideRight; color: Theme.ink; font.pixelSize: Theme.font(11) }
        ActionButton { objectName: "closeWebPaneButton"; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; width: Theme.control(28); height: width; quiet: true; glyph: "x"; hint: I18n.t("关闭预览"); onClicked: pane.dismiss() }
    }
    Row {
        id: toolbar
        x: 9; y: heading.height; spacing: 3; height: pane.mode === "web" ? Theme.control(42) : 0; visible: pane.mode === "web"
        ActionButton { objectName: "webBackButton"; width: Theme.control(29); height: Theme.control(30); quiet: true; glyph: "arrow-left"; enabled: !!surface.item && surface.item.canGoBack; hint: I18n.t("后退"); onClicked: surface.item.goBack() }
        ActionButton { objectName: "webForwardButton"; width: Theme.control(29); height: Theme.control(30); quiet: true; glyph: "arrow-right"; enabled: !!surface.item && surface.item.canGoForward; hint: I18n.t("前进"); onClicked: surface.item.goForward() }
        ActionButton { objectName: "webReloadButton"; width: Theme.control(29); height: Theme.control(30); quiet: true; glyph: "refresh-cw"; enabled: !!surface.item; hint: I18n.t("刷新"); onClicked: { surface.item.errorMessage = ""; surface.item.reload() } }
        TextField { font.family: Theme.fontFamily;
            id: address; objectName: "webAddress"
            width: Math.max(80, pane.width - toolbar.x * 2 - Theme.control(96)); height: Theme.control(30)
            text: pane.pageUrl; selectByMouse: true; font.pixelSize: Theme.font(11); color: Theme.ink; leftPadding: 11; rightPadding: 11
            background: Rectangle { radius: 15; color: Theme.bg; border.color: address.activeFocus ? Theme.accent : Theme.line }
            onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { if (address.activeFocus) address.selectAll() })
            onAccepted: { pane.navigate(); focus = false }
        }
    }
    Item {
        id: viewSwitch; x: 16; y: heading.height; width: parent.width-32
        height: visible ? Theme.control(39) : 0
        visible: pane.mode === "document" && ["markdown","html"].includes(backend.documentPreview.state.fileType || "")
        Row { spacing: 3; anchors.verticalCenter: parent.verticalCenter
            Repeater {
                model: ["source","rendered"]
                ActionButton {
                    required property string modelData
                    objectName: "documentMode_" + modelData
                    readonly property bool selected: backend.documentPreview.state.mode === modelData
                    text: modelData === "source" ? I18n.t("源码") : backend.documentPreview.state.fileType === "html" ? I18n.t("网页") : I18n.t("渲染")
                    width: Theme.control(70); height: Theme.control(29); quiet: true
                    enabled: modelData === "source" || backend.documentPreview.state.fileType !== "html" || !!backend.documentPreview.state.renderable
                    hint: !enabled ? I18n.t(backend.documentPreview.state.renderNote || "") : ""
                    background: Rectangle { radius: 7; color: parent.selected ? Theme.accentBg : parent.interactionHovered ? Theme.hover : "transparent" }
                    onClicked: backend.documentPreview.setMode(backend.documentPreview.state.fileType,modelData)
                    Accessible.role: Accessible.RadioButton; Accessible.checked: selected
                }
            }
        }
    }
    Item {
        id: fileToolbar; x: 12; y: heading.height + viewSwitch.height; width: parent.width - 24; height: pane.mode === "document" ? Theme.control(36) : 0; visible: pane.mode === "document"
        Text { font.family: Theme.fontFamily; anchors.left: parent.left; anchors.right: fileActions.left; anchors.verticalCenter: parent.verticalCenter; text: pane.documentPath; textFormat: Text.PlainText; elide: Text.ElideMiddle; color: Theme.muted; font.pixelSize: Theme.font(10) }
        Row {
            id: fileActions; anchors.right: parent.right; spacing: 2
            ActionButton { objectName: "copyDocumentPreviewButton"; glyph: "copy"; quiet: true; width: Theme.control(30); height: Theme.control(30); enabled: !backend.documentPreview.state.busy && !backend.documentPreview.state.error; hint: I18n.t("复制预览内容"); onClicked: backend.copy(backend.documentPreview.state.text || "") }
            ActionButton { objectName: "openDocumentFileButton"; glyph: "external-link"; quiet: true; width: Theme.control(30); height: Theme.control(30); hint: I18n.t("打开完整文件"); onClicked: backend.openChatboxPath(pane.documentPath, false) }
        }
    }
    Rectangle { x: 1; y: toolbar.y + toolbar.height; width: parent.width - 1; height: 1; color: Theme.line; visible: pane.mode !== "subagent" }
    Rectangle { x: 1; y: toolbar.y + toolbar.height; height: 2; color: Theme.accent; width: surface.item ? (parent.width - 1) * surface.item.loadProgress / 100 : 0; visible: !!surface.item && surface.item.loading }
    // WebView2 must be initialized in a visible, settled native window.
    // Retain the page through later resizes and temporary overlay blocking.
    Timer {
        interval: 0
        running: pane.opened && pane.mode === "web" && !pane.moving && !pane.blocked && !pane.surfaceReady
        onTriggered: pane.surfaceReady = true
    }
    Loader {
        id: surface; objectName: "webSurfaceLoader"
        anchors.left: parent.left; anchors.leftMargin: 6; anchors.right: parent.right; anchors.rightMargin: 12
        anchors.top: toolbar.bottom; anchors.topMargin: 1; anchors.bottom: parent.bottom; anchors.bottomMargin: 12
        active: pane.opened && pane.mode === "web" && pane.surfaceReady
        visible: !pane.moving && !pane.blocked && (!item || !item.errorMessage)
        source: active ? "WebSurface.qml" : ""
        onLoaded: item.url = pane.pageUrl
    }
    Item {
        objectName: "webLoadError"
        anchors.fill: surface
        visible: pane.opened && pane.mode === "web" && !pane.moving && !pane.blocked
                 && (surface.status === Loader.Error || !!surface.item && !!surface.item.errorMessage)
        Column {
            anchors.centerIn: parent; width: Math.max(0, Math.min(parent.width - 48, 420)); spacing: 16
            Text { font.family: Theme.fontFamily; width: parent.width; text: I18n.t("网页加载失败"); color: Theme.ink; font.pixelSize: Theme.font(15); wrapMode: Text.Wrap }
            Text { font.family: Theme.fontFamily; width: parent.width; text: surface.item ? surface.item.errorMessage : I18n.t("网页组件加载失败，请重新安装最新版本。"); color: Theme.muted; font.pixelSize: Theme.font(12); wrapMode: Text.WrapAnywhere }
            ActionButton {
                objectName: "retryWebLoadButton"; text: I18n.t("重试"); glyph: "refresh-cw"
                onClicked: {
                    if (surface.item) { surface.item.errorMessage = ""; surface.item.reload() }
                    else { pane.surfaceReady = false }
                }
            }
        }
    }
    Loader {
        id: documentSurface; objectName: "documentSurfaceLoader"
        x: 1; y: fileToolbar.y + fileToolbar.height + 1
        width: Math.max(0, pane.preferredWidth - 1); height: parent.height - y
        active: pane.opened && pane.mode === "document"; visible: !pane.blocked
        source: active ? "DocumentSurface.qml" : ""
        onLoaded: item.browserAllowed = Qt.binding(function() { return pane.live })
    }
    Connections {
        target: surface.item
        function onUrlChanged() { pane.pageUrl = String(surface.item.url); if (!address.activeFocus) address.text = pane.pageUrl }
    }
    Loader {
        id: pluginSurface; objectName: "desktopPluginSurfaceLoader"
        x: 1; y: heading.height; width: Math.max(0,pane.preferredWidth-1); height: parent.height-y
        active: pane.opened && pane.mode === "plugin"
        source: active ? "DesktopPluginSurface.qml" : ""
        onLoaded: item.live = Qt.binding(function() { return pane.live })
    }
    Connections { target: backend.desktopPlugins; function onDismissed() { if (pane.mode === "plugin") { pane.opened = false } } }
    Loader {
        id: agentSurface; objectName: "subagentSurfaceLoader"
        x: 1; y: 0; width: Math.max(0,pane.preferredWidth-1); height: parent.height
        active: pane.opened && pane.mode === "subagent"
        source: active ? "SubagentPane.qml" : ""
    }
    Connections { target: agentSurface.item; function onClosed() { pane.dismiss() } }
}
