import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

SectionCard {
    id: root
    objectName: "requestHeadersSettings"
    property bool dirty: false
    property bool saving: false
    property string feedback: ""
    property string persisted: ""
    ListModel { id: rows }
    function load(force) {
        const snapshot = JSON.stringify(backend.requestHeaders)
        if (!force && snapshot === persisted) return
        persisted = snapshot
        rows.clear()
        for (const row of backend.requestHeaders)
            rows.append({headerId:row.id, headerName:row.name, headerValue:row.value, headerEnabled:row.enabled})
        dirty = false
    }
    function save(reset) {
        const values = []
        if (!reset) for (let i = 0; i < rows.count; i++) {
            const row = rows.get(i)
            values.push({id:row.headerId, name:row.headerName, value:row.headerValue, enabled:row.headerEnabled})
        }
        saving = true
        const ok = backend.saveRequestHeaders(JSON.stringify(values))
        saving = false
        if (ok) load(true)
    }
    Component.onCompleted: load()
    Connections {
        target: backend
        function onChanged() { if (!root.dirty && !root.saving) root.load() }
        function onToast(message) { if (root.saving) root.feedback = I18n.t(message) }
    }
    ColumnLayout {
        width: parent.width; spacing: 18
        Text {
            Layout.fillWidth: true
            text: I18n.t("编辑 User-Agent 与其他模型请求头")
            color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold; wrapMode: Text.Wrap
        }
        ColumnLayout {
            Layout.fillWidth: true; spacing: 16
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.line }
            Text {
                Layout.fillWidth: true
                text: I18n.t("用于内置 OpenAI / Anthropic 的聊天、模型探测与媒体生成请求。插件和外部 dsh 自行管理请求头。")
                color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12); wrapMode: Text.Wrap
            }
            Text {
                Layout.fillWidth: true
                text: I18n.t("{{apiKey}} 会使用当前供应商的密钥。关闭开关后，该字段不会发送。")
                color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12); wrapMode: Text.Wrap
            }
            Repeater {
                model: rows
                delegate: Rectangle {
                    id: rowCard
                    required property int index
                    required property string headerId
                    required property string headerName
                    required property string headerValue
                    required property bool headerEnabled
                    readonly property bool builtin: ["content-type","user-agent","authorization","x-api-key","anthropic-version"].indexOf(headerId) >= 0
                    Layout.fillWidth: true
                    implicitHeight: rowContent.implicitHeight + 28
                    radius: 10; color: Theme.bg; border.color: Theme.line
                    ColumnLayout {
                        id: rowContent
                        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 14 }
                        spacing: 10
                        RowLayout {
                            Layout.fillWidth: true; spacing: 10
                            Text {
                                Layout.fillWidth: true
                                text: rowCard.headerId === "authorization" ? "OpenAI" : ["x-api-key","anthropic-version"].indexOf(rowCard.headerId) >= 0 ? "Anthropic" : I18n.t("所有内置请求")
                                color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11)
                            }
                            Text { text: rowCard.headerEnabled ? I18n.t("发送") : I18n.t("不发送"); color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11) }
                            Toggle {
                                objectName: "requestHeaderEnabled_" + rowCard.headerId
                                checked: rowCard.headerEnabled
                                Accessible.name: I18n.t("发送请求头") + " " + rowCard.headerName
                                onClicked: { rows.setProperty(rowCard.index, "headerEnabled", checked); root.dirty = true; root.feedback = "" }
                            }
                            ActionButton {
                                objectName: "deleteRequestHeader_" + rowCard.headerId
                                visible: !rowCard.builtin; glyph: "trash"; quiet: true
                                Accessible.name: I18n.t("删除请求头")
                                onClicked: { root.dirty = true; root.feedback = ""; rows.remove(rowCard.index) }
                            }
                        }
                        GridLayout {
                            Layout.fillWidth: true; columns: width >= 600 ? 2 : 1; columnSpacing: 12; rowSpacing: 10
                            InputField {
                                objectName: "requestHeaderName_" + rowCard.headerId
                                Layout.fillWidth: true; Layout.preferredWidth: 220; Layout.minimumWidth: 0
                                text: rowCard.headerName; placeholderText: I18n.t("字段名称，例如 User-Agent"); maximumLength: 128
                                Accessible.name: I18n.t("请求头名称")
                                onTextEdited: { rows.setProperty(rowCard.index, "headerName", text); root.dirty = true; root.feedback = "" }
                            }
                            InputField {
                                objectName: "requestHeaderValue_" + rowCard.headerId
                                Layout.fillWidth: true; Layout.preferredWidth: 400; Layout.minimumWidth: 0
                                text: rowCard.headerValue; placeholderText: I18n.t("字段值"); maximumLength: 4096
                                Accessible.name: I18n.t("请求头值")
                                onTextEdited: { rows.setProperty(rowCard.index, "headerValue", text); root.dirty = true; root.feedback = "" }
                            }
                        }
                    }
                }
            }
            Flow {
                Layout.fillWidth: true; spacing: 10
                ActionButton {
                    objectName: "addRequestHeader"; text: I18n.t("添加字段"); glyph: "plus"; quiet: true
                    enabled: rows.count < 32
                    onClicked: { rows.append({headerId:"custom-" + Date.now() + "-" + rows.count, headerName:"", headerValue:"", headerEnabled:true}); root.dirty = true; root.feedback = "" }
                }
                ActionButton { objectName: "restoreRequestHeaders"; text: I18n.t("恢复默认"); quiet: true; onClicked: root.save(true) }
            }
            Text { visible: root.feedback.length > 0; text: root.feedback; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12); Accessible.role: Accessible.AlertMessage }
            Flow {
                Layout.fillWidth: true; spacing: 10
                ActionButton { objectName: "saveRequestHeaders"; text: I18n.t("保存请求头"); primary: true; enabled: root.dirty; onClicked: root.save(false) }
                ActionButton { objectName: "discardRequestHeaderChanges"; text: I18n.t("撤销修改"); quiet: true; enabled: root.dirty; onClicked: { root.load(true); root.feedback = "" } }
            }
        }
    }
}
