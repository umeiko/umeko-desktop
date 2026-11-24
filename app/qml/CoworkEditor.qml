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
    property string workspace: ""
    property var selectedTools: []
    property var selectedSkills: []
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
    function begin(role) {
        roleId = role.id || ""
        skillRoleId = roleId || service.newRoleId()
        workspace = role.workspace || ""
        nameField.text = role.name || ""
        descriptionField.text = role.description || ""
        instructions.text = role.prompt || ""
        selectedSkills = (role.skills || []).slice()
        selectedTools = (role.tools || ["read"]).slice()
        contextChoice.currentIndex = Math.max(0, service.contextOptions.findIndex(value => value.id === (role.context || "files")))
        saveFailed = false
        folderError = ""
        tabs.currentIndex = 0
        service.loadSkills(skillRoleId, workspace)
        open()
        Qt.callLater(nameField.forceActiveFocus)
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
        const id = service.saveRole(JSON.stringify({id:skillRoleId, name:nameField.text, description:descriptionField.text,
            workspace:workspace, prompt:instructions.text, context:contextChoice.currentValue, tools:selectedTools, skills:selectedSkills}))
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
                        "Skills (" + root.selectedSkills.length + ")"]
                delegate: ActionButton {
                    required property int index
                    required property string modelData
                    objectName: ["coworkRoleTab", "coworkToolsTab", "coworkSkillsTab"][index]
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
                text: root.tr("保存角色", "Save coworker"); primary: true
                enabled: !!root.workspace && nameField.text.trim() !== "" && instructions.text.trim() !== "" && !root.service.importingSkill
                onClicked: root.save()
            }
        }
    }
}
