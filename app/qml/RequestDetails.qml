import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: root; objectName: "requestDetailsDialog"
    property string report: ""
    property var reportData: ({})
    property int section: 0
    property int callIndex: -1
    readonly property var calls: reportData && Array.isArray(reportData.http) ? reportData.http : []
    readonly property var selectedCall: callIndex >= 0 && callIndex < calls.length ? calls[callIndex] : null
    readonly property string compatibilityNotice: {
        const records = selectedCall && Array.isArray(selectedCall.compatibility) ? selectedCall.compatibility : []
        return records.map(record => {
            const days = record.ageDays || 0
            const age = days === 0 ? I18n.t("今天记录")
                : days === 1 ? I18n.t("1 天前记录")
                : I18n.t("{days} 天前记录").replace("{days}", String(days))
            return I18n.t(record.action === "auto"
                ? "已按此前的拒绝记录将 {parameter} 改为 auto（{age}）"
                : "已按此前的拒绝记录省略 {parameter}（{age}）")
                .replace("{parameter}", String(record.parameter || ""))
                .replace("{age}", age)
        }).join("；")
    }
    readonly property string visibleText: {
        if (!report) return I18n.t("此请求的详情已过期或不可读取。")
        if (!reportData || typeof reportData !== "object") return report
        const value = selectedCall ? selectedCall[section === 0 ? "request" : "response"] : reportData[section === 0 ? "request" : "response"]
        return section === 0 ? formatRequest(value) : formatResponse(value)
    }
    function show(identifier) {
        report = backend.requestReport(identifier)
        try { reportData = JSON.parse(report) } catch (_) { reportData = null }
        section = 0
        callIndex = calls.length - 1
        open()
        Qt.callLater(resetScroll)
    }
    function pretty(value) { return typeof value === "string" ? value : JSON.stringify(value, null, 2) || "" }
    function splitBody(value) {
        const metadata = Object.assign({}, value)
        delete metadata.body
        return Object.keys(metadata).length ? pretty(metadata) + "\n\n" : ""
    }
    function formatRequest(value) {
        if (!value || typeof value !== "object") return pretty(value) || I18n.t("未记录请求内容")
        if (!Object.prototype.hasOwnProperty.call(value, "body")) return pretty(value)
        return splitBody(value) + I18n.t("请求正文") + "\n" + pretty(value.body)
    }
    function formatDuration(ms) {
        if (ms === undefined || ms === null || isNaN(Number(ms))) return "—"
        const value = Math.max(0, Math.round(Number(ms)))
        if (value < 1000) return value + " ms"
        return (value / 1000).toFixed(2) + " s (" + value + " ms)"
    }
    function formatPhase(phase, fallback) {
        const labels = {
            waiting_headers: "发出请求后等待响应头",
            waiting_first_sse: "收到响应头后等待首条 SSE 事件",
            stream_idle: "流式输出中途长时间无数据",
            incomplete_stream: "未收到正常结束标记即断流",
            http_error: "供应商返回 HTTP 错误",
            completed: "已正常结束"
        }
        return I18n.t(labels[phase] || fallback || phase || "—")
    }
    function formatTiming(timing) {
        if (!timing || typeof timing !== "object") return ""
        const lines = [I18n.t("流式诊断")]
        lines.push(I18n.t("当前阶段：") + formatPhase(timing.phase, timing.phaseLabel))
        const firstEvent = timing.firstEventMs !== undefined && timing.firstEventMs !== null
            ? formatDuration(timing.firstEventMs) + (timing.firstEventAt ? " (" + timing.firstEventAt + ")" : "")
            : I18n.t("未收到")
        lines.push(I18n.t("第一条事件时间：") + firstEvent)
        lines.push(I18n.t("最后一次收到数据到报错间隔：") + formatDuration(timing.lastDataToErrorMs))
        lines.push(I18n.t("总耗时：") + formatDuration(timing.totalMs))
        lines.push(I18n.t("是否正常结束：") + I18n.t(timing.completedNormally ? "是" : "否"))
        if (timing.heartbeatCount > 0)
            lines.push(I18n.t("收到 SSE 心跳注释：") + String(timing.heartbeatCount))
        return lines.join("\n") + "\n\n"
    }
    function formatResponse(value) {
        const response = value && typeof value === "object" ? value : {body: value}
        const body = response.body === undefined || response.body === null ? "" : pretty(response.body)
        const received = response.status !== undefined && response.status !== null ||
                         response.headers && Object.keys(response.headers).length > 0 || body.length > 0
        const timing = (selectedCall && selectedCall.timing) || reportData.streamDiagnostics || null
        let text = formatTiming(timing) + splitBody(response)
        if (reportData.summary) text = I18n.t(reportData.summary) + "\n\n" + text
        text += !received ? I18n.t("未收到服务器响应") : body ? I18n.t("服务器返回正文") + "\n" + body : I18n.t("服务器未返回响应正文")
        if (reportData.error) text += "\n\n" + I18n.t("本地异常") + "\n" + pretty(reportData.error)
        return text
    }
    function resetScroll() {
        details.cursorPosition = 0
        if (detailsScroll.contentItem) {
            detailsScroll.contentItem.contentX = 0
            detailsScroll.contentItem.contentY = 0
        }
    }
    onSectionChanged: Qt.callLater(resetScroll)
    onCallIndexChanged: Qt.callLater(resetScroll)
    parent: Overlay.overlay; anchors.centerIn: parent
    width: Math.min(1000, parent.width - 48); height: Math.min(730, parent.height - 48)
    modal: true; focus: true; padding: 22
    background: Rectangle { radius: 14; color: Theme.surface; border.color: Theme.line }
    contentItem: ColumnLayout {
        spacing: 14
        RowLayout {
            Layout.fillWidth: true
            Text { font.family: Theme.fontFamily; text: I18n.t("请求与返回详情"); color: Theme.ink; font.pixelSize: Theme.font(17, visible); font.weight: Font.DemiBold }
            HelpButton { help: I18n.t("完整请求正文、HTTP 状态、响应与异常。密钥和登录凭据已隐藏，仅保存在本机。") }
            Item { Layout.fillWidth: true }
            ActionButton { objectName: "copyRequestDetails"; text: I18n.t("复制完整详情"); glyph: "copy"; enabled: root.report.length > 0; onClicked: backend.copy(root.report) }
            ActionButton { text: I18n.t("关闭"); glyph: "x"; quiet: true; onClicked: root.close() }
        }
        RowLayout {
            Layout.fillWidth: true
            Item {
                implicitWidth: tabRow.implicitWidth; implicitHeight: requestTab.height
                PidHighlight { objectName: "requestDetailsHighlight"; height: requestTab.height; targetX: root.section === 0 ? requestTab.x : responseTab.x; targetWidth: root.section === 0 ? requestTab.width : responseTab.width }
                Row {
                    id: tabRow; spacing: 4
                    ActionButton { id: requestTab; objectName: "requestDetailsRequestTab"; text: I18n.t("请求"); quiet: true; onClicked: root.section = 0 }
                    ActionButton { id: responseTab; objectName: "requestDetailsResponseTab"; text: I18n.t("服务器返回"); quiet: true; onClicked: root.section = 1 }
                }
            }
            Item { Layout.fillWidth: true }
            ComboBox {
                objectName: "requestDetailsHttpCall"
                visible: root.calls.length > 1
                Layout.preferredWidth: Math.min(420, root.width * 0.48)
                model: root.calls.map((call, index) => (index + 1) + " · " + ((call.request || {}).method || "HTTP") + " " + ((call.request || {}).url || ""))
                currentIndex: root.callIndex
                onActivated: index => root.callIndex = index
            }
        }
        Text {
            objectName: "requestCompatibilityNotice"
            visible: root.compatibilityNotice.length > 0
            Layout.fillWidth: true
            text: root.compatibilityNotice; textFormat: Text.PlainText
            color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible)
            elide: Text.ElideRight
            HoverHandler { id: compatibilityHover }
            HoverTip { active: compatibilityHover.hovered; text: root.compatibilityNotice }
        }
        ScrollView {
            id: detailsScroll
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            TextArea { id: details; objectName: "requestDetailsText"; text: root.visibleText; readOnly: true; selectByMouse: true; textFormat: TextEdit.PlainText; wrapMode: TextEdit.NoWrap; color: Theme.ink; font.family: "monospace"; font.pixelSize: Theme.font(12, visible); background: Rectangle { color: Theme.bg; radius: 8 } }
        }
    }
}
