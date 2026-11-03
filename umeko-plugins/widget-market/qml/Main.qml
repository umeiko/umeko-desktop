import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "widgetMarket"
    required property var sdk
    color: sdk.colors.surface
    clip: true

    property bool initialized: false
    property int epoch: 0
    property var rows: []
    property var pending: ({})
    property var localStates: ({})
    property var stagedTokens: ({})
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
        if (local && local.state === "failed") return t("操作失败：", "Failed: ") + local.reason
        const installed = row.installedVersion ? t("已安装版本 ", "Installed version ") + row.installedVersion : t("已安装", "Installed")
        if (row.state === "update-available") return t("有可用更新", "Update available") + (row.installedVersion ? " · " + installed : "")
        if (row.state === "installed") return installed
        return t("未安装", "Not installed")
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
        if (code === "source") return t("固定发布源暂不可用，请稍后刷新。", "The fixed release source is unavailable. Refresh again later.")
        if (code === "metadata") return t("部分 Widget 的发布信息无效，已从列表中跳过。", "Some Widgets have invalid release information and were skipped.")
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
    function deactivate() {
        initialized = false
        epoch += 1
        Object.keys(stagedTokens).forEach(token => discard(token))
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

    component Copy: Text {
        textFormat: Text.PlainText
        color: root.sdk.colors.ink
        font.pixelSize: 12 * root.sdk.scale
        wrapMode: Text.Wrap
    }
    component MarketButton: Button {
        id: control
        property bool primary: false
        implicitHeight: 34 * root.sdk.scale
        leftPadding: 12 * root.sdk.scale
        rightPadding: 12 * root.sdk.scale
        topPadding: 6 * root.sdk.scale
        bottomPadding: 6 * root.sdk.scale
        Accessible.name: text
        background: Rectangle {
            radius: 7 * root.sdk.scale
            color: control.down || (control.primary && control.enabled) ? root.sdk.colors.accentBg : control.hovered ? root.sdk.colors.hover : "transparent"
            border.width: control.activeFocus ? 2 : 1
            border.color: control.activeFocus || (control.primary && control.enabled) ? root.sdk.colors.accent : root.sdk.colors.line
        }
        contentItem: Text {
            text: control.text
            textFormat: Text.PlainText
            color: !control.enabled ? root.sdk.colors.muted : control.primary ? root.sdk.colors.accent : root.sdk.colors.ink
            font.pixelSize: 12 * root.sdk.scale
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16 * root.sdk.scale
        spacing: 12 * root.sdk.scale
        RowLayout {
            Layout.fillWidth: true
            spacing: 10 * root.sdk.scale
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4 * root.sdk.scale
                Copy {
                    text: root.t("Widget 市场", "Widget Market")
                    font.pixelSize: 18 * root.sdk.scale
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                }
                Copy {
                    text: root.t("固定发布源 · GitHub Releases", "Fixed source · GitHub Releases")
                    color: root.sdk.colors.muted
                    font.pixelSize: 11 * root.sdk.scale
                    Layout.fillWidth: true
                }
            }
            MarketButton {
                objectName: "widgetMarketRefresh"
                text: root.t("刷新", "Refresh")
                enabled: root.sdk.active && !root.working
                onClicked: root.load(true)
            }
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: helpText.implicitHeight + 20 * root.sdk.scale
            radius: 8 * root.sdk.scale
            color: root.sdk.colors.bg
            border.color: root.sdk.colors.line
            Copy {
                id: helpText
                anchors.fill: parent
                anchors.margins: 10 * root.sdk.scale
                text: root.t("新安装的 Widget 不会加入当前聊天或运行，请到“设置 > Agent > 插件管理”明确启用。手动导入 ZIP 也在此处。", "New Widgets are not added to this chat or run until explicitly enabled in Settings > Agent > Plugin Management. Import a local ZIP there too.")
                color: root.sdk.colors.muted
                font.pixelSize: 11 * root.sdk.scale
            }
        }
        Copy {
            objectName: "widgetMarketNotice"
            Layout.fillWidth: true
            visible: text !== ""
            text: root.notice || (root.loading ? root.t("正在读取发布列表…", "Loading releases…") : "")
            color: root.noticeError ? root.sdk.colors.danger : root.sdk.colors.muted
            Accessible.role: Accessible.StaticText
        }
        ListView {
            id: list
            objectName: "widgetMarketList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: root.rows
            spacing: 10 * root.sdk.scale
            ScrollBar.vertical: ScrollBar { }
            delegate: Rectangle {
                id: card
                required property var modelData
                readonly property var local: root.localStates[modelData.id] || ({})
                width: list.width
                implicitHeight: content.implicitHeight + 24 * root.sdk.scale
                radius: 8 * root.sdk.scale
                color: root.sdk.colors.bg
                border.color: root.sdk.colors.line
                ColumnLayout {
                    id: content
                    anchors.fill: parent
                    anchors.margins: 12 * root.sdk.scale
                    spacing: 8 * root.sdk.scale
                    Copy {
                        Layout.fillWidth: true
                        text: card.modelData.name || card.modelData.id
                        font.pixelSize: 14 * root.sdk.scale
                        font.weight: Font.DemiBold
                        wrapMode: Text.WrapAnywhere
                    }
                    Copy {
                        Layout.fillWidth: true
                        visible: text !== ""
                        text: card.modelData.description || ""
                        color: root.sdk.colors.muted
                    }
                    Copy {
                        objectName: "widgetMarketRelease_" + card.modelData.id
                        Layout.fillWidth: true
                        text: root.t("版本 ", "Version ") + (card.modelData.version || "—") + "  ·  " + root.t("发布于 ", "Published ") + root.localDate(card.modelData.publishedAt)
                        color: root.sdk.colors.muted
                        font.pixelSize: 11 * root.sdk.scale
                        wrapMode: Text.WrapAnywhere
                    }
                    Copy {
                        objectName: "widgetMarketState_" + card.modelData.id
                        Layout.fillWidth: true
                        text: root.stateText(card.modelData)
                        color: card.local.state === "failed" ? root.sdk.colors.danger : root.sdk.colors.muted
                        Accessible.role: Accessible.StaticText
                    }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 8 * root.sdk.scale
                        MarketButton {
                            objectName: "widgetMarketInstall_" + card.modelData.id
                            visible: !card.modelData.builtin && card.modelData.state !== "installed"
                            primary: true
                            text: card.modelData.state === "update-available" ? root.t("更新", "Update") : root.t("安装", "Install")
                            Accessible.name: text + " " + (card.modelData.name || card.modelData.id)
                            enabled: root.sdk.active && !root.working
                            onClicked: root.install(card.modelData)
                        }
                        MarketButton {
                            objectName: "widgetMarketUninstall_" + card.modelData.id
                            visible: !card.modelData.builtin && !!card.modelData.installedVersion
                            text: root.t("卸载", "Uninstall")
                            Accessible.name: text + " " + (card.modelData.name || card.modelData.id)
                            enabled: root.sdk.active && !root.working
                            onClicked: root.uninstall(card.modelData)
                        }
                    }
                }
            }
            Copy {
                anchors.centerIn: parent
                width: Math.max(0, parent.width - 32 * root.sdk.scale)
                horizontalAlignment: Text.AlignHCenter
                visible: root.rows.length === 0 && !root.loading && !root.noticeError
                text: root.t("暂无可安装的 Widget。", "No Widgets are available.")
                color: root.sdk.colors.muted
            }
        }
    }
    Connections {
        target: root.sdk
        ignoreUnknownSignals: true
        function onActiveChanged() {
            if (root.sdk.active) root.initialize()
            else root.deactivate()
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
                root.rows = result.rows || []
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
                if (!root.request("market.install", {token: result.token}, entry.rowId)) root.discard(result.token)
            } else if (entry.operation === "market.install" || entry.operation === "market.uninstall") {
                root.setState(entry.rowId, "")
                if (root.sdk.active) root.load(false)
            }
        }
    }
}
