import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "UmekoStyle" as UmekoStyle

Popup {
    id: root
    objectName: "coworkEditor"
    required property var service
    property string roleId: ""
    property string skillRoleId: ""
    property string templateId: ""
    property string workspace: ""
    property var selectedTools: []
    property var selectedSkills: []
    property var selectedSubagents: []
    property bool saveFailed: false
    property string folderError: ""
    signal saved(string roleId, bool created)

    modal: true; focus: true; padding: 21
    width: Math.min(650, parent.width - 42)
    height: Math.min(570, parent.height - 54)
    x: (parent.width - width) / 2; y: (parent.height - height) / 2
    closePolicy: service.importingSkill ? Popup.NoAutoClose : Popup.CloseOnEscape
    background: Rectangle { radius: 15; color: Theme.surface; border.color: Theme.line }
    Overlay.modal: Rectangle { color: Qt.alpha(Theme.ink, 0.26) }

    function tr(zh, en) { return backend.language === "zh" ? zh : en }
    function begin(role, source, folder) {
        roleId = role.id || ""
        skillRoleId = roleId || service.newRoleId()
        templateId = source || ""
        workspace = role.workspace || folder || ""
        templateChoice.currentIndex = Math.max(0, service.templates.findIndex(row => row.id === templateId))
        applyRole(roleId ? role : service.templateDetails(templateId))
        saveFailed = false
        folderError = ""
        tabs.currentIndex = 0
        service.loadSkills(skillRoleId, workspace)
        open()
        Qt.callLater(nameField.forceActiveFocus)
    }
    function applyRole(role) {
        nameField.text = role.name || ""
        descriptionField.text = role.description || ""
        instructions.text = role.prompt || ""
        selectedSkills = (role.skills || []).slice()
        selectedTools = (role.tools || ["read"]).slice()
        selectedSubagents = (role.subagents || []).slice()
        contextChoice.currentIndex = Math.max(0, service.contextOptions.findIndex(value => value.id === (role.context || "files")))
    }
    function chooseWorkspace(url) {
        const path = service.folderPath(String(url))
        if (!path) {
            folderError = root.tr("请选择一个本地文件夹。", "Choose a local folder.")
            return
        }
        folderError = ""
        workspace = path
        service.loadSkills(skillRoleId, path)
    }
    function save() {
        const created = !roleId
        const id = service.saveRole(JSON.stringify({id:skillRoleId, template:templateId, name:nameField.text, description:descriptionField.text,
            workspace:workspace, prompt:instructions.text, context:contextChoice.currentValue, tools:selectedTools, skills:selectedSkills,
            subagents:selectedSubagents}))
        saveFailed = !id
        if (id) {
            close()
            saved(id, created)
        }
    }
    function importSkill(url) {
        if (workspace && !service.importingSkill)
            service.importSkill(skillRoleId, workspace, String(url))
    }
    function setChild(row, enabled) {
        const items = selectedSubagents.filter(item => item.id !== row.id)
        selectedSubagents = enabled ? items.concat([row]) : items
    }

    Connections {
        target: root.service
        function onSkillImportFinished(ids) {
            const chosen = root.selectedSkills.slice()
            for (const id of ids) if (!chosen.includes(id)) chosen.push(id)
            root.selectedSkills = chosen
        }
    }
    FolderDialog {
        id: workspaceDialog
        title: root.tr("选择工作目录", "Choose a working folder")
        onAccepted: root.chooseWorkspace(selectedFolder)
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

    component CapabilityPicker: ColumnLayout {
        id: picker
        property var options: []
        property var selection: []
        property var filtered: {
            const query = filter.text.trim().toLowerCase()
            const known = new Set(options.map(row => row.id))
            const missing = selection.filter(id => !known.has(id)).map(id =>
                ({id: id, label: id.split(/[\\/]/).slice(-2).join("/"), source: "", description: ""}))
            return options.concat(missing).filter(row =>
                (row.id + " " + row.label + " " + row.source + " " + row.description).toLowerCase().includes(query))
        }
        signal selectionUpdated(var values)
        spacing: 6
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
            delegate: CheckDelegate {
                id: option
                required property var modelData
                objectName: "coworkOption_" + modelData.id
                width: ListView.view.width - 10
                implicitHeight: Math.max(44, optionText.implicitHeight + 14)
                checked: picker.selection.includes(modelData.id)
                onClicked: picker.selectionUpdated(checked ? picker.selection.concat([modelData.id]) :
                                                   picker.selection.filter(id => id !== modelData.id))
                Accessible.name: modelData.label
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
                        text: option.modelData.label
                        color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13)
                        textFormat: Text.PlainText; elide: Text.ElideRight
                    }
                    Text {
                        width: Math.max(0, optionText.width - optionText.leftPadding - optionText.rightPadding)
                        text: [option.modelData.source, option.modelData.description].filter(Boolean).join(" · ")
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
        }
    }

    Popup {
        id: childEditor
        objectName: "coworkSubagentEditor"
        parent: Overlay.overlay; modal: true; focus: true; anchors.centerIn: parent
        width: Math.min(root.width, parent.width - 42); height: Math.min(root.height, parent.height - 54)
        padding: 20
        background: Rectangle { radius: 15; color: Theme.surface; border.color: Theme.line }
        property var draft: ({id:"", name:"", description:"", prompt:"", context:"files", tools:[], skills:[]})
        property int tab: 0
        function edit(source, clone) {
            const row = source || {name:root.tr("我的子智能体", "My subagent"), description:"", prompt:"Handle the assigned subtask and report findings.", context:"files", tools:["read"], skills:[]}
            draft = Object.assign({}, row, {id:clone ? root.service.newSubagentId() : row.id,
                     name:clone && source ? row.name + root.tr(" 副本", " copy") : row.name,
                     tools:row.tools.slice(), skills:row.skills.slice()})
            childName.text = draft.name; childPrompt.text = draft.prompt
            childContext.currentIndex = Math.max(0, root.service.contextOptions.findIndex(item => item.id === draft.context))
            tab = 0; open()
        }
        ColumnLayout {
            anchors.fill: parent; spacing: 10
            Text {
                text: root.tr("配置子智能体", "Configure subagent")
                color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(20); font.weight: Font.DemiBold
            }
            RowLayout {
                Repeater {
                    model: [root.tr("角色", "Role"), root.tr("Pi 工具", "Pi tools"), "Skills"]
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
                    options: root.service.subagentToolOptions; selection: childEditor.draft.tools
                    onSelectionUpdated: values => childEditor.draft = Object.assign({}, childEditor.draft, {tools:values})
                }
                CapabilityPicker {
                    options: root.service.skillOptions; selection: childEditor.draft.skills
                    onSelectionUpdated: values => childEditor.draft = Object.assign({}, childEditor.draft, {skills:values})
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
                        root.setChild(Object.assign({}, childEditor.draft, {name:childName.text, prompt:childPrompt.text,
                                      context:childContext.selectionId}), true)
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
                text: root.roleId ? root.tr("编辑 Coworker", "Edit coworker") : root.tr("新建 Coworker", "New coworker")
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
                model: [root.tr("角色", "Role"), root.tr("Pi 工具", "Pi tools") + " (" + root.selectedTools.length + ")",
                        "Skills (" + root.selectedSkills.length + ")", root.tr("子智能体", "Subagents") + " (" + root.selectedSubagents.length + ")"]
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
                    RowLayout {
                        visible: !root.roleId
                        Layout.fillWidth: true
                        Text {
                            Layout.fillWidth: true
                            text: root.tr("从模板或现有 Coworker 创建", "Start from a template or coworker")
                            color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13)
                        }
                        Picker {
                            id: templateChoice; objectName: "coworkTemplateChoice"
                            Layout.preferredWidth: 252
                            model: root.service.templates.map(row => row.label)
                            Accessible.name: root.tr("Coworker 模板", "Coworker template")
                            enabled: !root.service.importingSkill
                            onActivated: {
                                root.templateId = root.service.templates[currentIndex].id
                                root.applyRole(root.service.templateDetails(root.templateId))
                            }
                        }
                    }
                    Text {
                        text: root.tr("工作目录", "Working folder")
                        color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); font.weight: Font.DemiBold
                    }
                    Rectangle {
                        objectName: "coworkFolderDrop"
                        Layout.fillWidth: true; implicitHeight: 55
                        radius: 9; color: folderDrop.containsDrag ? Theme.accentBg : Theme.bg
                        border.color: folderDrop.containsDrag ? Theme.accent : Theme.line
                        DropArea {
                            id: folderDrop
                            anchors.fill: parent
                            enabled: !root.service.importingSkill
                            onEntered: drag => { drag.accepted = drag.urls.length === 1 && root.service.folderPath(String(drag.urls[0])) !== "" }
                            onDropped: drop => {
                                if (drop.urls.length !== 1) return
                                root.chooseWorkspace(drop.urls[0])
                                drop.acceptProposedAction()
                            }
                        }
                        RowLayout {
                            anchors.fill: parent; anchors.margins: 8
                            Glyph { name: "folder"; color: Theme.muted; width: 18; height: 18 }
                            Text {
                                objectName: "coworkWorkspaceText"
                                Layout.fillWidth: true
                                text: root.workspace || root.tr("将文件夹拖到这里，或点击选择", "Drop a folder here or choose one")
                                textFormat: Text.PlainText; elide: Text.ElideMiddle
                                color: root.workspace ? Theme.ink : Theme.muted
                                font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                            }
                            ActionButton {
                                objectName: "coworkChooseWorkspace"
                                text: root.tr("选择目录", "Choose folder"); quiet: true
                                enabled: !root.service.importingSkill
                                height: 30
                                onClicked: workspaceDialog.open()
                            }
                        }
                    }
                    Text {
                        visible: text.length > 0; text: root.folderError
                        color: Theme.danger; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                    }
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

            ColumnLayout {
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        text: root.tr("使用 Pi 当前工具与已加载的扩展工具", "Use Pi tools and tools from loaded extensions")
                        color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                        wrapMode: Text.Wrap
                    }
                    ActionButton {
                        text: root.tr("刷新工具", "Refresh tools"); glyph: "refresh"; quiet: true
                        onClicked: root.service.refreshTools(root.workspace)
                    }
                }
                CapabilityPicker {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    options: root.service.toolOptions
                    selection: root.selectedTools
                    onSelectionUpdated: values => root.selectedTools = values
                }
            }

            ColumnLayout {
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        text: root.tr("导入到此 Coworker 的工作区", "Import into this coworker’s workspace")
                        wrapMode: Text.Wrap; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                    }
                    ActionButton {
                        objectName: "coworkImportSkillFolder"
                        text: root.tr("导入文件夹", "Import folder"); glyph: "folder"
                        enabled: !!root.workspace && !root.service.importingSkill
                        onClicked: skillFolder.open()
                    }
                    ActionButton {
                        objectName: "coworkImportSkillArchive"
                        text: root.tr("导入压缩包", "Import archive"); glyph: "plus"
                        enabled: !!root.workspace && !root.service.importingSkill
                        onClicked: skillArchive.open()
                    }
                }
                Text {
                    Layout.fillWidth: true; visible: root.service.skillsLoading || !!root.service.resourceError
                    text: root.service.resourceError || (root.service.importingSkill ?
                              root.tr("正在导入 Skill…", "Importing Skill…") : root.tr("正在读取 Pi Skills…", "Loading Pi Skills…"))
                    color: root.service.resourceError ? Theme.danger : Theme.muted
                    font.family: Theme.fontFamily; font.pixelSize: Theme.font(12); wrapMode: Text.Wrap
                }
                CapabilityPicker {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    options: root.service.skillOptions
                    selection: root.selectedSkills
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
                        model: root.service.subagentTemplates.concat(root.selectedSubagents.filter(row => row.id.startsWith("child-")))
                        delegate: RowLayout {
                            id: childRow
                            required property var modelData
                            readonly property bool custom: modelData.id.startsWith("child-")
                            Layout.fillWidth: true
                            CheckBox {
                                objectName: "coworkSubagentEnabled_" + childRow.modelData.id
                                Layout.fillWidth: true
                                text: childRow.modelData.name
                                checked: root.selectedSubagents.some(row => row.id === childRow.modelData.id)
                                onClicked: root.setChild(childRow.modelData, checked)
                            }
                            ActionButton {
                                objectName: "coworkSubagentEdit_" + childRow.modelData.id
                                text: childRow.custom ? root.tr("编辑", "Edit") : root.tr("克隆", "Clone")
                                glyph: childRow.custom ? "edit" : "copy"; quiet: true
                                onClicked: childEditor.edit(childRow.modelData, !childRow.custom)
                            }
                        }
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
                text: root.roleId ? root.tr("保存", "Save") : root.tr("创建 Coworker", "Create coworker"); primary: true
                enabled: !!root.workspace && nameField.text.trim() !== "" && instructions.text.trim() !== "" && !root.service.importingSkill
                onClicked: root.save()
            }
        }
    }
}
