import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Column {
    id: root
    property string query: ""
    spacing: 12
    SectionCard {
        objectName: "toolPermissionSettings"
        width: parent.width
        ColumnLayout {
            width: parent.width; spacing: 12
            Text { objectName: "toolPermissionTitle"; text: I18n.t("工具执行权限"); color: Theme.ink; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Repeater {
                    model: [{mode:"ask",label:I18n.t("每次询问")},{mode:"auto",label:I18n.t("全自动")}]
                    ActionButton {
                        required property var modelData
                        objectName: "toolPermission_" + modelData.mode
                        text: modelData.label
                        primary: backend.config.agent.toolPermissionMode === modelData.mode
                        Accessible.role: Accessible.RadioButton
                        Accessible.checked: primary
                        onClicked: backend.setToolPermissionMode(modelData.mode)
                    }
                }
                Item { Layout.fillWidth: true }
            }
            Text {
                Layout.fillWidth: true; wrapMode: Text.Wrap
                text: backend.config.agent.toolPermissionMode === "ask"
                    ? I18n.t("每次执行命令、编辑或写入文件前询问；读取和搜索直接执行。切换立即保存并生效。")
                    : I18n.t("工具自动执行，仅七类高风险操作需要确认。切换立即保存并生效。")
                color: Theme.muted; font.pixelSize: Theme.font(11)
            }
        }
    }
    SettingsFold { objectName: "piFold_context"; width: parent.width; title: I18n.t("上下文"); nested: true; query: root.query; searchTerms: I18n.t("自动压缩 compaction 重新加载 运行设置 自定义指令 提示词 instructions token 回答 上限")
    SectionCard {
        width: parent.width
        ColumnLayout {
            width: parent.width; spacing: 18
            RowLayout {
                Layout.fillWidth: true
                Text { text: I18n.t("上下文与运行配置"); color: Theme.ink; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold }
                HelpButton { help: I18n.t("默认启用全部 Pi 内置工具、codemode、tool_search 和可直接调用的扩展工具。MCP 与按需扩展工具通过原生发现和调用入口使用，明确隐藏或禁用的配置仍生效。支持原生 Agent 循环、Skills 和 JSONL 会话。工具使用当前用户权限；工作目录并非文件系统沙箱。Pi 主会话模型由供应商设置统一管理；联网扩展按其功能正常访问网络。") }
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "reloadPiButton"; text: I18n.t("重新加载"); glyph: "refresh"; enabled: !backend.piManagement.busy; onClicked: backend.refreshAgent() }
            }
            RowLayout {
                Layout.fillWidth: true
                Text { text: I18n.t("自动压缩上下文"); color: Theme.ink; font.pixelSize: Theme.font(12) }
                HelpButton { help: I18n.t("这里只控制是否启用自动压缩。压缩时机、摘要和上下文保留均由 Pi 原生机制与设置决定，使用当前配置的供应商。") }
                Item { Layout.fillWidth: true }
                Toggle { id: compaction; objectName: "piAutoCompaction"; checked: backend.config.agent.autoCompaction }
            }
        }
    }
    SectionCard {
        objectName: "piRuntimeSettings"
        width: parent.width
        ColumnLayout {
            width: parent.width; spacing: 16
            RowLayout {
                Text { text: I18n.t("运行设置"); color: Theme.ink; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold }
                HelpButton { help: I18n.t("设置附加到 Pi 原生系统提示词，不替换其编码能力和工具说明。回答上限为每次模型请求的最大 token 数。保存后重新加载生效。") }
                Item { Layout.fillWidth: true }
                Text { text: I18n.t("回答上限"); color: Theme.muted; font.pixelSize: Theme.font(11) }
                InputField { id: tokens; Layout.preferredWidth: 100; text: backend.config.agent.maxTokens; validator: IntValidator { bottom:256; top:32768 } }
            }
            InlineScrollView {
                objectName: "agentInstructionsScroll"; Layout.fillWidth: true; Layout.preferredHeight: 120; clip: true
                TextArea { id: instructions; objectName: "agentInstructions"; text: backend.config.agent.instructions; placeholderText: I18n.t("自定义指令"); color: Theme.ink; placeholderTextColor: Theme.muted; font.pixelSize: Theme.font(12); wrapMode: TextArea.Wrap; padding: 13; selectByMouse: true
                    background: Rectangle { radius: 8; color: Theme.bg; border.color: Theme.line }
                }
            }

        }
    }
    }
    SettingsFold { objectName: "piFold_paths"; width: parent.width; title: I18n.t("资源路径"); nested: true; query: root.query; searchTerms: I18n.t("Skills 扩展 路径 agentDir 配置目录")
    SectionCard {
        width: parent.width
        ColumnLayout {
            width: parent.width; spacing: 18
            RowLayout {
                Layout.fillWidth: true
                Text { text: I18n.t("资源路径"); color: Theme.ink; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold }
                HelpButton { help: I18n.t("沿用 Pi 的 agent 目录和工作目录下的 .pi 配置，支持原生 Skills、扩展、提示模板、工具和事件钩子。选择工作目录后会加载其配置。扩展的确认、选择和输入窗口会显示在这里；依赖终端自定义组件的界面需在 Pi 终端使用。扩展不能另行注册模型供应商。") }
                Item { Layout.fillWidth: true }
                ActionButton { text: I18n.t("打开目录"); glyph: "folder"; onClicked: backend.openPiFolder("") }
            }
            Text { text: I18n.t("Pi 配置目录"); color: Theme.ink; font.pixelSize: Theme.font(11) }
            InputField { id: agentDir; objectName: "piAgentDir"; Layout.fillWidth: true; text: backend.config.agent.agentDir; placeholderText: I18n.t("默认 ~/.pi/agent") }
            Repeater {
                model: [{kind:"skills",label:"Skills",items:backend.agentResources.skills}]
                ColumnLayout {
                    required property var modelData
                    Layout.fillWidth: true; spacing: 9
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: modelData.label; color: Theme.ink; font.pixelSize: Theme.font(12) }
                        Text { text: modelData.items.length; color: Theme.muted; font.pixelSize: Theme.font(11) }
                        Item { Layout.fillWidth: true }
                        ActionButton { text: I18n.t("打开文件夹"); quiet: true; onClicked: backend.openPiFolder(modelData.kind) }
                    }
                    Repeater {
                        model: modelData.items
                        RowLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            Text { text: modelData.name; color: Theme.ink; font.pixelSize: Theme.font(11); Layout.preferredWidth: 160; elide: Text.ElideRight }
                            Text { text: modelData.path; color: Theme.muted; font.pixelSize: Theme.font(10); Layout.fillWidth: true; elide: Text.ElideMiddle }
                        }
                    }
                }
            }
            Text { text: I18n.t("额外 Skills 路径"); color: Theme.ink; font.pixelSize: Theme.font(11) }
            InputField { id: skillPaths; Layout.fillWidth: true; text: backend.config.agent.skillPaths.join(";"); placeholderText: I18n.t("多个路径用分号分隔") }
            Text { text: I18n.t("额外扩展路径"); color: Theme.ink; font.pixelSize: Theme.font(11) }
            InputField { id: extensionPaths; Layout.fillWidth: true; text: backend.config.agent.extensionPaths.join(";"); placeholderText: I18n.t("多个路径用分号分隔") }
            Repeater {
                model: backend.agentResources.diagnostics
                Text { required property var modelData; Layout.fillWidth: true; text: modelData.message || ""; color: Theme.danger; font.pixelSize: Theme.font(11); wrapMode: Text.Wrap }
            }
        }
    }
    }
    ActionButton { objectName: "saveAgentButton"; anchors.right: parent.right; text: I18n.t("保存设置"); primary: true; onClicked: backend.saveAgent(JSON.stringify({maxTokens:Number(tokens.text),instructions:instructions.text,autoCompaction:compaction.checked,agentDir:agentDir.text,skillPaths:skillPaths.text.split(";"),extensionPaths:extensionPaths.text.split(";")})) }
}
