import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

Item {
    id: root
    property var target: ({})
    property string exportId: ""
    signal coworkInstanceRequested(string id, string action)
    function tr(zh, en) { return backend.language === "en" ? en : zh }
    function openFor(item, point) {
        target = item
        const menu = item.kind === "project" ? projectMenu : sessionMenu
        // The first implicit size still contains unpolished, wrapped labels.
        // Keep the actual click as Popup's requested position; Qt and
        // FloatingMenu fit it to the window again when its final size is known.
        menu.openAt(point)
    }
    function rename(instance) {
        renamePopup.instance = !!instance
        renamePopup.errorText = ""
        renameField.text = renamePopup.instance ? target.instanceName : target.title
        renamePopup.open()
    }
    function saveRename() {
        if (!renameField.text.trim()) return
        if (renamePopup.instance) {
            renamePopup.errorText = backend.cowork.renameInstance(target.instanceId, renameField.text)
            if (renamePopup.errorText) return
        } else if (target.kind === "project") backend.renameProject(target.id, renameField.text)
        else backend.renameSession(target.id, renameField.text)
        renamePopup.close()
    }
    component RowMenu: FloatingMenu {}

    RowMenu {
        id: sessionMenu; objectName: "sessionContextMenu"
        readonly property bool savedSession: root.target.kind === "session"
        readonly property bool instance: !!root.target.instanceId
        ContextAction { objectName: "contextFork"; visible: sessionMenu.savedSession; text: I18n.t("分支会话"); glyph: "chat-fork"; enabled: !root.target.busy; onTriggered: backend.forkSessionById(root.target.id) }
        ContextAction { objectName: "contextPinSession"; visible: sessionMenu.savedSession; text: root.target.pinned ? I18n.t("取消置顶") : I18n.t("置顶"); glyph: "pin"; onTriggered: backend.togglePinned("session", root.target.id) }
        ContextAction { objectName: "contextArchiveSession"; visible: sessionMenu.savedSession; text: root.target.archived ? I18n.t("取消归档") : I18n.t("归档"); glyph: "archive"; enabled: !backend.sessionFiles.busy; onTriggered: backend.archiveSession(root.target.id, !root.target.archived) }
        ContextAction { objectName: "contextRenameSession"; visible: sessionMenu.savedSession; text: sessionMenu.instance ? I18n.t("重命名会话") : I18n.t("重命名"); glyph: "edit"; enabled: !root.target.busy; onTriggered: root.rename() }
        MenuSeparator { visible: sessionMenu.savedSession; height: visible ? implicitHeight : 0; contentItem: Rectangle { implicitHeight: 1; color: Theme.line } }
        ContextAction { objectName: "contextCopyId"; visible: sessionMenu.savedSession; text: I18n.t("复制 Session ID"); glyph: "copy"; onTriggered: backend.copy(root.target.id) }
        ContextAction { objectName: "contextExportSession"; visible: sessionMenu.savedSession; text: I18n.t("导出会话"); glyph: "download"; enabled: !root.target.busy; onTriggered: { root.exportId = root.target.id; exportDialog.open() } }
        MenuSeparator { visible: sessionMenu.savedSession; height: visible ? implicitHeight : 0; contentItem: Rectangle { implicitHeight: 1; color: Theme.line } }
        ContextAction { objectName: "contextDeleteSession"; visible: sessionMenu.savedSession; text: sessionMenu.instance ? root.tr("删除会话", "Delete conversation") : I18n.t("删除"); glyph: "trash"; destructive: true; enabled: !root.target.busy && !backend.sessionFiles.busy; onTriggered: deletePopup.open() }
        MenuSeparator { visible: sessionMenu.savedSession && sessionMenu.instance; height: visible ? implicitHeight : 0; contentItem: Rectangle { implicitHeight: 1; color: Theme.line } }
        ContextAction { objectName: "coworkContextNewSession"; visible: sessionMenu.instance && !backend.showArchived; text: I18n.t("新增会话"); glyph: "plus"; onTriggered: backend.cowork.requestTask(root.target.instanceId) }
        ContextAction { objectName: "coworkContextClone"; visible: sessionMenu.instance; text: root.tr("克隆实例", "Clone instance"); glyph: "copy"; enabled: !backend.sessionFiles.busy; onTriggered: root.coworkInstanceRequested(root.target.instanceId, "clone") }
        ContextAction { objectName: "coworkContextRename"; visible: sessionMenu.instance; text: root.tr("重命名实例", "Rename instance"); glyph: "edit"; enabled: !backend.sessionFiles.busy; onTriggered: root.rename(true) }
        ContextAction { objectName: "coworkContextFolder"; visible: sessionMenu.instance; text: root.tr("更换工作目录", "Change working folder"); glyph: "folder"; enabled: !backend.sessionFiles.busy; onTriggered: root.coworkInstanceRequested(root.target.instanceId, "folder") }
        ContextAction { objectName: "coworkContextDelete"; visible: sessionMenu.instance; text: root.tr("删除实例", "Delete instance"); glyph: "trash"; destructive: true; enabled: !backend.sessionFiles.busy; onTriggered: {
            deleteProjectPopup.cowork = true
            deleteProjectPopup.summary = backend.sessionFiles.coworkSummary(root.target.instanceId)
            deleteProjectPopup.open()
        } }
    }
    RowMenu {
        id: projectMenu; objectName: "projectContextMenu"
        ContextAction { objectName: "contextPinProject"; text: root.target.pinned ? I18n.t("取消置顶") : I18n.t("置顶"); glyph: "pin"; onTriggered: backend.togglePinned("project", root.target.id) }
        ContextAction { objectName: "contextRenameProject"; text: I18n.t("重命名"); glyph: "edit"; onTriggered: root.rename() }
        MenuSeparator { contentItem: Rectangle { implicitHeight: 1; color: Theme.line } }
        ContextAction { objectName: "contextRevealProject"; text: root.target.ssh ? (backend.language === "en" ? "Copy remote folder path" : "复制远程目录路径") : I18n.t("在资源管理器中打开"); glyph: root.target.ssh ? "copy" : "folder"; onTriggered: backend.revealProject(root.target.id) }
        ContextAction { objectName: "contextArchiveProject"; text: backend.showArchived ? I18n.t("恢复项目会话") : I18n.t("归档项目会话"); glyph: "archive"; enabled: !backend.sessionFiles.busy; onTriggered: backend.archiveProject(root.target.id, !backend.showArchived) }
        MenuSeparator { contentItem: Rectangle { implicitHeight: 1; color: Theme.line } }
        ContextAction { objectName: "contextRemoveProject"; text: I18n.t("删除项目"); glyph: "trash"; destructive: true; enabled: !backend.sessionFiles.busy; onTriggered: { deleteProjectPopup.cowork = false; deleteProjectPopup.summary = backend.sessionFiles.projectSummary(root.target.id); deleteProjectPopup.open() } }
    }
    Popup {
        id: renamePopup; objectName: "renamePopup"; parent: Overlay.overlay
        property string errorText: ""
        property bool instance: false
        width: 420; height: 188 + (errorText ? 36 : 0); padding: 22; modal: true; focus: true
        x: (parent.width-width)/2; y: (parent.height-height)/2
        background: Rectangle { radius: 12; color: Theme.surface; border.color: Theme.line }
        onOpened: { renameField.forceActiveFocus(); renameField.selectAll() }
        ColumnLayout {
            anchors.fill: parent; spacing: 15
            Text { font.family: Theme.fontFamily; text: renamePopup.instance ? root.tr("重命名实例", "Rename instance") : root.target.kind === "project" ? I18n.t("重命名项目") : I18n.t("重命名会话"); color: Theme.ink; font.pixelSize: Theme.font(15, visible); font.weight: Font.Medium }
            InputField { id: renameField; objectName: "renameInput"; Layout.fillWidth: true; maximumLength: renamePopup.instance ? 60 : 120; Keys.onReturnPressed: root.saveRename(); onTextEdited: renamePopup.errorText = "" }
            Text { Layout.fillWidth: true; visible: !!renamePopup.errorText; text: renamePopup.errorText; wrapMode: Text.Wrap; color: Theme.danger; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible) }
            RowLayout { Layout.fillWidth: true; Item { Layout.fillWidth: true }
                ActionButton { text: I18n.t("取消"); quiet: true; onClicked: renamePopup.close() }
                ActionButton { objectName: "confirmRenameButton"; text: I18n.t("保存"); primary: true; enabled: renameField.text.trim().length > 0; onClicked: root.saveRename() }
            }
        }
    }
    Popup {
        id: deletePopup; objectName: "deleteSessionPopup"; parent: Overlay.overlay
        width: Math.min(440, parent.width - 40); height: Math.min(parent.height - 40, deleteSessionContent.implicitHeight + 44); padding: 22; modal: true; focus: true
        x: (parent.width-width)/2; y: (parent.height-height)/2
        background: Rectangle { radius: 12; color: Theme.surface; border.color: Theme.line }
        ColumnLayout { id: deleteSessionContent; anchors.fill: parent; spacing: 18
            Text { font.family: Theme.fontFamily; text: I18n.t("永久删除这条会话？"); color: Theme.ink; font.pixelSize: Theme.font(15, visible) }
            Text { Layout.fillWidth: true; text: I18n.t("会话历史、附件副本、子智能体记录和缓存将被删除，无法撤销。"); wrapMode: Text.Wrap; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible) }
            RowLayout { Layout.fillWidth: true; Item { Layout.fillWidth: true }
                ActionButton { text: I18n.t("取消"); quiet: true; onClicked: deletePopup.close() }
                ActionButton { objectName: "confirmDeleteSessionButton"; text: I18n.t("删除"); destructive: true; onClicked: { backend.deleteSession(root.target.id); deletePopup.close() } }
            }
        }
    }
    Popup {
        id: deleteProjectPopup; objectName: "deleteProjectPopup"; parent: Overlay.overlay
        property var summary: ({})
        property bool cowork: false
        width: Math.min(460, parent.width - 40); height: Math.min(parent.height - 40, deleteProjectContent.implicitHeight + 44); padding: 22; modal: true; focus: true
        x: (parent.width-width)/2; y: (parent.height-height)/2
        background: Rectangle { radius: 12; color: Theme.surface; border.color: Theme.line }
        ColumnLayout { id: deleteProjectContent; anchors.fill: parent; spacing: 16
            Text { text: deleteProjectPopup.cowork ? root.tr("删除 Coworker 实例及其会话？", "Delete Coworker instance and its conversations?") : I18n.t("删除项目及其会话？"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(16, visible); font.weight: Font.Medium }
            Text { Layout.fillWidth: true; text: (deleteProjectPopup.cowork ? root.target.instanceName : root.target.title) || ""; elide: Text.ElideRight; color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13, visible) }
            Text { Layout.fillWidth: true; text: deleteProjectPopup.cowork ? root.tr("将永久删除此实例的全部会话和归档。工作目录中的文件会保留。", "This permanently deletes this instance’s conversations and archives. Files in the working folder are kept.") : I18n.t("将永久删除项目下的全部会话（含归档），以及会话历史、附件副本、子智能体记录和缓存。项目文件夹和源文件会保留。此操作无法撤销。"); wrapMode: Text.Wrap; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible) }
            Text { Layout.fillWidth: true; visible: deleteProjectPopup.summary.busy === true; text: I18n.t("项目仍有任务运行，请先停止任务。"); wrapMode: Text.Wrap; color: Theme.danger; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible) }
            Item { Layout.fillHeight: true }
            RowLayout { Layout.fillWidth: true; Item { Layout.fillWidth: true }
                ActionButton { text: I18n.t("取消"); quiet: true; onClicked: deleteProjectPopup.close() }
                ActionButton { objectName: "confirmDeleteProjectButton"; text: I18n.t("永久删除"); destructive: true; enabled: !deleteProjectPopup.summary.busy && !backend.sessionFiles.busy; onClicked: {
                    if (deleteProjectPopup.cowork) backend.sessionFiles.deleteCoworker(root.target.instanceId)
                    else backend.removeProject(root.target.id)
                    deleteProjectPopup.close()
                } }
            }
        }
    }
    SessionFilesNotice {}
    FileDialog {
        id: exportDialog; title: I18n.t("导出 Pi 会话"); fileMode: FileDialog.SaveFile
        nameFilters: [I18n.t("Pi 会话 (*.jsonl)")]; defaultSuffix: "jsonl"
        onAccepted: backend.exportSession(root.exportId, selectedFile.toString())
    }
}
