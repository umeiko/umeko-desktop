import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

Popup {
    id: root
    objectName: "coworkSessionDialog"
    required property var service
    property string mode: "task"
    property string roleId: ""
    property string roleName: ""
    property string typeId: ""
    property bool chooseType: false
    property string workspace: ""
    property string errorText: ""
    signal configured()
    signal newTypeRequested(string folder)

    anchors.centerIn: parent
    width: Math.min(490, parent.width - 42)
    height: content.implicitHeight + 2 * padding
    padding: 21
    focus: true
    modal: true
    closePolicy: Popup.CloseOnEscape
    background: Rectangle { radius: 15; color: Theme.surface; border.color: Theme.line }
    Overlay.modal: Rectangle { color: Qt.alpha(Theme.ink, 0.26) }

    function tr(zh, en) { return backend.language === "en" ? en : zh }

    function begin(identifier) {
        const defaults = service.taskDefaults(identifier)
        if (!defaults.roleName) return
        mode = "task"
        roleId = identifier
        roleName = defaults.roleName
        setFolder(defaults.workspace)
        titleField.text = defaults.title
        errorText = ""
        open()
    }

    function beginInstance(category, folder, instance, action) {
        mode = action
        roleId = instance
        chooseType = mode === "create" && category === ""
        typeId = category || service.templates[0].id
        setType(typeId)
        const values = service.instanceDefaults(typeId, roleId, mode === "clone")
        if (!values.typeId) return
        typeId = values.typeId
        roleName = values.typeName
        titleField.text = values.title
        setFolder(folder || values.workspace)
        errorText = ""
        open()
    }

    function setType(identifier) {
        typeId = identifier
        const values = service.instanceDefaults(identifier, "", false)
        roleName = values.typeName
        titleField.text = values.title
        if (!workspace && values.workspace) setFolder(values.workspace)
        typeChoice.currentIndex = service.templates.findIndex(row => row.id === identifier)
        errorText = ""
    }

    function setFolder(path) {
        workspace = path || ""
        folderDialog.currentFolder = service.folderUrl(workspace)
    }

    function chooseFolder(url) {
        const path = service.folderPath(String(url))
        if (!path) {
            errorText = tr("请选择有效的本地目录。", "Choose an existing local folder.")
            return
        }
        setFolder(path)
        errorText = ""
    }

    function confirm() {
        if (!confirmButton.enabled) return
        errorText = mode === "task" ? service.configureTask(roleId, workspace, titleField.text)
            : service.saveInstance(mode === "folder" ? roleId : "", typeId, titleField.text, workspace)
        if (!errorText) {
            close()
            if (mode !== "folder") configured()
        }
    }

    onOpened: {
        if (mode === "folder") folderChoice.forceActiveFocus()
        else {
            titleField.forceActiveFocus()
            titleField.selectAll()
        }
    }

    FolderDialog {
        id: folderDialog
        title: root.tr("选择工作目录", "Choose a working folder")
        onAccepted: root.chooseFolder(selectedFolder)
    }

    contentItem: ColumnLayout {
        id: content
        spacing: 10
        Text {
            Layout.fillWidth: true
            text: root.mode === "task" ? root.tr("新增会话", "New conversation")
                : root.mode === "clone" ? root.tr("克隆 Coworker 实例", "Clone Coworker instance")
                : root.mode === "folder" ? root.tr("更换工作目录", "Change working folder")
                : root.tr("新建 Coworker 实例", "New Coworker instance")
            font.family: Theme.fontFamily; font.pixelSize: Theme.font(20); font.weight: Font.DemiBold
            color: Theme.ink
        }
        Text {
            Layout.fillWidth: true
            visible: root.mode === "task" || !root.chooseType
            text: root.roleName; textFormat: Text.PlainText; elide: Text.ElideRight
            font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
            color: Theme.muted
        }
        RowLayout {
            visible: root.mode === "create" && root.chooseType
            Layout.fillWidth: true
            Picker {
                id: typeChoice
                objectName: "coworkTemplateChoice"
                Layout.fillWidth: true
                model: root.service.templates.map(row => row.label)
                Accessible.name: root.tr("Coworker 大类", "Coworker type")
                onActivated: root.setType(root.service.templates[currentIndex].id)
            }
            ActionButton {
                objectName: "coworkCreateType"
                text: root.tr("新建大类", "New type"); glyph: "plus"; quiet: true
                onClicked: {
                    root.close()
                    root.newTypeRequested(root.workspace)
                }
            }
        }
        Text {
            visible: root.mode !== "folder"
            text: root.mode === "task" ? root.tr("会话名称", "Conversation name") : root.tr("实例名称", "Instance name")
            font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); color: Theme.ink
        }
        InputField {
            id: titleField
            objectName: root.mode === "task" ? "coworkSessionTitle" : "coworkInstanceTitle"
            Layout.fillWidth: true
            visible: root.mode !== "folder"
            maximumLength: root.mode === "task" ? 120 : 60
            Accessible.name: root.mode === "task" ? root.tr("会话名称", "Conversation name") : root.tr("实例名称", "Instance name")
            onAccepted: root.confirm()
        }
        Text {
            text: root.tr("工作目录", "Working folder")
            font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); color: Theme.ink
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 52
            radius: 8
            color: folderDrop.containsDrag ? Theme.accentBg : Theme.bg
            border.color: folderDrop.containsDrag ? Theme.accent : Theme.line
            DropArea {
                id: folderDrop
                anchors.fill: parent
                onEntered: drag => { drag.accepted = drag.urls.length === 1 && !!root.service.folderPath(String(drag.urls[0])) }
                onDropped: drop => {
                    if (drop.urls.length !== 1) return
                    root.chooseFolder(drop.urls[0])
                    drop.acceptProposedAction()
                }
            }
            RowLayout {
                anchors.fill: parent; anchors.margins: 8
                Glyph { name: "folder"; color: Theme.muted; width: 17; height: 17 }
                Text {
                    objectName: root.mode === "task" ? "coworkSessionWorkspace" : "coworkInstanceWorkspace"
                    Layout.fillWidth: true
                    text: root.workspace || root.tr("拖入文件夹或点击选择", "Drop or choose a folder")
                    textFormat: Text.PlainText; elide: Text.ElideMiddle
                    color: root.workspace ? Theme.ink : Theme.muted
                    font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                }
                ActionButton {
                    id: folderChoice
                    objectName: "coworkSessionChooseFolder"
                    text: root.tr("选择目录", "Choose folder"); quiet: true
                    onClicked: folderDialog.open()
                }
            }
        }
        Text {
            visible: !!root.errorText
            Layout.fillWidth: true
            text: root.errorText; wrapMode: Text.Wrap
            color: Theme.danger; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
        }
        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            ActionButton {
                objectName: root.mode === "task" ? "coworkSessionCancel" : "coworkInstanceCancel"
                text: root.tr("取消", "Cancel"); quiet: true
                onClicked: root.close()
            }
            ActionButton {
                id: confirmButton
                objectName: root.mode === "task" ? "coworkSessionConfirm" : "coworkInstanceConfirm"
                text: root.mode === "task" ? root.tr("创建会话", "Create conversation")
                    : root.mode === "folder" ? root.tr("保存", "Save")
                    : root.mode === "clone" ? root.tr("克隆实例", "Clone instance")
                    : root.tr("创建实例", "Create instance")
                primary: true
                enabled: !!root.workspace && !!titleField.text.trim()
                onClicked: root.confirm()
            }
        }
    }
}
