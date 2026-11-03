import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../app/qml" as Umeko

FocusScope {
    id: root
    objectName: "widgetMarket"
    required property var sdk
    clip: true
    focus: true

    property bool initialized: false
    property int epoch: 0
    property var rows: []
    property var pending: ({})
    property var localStates: ({})
    property var stagedTokens: ({})
    property var localDigests: ({})
    property string query: ""
    property string selectedId: ""
    readonly property var selected: rows.find(row => row.id === selectedId) || null
    readonly property var entries: rows.filter(row => ((row.name || row.id) + " " + (row.description || "")).toLowerCase().indexOf(query.toLowerCase()) >= 0)
    property string notice: ""
    property bool noticeError: false
    readonly property bool loading: Object.keys(pending).some(key => pending[key].operation === "market.list")
    readonly property bool working: Object.keys(pending).some(key => pending[key].operation !== "market.discard")

    function t(zh, en) { return sdk.language.indexOf("zh") === 0 ? zh : en }
    function localDate(value) {
        if (!value) return "—"
        const date = new Date(value)
        if (isNaN(date.getTime())) return "—"
        const month = String(date.getMonth() + 1).padStart(2, "0")
        const day = String(date.getDate()).padStart(2, "0")
        return String(date.getFullYear()).padStart(4, "0") + "-" + month + "-" + day
    }
    function setState(id, state, reason) {
        const next = Object.assign({}, localStates)
        if (state) next[id] = {state: state, reason: reason || ""}
        else delete next[id]
        localStates = next
    }
    function stateText(row) {
        const local = localStates[row.id]
        if (local && local.state === "installing") return t("正在安装…", "Installing…")
        if (local && local.state === "uninstalling") return t("正在卸载…", "Uninstalling…")
        if (local && local.state === "failed") return t("失败", "Failed")
        if (row.state === "update-available") return t("有可用更新", "Update available")
        if (row.state === "installed") return chatEnabled(row) ? t("已启用", "Enabled") : t("已安装", "Installed")
        return t("未安装", "Not installed")
    }
    function chatEnabled(row) { return !!row.sessionEnabled && row.enabled !== false }
    function actionText(row) {
        if (row.state === "update-available") return t("更新", "Update")
        if (row.state !== "installed") return t("安装", "Install")
        return chatEnabled(row) ? t("打开", "Open") : t("启用到当前会话", "Enable in this chat")
    }
    function activate(row) {
        if (!row || working || !sdk.active || row.builtin) return
        selectedId = row.id
        if (row.state !== "installed") install(row)
        else request(chatEnabled(row) ? "market.open" : "market.enable", {id: row.id}, row.id)
    }
    function browse(target) {
        if (!working) request("market.browse", target === "readme" ? {target: target, id: selectedId} : {target: target})
    }
    function digestText(row) {
        if (!row) return ""
        const verified = localDigests[row.id] !== undefined ? localDigests[row.id] : row.digestVerified
        if (verified === true) return t("校验值已核对", "Digest verified")
        if (verified === false) return t("发布源未提供校验值，无法核对", "No release digest is available to verify")
        return t("安装时核对校验值", "Digest is checked during installation")
    }
    function failure(value) {
        if (value && (value.status === "declined" || value.declined || (value.result && value.result.declined)))
            return t("已取消，未执行操作。", "Canceled; no action was taken.")
        const error = value ? (value.error || value.message || value.status) : ""
        if (error && typeof error === "object") return String(error.message || error.code || t("未知错误", "Unknown error"))
        return error ? String(error) : t("请求失败，请重试。", "Request failed. Please retry.")
    }
    function warningText(result) {
        const code = result.warningCode || ""
        if (code === "network") return t("暂时无法连接发布源，请稍后刷新。", "Cannot connect to the release source. Refresh again later.")
        if (code === "response") return t("发布源返回的响应无效，请稍后刷新。", "The release source returned an invalid response. Refresh again later.")
        if (code === "source") return t("暂时无法访问 Widget 列表，请稍后刷新。", "The Widget list is unavailable. Refresh again later.")
        if (code === "metadata") return t("部分 Widget 的说明暂时无法读取。", "Some Widget descriptions could not be loaded.")
        if (code === "rate-limit") {
            const limit = result.rateLimit || {}
            const after = limit.retryAfter !== undefined ? limit.retryAfter : limit["retry-after"]
            const reset = limit.reset !== undefined ? limit.reset : limit["x-ratelimit-reset"]
            let message = t("发布源请求过于频繁，请稍后刷新。", "The release source rate limit was reached. Refresh again later.")
            if (after !== undefined && after !== null && String(after) !== "")
                message += t(" 重试等待秒数：", " Retry after this many seconds: ") + String(after)
            else if (reset !== undefined && reset !== null && String(reset) !== "") {
                const seconds = Number(reset)
                const date = new Date(seconds * 1000)
                const timestamp = Number.isFinite(seconds) && !isNaN(date.getTime()) ? date.toISOString() : String(reset)
                message += t(" 配额重置时间：", " Rate limit resets at: ") + timestamp
            }
            return message
        }
        return result.warning ? t("提示：", "Notice: ") + result.warning : ""
    }
    function request(operation, args, rowId, allowInactive) {
        if (!sdk.active && !allowInactive) return false
        if (!sdk.hostCapabilities || !sdk.hostCapabilities.operations || !sdk.hostCapabilities.operations[operation]) {
            const reason = t("请升级到支持 Widget 市场的 Umeko 版本。", "Upgrade Umeko to a version that supports Widget Market.")
            if (rowId) setState(rowId, "failed", reason)
            else if (!allowInactive) { notice = reason; noticeError = true }
            return false
        }
        const id = sdk.requestHost(operation, args || {})
        if (!id) {
            const reason = t("宿主忙碌，请稍后重试。", "Umeko is busy. Please retry.")
            if (rowId) setState(rowId, "failed", reason)
            else if (!allowInactive) { notice = reason; noticeError = true }
            return false
        }
        const next = Object.assign({}, pending)
        next[id] = {operation: operation, args: args || {}, rowId: rowId || "", epoch: epoch}
        pending = next
        return true
    }
    function load(force) {
        if (!sdk.active) return
        notice = ""
        noticeError = false
        request("market.list", {force: !!force})
    }
    function initialize() {
        if (sdk.active && !initialized) {
            initialized = true
            epoch += 1
            load(false)
        }
    }
    function discard(token) {
        if (!token) return
        request("market.discard", {token: token}, "", true)
        const next = Object.assign({}, stagedTokens)
        delete next[token]
        stagedTokens = next
    }
    function install(row) {
        if (!sdk.active || working) return
        setState(row.id, "installing")
        request("market.prepare", {id: row.id}, row.id)
    }
    function uninstall(row) {
        if (!sdk.active || working) return
        setState(row.id, "uninstalling")
        request("market.uninstall", {id: row.id}, row.id)
    }
    Component.onCompleted: initialize()
    Component.onDestruction: Object.keys(stagedTokens).forEach(token => discard(token))

    Keys.onPressed: event => {
        if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_F) {
            search.forceActiveFocus(); search.selectAll(); event.accepted = true
        }
    }
    Rectangle { anchors.fill: parent; color: root.sdk.colors.surface; z: -1 }
    component Label: Text { color: root.sdk.colors.ink; font.family: Umeko.Theme.fontFamily; font.pixelSize: Umeko.Theme.font(12); textFormat: Text.PlainText; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
    component SmallButton: Button {
        id: button
        property bool selected: false
        font.family: Umeko.Theme.fontFamily
        implicitHeight: 28 * root.sdk.scale
        implicitWidth: Math.max(28 * root.sdk.scale, label.implicitWidth + 18 * root.sdk.scale)
        background: Rectangle { radius: 5 * root.sdk.scale; color: button.selected ? root.sdk.colors.accentBg : button.hovered ? root.sdk.colors.hover : "transparent"; border.color: button.selected ? root.sdk.colors.accent : root.sdk.colors.line }
        contentItem: Label { id: label; text: button.text; font.pixelSize: Umeko.Theme.font(11); horizontalAlignment: Text.AlignHCenter; color: button.enabled ? root.sdk.colors.ink : root.sdk.colors.muted }
        Accessible.name: text
    }
    component Input: TextField {
        selectByMouse: true; color: root.sdk.colors.ink; font.family: Umeko.Theme.fontFamily; font.pixelSize: Umeko.Theme.font(12)
        implicitHeight: 34 * root.sdk.scale; placeholderTextColor: root.sdk.colors.muted
        background: Rectangle { radius: 5 * root.sdk.scale; color: root.sdk.colors.surface; border.color: parent.activeFocus ? root.sdk.colors.accent : root.sdk.colors.line }
    }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 12 * root.sdk.scale; spacing: 8 * root.sdk.scale
        RowLayout {
            Layout.fillWidth: true; spacing: 8 * root.sdk.scale
            Input {
                id: search; objectName: "widgetMarketSearch"; Layout.fillWidth: true; Layout.minimumWidth: 80 * root.sdk.scale
                placeholderText: root.t("搜索名称或简介…", "Find name or description…")
                onTextChanged: root.query = text
                Accessible.name: root.t("搜索 Widget", "Search Widgets")
            }
            Label { objectName:"widgetMarketCount";text: root.entries.length + root.t(" 个 Widget", " Widgets"); color: root.sdk.colors.muted; font.pixelSize: Umeko.Theme.font(10) }
            SmallButton {
                objectName: "widgetMarketRefresh"; text: ""; enabled: root.sdk.active && !root.working
                contentItem: Umeko.Glyph { name:"refresh-cw";width:16*root.sdk.scale;height:16*root.sdk.scale;color:root.sdk.colors.muted }
                onClicked: root.load(true); Accessible.name: root.t("刷新", "Refresh")
                ToolTip.visible: hovered; ToolTip.text: root.t("刷新发布列表", "Refresh releases")
            }
        }
        RowLayout {
            Layout.fillWidth: true
            SmallButton {
                id: sourceButton; objectName: "widgetMarketSource"; Layout.fillWidth: true
                text: root.t("来自 umeko-desktop-widgets", "From umeko-desktop-widgets")
                enabled: root.sdk.active && !root.working
                background: Item { }
                contentItem: Label { text: sourceButton.text; color: root.sdk.colors.muted; font.pixelSize: Umeko.Theme.font(10) }
                onClicked: root.browse("repository")
            }
            SmallButton {
                objectName: "widgetMarketImportLocal"; text: root.t("导入本地 ZIP", "Import local ZIP")
                enabled: root.sdk.active && !root.working; onClicked: root.request("market.importLocal", {})
            }
        }
        Label {
            Layout.fillWidth: true; font.pixelSize: Umeko.Theme.font(10); color: root.sdk.colors.muted
            text: root.t("新安装的 Widget 需明确启用后才加入当前会话。", "New Widgets join this chat only after you enable them.")
            wrapMode: Text.Wrap
        }
        Label {
            objectName: "widgetMarketNotice"; Layout.fillWidth: true; visible: root.rows.length > 0 && text !== ""
            text: root.notice || (root.loading ? root.t("正在读取…", "Loading…") : "")
            color: root.sdk.colors.muted; font.pixelSize: Umeko.Theme.font(10); wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter
        }
        SplitView {
            id: marketSplit; objectName: "widgetMarketSplit"; orientation: Qt.Vertical
            Layout.fillWidth: true; Layout.fillHeight: true
            handle: Rectangle {
                objectName: "widgetMarketSplitHandle"; implicitHeight: 10 * (root.sdk ? root.sdk.scale : 1); color: "transparent"
                Rectangle { anchors.centerIn: parent; width: 42 * (root.sdk ? root.sdk.scale : 1); height: 3; radius: 2; color: !root.sdk ? "transparent" : SplitHandle.hovered || SplitHandle.pressed ? root.sdk.colors.accent : root.sdk.colors.line }
                HoverHandler { cursorShape: Qt.SplitVCursor }
            }
            ListView {
                id: list; objectName: "widgetMarketList"; SplitView.fillHeight: true
                SplitView.preferredHeight: marketSplit.height * .58; SplitView.minimumHeight: Math.min(100 * root.sdk.scale, marketSplit.height * .25)
                clip: true; reuseItems: true; spacing: 0; model: root.entries; currentIndex: 0; boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                onCurrentIndexChanged: { const row = root.entries[currentIndex]; if (row) root.selectedId = row.id }
                Keys.onReturnPressed: { const row = root.entries[currentIndex]; if (row) root.activate(row) }
                delegate: Rectangle {
                    id: entry; required property var modelData; required property int index
                    objectName: "widgetMarketRow_" + modelData.id
                    readonly property var local: root.localStates[modelData.id] || ({})
                    width: list.width; height: 64 * root.sdk.scale
                    color: root.selectedId === modelData.id ? root.sdk.colors.accentBg : hover.hovered ? root.sdk.colors.hover : "transparent"
                    HoverHandler { id: hover }
                    MouseArea { anchors.fill: parent; onClicked: { list.currentIndex = entry.index; root.selectedId = entry.modelData.id; list.forceActiveFocus() } }
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 4 * root.sdk.scale; anchors.rightMargin: 6 * root.sdk.scale; spacing: 8 * root.sdk.scale
                        Umeko.WidgetIcon { plugin: entry.modelData; Layout.preferredWidth: 20 * root.sdk.scale; Layout.preferredHeight: 20 * root.sdk.scale }
                        ColumnLayout {
                            Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 2 * root.sdk.scale
                            Label { Layout.fillWidth: true; text: entry.modelData.name || entry.modelData.id; font.pixelSize: Umeko.Theme.font(11) }
                            Label {
                                objectName: "widgetMarketDescription_" + entry.modelData.id
                                Layout.fillWidth: true; text: entry.modelData.description || ""; color: root.sdk.colors.muted; font.pixelSize: Umeko.Theme.font(10)
                            }
                            RowLayout {
                                Layout.fillWidth: true; spacing: 5 * root.sdk.scale
                                Label { text: entry.modelData.version || "—"; color: root.sdk.colors.muted; font.pixelSize: Umeko.Theme.font(10) }
                                Rectangle {
                                    Layout.preferredHeight: 17 * root.sdk.scale; Layout.preferredWidth: Math.min(badge.implicitWidth + 10 * root.sdk.scale, Math.max(0, parent.width - 50 * root.sdk.scale))
                                    color: "transparent"; border.color: root.sdk.colors.line; radius: 3 * root.sdk.scale
                                    Label {
                                        id: badge; objectName: "widgetMarketState_" + entry.modelData.id
                                        anchors.fill: parent; anchors.leftMargin: 5 * root.sdk.scale; anchors.rightMargin: 5 * root.sdk.scale
                                        text: root.stateText(entry.modelData); color: entry.local.state === "failed" ? root.sdk.colors.danger : root.sdk.colors.muted; font.pixelSize: Umeko.Theme.font(9)
                                    }
                                }
                                Item { Layout.fillWidth: true }
                            }
                        }
                        SmallButton {
                            objectName: "widgetMarketAction_" + entry.modelData.id
                            visible: !entry.modelData.builtin; text: root.actionText(entry.modelData)
                            Layout.preferredWidth: implicitWidth; Layout.maximumWidth: Math.max(100 * root.sdk.scale, list.width * .42)
                            enabled: root.sdk.active && !root.working
                            onClicked: root.activate(entry.modelData)
                            Accessible.name: text + " " + (entry.modelData.name || entry.modelData.id)
                        }
                    }
                }
                ColumnLayout {
                    anchors.centerIn: parent; width: Math.max(0, parent.width - 36 * root.sdk.scale); spacing: 8 * root.sdk.scale
                    visible: root.entries.length === 0
                    Label {
                        objectName: "widgetMarketEmpty"
                        Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
                        text: root.notice || (root.loading ? root.t("正在读取发布列表…", "Loading releases…") : root.query ? root.t("没有匹配的 Widget", "No matching Widgets") : root.t("暂无可安装的 Widget", "No Widgets are available"))
                        color: root.sdk.colors.muted; font.pixelSize: Umeko.Theme.font(11)
                    }
                    SmallButton {
                        Layout.alignment: Qt.AlignHCenter; text: root.t("导入本地 ZIP", "Import local ZIP")
                        enabled: root.sdk.active && !root.working; onClicked: root.request("market.importLocal", {})
                    }
                }
            }
            Rectangle {
                objectName: "widgetMarketDetails"; color: root.sdk.colors.surface; border.color: root.sdk.colors.line; radius: 6
                SplitView.minimumHeight: Math.min(130 * root.sdk.scale, marketSplit.height * .3); SplitView.preferredHeight: marketSplit.height * .42
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 10 * root.sdk.scale; spacing: 6 * root.sdk.scale
                    RowLayout {
                        Layout.fillWidth: true; spacing: 7 * root.sdk.scale
                        Umeko.WidgetIcon { visible: !!root.selected; plugin: root.selected || ({}); Layout.preferredWidth: 18 * root.sdk.scale; Layout.preferredHeight: 18 * root.sdk.scale }
                        Label { Layout.fillWidth: true; font.bold: true; text: root.selected ? root.selected.name || root.selected.id : root.t("Widget 详情", "Widget details") }
                        SmallButton { objectName: "widgetMarketReadme"; visible: !!root.selected; text: "README"; enabled: !root.working; onClicked: root.browse("readme") }
                        SmallButton {
                            objectName: "widgetMarketUninstall"; visible: !!root.selected && !root.selected.builtin && !!root.selected.installedVersion
                            text: root.t("卸载", "Uninstall"); enabled: !root.working; onClicked: root.uninstall(root.selected)
                        }
                    }
                    ScrollView {
                        id: detailsScroll; Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                        Column {
                            width: detailsScroll.availableWidth; spacing: 6 * root.sdk.scale
                            Label {
                                width: parent.width; text: root.selected ? root.selected.description || "" : root.t("选择一个 Widget 查看详情。", "Select a Widget to see its details.")
                                wrapMode: Text.Wrap; elide: Text.ElideNone; color: root.sdk.colors.muted; font.pixelSize: Umeko.Theme.font(11)
                            }
                            Label {
                                objectName: "widgetMarketRelease"; width: parent.width; visible: !!root.selected
                                text: root.selected ? root.t("版本 ", "Version ") + (root.selected.version || "—") + " · " + root.t("发布于 ", "Published ") + root.localDate(root.selected.publishedAt) : ""
                                wrapMode: Text.Wrap; color: root.sdk.colors.muted; font.pixelSize: Umeko.Theme.font(10)
                            }
                            Label {
                                width: parent.width; visible: !!root.selected && !!root.selected.installedVersion
                                text: root.selected ? root.t("已安装版本 ", "Installed version ") + (root.selected.installedVersion || "") : ""
                                wrapMode: Text.Wrap; color: root.sdk.colors.muted; font.pixelSize: Umeko.Theme.font(10)
                            }
                            Label {
                                objectName: "widgetMarketPermissions"; width: parent.width; visible: !!root.selected
                                text: root.selected ? root.t("权限：", "Permissions: ") + ((root.selected.permissions || []).join(" · ") || root.t("未声明", "None declared")) : ""
                                wrapMode: Text.Wrap; color: root.sdk.colors.muted; font.pixelSize: Umeko.Theme.font(10)
                            }
                            Label {
                                objectName: "widgetMarketDigest"; width: parent.width; visible: !!root.selected
                                text: root.digestText(root.selected); wrapMode: Text.Wrap; color: root.sdk.colors.muted; font.pixelSize: Umeko.Theme.font(10)
                            }
                            Label {
                                objectName: "widgetMarketDetailState"; width: parent.width; visible: !!root.selected && (root.localStates[root.selectedId] || {}).state === "failed"
                                text: root.selected ? (root.localStates[root.selectedId] || {}).reason || "" : ""; wrapMode: Text.Wrap; elide: Text.ElideNone; color: root.sdk.colors.danger; font.pixelSize: Umeko.Theme.font(10)
                            }
                        }
                    }
                }
            }
        }
    }
    Connections {
        target: root.sdk
        ignoreUnknownSignals: true
        function onActiveChanged() {
            // Native approval temporarily blocks the pane. Keep its download
            // token; the host owns cleanup when the page/worker actually stops.
            root.initialize()
        }
        function onHostResponse(id, value) {
            const entry = root.pending[id]
            if (!entry) return
            const next = Object.assign({}, root.pending)
            delete next[id]
            root.pending = next
            const result = value && value.result ? value.result : {}
            const current = root.sdk.active && entry.epoch === root.epoch
            if (entry.operation === "market.discard") return
            if (entry.operation === "market.install") {
                const tokens = Object.assign({}, root.stagedTokens)
                delete tokens[entry.args.token]
                root.stagedTokens = tokens
            }
            if (entry.operation === "market.prepare" && result.token && !current) {
                root.discard(result.token)
                root.setState(entry.rowId, "")
                return
            }
            const declined = value && (value.status === "declined" || value.declined || result.declined)
            if (!value || !value.ok || declined) {
                if (entry.rowId) root.setState(entry.rowId, "failed", root.failure(value))
                else if (current) { root.notice = root.failure(value); root.noticeError = true }
                return
            }
            if (entry.operation === "market.list") {
                if (!current) return
                const returned = result.rows || []
                if (returned.length || !result.warningCode || !root.rows.length) root.rows = returned
                if (!root.selected) root.selectedId = root.rows.length ? root.rows[0].id : ""
                root.notice = root.warningText(result)
                root.noticeError = !!result.warningCode && result.warningCode !== "metadata"
            } else if (entry.operation === "market.prepare") {
                if (!result.token) {
                    root.setState(entry.rowId, "failed", root.t("未收到有效的安装包。", "No valid installation package was returned."))
                    return
                }
                const tokens = Object.assign({}, root.stagedTokens)
                tokens[result.token] = entry.rowId
                root.stagedTokens = tokens
                const digests = Object.assign({}, root.localDigests)
                digests[entry.rowId] = !!result.digestVerified
                root.localDigests = digests
                if (!root.request("market.install", {token: result.token}, entry.rowId)) root.discard(result.token)
            } else if (["market.install", "market.uninstall", "market.enable"].indexOf(entry.operation) >= 0) {
                root.setState(entry.rowId, "")
                Qt.callLater(() => { if (root.sdk.active) root.load(false) })
            }
        }
    }
}
