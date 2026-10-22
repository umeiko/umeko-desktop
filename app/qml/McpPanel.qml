import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    property string scope: "global"
    property string globalDraft: ""
    property string projectDraft: ""
    property string globalSaved: ""
    property string projectSaved: ""
    property string loadedContext: ""
    readonly property string contextKey: JSON.stringify([backend.config.agent.agentDir, backend.config.workspace])
    readonly property bool dirty: globalDraft !== globalSaved || projectDraft !== projectSaved || editor.text !== (scope === "global" ? globalSaved : projectSaved)
    spacing: 14
    function load() {
        globalDraft = backend.readMcp("global")
        projectDraft = backend.config.workspace ? backend.readMcp("project") : '{\n  "mcpServers": {}\n}'
        globalSaved = globalDraft
        projectSaved = projectDraft
        loadedContext = contextKey
        editor.text = scope === "global" ? globalDraft : projectDraft
    }
    function changeScope(value) {
        if (scope === "global") globalDraft = editor.text; else projectDraft = editor.text
        scope = value
        editor.text = scope === "global" ? globalDraft : projectDraft
    }
    Component.onCompleted: load()
    onVisibleChanged: if (visible && (loadedContext !== contextKey || !dirty)) load()
    RowLayout {
        Layout.fillWidth: true
        ActionButton { objectName: "mcpGlobalTab"; text: I18n.t("全局"); quiet: root.scope !== "global"; onClicked: root.changeScope("global") }
        ActionButton { objectName: "mcpProjectTab"; text: I18n.t("当前项目"); quiet: root.scope !== "project"; enabled: backend.config.workspace !== ""; onClicked: root.changeScope("project") }
        HelpButton { help: I18n.t('直接粘贴 Pi 原生 JSON，例如 {"mcpServers":{"tools":{"command":"node","args":["server.mjs"]}}}。支持 stdio 与 Streamable HTTP；同名项目配置优先于全局配置。保存后由 Pi 原生校验并重新连接。环境变量使用 ${NAME}。') }
        Item { Layout.fillWidth: true }
        ActionButton { objectName: "mcpSaveButton"; text: I18n.t("保存并连接"); primary: true; enabled: !backend.busy; onClicked: backend.saveMcp(root.scope, editor.text) }
    }
    Text { Layout.fillWidth: true; text: backend.mcpConfigPath(root.scope); color: Theme.muted; font.pixelSize: Theme.font(10); elide: Text.ElideMiddle }
    InlineScrollView {
        objectName: "mcpEditorScroll"
        Layout.fillWidth: true; Layout.preferredHeight: 230; clip: true
        TextArea {
            id: editor; objectName: "mcpJsonEditor"
            textFormat: TextEdit.PlainText; color: Theme.ink; font.family: "Consolas"; font.pixelSize: Theme.font(12)
            selectByMouse: true; wrapMode: TextEdit.NoWrap; padding: 14; placeholderText: I18n.t("粘贴 MCP JSON")
            background: Rectangle { radius: 8; color: Theme.bg; border.color: Theme.line }
        }
    }
    Repeater {
        model: backend.agentResources.mcp || []
        ColumnLayout {
            required property var modelData
            Layout.fillWidth: true; spacing: 7
            RowLayout {
                Layout.fillWidth: true
                Text { text: modelData.name; color: Theme.ink; font.pixelSize: Theme.font(12); font.weight: Font.Medium }
                Text { text: modelData.scope === "project" ? I18n.t("项目") : I18n.t("全局"); color: Theme.muted; font.pixelSize: Theme.font(10) }
                Text { Layout.fillWidth: true; text: modelData.state; color: Theme.muted; font.pixelSize: Theme.font(10); elide: Text.ElideRight }
                ActionButton { text: I18n.t("重新连接"); glyph: "refresh"; quiet: true; enabled: !backend.busy; onClicked: backend.reconnectMcp(modelData.name) }
            }
            Repeater {
                model: modelData.tools
                Text { required property var modelData; Layout.fillWidth: true; text: modelData.name; color: Theme.muted; font.family: "Consolas"; font.pixelSize: Theme.font(10); elide: Text.ElideRight }
            }
        }
    }
    Text { visible: !(backend.agentResources.mcp || []).length; text: I18n.t("暂无 MCP 服务器"); color: Theme.muted; font.pixelSize: Theme.font(11) }
}
