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
    function formatResponse(value) {
        const response = value && typeof value === "object" ? value : {body: value}
        const body = response.body === undefined || response.body === null ? "" : pretty(response.body)
        const received = response.status !== undefined && response.status !== null ||
                         response.headers && Object.keys(response.headers).length > 0 || body.length > 0
        let text = splitBody(response)
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
            Text { text: I18n.t("请求与返回详情"); color: Theme.ink; font.pixelSize: Theme.font(17); font.weight: Font.DemiBold }
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
        ScrollView {
            id: detailsScroll
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            TextArea { id: details; objectName: "requestDetailsText"; text: root.visibleText; readOnly: true; selectByMouse: true; textFormat: TextEdit.PlainText; wrapMode: TextEdit.NoWrap; color: Theme.ink; font.family: "monospace"; font.pixelSize: Theme.font(12); background: Rectangle { color: Theme.bg; radius: 8 } }
        }
    }
}
