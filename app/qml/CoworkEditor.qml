import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "UmekoStyle" as UmekoStyle

Popup {
    id: root
    objectName: "coworkEditor"
    required property var service
    property string typeId: ""
    property string skillTypeId: ""
    property var selectedTools: []
    property var selectedSkills: []
    property var subagentOverrides: []
    property var hiddenSubagents: []
    readonly property var subagentPool: service.subagentTemplates.filter(row => !hiddenSubagents.includes(row.id))
        .map(row => subagentOverrides.find(item => item.id === row.id) || Object.assign({}, row, {enabled:false}))
        .concat(subagentOverrides.filter(row => row.id.startsWith("child-")))
    property bool saveFailed: false
    signal saved(string typeId, bool created)

    modal: true; focus: true; padding: 21
    width: Math.min(650, parent.width - 42)
    height: Math.min(570, parent.height - 54)
    x: (parent.width - width) / 2; y: (parent.height - height) / 2
    closePolicy: service.importingSkill ? Popup.NoAutoClose : Popup.CloseOnEscape
    background: Rectangle { radius: 15; color: Theme.surface; border.color: Theme.line }
    Overlay.modal: Rectangle { color: Qt.alpha(Theme.ink, 0.26) }

    function tr(zh, en) { return backend.language === "zh" ? zh : en }
    function begin(identifier) {
        typeId = identifier
        skillTypeId = typeId || service.newRoleId()
        service.selectMcpScope(skillTypeId)
        applyRole(service.typeDetails(typeId))
        saveFailed = false
        tabs.currentIndex = 0
        service.loadSkills(skillTypeId, "")
        open()
        Qt.callLater(nameField.forceActiveFocus)
    }
    function applyRole(role) {
        nameField.text = role.name || ""
        descriptionField.text = role.description || ""
        instructions.text = role.prompt || ""
        selectedSkills = (role.skills || []).slice()
        selectedTools = (role.tools || ["read"]).slice()
        subagentOverrides = (role.subagents || []).slice()
        hiddenSubagents = (role.hiddenSubagents || []).slice()
        typeSkillsPicker.group = "bundled"
        contextChoice.currentIndex = Math.max(0, service.contextOptions.findIndex(value => value.id === (role.context || "files")))
    }
    function save() {
        const created = !typeId
        const id = service.saveType(JSON.stringify({id:skillTypeId, name:nameField.text, description:descriptionField.text,
            prompt:instructions.text, context:contextChoice.currentValue, tools:selectedTools, skills:selectedSkills,
            subagents:subagentOverrides, hiddenSubagents:hiddenSubagents}))
        saveFailed = !id
        if (id) {
            close()
            saved(id, created)
        }
    }
    function importSkill(url) {
        if (!service.importingSkill)
            service.importSkill(skillTypeId, "", String(url))
    }
    function saveChild(row) {
        const updated = subagentOverrides.slice()
        const index = updated.findIndex(item => item.id === row.id)
        if (index < 0) updated.push(row)
        else updated[index] = row
        subagentOverrides = updated
    }
    function removeChild(row) {
        subagentOverrides = subagentOverrides.filter(item => item.id !== row.id)
        if (!row.id.startsWith("child-"))
            hiddenSubagents = hiddenSubagents.concat([row.id])
    }

    Connections {
        target: root.service
        function onMcpAdded() { mcpInstaller.close() }
        function onSkillImportFinished(ids) {
            const chosen = root.selectedSkills.slice()
            for (const id of ids) if (!chosen.includes(id)) chosen.push(id)
            root.selectedSkills = chosen
            typeSkillsPicker.group = "library"
        }
        function onSkillRemoved(id) {
            root.selectedSkills = root.selectedSkills.filter(skill => skill !== id)
            root.subagentOverrides = root.subagentOverrides.map(row => Object.assign({}, row, {
                skills:row.skills.filter(skill => skill !== id)
            }))
            childEditor.draft = Object.assign({}, childEditor.draft, {
                skills:childEditor.draft.skills.filter(skill => skill !== id)
            })
        }
    }
    FolderDialog {
        id: skillFolder
        title: root.tr("选择 Skill 文件夹", "Choose a Skill folder")
        onAccepted: root.importSkill(selectedFolder)
    }
    FileDialog {
        id: skillArchive
        title: root.tr("选择 Skill 压缩包", "Choose a Skill archive")
        fileMode: FileDialog.OpenFile
        nameFilters: [root.tr("Skill 文件 (*.zip *.skill)", "Skill archives (*.zip *.skill)")]
        onAccepted: root.importSkill(selectedFile)
    }

    Popup {
        id: skillDelete
        parent: Overlay.overlay; modal: true; focus: true; anchors.centerIn: parent
        width: Math.min(430, parent.width - 42); padding: 20
        property var skill: ({})
        background: Rectangle { radius: 14; color: Theme.surface; border.color: Theme.line }
        contentItem: ColumnLayout {
            spacing: 12
            Text {
                Layout.fillWidth: true; wrapMode: Text.Wrap
                text: root.tr("从用户库删除此 Skill？", "Delete this Skill from the user library?")
                color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(16); font.weight: Font.DemiBold
            }
            Text {
                Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText
                text: (skillDelete.skill.label || "") + "\n" + root.tr("其存档与 Coworker 中的选择都会移除。", "This removes the archived copy and its Coworker selections.")
                color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { text: root.tr("取消", "Cancel"); quiet: true; onClicked: skillDelete.close() }
                ActionButton {
                    objectName: "coworkConfirmDeleteSkill"
                    text: root.tr("删除", "Delete"); destructive: true
                    enabled: !root.service.importingSkill
                    onClicked: {
                        root.service.deleteSkill(root.skillTypeId, skillDelete.skill.id)
                        skillDelete.close()
                    }
                }
            }
        }
    }

    Popup {
        id: mcpInstaller
        parent: Overlay.overlay; modal: true; focus: true; anchors.centerIn: parent
        width: Math.min(590, parent.width - 42); padding: 21
        closePolicy: root.service.mcpBusy ? Popup.NoAutoClose : Popup.CloseOnEscape
        property bool submitted: false
        onOpened: { submitted = false; mcpJson.text = ""; mcpJson.forceActiveFocus() }
        background: Rectangle { radius: 14; color: Theme.surface; border.color: Theme.line }
        contentItem: ColumnLayout {
            spacing: 12
            Text {
                text: root.tr("添加 MCP 服务器", "Add MCP servers")
                color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(19); font.weight: Font.DemiBold
            }
            Text {
                Layout.fillWidth: true; wrapMode: Text.Wrap
                text: root.tr("粘贴 MCP JSON。添加后，Umeko 会连接服务器并列出工具。", "Paste MCP JSON. Umeko will connect and list the available tools.")
                color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
            }
            ScrollView {
                Layout.fillWidth: true; Layout.preferredHeight: 174; contentWidth: availableWidth; clip: true
                TextArea {
                    id: mcpJson; objectName: "coworkMcpJson"
                    textFormat: TextEdit.PlainText; selectByMouse: true; wrapMode: TextEdit.Wrap
                    font.family: "monospace"; font.pixelSize: Theme.font(12); color: Theme.ink
                    enabled: !root.service.mcpBusy
                    placeholderText: '{ "mcpServers": { "docs": { "url": "https://example.com/mcp" } } }'
                    Accessible.name: "MCP JSON"
                    onTextChanged: mcpInstaller.submitted = false
                    background: Rectangle { radius: 8; color: Theme.bg; border.color: mcpJson.activeFocus ? Theme.accent : Theme.line }
                }
            }
            Text {
                Layout.fillWidth: true; wrapMode: Text.WrapAnywhere; textFormat: Text.PlainText
                visible: mcpInstaller.submitted && !!root.service.mcpError
                text: root.service.mcpError; color: Theme.danger
                font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { text: root.tr("取消", "Cancel"); quiet: true; enabled: !root.service.mcpBusy; onClicked: mcpInstaller.close() }
                ActionButton {
                    objectName: "coworkConfirmMcp"
                    text: root.service.mcpBusy ? root.tr("正在读取工具…", "Reading tools…") : root.tr("添加", "Add")
                    primary: true; enabled: !root.service.mcpBusy && !!mcpJson.text.trim()
                    onClicked: { mcpInstaller.submitted = true; root.service.addMcp(root.skillTypeId, mcpJson.text) }
                }
            }
        }
    }

    component CapabilityPicker: ColumnLayout {
        id: picker
        property var options: []
        property var selection: []
        property string groupKind: ""
        property bool manageLibrary: false
        property string group: "bundled"
        readonly property var filtered: {
            const query = filter.text.trim().toLowerCase()
            const known = new Set(options.map(row => row.id))
            const missing = selection.filter(id => !known.has(id)).map(id => ({
                id:id, label:id.split(/[\\/]/).slice(-2).join("/"),
                source:"", description:root.tr("当前不可用", "Unavailable"),
                group:id.startsWith("mcp__") ? "mcp" : id.endsWith("SKILL.md") ? "library" : "bundled", unavailable:true
            }))
            const rows = options.concat(missing).filter(row =>
                (row.id + " " + row.label + " " + row.source + " " + row.description).toLowerCase().includes(query))
            const visibleRows = groupKind ? rows.filter(row => row.group === group) : rows
            if (!groupKind || visibleRows.length) return visibleRows
            return [{empty:true, label:query ? root.tr("没有匹配的结果", "No results")
                : groupKind === "tools" ? (group === "mcp" ? root.tr("暂无可选 MCP 工具", "No MCP tools available") : root.tr("暂无工具", "No tools"))
                : group === "library" ? root.tr("还没有上传的 Skill", "No uploaded Skills yet")
                : root.tr("暂无内置 Skill", "No bundled Skills")}]

        }
        signal selectionUpdated(var values)
        spacing: 6
        RowLayout {
            Layout.fillWidth: true; visible: !!picker.groupKind
            spacing: 5
            ActionButton {
                objectName: picker.groupKind === "tools" ? "coworkToolGroup_bundled" : "coworkSkillGroup_bundled"
                text: "umeko-desktop"; implicitHeight: 32
                primary: picker.group === "bundled"; quiet: !primary
                onClicked: picker.group = "bundled"
            }
            ActionButton {
                objectName: picker.groupKind === "tools" ? "coworkToolGroup_mcp" : "coworkSkillGroup_library"
                text: picker.groupKind === "tools" ? "MCP" : root.tr("用户自定义 Skill 库", "User Skill library")
                implicitHeight: 32; primary: picker.group !== "bundled"; quiet: !primary
                onClicked: {
                    if (picker.groupKind === "tools") {
                        picker.group = "mcp"
                        root.service.refreshMcp(root.skillTypeId)
                    } else picker.group = "library"
                }
            }
            Item { Layout.fillWidth: true }
            ActionButton {
                visible: picker.groupKind === "tools" && picker.group === "bundled"
                glyph: "refresh"; quiet: true; implicitWidth: 32; implicitHeight: 32
                hint: root.tr("刷新工具", "Refresh tools"); Accessible.name: hint
                onClicked: root.service.refreshTools("")
            }
            ActionButton {
                objectName: "coworkRefreshMcp"
                visible: picker.groupKind === "tools" && picker.group === "mcp"
                glyph: "refresh"; quiet: true; implicitWidth: 32; implicitHeight: 32
                hint: root.tr("刷新 MCP 工具", "Refresh MCP tools"); Accessible.name: hint
                enabled: !root.service.mcpBusy
                onClicked: root.service.refreshMcp(root.skillTypeId)
            }
            ActionButton {
                objectName: "coworkAddMcp"
                visible: picker.groupKind === "tools" && picker.group === "mcp"
                glyph: "plus"; implicitHeight: 32; text: root.tr("添加 JSON", "Add JSON")
                enabled: !root.service.mcpBusy
                onClicked: mcpInstaller.open()
            }
        }
        Text {
            Layout.fillWidth: true
            visible: picker.groupKind === "tools" && picker.group === "mcp" && !!text
            color: root.service.mcpError ? Theme.danger : Theme.muted
            font.family: Theme.fontFamily; font.pixelSize: Theme.font(11)
            wrapMode: Text.WrapAnywhere; maximumLineCount: 2; elide: Text.ElideRight; textFormat: Text.PlainText
            text: root.service.mcpBusy ? root.tr("正在读取 MCP 工具…", "Reading MCP tools…")
                : root.service.mcpError || root.service.mcpServers.map(server => server.name + " · " +
                    (server.state === "connected" ? server.count + root.tr(" 个工具", " tools")
                    : server.state === "disabled" ? root.tr("已停用", "Disabled")
                    : server.state === "needs-auth" ? root.tr("需要认证", "Authentication required")
                    : root.tr("暂时无法连接", "Unavailable"))).join("  •  ")
        }
        InputField {
            id: filter
            Layout.fillWidth: true
            placeholderText: root.tr("按名称或来源搜索…", "Search by name or source…")
        }
        ListView {
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; spacing: 2
            model: picker.filtered
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            delegate: Item {
                id: entry
                required property var modelData
                readonly property bool empty: !!modelData.empty
                width: ListView.view.width - 10
                height: empty ? 32 : option.implicitHeight
                Text {
                    anchors.left: parent.left; anchors.leftMargin: 9
                    anchors.verticalCenter: parent.verticalCenter
                    visible: entry.empty
                    text: entry.empty ? entry.modelData.label : ""
                    font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                    color: Theme.muted
                }
                RowLayout {
                    anchors.fill: parent; spacing: 3; visible: !entry.empty
                    CheckDelegate {
                        id: option
                        objectName: "coworkOption_" + entry.modelData.id
                        Layout.fillWidth: true
                        enabled: entry.modelData.valid !== false || checked
                        implicitHeight: Math.max(44, optionText.implicitHeight + 14)
                        checked: picker.selection.includes(entry.modelData.id)
                        onClicked: picker.selectionUpdated(checked ? picker.selection.concat([entry.modelData.id]) :
                                                           picker.selection.filter(id => id !== entry.modelData.id))
                        Accessible.name: entry.modelData.label
                        indicator: UmekoStyle.SelectionIndicator {
                            checkState: option.checkState
                            pressed: option.down
                            hovered: option.hovered
                            focused: option.visualFocus
                            x: option.mirrored ? option.leftPadding : option.width - option.rightPadding - width
                            y: option.topPadding + (option.availableHeight - height) / 2
                        }
                        contentItem: Column {
                            id: optionText
                            leftPadding: option.mirrored ? option.indicator.width + option.spacing : 8
                            rightPadding: option.mirrored ? 8 : option.indicator.width + option.spacing
                            spacing: 2
                            Text {
                                width: Math.max(0, optionText.width - optionText.leftPadding - optionText.rightPadding)
                                text: entry.modelData.label
                                color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13)
                                textFormat: Text.PlainText; elide: Text.ElideRight
                            }
                            Text {
                                width: Math.max(0, optionText.width - optionText.leftPadding - optionText.rightPadding)
                                text: [entry.modelData.source, entry.modelData.description].filter(Boolean).join(" · ")
                                visible: !!text
                                color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11)
                                textFormat: Text.PlainText; elide: Text.ElideRight
                            }
                        }
                        background: Rectangle {
                            radius: 7
                            color: option.hovered || option.activeFocus ? Theme.hover : option.checked ? Theme.accentBg : "transparent"
                        }
                    }
                    ActionButton {
                        visible: picker.manageLibrary && entry.modelData.group === "library" && !entry.modelData.unavailable
                        objectName: "coworkDeleteSkill_" + entry.modelData.id
                        implicitWidth: 34; implicitHeight: 34
                        glyph: "trash"; quiet: true; destructive: true
                        hint: root.tr("从用户库删除", "Delete from user library"); Accessible.name: hint
                        enabled: !root.service.importingSkill
                        onClicked: { skillDelete.skill = entry.modelData; skillDelete.open() }
                    }
                }
            }
        }
    }

    Popup {
        id: childEditor
        objectName: "coworkSubagentEditor"
        parent: Overlay.overlay; modal: true; focus: true; anchors.centerIn: parent
        width: Math.min(root.width, parent.width - 42); height: Math.min(root.height, parent.height - 54)
        padding: 20
        background: Rectangle { radius: 15; color: Theme.surface; border.color: Theme.line }
        property var draft: ({id:"", name:"", description:"", prompt:"", context:"files", tools:[], skills:[],
                              model:"", character:"", enabled:false})
        property var models: []
        property var characters: []
        property int tab: 0
        function options(rows, current, fallback) {
            const list = [{id:"", label:fallback}].concat(rows)
            if (current && !list.some(row => row.id === current))
                list.push({id:current, label:current + root.tr("（当前不可用）", " (unavailable)")})
            return list
        }
        function edit(source, clone) {
            const row = source || {name:root.tr("我的子智能体", "My subagent"), description:"",
                prompt:"Handle the assigned subtask and report findings.", context:"files", tools:["read"], skills:[]}
            const suffix = root.tr(" 副本", " copy")
            draft = Object.assign({}, row, {
                id:clone ? root.service.newSubagentId() : row.id,
                name:clone && source ? row.name.slice(0, 60 - suffix.length) + suffix : row.name,
                tools:row.tools.slice(), skills:row.skills.slice(), enabled:clone || !!row.enabled,
                model:row.model || "", character:row.character || ""
            })
            models = options(root.service.subagentModels(), draft.model, root.tr("跟随主会话", "Inherit from parent conversation"))
            characters = options(Character.subagentPacks.filter(item => item.id !== "system")
                .map(item => ({id:item.id, label:item.name})), draft.character, root.tr("跟随默认子智能体形象", "Use default subagent appearance"))
            modelChoice.currentIndex = models.findIndex(item => item.id === draft.model)
            characterChoice.currentIndex = characters.findIndex(item => item.id === draft.character)
            childName.text = draft.name
            childDescription.text = draft.description
            childPrompt.text = draft.prompt
            childContext.currentIndex = Math.max(0, root.service.contextOptions.findIndex(item => item.id === draft.context))
            tab = 0
            open()
        }
        ColumnLayout {
            anchors.fill: parent; spacing: 10
            Text {
                text: root.tr("配置子智能体", "Configure subagent")
                color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(20); font.weight: Font.DemiBold
            }
            RowLayout {
                Repeater {
                    model: [root.tr("提示词", "Prompt"), "Tools", "Skills", root.tr("模型偏好", "Model"), root.tr("虚拟角色", "Character")]
                    delegate: ActionButton {
                        required property int index
                        required property string modelData
                        objectName: "coworkSubagentTab_" + index
                        text: modelData; primary: childEditor.tab === index; quiet: !primary
                        onClicked: childEditor.tab = index
                    }
                }
            }
            StackLayout {
                Layout.fillWidth: true; Layout.fillHeight: true; currentIndex: childEditor.tab
                ColumnLayout {
                    InputField {
                        id: childName; objectName: "coworkSubagentName"
                        Layout.fillWidth: true; maximumLength: 60
                        placeholderText: root.tr("子智能体名称", "Subagent name")
                    }
                    InputField {
                        id: childDescription
                        Layout.fillWidth: true; maximumLength: 180
                        placeholderText: root.tr("适合处理的任务（选填）", "Tasks this subagent handles (optional)")
                    }
                    Picker {
                        id: childContext; objectName: "coworkSubagentContext"
                        Layout.fillWidth: true; model: root.service.contextOptions.map(item => item.label)
                        readonly property string selectionId: currentIndex < 0 ? "files" : root.service.contextOptions[currentIndex].id
                        Accessible.name: root.tr("上下文", "Context")
                    }
                    Text {
                        Layout.fillWidth: true; wrapMode: Text.Wrap
                        text: childContext.selectionId === "chat" ? root.tr("继承主会话中的消息。", "Inherit messages from the parent conversation.") :
                              root.tr("使用委派指令与当前工作目录。", "Use the delegated task and current working folder.")
                        color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                    }
                    ScrollView {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        TextArea {
                            id: childPrompt; objectName: "coworkSubagentPrompt"
                            placeholderText: root.tr("系统提示词", "System prompt")
                            color: Theme.ink; wrapMode: TextEdit.Wrap; selectByMouse: true; font.family: Theme.fontFamily
                            background: Rectangle { radius: 8; color: Theme.bg; border.color: Theme.line }
                            onTextChanged: if (length > 8000) remove(8000, length)
                        }
                    }
                }
                CapabilityPicker {
                    options: root.service.subagentToolOptions; selection: childEditor.draft.tools; groupKind: "tools"
                    onSelectionUpdated: values => childEditor.draft = Object.assign({}, childEditor.draft, {tools:values})
                }
                CapabilityPicker {
                    options: root.service.skillOptions; selection: childEditor.draft.skills; groupKind: "skills"
                    onSelectionUpdated: values => childEditor.draft = Object.assign({}, childEditor.draft, {skills:values})
                }
                ColumnLayout {
                    spacing: 10
                    Text {
                        text: root.tr("委派任务使用的模型", "Model used for delegated tasks")
                        color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13)
                    }
                    Picker {
                        id: modelChoice; objectName: "coworkSubagentModel"
                        Layout.fillWidth: true; model: childEditor.models.map(row => row.label)
                        Accessible.name: root.tr("子智能体模型偏好", "Subagent model preference")
                    }
                    Text {
                        Layout.fillWidth: true; wrapMode: Text.Wrap
                        text: root.tr("所选模型不可用时，子智能体会跟随主会话。", "The subagent inherits the parent model if the selected model is unavailable.")
                        color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                    }
                    Item { Layout.fillHeight: true }
                }
                ColumnLayout {
                    spacing: 12
                    Picker {
                        id: characterChoice; objectName: "coworkSubagentCharacter"
                        Layout.fillWidth: true; model: childEditor.characters.map(row => row.label)
                        Accessible.name: root.tr("子智能体虚拟角色", "Subagent character")
                    }
                    SubagentAvatar {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.preferredWidth: 104; Layout.preferredHeight: 104
                        character: childEditor.characters[characterChoice.currentIndex]?.id || ""
                    }
                    Item { Layout.fillHeight: true }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { text: root.tr("取消", "Cancel"); quiet: true; onClicked: childEditor.close() }
                ActionButton {
                    objectName: "coworkSaveSubagent"; primary: true
                    text: root.tr("保存子智能体", "Save subagent")
                    enabled: childName.text.trim() !== "" && childPrompt.text.trim() !== ""
                    onClicked: {
                        root.saveChild(Object.assign({}, childEditor.draft, {
                            name:childName.text, description:childDescription.text, prompt:childPrompt.text,
                            context:childContext.selectionId, model:childEditor.models[modelChoice.currentIndex]?.id || "",
                            character:childEditor.characters[characterChoice.currentIndex]?.id || ""
                        }))
                        childEditor.close()
                    }
                }
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent; spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: root.typeId ? root.tr("配置 Coworker 大类", "Configure Coworker type") : root.tr("新建 Coworker 大类", "New Coworker type")
                color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(20); font.weight: Font.DemiBold
            }
            ExperimentalBadge {}
            ActionButton {
                glyph: "x"; quiet: true; hint: root.tr("关闭", "Close")
                enabled: !root.service.importingSkill
                onClicked: root.close()
            }
        }

        RowLayout {
            Layout.fillWidth: true; spacing: 7
            Repeater {
                model: [root.tr("角色", "Role"), "Tools (" + root.selectedTools.length + ")",
                        "Skills (" + root.selectedSkills.length + ")", root.tr("子智能体", "Subagents") + " (" + root.subagentPool.filter(row => row.enabled).length + ")"]
                delegate: ActionButton {
                    required property int index
                    required property string modelData
                    objectName: ["coworkRoleTab", "coworkToolsTab", "coworkSkillsTab", "coworkSubagentsTab"][index]
                    text: modelData; primary: tabs.currentIndex === index; quiet: !primary
                    implicitHeight: 34
                    onClicked: tabs.currentIndex = index
                }
            }
        }

        StackLayout {
            id: tabs
            currentIndex: 0
            Layout.fillWidth: true; Layout.fillHeight: true

            ScrollView {
                id: form
                clip: true; contentWidth: availableWidth
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ColumnLayout {
                    width: form.availableWidth - 8
                    spacing: 7
                    Text { text: root.tr("名称", "Name"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); font.weight: Font.DemiBold }
                    InputField {
                        id: nameField
                        objectName: "coworkNameField"
                        Layout.fillWidth: true; maximumLength: 60
                        placeholderText: root.tr("例如，阅读清单助手", "For example, Reading list assistant")
                        Accessible.name: root.tr("名称", "Name")
                    }
                    Text { text: root.tr("简介", "Description"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); font.weight: Font.DemiBold }
                    InputField {
                        id: descriptionField
                        Layout.fillWidth: true; maximumLength: 180
                        placeholderText: root.tr("用一句话说明它适合做什么", "Describe the tasks it is suited for")
                        Accessible.name: root.tr("简介", "Description")
                    }
                    Text { text: root.tr("系统提示词", "System prompt"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); font.weight: Font.DemiBold }
                    ScrollView {
                        Layout.fillWidth: true; Layout.preferredHeight: 83
                        clip: true; contentWidth: availableWidth
                        TextArea {
                            id: instructions
                            objectName: "coworkInstructionsField"
                            font.family: Theme.fontFamily; font.pixelSize: Theme.font(13)
                            color: Theme.ink; placeholderTextColor: Theme.muted
                            placeholderText: root.tr("说明它如何使用资料和交付结果", "Explain how it should use sources and deliver results")
                            Accessible.name: root.tr("系统提示词", "System prompt")
                            wrapMode: TextEdit.Wrap; selectByMouse: true
                            background: Rectangle { radius: 8; color: Theme.bg; border.color: instructions.activeFocus ? Theme.accent : Theme.line }
                            onTextChanged: if (length > 8000) remove(8000, length)
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            Layout.fillWidth: true
                            text: root.tr("默认上下文", "Default context")
                            color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); font.weight: Font.DemiBold
                        }
                        ComboBox {
                            id: contextChoice; objectName: "coworkContextChoice"
                            Layout.preferredWidth: 232
                            model: root.service.contextOptions; textRole: "label"; valueRole: "id"
                            Accessible.name: root.tr("默认上下文", "Default context")
                            font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                            palette.text: Theme.ink; palette.buttonText: Theme.ink; palette.base: Theme.surface
                            background: Rectangle { radius: 8; color: Theme.bg; border.color: contextChoice.activeFocus ? Theme.accent : Theme.line }
                            contentItem: Text {
                                text: contextChoice.displayText; font: contextChoice.font; color: Theme.ink
                                verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
                                leftPadding: 12; rightPadding: 27
                            }
                            indicator: Glyph {
                                name: "chevron-down"; color: Theme.muted; width: 13; height: 13
                                x: parent.width - width - 11; y: (parent.height - height) / 2
                            }
                        }
                    }
                }
            }

            CapabilityPicker {
                options: root.service.toolOptions
                selection: root.selectedTools; groupKind: "tools"
                onSelectionUpdated: values => root.selectedTools = values
            }

            ColumnLayout {
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        text: root.tr("为此大类的所有实例启用 Skills", "Choose Skills shared by instances of this type")
                        wrapMode: Text.Wrap; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                    }
                    ActionButton {
                        objectName: "coworkImportSkillFolder"
                        text: root.tr("导入文件夹", "Import folder"); glyph: "folder"
                        enabled: !root.service.importingSkill
                        onClicked: skillFolder.open()
                    }
                    ActionButton {
                        objectName: "coworkImportSkillArchive"
                        text: root.tr("导入压缩包", "Import archive"); glyph: "plus"
                        enabled: !root.service.importingSkill
                        onClicked: skillArchive.open()
                    }
                }
                Text {
                    Layout.fillWidth: true; visible: root.service.skillsLoading || !!root.service.resourceError
                    text: root.service.resourceError || (root.service.importingSkill ?
                              root.tr("正在更新 Skill 库…", "Updating the Skill library…") : root.tr("正在读取 Pi Skills…", "Loading Pi Skills…"))
                    color: root.service.resourceError ? Theme.danger : Theme.muted
                    font.family: Theme.fontFamily; font.pixelSize: Theme.font(12); wrapMode: Text.Wrap
                }
                CapabilityPicker {
                    id: typeSkillsPicker
                    Layout.fillWidth: true; Layout.fillHeight: true
                    options: root.service.skillOptions
                    selection: root.selectedSkills; groupKind: "skills"; manageLibrary: true
                    onSelectionUpdated: values => root.selectedSkills = values
                }
            }
            ScrollView {
                id: poolView
                contentWidth: availableWidth; clip: true
                ColumnLayout {
                    width: poolView.availableWidth - 8; spacing: 8
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            Layout.fillWidth: true
                            text: root.tr("子智能体池", "Subagent pool"); color: Theme.ink
                            font.family: Theme.fontFamily; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold
                        }
                        ActionButton {
                            objectName: "coworkCreateSubagent"; glyph: "plus"
                            text: root.tr("新建自定义", "New custom")
                            onClicked: childEditor.edit(null, true)
                        }
                    }
                    Repeater {
                        model: root.subagentPool
                        delegate: RowLayout {
                            id: childRow
                            required property var modelData
                            Layout.fillWidth: true
                            CheckBox {
                                objectName: "coworkSubagentEnabled_" + childRow.modelData.id
                                Layout.fillWidth: true
                                text: childRow.modelData.name
                                checked: !!childRow.modelData.enabled
                                onClicked: root.saveChild(Object.assign({}, childRow.modelData, {enabled:checked}))
                            }
                            ActionButton {
                                objectName: "coworkSubagentEdit_" + childRow.modelData.id
                                glyph: "settings"; quiet: true
                                hint: root.tr("配置子智能体", "Configure subagent"); Accessible.name: hint
                                onClicked: childEditor.edit(childRow.modelData, false)
                            }
                            ActionButton {
                                objectName: "coworkSubagentClone_" + childRow.modelData.id
                                glyph: "copy"; quiet: true
                                hint: root.tr("克隆", "Clone"); Accessible.name: hint
                                onClicked: childEditor.edit(childRow.modelData, true)
                            }
                            ActionButton {
                                objectName: "coworkSubagentDelete_" + childRow.modelData.id
                                glyph: "trash"; quiet: true; destructive: true
                                hint: root.tr("从池中删除", "Remove from pool"); Accessible.name: hint
                                onClicked: root.removeChild(childRow.modelData)
                            }
                        }
                    }
                    ActionButton {
                        visible: root.hiddenSubagents.length > 0
                        text: root.tr("恢复已删除的内置子智能体", "Restore removed built-in subagents")
                        quiet: true
                        onClicked: root.hiddenSubagents = []
                    }
                }
            }
        }

        Text {
            Layout.fillWidth: true; visible: root.saveFailed
            text: root.service.problem; color: Theme.danger; wrapMode: Text.Wrap
            font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
        }
        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            ActionButton {
                text: root.tr("取消", "Cancel"); quiet: true
                enabled: !root.service.importingSkill
                onClicked: root.close()
            }
            ActionButton {
                objectName: "coworkSaveRole"
                text: root.typeId ? root.tr("保存", "Save") : root.tr("创建大类", "Create type"); primary: true
                enabled: nameField.text.trim() !== "" && instructions.text.trim() !== "" && !root.service.importingSkill
                onClicked: root.save()
            }
        }
    }
}
