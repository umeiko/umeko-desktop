import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

Popup {
    id: root
    objectName: "sessionWorkspaceDialog"
    required property var service
    signal configured()
    property bool remote: false
    property string localFolder: ""
    property string remoteFolder: ""
    property string remoteParent: ""
    property var folders: []
    property var hosts: []
    property var entries: []
    property bool limited: false
    property bool useAfterBrowse: false
    property string errorText: ""

    anchors.centerIn: parent
    width: Math.min(620, parent.width - 44)
    height: content.implicitHeight + 2 * padding
    padding: 22
    modal: true; focus: true
    closePolicy: Popup.CloseOnEscape
    background: Rectangle { color: Theme.surface; radius: 15; border.color: Theme.line }
    Overlay.modal: Rectangle { color: Qt.alpha(Theme.ink, 0.26) }

    function tr(zh, en) { return backend.language === "en" ? en : zh }
    function begin() {
        const choices = service.choices()
        folders = choices.folders
        hosts = choices.hosts
        remote = !!choices.active.ssh
        localFolder = remote ? "" : choices.active.path || ""
        folderDialog.currentFolder = localFolder ? service.folderUrl(localFolder) : choices.homeUrl
        hostField.text = remote ? choices.active.ssh.host : hosts[0] || ""
        resetRemote()
        pathField.text = remote ? choices.active.ssh.path : ""
        open()
    }
    function resetRemote() {
        service.cancel()
        remoteFolder = ""
        remoteParent = ""
        entries = []
        limited = false
        useAfterBrowse = false
        errorText = ""
    }
    function selectMode(isRemote) {
        if (remote === isRemote) return
        if (!isRemote) resetRemote()
        remote = isRemote
        errorText = ""
    }
    function pickLocal(url) {
        const path = service.localPath(String(url))
        if (!path) {
            errorText = tr("请选择有效的本地目录。", "Choose an existing local folder.")
            return
        }
        localFolder = path
        folderDialog.currentFolder = url
        errorText = ""
    }
    function browse(path, use) {
        if (!hostField.text.trim() || service.busy) return
        errorText = ""
        pathField.text = path
        useAfterBrowse = !!use
        service.browse(hostField.text.trim(), path)
    }
    function confirm() {
        if (!confirmButton.enabled) return
        if (remote && (!remoteFolder || pathField.text !== remoteFolder)) {
            browse(pathField.text, true)
            return
        }
        const ok = remote ? service.startRemote(hostField.text.trim(), remoteFolder) : service.startLocal(localFolder)
        if (ok) { close(); configured() }
        else errorText = tr("无法使用此目录，请重新选择。", "Could not use this folder. Choose another folder.")
    }
    onClosed: service.cancel()
    Connections {
        target: root.service
        function onBrowseFinished(result) {
            if (!root.visible || !root.remote) return
            const shouldUse = root.useAfterBrowse
            root.useAfterBrowse = false
            if (result.error) {
                root.remoteFolder = ""
                root.errorText = result.error + (result.detail ? "\n" + result.detail : "")
                return
            }
            root.remoteFolder = result.path
            root.remoteParent = result.parent
            root.entries = result.entries
            root.limited = result.limited
            pathField.text = result.path
            if (shouldUse) root.confirm()
        }
    }
    FolderDialog {
        id: folderDialog
        title: root.tr("选择工作目录", "Choose a working folder")
        onAccepted: root.pickLocal(selectedFolder)
    }

    contentItem: ColumnLayout {
        id: content
        spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: root.tr("选择工作目录", "Choose a working folder")
                color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(20); font.weight: Font.DemiBold
            }
            ActionButton {
                objectName: "sessionWorkspaceClose"
                glyph: "x"; quiet: true; implicitWidth: 30; implicitHeight: 30
                Accessible.name: root.tr("关闭", "Close")
                onClicked: root.close()
            }
        }
        Rectangle {
            color: Theme.bg; border.color: Theme.line; radius: 9
            implicitWidth: modes.implicitWidth + 8; implicitHeight: modes.implicitHeight + 8
            RowLayout {
                id: modes
                anchors.centerIn: parent; spacing: 3
                ModeButton {
                    objectName: "sessionWorkspaceLocal"
                    text: root.tr("本机", "Local"); selected: !root.remote
                    onClicked: root.selectMode(false)
                }
                ModeButton {
                    objectName: "sessionWorkspaceSsh"
                    text: root.tr("远程 SSH", "Remote SSH"); selected: root.remote
                    onClicked: root.selectMode(true)
                }
            }
        }

        ColumnLayout {
            visible: !root.remote
            Layout.fillWidth: true; spacing: 8
            RowLayout {
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    text: root.tr("已打开的目录", "Open folders")
                    color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); font.weight: Font.Medium
                }
                ActionButton {
                    objectName: "sessionWorkspaceBrowseLocal"
                    text: root.tr("浏览…", "Browse…"); glyph: "folder"; quiet: true; implicitHeight: 34
                    onClicked: folderDialog.open()
                }
            }
            Rectangle {
                Layout.fillWidth: true; implicitHeight: Math.min(235, Math.max(112, 48 * root.folders.length + 10))
                color: localDrop.containsDrag ? Theme.accentBg : Theme.bg
                border.color: localDrop.containsDrag ? Theme.accent : Theme.line; radius: 8
                DropArea {
                    id: localDrop; anchors.fill: parent
                    onEntered: drag => { drag.accepted = drag.urls.length === 1 && !!root.service.localPath(String(drag.urls[0])) }
                    onDropped: drop => { root.pickLocal(drop.urls[0]); drop.acceptProposedAction() }
                }
                Text {
                    visible: root.folders.length === 0
                    anchors.centerIn: parent
                    text: root.tr("点击「浏览」或拖入文件夹", "Browse or drop a folder here")
                    color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                }
                ListView {
                    anchors.fill: parent; anchors.margins: 5; clip: true
                    model: root.folders
                    ScrollBar.vertical: ScrollBar {}
                    delegate: DirectoryRow {
                        required property var modelData
                        width: ListView.view.width; height: 48
                        objectName: "sessionWorkspaceLocalFolder"
                        title: modelData.name; detail: modelData.path; chosen: root.localFolder === modelData.path
                        onClicked: { root.localFolder = modelData.path; folderDialog.currentFolder = root.service.folderUrl(modelData.path); root.errorText = "" }
                        onDoubleClicked: root.confirm()
                    }
                }
            }
        }

        ColumnLayout {
            visible: root.remote
            Layout.fillWidth: true; spacing: 8
            RowLayout {
                Layout.fillWidth: true
                InputField {
                    id: hostField; objectName: "sessionWorkspaceSshHost"
                    Layout.fillWidth: true; maximumLength: 260
                    placeholderText: root.tr("SSH 主机别名或 user@host", "SSH host alias or user@host")
                    Accessible.name: root.tr("SSH 主机", "SSH host")
                    onTextEdited: { root.resetRemote(); pathField.text = "" }
                    onAccepted: root.browse(pathField.text, false)
                }
                ActionButton {
                    id: showHosts; objectName: "sessionWorkspaceSshHosts"
                    visible: root.hosts.length > 0; glyph: "chevron-down"
                    text: root.tr("主机", "Hosts")
                    onClicked: hostMenu.open()
                    FloatingMenu {
                        id: hostMenu
                        y: showHosts.height + 4
                        Instantiator {
                            model: root.hosts
                            delegate: ContextAction {
                                required property string modelData
                                text: modelData; glyph: "server"
                                onTriggered: {
                                    root.resetRemote()
                                    hostField.text = modelData
                                    root.browse("", false)
                                }
                            }
                            onObjectAdded: (index, item) => hostMenu.insertItem(index, item)
                            onObjectRemoved: (index, item) => hostMenu.removeItem(item)
                        }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                InputField {
                    id: pathField; objectName: "sessionWorkspaceSshPath"
                    Layout.fillWidth: true; maximumLength: 4096; enabled: !root.service.busy
                    placeholderText: root.tr("远程路径，例如 ~/projects", "Remote path, e.g. ~/projects")
                    Accessible.name: root.tr("远程目录", "Remote folder")
                    onTextEdited: root.errorText = ""
                    onAccepted: root.browse(text, false)
                }
                ActionButton {
                    objectName: "sessionWorkspaceBrowseSsh"
                    text: root.tr("浏览…", "Browse…"); enabled: !!hostField.text.trim() && !root.service.busy
                    onClicked: root.browse(pathField.text, false)
                }
                ActionButton {
                    objectName: "sessionWorkspaceSshHome"
                    text: root.tr("主目录", "Home"); quiet: true; enabled: !!hostField.text.trim() && !root.service.busy
                    onClicked: root.browse("", false)
                }
            }
            Rectangle {
                Layout.fillWidth: true; implicitHeight: 246
                color: Theme.bg; border.color: Theme.line; radius: 8
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 5; spacing: 2
                    RowLayout {
                        visible: !!root.remoteFolder
                        Layout.fillWidth: true
                        ActionButton {
                            objectName: "sessionWorkspaceSshParent"
                            glyph: "arrow-up"; quiet: true; implicitHeight: 31
                            text: root.tr("上一级", "Parent")
                            enabled: root.remoteParent !== root.remoteFolder && !root.service.busy
                            onClicked: root.browse(root.remoteParent, false)
                        }
                        Text {
                            Layout.fillWidth: true
                            text: root.remoteFolder; textFormat: Text.PlainText; elide: Text.ElideMiddle
                            color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11)
                        }
                    }
                    Item {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        ListView {
                            anchors.fill: parent; clip: true; model: root.entries
                            visible: !root.service.busy && !!root.remoteFolder
                            ScrollBar.vertical: ScrollBar {}
                            delegate: DirectoryRow {
                                required property var modelData
                                width: ListView.view.width; height: 33
                                objectName: "sessionWorkspaceRemoteFolder"
                                title: modelData.name
                                onClicked: root.browse(modelData.path, false)
                            }
                        }
                        Text {
                            anchors.centerIn: parent
                            visible: root.service.busy || !root.remoteFolder || root.entries.length === 0
                            text: root.service.busy ? root.tr("正在连接 SSH…", "Connecting over SSH…")
                                : root.remoteFolder ? root.tr("没有子目录", "No subfolders")
                                : root.tr("使用本机 OpenSSH 配置和密钥连接", "Connect using your local OpenSSH configuration and keys")
                            color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                        }
                    }
                    Text {
                        visible: root.limited && !!root.remoteFolder
                        Layout.fillWidth: true; leftPadding: 8; bottomPadding: 4
                        text: root.tr("目录较多，可输入完整路径定位。", "Enter the full path to find folders outside this list.")
                        color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11)
                    }
                }
            }
        }

        Text {
            Layout.fillWidth: true
            visible: !!root.errorText; text: root.errorText; textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere
            maximumLineCount: 3; elide: Text.ElideRight
            color: Theme.danger; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
        }
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                objectName: "sessionWorkspaceSelectedPath"
                text: root.remote ? root.remoteFolder : root.localFolder
                textFormat: Text.PlainText; elide: Text.ElideMiddle
                color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11)
            }
            ActionButton {
                objectName: "sessionWorkspaceCancel"
                text: root.tr("取消", "Cancel"); quiet: true
                onClicked: root.close()
            }
            ActionButton {
                id: confirmButton; objectName: "sessionWorkspaceConfirm"
                text: root.tr("选用此路径", "Use this folder"); primary: true
                enabled: root.remote ? !!hostField.text.trim() && !root.service.busy : !!root.localFolder
                onClicked: root.confirm()
            }
        }
    }

    component ModeButton: ActionButton {
        property bool selected: false
        implicitHeight: 32
        quiet: !selected
        textColor: selected ? Theme.ink : Theme.muted
        Accessible.selected: selected
    }

    component DirectoryRow: ItemDelegate {
        id: directory
        property string title: ""
        property string detail: ""
        property bool chosen: false
        hoverEnabled: true
        padding: 9
        Accessible.name: title + (detail ? ", " + detail : "")
        Accessible.selected: chosen
        background: Rectangle { radius: 6; color: directory.chosen ? Theme.accentBg : directory.hovered ? Theme.hover : "transparent" }
        contentItem: RowLayout {
            spacing: 9
            Glyph { name: "folder"; width: Theme.icon(16); height: Theme.icon(16); color: directory.chosen ? Theme.accent : Theme.muted }
            ColumnLayout {
                Layout.fillWidth: true; spacing: 2
                Text {
                    Layout.fillWidth: true
                    text: directory.title; textFormat: Text.PlainText; elide: Text.ElideRight
                    color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                }
                Text {
                    visible: !!directory.detail; Layout.fillWidth: true
                    text: directory.detail; textFormat: Text.PlainText; elide: Text.ElideMiddle
                    color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(10)
                }
            }
            Glyph { visible: directory.chosen; name: "check"; width: Theme.icon(14); height: Theme.icon(14); color: Theme.accent }
        }
    }
}
