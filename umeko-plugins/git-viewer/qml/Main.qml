import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Umeko.Text 1.0

Rectangle {
    id: root
    objectName: "gitViewerPluginPage"
    required property var sdk
    readonly property var c: sdk.colors
    readonly property real s: sdk.scale
    readonly property color graphBlue: c.dark ? "#54a3ff" : "#0078d4"
    readonly property color commitBlue: c.dark ? "#0e639c" : "#0078d4"
    color: c.surface
    property var requests: ({})
    property var changes: []
    property var commits: []
    property var collapsed: ({})
    property string branch: ""
    property string error: ""
    property string diff: ""
    property string diffPath: ""
    property string selectedCommit: ""
    property bool repository: true
    property bool truncated: false
    property bool changesOpen: true
    property bool graphOpen: true
    property bool allBranches: true
    property int loading: 0
    property var refs: []
    property var contextEntry: ({})
    property var diffEntry: ({})
    readonly property int stagedCount: changes.filter(x => x.group === "staged").length
    readonly property bool canCommit: stagedCount > 0 && message.text.trim().length > 0 && !loading

    function call(method, args, kind) {
        const token = sdk.call(method, args || {})
        if (!token) { error = "插件暂时繁忙，请稍后重试"; return }
        const pending = Object.assign({}, requests); pending[token] = kind || method; requests = pending; loading++
    }
    function refresh() { error = ""; call("status", {}); call("history", {all: allBranches}) }
    function commit() { if (canCommit) call("commit", {message: message.text}) }
    function toggleGroup(group) { const next = Object.assign({}, collapsed); next[group] = !next[group]; collapsed = next; rebuild() }
    function showDiff(path, group) { diffEntry=changes.find(row=>row.path===path && row.group===group)||{path:path,group:group};diffPath = path; diff = ""; call("diff", {path: path, group: group}) }
    function contextMenuAt(item,x,y) {const point=item.mapToItem(root,x,y);fileMenu.x=point.x;fileMenu.y=point.y;fileMenu.open()}
    function fileOperation(method,args) {
        if(method==="diff")showDiff(args.path,args.group)
        else {if(method==="headFile"){diffEntry=contextEntry;diffPath=args.path+"（HEAD）";diff=""};call(method,args)}
    }
    function rebuild() {
        rows.clear()
        for (const group of ["staged", "changes"]) {
            const items = changes.filter(x => group === "staged" ? x.group === "staged" : x.group !== "staged")
            if (!items.length) continue
            rows.append({header:true, name:group === "staged" ? "暂存的更改" : "更改", path:"", directory:"", group:group, status:String(items.length)})
            if (!collapsed[group]) for (const item of items) rows.append({header:false, name:item.name, path:item.path, directory:item.directory === "." ? "" : item.directory, group:item.group, status:item.status})
        }
    }
    function laneColor(column) { return [graphBlue, "#b180d7", "#3fb8af", "#e4a545", "#d67087"][column % 5] }
    Component.onCompleted: refresh()
    Connections {
        target: root.sdk
        function onEvent(topic,data) {
            if(topic==="git.diff"){root.diffEntry={path:data.path,group:data.group};root.diffPath=data.path;root.diff=data.text || "";root.truncated=!!data.truncated}
        }
        function onResponse(token, value) {
            const kind = root.requests[token]; if (!kind) return
            const pending = Object.assign({}, root.requests); delete pending[token]; root.requests = pending; root.loading = Math.max(0, root.loading - 1)
            if (!value.ok) { root.error = value.error || "版本管理操作失败"; return }
            const result = value.result || {}
            if (kind === "status") { root.repository = result.repository !== false; root.changes = result.entries || []; root.branch = result.branch || ""; root.truncated = !!result.truncated; root.rebuild() }
            else if (kind === "history") root.commits = result.entries || []
            else if (kind === "branches") root.refs = result.entries || []
            else if (kind === "diff" || kind === "commitDiff" || kind === "headFile") { root.diff = result.text || ""; root.truncated = !!result.truncated }
            else if (["attach","reveal","explorer"].includes(kind)) { }
            else { if (kind === "commit") message.clear(); root.diff = ""; root.diffPath = ""; root.refresh() }
        }
    }
    ListModel { id: rows }

    SplitView {
        id: sections
        anchors.left:parent.left;anchors.right:parent.right;anchors.top:parent.top;anchors.bottom:branchStatus.top
        orientation: Qt.Vertical
        visible: root.repository && !root.diffPath
        handle: Rectangle { implicitHeight: root.changesOpen && root.graphOpen ? 3 : 0; color: SplitHandle.hovered || SplitHandle.pressed ? root.graphBlue : root.c.line }
        Item {
            objectName:"gitChangesSection"
            SplitView.preferredHeight: root.changesOpen ? Math.max(150 * root.s, root.height * 0.48) : 22 * root.s
            SplitView.minimumHeight: 22 * root.s
            SplitView.maximumHeight:root.changesOpen?Infinity:22*root.s
            SplitView.fillHeight:root.changesOpen && !root.graphOpen
            ColumnLayout {
                anchors.fill: parent; spacing: 0
                Rectangle {
                    Layout.fillWidth: true; implicitHeight: 22 * root.s; color: root.c.surface
                    MouseArea {objectName:"gitChangesToggle"; anchors.fill: parent; onClicked: root.changesOpen = !root.changesOpen }
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 3 * root.s; anchors.rightMargin: 5 * root.s; spacing: 3 * root.s
                        VsIcon { name: root.changesOpen ? "chevron-down" : "chevron-right"; size: 16 * root.s; color: root.c.ink }
                        Text { text: "更改"; color: root.c.ink; font.family: "Segoe UI"; font.pixelSize: 11 * root.s; font.weight: Font.DemiBold; Layout.fillWidth: true }
                        VsButton { objectName: "gitViewerRefresh"; uiScale: root.s; iconName: "refresh"; hint: "刷新"; foreground: root.c.ink; hoverColor: root.c.hover; enabled: !root.loading; onClicked: root.refresh() }
                        VsButton { uiScale: root.s; hint: "更多操作"; foreground: root.c.ink; hoverColor: root.c.hover; onClicked: changesMenu.popup() }
                    }
                }
                ColumnLayout {
                    visible: root.changesOpen; Layout.fillWidth: true; Layout.leftMargin: 16 * root.s; Layout.rightMargin: 16 * root.s; Layout.topMargin: 8 * root.s; Layout.bottomMargin: 8 * root.s; spacing: 8 * root.s
                    TextArea {
                        id: message; objectName: "gitCommitMessage"
                        Layout.fillWidth: true; Layout.preferredHeight: Math.max(26 * root.s, Math.min(80 * root.s, contentHeight + 8 * root.s))
                        placeholderText: "消息（Ctrl+Enter 提交）"; placeholderTextColor: root.c.muted
                        color: root.c.ink; selectionColor: root.c.accentBg; selectByMouse: true; wrapMode: TextEdit.Wrap
                        font.family: "Segoe UI"; font.pixelSize: 13 * root.s
                        leftPadding: 7 * root.s; rightPadding: 7 * root.s; topPadding: 4 * root.s; bottomPadding: 4 * root.s
                        onTextChanged: if (text.length > 4000) text = text.slice(0, 4000)
                        Keys.onPressed: event => { if ((event.modifiers & Qt.ControlModifier) && (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)) { root.commit(); event.accepted = true } }
                        background: Rectangle { color: root.c.bg; radius: 3; border.color: message.activeFocus ? root.graphBlue : root.c.line }
                    }
                    Rectangle {
                        Layout.fillWidth: true; implicitHeight: 26 * root.s; radius: 3; color: root.commitBlue
                        Button {
                            id: commitButton; objectName: "gitCommitButton"
                            anchors.left: parent.left; anchors.right: commitMore.left; height: parent.height
                            enabled: root.canCommit; padding: 0; hoverEnabled: true; opacity: enabled ? 1 : 0.45
                            HoverHandler { cursorShape: commitButton.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
                            background: Rectangle { radius: 3; color: commitButton.hovered ? "#1affffff" : "transparent" }
                            contentItem: Item {
                                Row { anchors.centerIn: parent; spacing: 5 * root.s
                                    VsIcon { name: "check"; size: 16 * root.s; color: "white"; anchors.verticalCenter: parent.verticalCenter }
                                    Text { text: "提交"; color: "white"; font.family: "Segoe UI"; font.pixelSize: 13 * root.s; anchors.verticalCenter: parent.verticalCenter }
                                }
                            }
                            onClicked: root.commit()
                        }
                        Rectangle { x: commitMore.x; width: 1; y: 5 * root.s; height: parent.height - 10 * root.s; color: "#50ffffff" }
                        VsButton { id: commitMore; anchors.right: parent.right; height: parent.height; width: 25 * root.s; uiScale: root.s; iconName: "chevron-down"; foreground: "white"; hint: "提交操作"; onClicked: commitMenu.popup() }
                    }
                }
                Text { visible: !!root.error; Layout.fillWidth: true; Layout.leftMargin: 16 * root.s; Layout.rightMargin: 16 * root.s; text: root.error; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: root.c.danger; font.pixelSize: 12 * root.s }
                ListView {
                    id: files; objectName: "gitChangesList"
                    visible: root.changesOpen; Layout.fillWidth: true; Layout.fillHeight: true
                    model: rows; clip: true; boundsBehavior: Flickable.StopAtBounds; ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    delegate: Rectangle {
                        id: row
                        required property bool header
                        required property string name
                        required property string path
                        required property string directory
                        required property string group
                        required property string status
                        objectName: "gitChange_" + group + "_" + path
                        width: files.width; height: 22 * root.s
                        color: mouse.containsMouse ? root.c.hover : "transparent"
                        MouseArea {id:mouse;anchors.fill:parent;hoverEnabled:true;acceptedButtons:Qt.LeftButton|Qt.RightButton;cursorShape:Qt.PointingHandCursor;onClicked:event=>{
                            if(row.header){if(event.button===Qt.LeftButton)root.toggleGroup(row.group);return}
                            if(event.button===Qt.RightButton){root.contextEntry={path:row.path,group:row.group,status:row.status};root.contextMenuAt(mouse,event.x,event.y)}else root.showDiff(row.path,row.group)
                        }}
                        RowLayout {
                            anchors.fill: parent; anchors.leftMargin: (row.header ? 3 : 20) * root.s; anchors.rightMargin: 8 * root.s; spacing: 6 * root.s
                            VsIcon { visible: row.header; name: root.collapsed[row.group] ? "chevron-right" : "chevron-down"; size: 16 * root.s; color: root.c.ink }
                            FileIcon { visible: !row.header; fileName: row.name; dark: root.c.dark; uiScale: root.s }
                            Text { text: row.name; textFormat: Text.PlainText; color: row.status === "D" ? root.c.danger : root.c.ink; font.strikeout: !row.header && row.status === "D"; font.family: "Segoe UI"; font.pixelSize: 13 * root.s; font.weight: row.header ? Font.DemiBold : Font.Normal; elide: Text.ElideRight; Layout.maximumWidth: row.header ? 100000 : files.width * 0.55 }
                            Text { text: row.directory; textFormat: Text.PlainText; color: root.c.muted; font.family: "Segoe UI"; font.pixelSize: 12 * root.s; Layout.fillWidth: true; elide: Text.ElideMiddle }
                            VsButton { objectName: "gitStage_" + row.path; visible: !row.header && (mouse.containsMouse || hovered); uiScale: root.s; iconName: row.group === "staged" ? "remove" : "add"; foreground: root.c.ink; hoverColor: root.c.hover; enabled: !root.loading; hint: row.group === "staged" ? "取消暂存" : "暂存更改"; onClicked: root.call(row.group === "staged" ? "unstage" : "stage", {path: row.path}) }
                            Text { text: row.status; color: row.header ? root.c.muted : row.status === "U" ? "#73a66b" : root.c.accent; font.pixelSize: 12 * root.s; horizontalAlignment: Text.AlignHCenter; Layout.preferredWidth: 18 * root.s }
                        }
                    }
                }
                Text { visible: root.truncated; Layout.fillWidth: true; Layout.margins: 8 * root.s; text: "预览内容已截断"; color: root.c.muted; font.pixelSize: 11 * root.s }
            }
        }
        Item {
            objectName:"gitGraphSection"
            SplitView.fillHeight:root.graphOpen;SplitView.minimumHeight:22*root.s
            SplitView.maximumHeight:root.graphOpen?Infinity:22*root.s
            SplitView.preferredHeight:root.graphOpen?root.height*.48:22*root.s
            ColumnLayout {
                anchors.fill: parent; spacing: 0
                Rectangle {
                    Layout.fillWidth: true; implicitHeight: 22 * root.s; color: root.c.surface
                    MouseArea {objectName:"gitGraphToggle";anchors.fill:parent;onClicked:root.graphOpen=!root.graphOpen}
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 3 * root.s; anchors.rightMargin: 5 * root.s; spacing: 3 * root.s
                        VsIcon { name: root.graphOpen ? "chevron-down" : "chevron-right"; size: 16 * root.s; color: root.c.ink }
                        Text { text: "图形"; color: root.c.ink; font.family: "Segoe UI"; font.pixelSize: 11 * root.s; font.weight: Font.DemiBold; Layout.fillWidth: true }
                        VsButton { uiScale: root.s; iconName: "git-branch"; hint: root.allBranches ? "所有分支" : "当前分支"; foreground: root.c.muted; hoverColor: root.c.hover; onClicked: graphMenu.popup() }
                        Text { text: root.allBranches ? "自动" : root.branch; color: root.c.muted; font.pixelSize: 11 * root.s; Layout.maximumWidth: 70 * root.s; elide: Text.ElideRight }
                        VsButton { uiScale: root.s; iconName: "refresh"; hint: "刷新提交图"; foreground: root.c.muted; hoverColor: root.c.hover; enabled: !root.loading; onClicked: root.call("history", {all: root.allBranches}) }
                        VsButton { uiScale: root.s; hint: "图形选项"; foreground: root.c.muted; hoverColor: root.c.hover; onClicked: graphMenu.popup() }
                    }
                }
                ListView {
                    id: history; objectName: "gitHistoryList"
                    visible: root.graphOpen; Layout.fillWidth: true; Layout.fillHeight: true
                    model: root.commits; clip: true; boundsBehavior: Flickable.StopAtBounds; ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    delegate: Rectangle {
                        id: commitRow
                        required property var modelData
                        required property int index
                        objectName: "gitCommit_" + modelData.hash
                        width: history.width; height: 22 * root.s
                        color: root.selectedCommit === modelData.id ? root.c.accentBg : commitMouse.containsMouse ? root.c.hover : "transparent"
                        MouseArea { id: commitMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { root.selectedCommit = commitRow.modelData.id;root.diffEntry=({}); root.diffPath = "提交 " + commitRow.modelData.hash; root.diff = ""; root.call("commitDiff", {hash: commitRow.modelData.id}) } }
                        RowLayout {
                            anchors.fill: parent; anchors.leftMargin: 3 * root.s; anchors.rightMargin: 8 * root.s; spacing: 5 * root.s
                            Canvas {
                                id: graph
                                Layout.preferredWidth: Math.max(14, Math.min(110, commitRow.modelData.graph.columns * 10 + 4)) * root.s
                                Layout.fillHeight: true
                                onPaint: {
                                    const ctx = getContext("2d"); ctx.reset()
                                    const data = commitRow.modelData.graph, step = 10 * root.s, middle = height / 2, x = 5 * root.s + data.column * step
                                    ctx.lineWidth = 1.35 * root.s
                                    for (const edge of data.edges) {
                                        const from = 5 * root.s + edge.from * step, to = 5 * root.s + edge.to * step, top = edge.node ? middle : 0
                                        ctx.strokeStyle = root.laneColor(edge.from); ctx.beginPath(); ctx.moveTo(from, top); ctx.bezierCurveTo(from, height * 0.7, to, height * 0.7, to, height); ctx.stroke()
                                    }
                                    ctx.strokeStyle = root.laneColor(data.column)
                                    if (data.incoming) { ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,middle); ctx.stroke() }
                                    ctx.beginPath(); ctx.arc(x,middle,3.4*root.s,0,Math.PI*2); ctx.fillStyle = commitRow.index === 0 ? root.c.surface : root.laneColor(data.column); ctx.fill(); ctx.stroke()
                                }
                                onWidthChanged: requestPaint()
                                Connections { target: root; function onCChanged() { graph.requestPaint() } }
                            }
                            Text { text: commitRow.modelData.subject; textFormat: Text.PlainText; color: root.c.ink; font.family: "Segoe UI"; font.pixelSize: 13 * root.s; Layout.fillWidth: true; elide: Text.ElideRight }
                            Text { text: commitRow.modelData.author; textFormat: Text.PlainText; color: root.c.muted; font.family: "Segoe UI"; font.pixelSize: 12 * root.s; Layout.maximumWidth: 70 * root.s; elide: Text.ElideRight }
                            Repeater {
                                model: commitRow.modelData.refs.slice(0, 1)
                                Rectangle {
                                    required property string modelData
                                    Layout.preferredWidth: Math.min(92 * root.s, badgeText.implicitWidth + 10 * root.s); Layout.preferredHeight: 17 * root.s
                                    radius: 7 * root.s; color: modelData.startsWith("HEAD ->") ? root.graphBlue : root.c.accentBg
                                    Text { id: badgeText; anchors.centerIn: parent; width: Math.min(implicitWidth,parent.width-8*root.s); text: parent.modelData.replace(/^HEAD -> /, ""); textFormat: Text.PlainText; color: parent.modelData.startsWith("HEAD ->") ? "white" : root.c.ink; font.family: "Segoe UI"; font.pixelSize: 11 * root.s; elide: Text.ElideRight }
                                }
                            }
                        }
                        ToolTip.visible: commitMouse.containsMouse; ToolTip.delay: 700
                        ToolTip.text: modelData.subject + "\n" + modelData.author + " · " + modelData.date + " · " + modelData.hash + "\n" + modelData.refs.join(", ")
                    }
                    Text { anchors.centerIn: parent; visible: !history.count && !root.loading; text: "尚无提交"; color: root.c.muted; font.pixelSize: 12 * root.s }
                }
            }
        }
    }
    ColumnLayout {
        anchors.left:parent.left;anchors.right:parent.right;anchors.top:parent.top;anchors.bottom:branchStatus.top;spacing:0;visible:!!root.diffPath
        RowLayout {
            Layout.fillWidth: true; Layout.preferredHeight: 30 * root.s; Layout.leftMargin: 6 * root.s; Layout.rightMargin: 6 * root.s
            VsButton { uiScale: root.s; iconName: "arrow-left"; hint: "返回更改"; foreground: root.c.ink; hoverColor: root.c.hover; onClicked: { root.diffPath = ""; root.diff = "" } }
            Text { text: root.diffPath; textFormat: Text.PlainText; color: root.c.ink; font.pixelSize: 13 * root.s; Layout.fillWidth: true; elide: Text.ElideMiddle }
            VsButton { uiScale: root.s; iconName: "copy"; hint: "复制差异"; foreground: root.c.ink; hoverColor: root.c.hover; onClicked: root.sdk.copyText(root.diff) }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: root.c.line }
        ScrollView {
            id: diffScroll; Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentWidth: availableWidth
            TextArea { id: diffText; objectName: "gitDiffText"; width: diffScroll.availableWidth; text: root.diff; readOnly: true; selectByMouse: true; textFormat: TextEdit.PlainText; wrapMode: TextEdit.WrapAnywhere; font.family: "Consolas"; font.pixelSize: 12 * root.s; color: root.c.ink; background: null; padding: 10 * root.s
                SyntaxHighlighter { document: diffText.textDocument; language: "diff"; dark: root.c.dark; enabled: root.diff.length <= 24000 && root.diff.split("\n").length <= 500 }
                MouseArea {id:diffContextMouse;anchors.fill:parent;acceptedButtons:Qt.RightButton;onClicked:event=>{if(root.diffEntry.path){root.contextEntry=root.diffEntry;root.contextMenuAt(diffContextMouse,event.x,event.y)}}}
            }
        }
    }
    Column {
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 16 * root.s
        visible: !root.repository; spacing: 12 * root.s
        Text { width: parent.width; text: "当前文件夹尚未使用 Git 管理。"; color: root.c.ink; font.pixelSize: 13 * root.s; wrapMode: Text.Wrap }
        Button { width: parent.width; height: 28 * root.s; text: "初始化仓库"; enabled: !root.loading; onClicked: root.call("init", {}); palette.buttonText: "white"; font.pixelSize: 13 * root.s; background: Rectangle { radius: 3; color: root.commitBlue } }
    }
    Rectangle {
        id:branchStatus;objectName:"gitBranchStatus";anchors.left:parent.left;anchors.right:parent.right;anchors.bottom:parent.bottom;height:root.repository?22*root.s:0;visible:root.repository;color:root.c.surface
        Rectangle {width:parent.width;height:1;color:root.c.line}
        RowLayout {anchors.fill:parent;anchors.leftMargin:7*root.s;spacing:0
            Button {
                id:branchButton;objectName:"gitBranchButton";Layout.preferredHeight:22*root.s;Layout.preferredWidth:Math.min(branchLabel.implicitWidth+28*root.s,root.width-40*root.s);padding:0;hoverEnabled:true
                background:Rectangle {color:branchButton.hovered?root.c.hover:"transparent"}
                contentItem:RowLayout {spacing:5*root.s;VsIcon {name:"git-branch";size:16*root.s;color:root.c.ink}Text {id:branchLabel;text:root.branch||"HEAD";color:root.c.ink;font.family:"Segoe UI";font.pixelSize:12*root.s;Layout.fillWidth:true;elide:Text.ElideRight}}
                HoverHandler {cursorShape:Qt.PointingHandCursor}onClicked:branchPicker.open()
            }
            VsButton {uiScale:root.s;iconName:"sync";hint:"刷新仓库状态";foreground:root.c.muted;hoverColor:root.c.hover;onClicked:root.refresh()}
            Item {Layout.fillWidth:true}
        }
    }
    BranchPicker {id:branchPicker;parent:root;sdk:root.sdk;entries:root.refs;onReferencesRequested:root.call("branches",{});onOperation:(method,args)=>root.call(method,args)}
    FileContextMenu {id:fileMenu;parent:root;sdk:root.sdk;entry:root.contextEntry;onOperation:(method,args)=>root.fileOperation(method,args)}
    Menu {
        id: changesMenu; font.pixelSize: 13 * root.s
        MenuItem { text: "刷新"; onTriggered: root.refresh() }
        MenuItem { text: "暂存所有更改"; enabled: !!root.changes.length; onTriggered: root.call("stageAll", {}) }
        MenuItem { text: "取消全部暂存"; enabled: root.stagedCount > 0; onTriggered: root.call("unstageAll", {}) }
        MenuItem { text: "复制当前分支名称"; enabled: !!root.branch; onTriggered: root.sdk.copyText(root.branch) }
    }
    Menu {
        id: commitMenu; font.pixelSize: 13 * root.s
        MenuItem { text: "提交暂存的更改"; enabled: root.canCommit; onTriggered: root.commit() }
        MenuItem { text: "暂存所有更改"; enabled: !!root.changes.length; onTriggered: root.call("stageAll", {}) }
    }
    Menu {
        id: graphMenu; font.pixelSize: 13 * root.s
        MenuItem { text: "所有分支"; checkable: true; checked: root.allBranches; onTriggered: { root.allBranches = true; root.call("history", {all:true}) } }
        MenuItem { text: "当前分支"; checkable: true; checked: !root.allBranches; onTriggered: { root.allBranches = false; root.call("history", {all:false}) } }
    }
}
