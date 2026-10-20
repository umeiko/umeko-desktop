import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

Item {
    id: root
    property var target: ({})
    property string exportId: ""
    function openFor(item, point) {
        target = item
        let menu = item.kind === "project" ? projectMenu : sessionMenu
        menu.x = Math.max(8, Math.min(point.x, width - menu.width - 8))
        menu.y = Math.max(8, Math.min(point.y, height - menu.implicitHeight - 8))
        menu.open()
    }
    function rename() { renameField.text = target.title; renamePopup.open() }
    function saveRename() {
        if (!renameField.text.trim()) return
        if (target.kind === "project") backend.renameProject(target.id, renameField.text)
        else backend.renameSession(target.id, renameField.text)
        renamePopup.close()
    }
    component RowMenu: Menu {
        width: 234; padding: 6
        background: Rectangle { radius: 10; color: Theme.surface; border.color: Theme.line }
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 100 } }
    }
    RowMenu {
        id: sessionMenu; objectName: "sessionContextMenu"
        ContextAction { objectName: "contextFork"; text: "分支会话"; glyph: "branch"; enabled: !root.target.busy; onTriggered: backend.forkSessionById(root.target.id) }
        ContextAction { objectName: "contextPinSession"; text: root.target.pinned ? "取消置顶" : "置顶"; glyph: "pin"; onTriggered: backend.togglePinned("session", root.target.id) }
        ContextAction { objectName: "contextArchiveSession"; text: root.target.archived ? "取消归档" : "归档"; glyph: "archive"; onTriggered: backend.archiveSession(root.target.id, !root.target.archived) }
        ContextAction { objectName: "contextRenameSession"; text: "重命名"; glyph: "edit"; enabled: !root.target.busy; onTriggered: root.rename() }
        MenuSeparator { contentItem: Rectangle { implicitHeight: 1; color: Theme.line } }
        ContextAction { objectName: "contextCopyId"; text: "复制 Session ID"; glyph: "copy"; onTriggered: backend.copy(root.target.id) }
        ContextAction { objectName: "contextExportSession"; text: "导出会话"; glyph: "download"; enabled: !root.target.busy; onTriggered: { root.exportId = root.target.id; exportDialog.open() } }
        MenuSeparator { contentItem: Rectangle { implicitHeight: 1; color: Theme.line } }
        ContextAction { objectName: "contextDeleteSession"; text: "删除"; glyph: "trash"; destructive: true; enabled: !root.target.busy; onTriggered: deletePopup.open() }
    }
    RowMenu {
        id: projectMenu; objectName: "projectContextMenu"
        ContextAction { objectName: "contextPinProject"; text: root.target.pinned ? "取消置顶" : "置顶"; glyph: "pin"; onTriggered: backend.togglePinned("project", root.target.id) }
        ContextAction { objectName: "contextRenameProject"; text: "重命名"; glyph: "edit"; onTriggered: root.rename() }
        MenuSeparator { contentItem: Rectangle { implicitHeight: 1; color: Theme.line } }
        ContextAction { objectName: "contextRevealProject"; text: "在资源管理器中打开"; glyph: "folder"; onTriggered: backend.revealProject(root.target.id) }
        ContextAction { objectName: "contextArchiveProject"; text: backend.showArchived ? "恢复项目会话" : "归档项目会话"; glyph: "archive"; onTriggered: backend.archiveProject(root.target.id, !backend.showArchived) }
        MenuSeparator { contentItem: Rectangle { implicitHeight: 1; color: Theme.line } }
        ContextAction { objectName: "contextRemoveProject"; text: "移除项目"; glyph: "x"; destructive: true; onTriggered: backend.removeProject(root.target.id) }
    }
    Popup {
        id: renamePopup; objectName: "renamePopup"; parent: Overlay.overlay
        width: 420; height: 188; padding: 22; modal: true; focus: true
        x: (parent.width-width)/2; y: (parent.height-height)/2
        background: Rectangle { radius: 12; color: Theme.surface; border.color: Theme.line }
        onOpened: { renameField.forceActiveFocus(); renameField.selectAll() }
        ColumnLayout {
            anchors.fill: parent; spacing: 15
            Text { text: root.target.kind === "project" ? "重命名项目" : "重命名会话"; color: Theme.ink; font.pixelSize: 15; font.weight: Font.Medium }
            InputField { id: renameField; objectName: "renameInput"; Layout.fillWidth: true; maximumLength: 120; Keys.onReturnPressed: root.saveRename() }
            RowLayout { Layout.fillWidth: true; Item { Layout.fillWidth: true }
                ActionButton { text: "取消"; quiet: true; onClicked: renamePopup.close() }
                ActionButton { objectName: "confirmRenameButton"; text: "保存"; primary: true; enabled: renameField.text.trim().length > 0; onClicked: root.saveRename() }
            }
        }
    }
    Popup {
        id: deletePopup; objectName: "deleteSessionPopup"; parent: Overlay.overlay
        width: 380; height: 152; padding: 22; modal: true; focus: true
        x: (parent.width-width)/2; y: (parent.height-height)/2
        background: Rectangle { radius: 12; color: Theme.surface; border.color: Theme.line }
        ColumnLayout { anchors.fill: parent; spacing: 18
            Text { text: "删除这条会话？"; color: Theme.ink; font.pixelSize: 15 }
            RowLayout { Layout.fillWidth: true; Item { Layout.fillWidth: true }
                ActionButton { text: "取消"; quiet: true; onClicked: deletePopup.close() }
                ActionButton { objectName: "confirmDeleteSessionButton"; text: "删除"; destructive: true; onClicked: { backend.deleteSession(root.target.id); deletePopup.close() } }
            }
        }
    }
    FileDialog {
        id: exportDialog; title: "导出 Pi 会话"; fileMode: FileDialog.SaveFile
        nameFilters: ["Pi 会话 (*.jsonl)"]; defaultSuffix: "jsonl"
        onAccepted: backend.exportSession(root.exportId, selectedFile.toString())
    }
}
