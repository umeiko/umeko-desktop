import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Rectangle {
    id: root
    objectName:"fileTreePluginPage"
    required property var sdk
    readonly property var c:sdk.colors
    color:c.surface
    property var cache:({})
    property var expanded:({".":true})
    property var requests:({})
    property bool hidden:!!sdk.config.showHidden
    property string selectedPath:""
    property string error:""
    property string rootName:""
    property bool clipped:false
    property int loading:0
    property bool filterOpen:false
    property bool workspaceOpen:true
    property var contextEntry:({})
    property string pendingReveal: sdk.revealPath || ""
    function revealNext() {
        if(!pendingReveal || !cache["."])return
        const parts=pendingReveal.split("/");let path=".";const next=Object.assign({},expanded)
        for(let index=0;index<parts.length-1;index++) {
            path=path==="."?parts[index]:path+"/"+parts[index];next[path]=true
            if(!cache[path]) {
                expanded=next
                if(!Object.values(requests).some(request=>request.kind==="list" && request.path===path))call("list",{path:path,showHidden:hidden},"list")
                return
            }
        }
        expanded=next;workspaceOpen=true;selectedPath=pendingReveal;pendingReveal="";rebuild()
        for(let index=0;index<tree.count;index++)if(tree.get(index).path===selectedPath){list.positionViewAtIndex(index,ListView.Contain);break}
    }
    function call(method,args,kind) {
        const token=sdk.call(method,args)
        if (!token) {error="插件暂时繁忙，请稍后重试";return false}
        const pending=Object.assign({},requests);pending[token]={kind:kind || method,path:args.path || "."};requests=pending;loading++
        return true
    }
    function refresh() {cancelRename(false);cache=({});expanded=({".":true});tree.clear();clipped=false;error="";call("list",{path:".",showHidden:hidden},"list")}
    function rebuild() {
        tree.clear()
        const query=filter.text.toLowerCase()
        function append(path,depth) {
            if (depth>32) {root.clipped=true;return}
            const children=cache[path] || []
            for (let i=0;i<children.length;i++) {
                if(tree.count>=4000){root.clipped=true;return}
                const row=children[i]
                if (!query || row.name.toLowerCase().includes(query) || row.directory)
                    tree.append({name:row.name,path:row.path,directory:row.directory,symlink:row.symlink,extension:row.extension,depth:depth,expanded:!!expanded[row.path]})
                if(row.directory && expanded[row.path])append(row.path,depth+1)
            }
        }
        if(workspaceOpen)append(".",0)
    }
    function toggle(row) {
        if(!row.directory)return
        const next=Object.assign({},expanded);next[row.path]=!next[row.path];expanded=next
        if(next[row.path] && !cache[row.path])call("list",{path:row.path,showHidden:hidden},"list")
        rebuild()
    }
    Shortcut { sequence:"Ctrl+F"; enabled:root.sdk.active; onActivated:{root.filterOpen=true;filter.forceActiveFocus()} }
    function renameSelected() {
        if(!selectedPath || renameBusy)return
        renameDraft=selectedPath.split("/").pop();renameError="";renameEntry=selectedPath
        Qt.callLater(function(){root.focusRename(true)})
    }
    function focusRename(selectStem) {
        if(!renameEntry || renameBusy)return
        for(let index=0;index<tree.count;index++)if(tree.get(index).path===renameEntry) {
            list.currentIndex=index;list.positionViewAtIndex(index,ListView.Contain)
            const item=list.itemAtIndex(index)
            if(item)item.focusNameEditor(!!selectStem)
            break
        }
    }
    function cancelRename(refocus) {
        if(renameBusy)return
        renameEntry="";renameDraft="";renameError=""
        if(refocus)list.forceActiveFocus()
    }
    function submitRename() {
        if(!renameEntry || renameBusy)return
        const name=renameDraft.trim()
        if(!name || name==="." || name===".." || /[\\/\u0000]/.test(name)) {renameError="请输入有效的文件名称";return}
        if(name===renameEntry.split("/").pop()){cancelRename(true);return}
        renameError="";renameBusy=true
        if(!call("rename",{path:renameEntry,name:name})) {renameBusy=false;renameError=error;focusRename(false)}
    }
    function deleteSelected() {if(!selectedPath)return;deleteEntry=selectedPath;deleteDialog.open()}
    property string renameEntry:""
    property string renameDraft:""
    property string renameError:""
    property bool renameBusy:false
    property string deleteEntry:""
    Shortcut {sequence:"Ctrl+C";enabled:list.activeFocus && !!root.selectedPath;onActivated:root.call("copy",{path:root.selectedPath})}
    Shortcut {sequence:"Ctrl+X";enabled:list.activeFocus && !!root.selectedPath;onActivated:root.call("cut",{path:root.selectedPath})}
    Shortcut {sequence:"Shift+Alt+C";enabled:list.activeFocus && !!root.selectedPath;onActivated:root.call("copyPath",{path:root.selectedPath},"copyPath")}
    Shortcut {sequence:"Ctrl+K, Ctrl+Shift+C";enabled:list.activeFocus && !!root.selectedPath;onActivated:root.sdk.copyText(root.selectedPath)}
    Shortcut {sequence:"F2";enabled:list.activeFocus && !!root.selectedPath;onActivated:root.renameSelected()}
    Shortcut {sequence:"Delete";enabled:list.activeFocus && !!root.selectedPath;onActivated:root.deleteSelected()}
    Component.onCompleted:refresh()
    Connections {target:root.sdk;function onResponse(token,value) {
        const request=root.requests[token];if(!request)return
        const pending=Object.assign({},root.requests);delete pending[token];root.requests=pending;root.loading=Math.max(0,root.loading-1)
        if(!value.ok){
            if(request.kind==="rename"){root.renameBusy=false;root.renameError=value.error || "重命名失败";Qt.callLater(function(){root.focusRename(false)})}
            else root.error=value.error || "插件操作失败"
            return
        }
        const result=value.result || {}
        if(request.kind==="list") {const cache=Object.assign({},root.cache);let total=0;for (const key of Object.keys(cache)) if(key!==request.path)total+=cache[key].length;const incoming=result.entries || [];cache[request.path]=incoming.slice(0,Math.max(0,10000-total));if(cache[request.path].length<incoming.length)root.clipped=true;root.cache=cache;root.rootName=result.root || root.rootName;root.clipped=root.clipped || !!result.truncated;root.rebuild();root.revealNext()}
        if(request.kind==="copyPath")root.sdk.copyText(result.path || "")
        if(request.kind==="rename" || request.kind==="delete"){root.renameBusy=false;root.pendingReveal=result.path || "";root.refresh()}
    }}
    Connections {target:root.sdk;function onRevealPathChanged(){root.pendingReveal=root.sdk.revealPath;root.revealNext()}function onEvent(topic,data){if(topic==="file.select"){root.pendingReveal=data.path || "";root.revealNext()}}}
    ListModel {id:tree;dynamicRoles:true}
    ColumnLayout {
        anchors.fill:parent;spacing:0
        RowLayout {
            Layout.fillWidth:true;Layout.preferredHeight:30*root.sdk.scale;Layout.leftMargin:16*root.sdk.scale;Layout.rightMargin:8*root.sdk.scale;spacing:0
            Text {text:"文件管理器";color:root.c.ink;font.family:"Segoe UI";font.pixelSize:11*root.sdk.scale;Layout.fillWidth:true}
            VsButton {uiScale:root.sdk.scale;iconName:"filter";foreground:root.c.muted;hoverColor:root.c.hover;hint:"筛选文件";onClicked:{root.filterOpen=!root.filterOpen;if(root.filterOpen)filter.forceActiveFocus();else filter.clear()}}
            VsButton {uiScale:root.sdk.scale;iconName:root.hidden?"eye":"eye-closed";foreground:root.c.muted;hoverColor:root.c.hover;hint:"显示隐藏文件";onClicked:{root.hidden=!root.hidden;root.refresh()}}
            VsButton {uiScale:root.sdk.scale;iconName:"collapse-all";foreground:root.c.muted;hoverColor:root.c.hover;hint:"全部折叠";onClicked:{root.expanded=({".":true});root.rebuild()}}
            VsButton {objectName:"fileTreeRefresh";uiScale:root.sdk.scale;iconName:"refresh";foreground:root.c.muted;hoverColor:root.c.hover;hint:"刷新";onClicked:root.refresh()}
        }
        TextField {
            id:filter;objectName:"fileTreeFilter";visible:root.filterOpen;Layout.fillWidth:true;Layout.preferredHeight:26*root.sdk.scale;Layout.leftMargin:16*root.sdk.scale;Layout.rightMargin:16*root.sdk.scale;Layout.bottomMargin:6*root.sdk.scale
            placeholderText:"筛选已加载的文件";font.family:"Segoe UI";font.pixelSize:13*root.sdk.scale;color:root.c.ink;selectByMouse:true
            background:Rectangle {color:root.c.bg;border.color:filter.activeFocus?root.c.accent:root.c.line;radius:3}
            onTextChanged:root.rebuild()
        }
        Rectangle {
            Layout.fillWidth:true;implicitHeight:22*root.sdk.scale;color:root.c.surface
            VsIcon {x:3*root.sdk.scale;anchors.verticalCenter:parent.verticalCenter;name:root.workspaceOpen?"chevron-down":"chevron-right";size:16*root.sdk.scale;color:root.c.ink}
            Text {anchors.verticalCenter:parent.verticalCenter;x:22*root.sdk.scale;width:parent.width-x-8*root.sdk.scale;text:(root.rootName || root.sdk.session.workspace.split(/[\\/]/).pop() || "工作目录").toUpperCase();elide:Text.ElideRight;color:root.c.ink;font.family:"Segoe UI";font.pixelSize:11*root.sdk.scale;font.weight:Font.DemiBold;textFormat:Text.PlainText}
            MouseArea {anchors.fill:parent;onClicked:{root.workspaceOpen=!root.workspaceOpen;root.rebuild()}ToolTip.visible:containsMouse;ToolTip.text:root.sdk.session.workspace || ""}
        }
        Text {visible:!!root.error;Layout.fillWidth:true;Layout.margins:14;text:root.error;textFormat:Text.PlainText;color:root.c.danger;wrapMode:Text.Wrap;font.pixelSize:12*root.sdk.scale}
        ListView {
            id:list;objectName:"fileTreeEntries";Layout.fillWidth:true;Layout.fillHeight:true;model:tree;clip:true;boundsBehavior:Flickable.StopAtBounds
            ScrollBar.vertical:ScrollBar{}
            delegate:Rectangle {
                id:row
                objectName:"fileTreeRow_"+path
                required property string name
                required property string path
                required property bool directory
                required property bool symlink
                required property string extension
                required property int depth
                required property bool expanded
                readonly property bool editing:root.renameEntry===path
                function focusNameEditor(selectStem) {
                    if(!editing)return
                    nameEditor.forceActiveFocus()
                    if(selectStem){const dot=row.directory?-1:nameEditor.text.lastIndexOf(".");nameEditor.select(0,dot>0?dot:nameEditor.text.length)}
                }
                width:list.width;height:22*root.sdk.scale
                color:root.selectedPath===path?root.c.accentBg:mouse.containsMouse?root.c.hover:"transparent"
                Repeater {model:row.depth;Rectangle {required property int index;x:(15+index*8)*root.sdk.scale;y:0;width:1;height:row.height;color:root.c.line;opacity:0.5}}
                Row {
                    x:(8+row.depth*8)*root.sdk.scale;anchors.verticalCenter:parent.verticalCenter;spacing:4*root.sdk.scale
                    VsIcon {size:16*root.sdk.scale;opacity:row.directory?1:0;name:row.expanded?"chevron-down":"chevron-right";color:root.c.muted;anchors.verticalCenter:parent.verticalCenter}
                    FileIcon {fileName:row.name;directory:row.directory;expanded:row.expanded;dark:root.c.dark;uiScale:root.sdk.scale;folderColor:root.c.muted;anchors.verticalCenter:parent.verticalCenter}
                    Item {
                        width:Math.max(0,row.width-parent.x-48*root.sdk.scale);height:row.height
                        Text {anchors.fill:parent;verticalAlignment:Text.AlignVCenter;visible:!row.editing;text:row.name;textFormat:Text.PlainText;color:root.c.ink;elide:Text.ElideRight;font.family:"Segoe UI";font.pixelSize:13*root.sdk.scale}
                        TextField {
                            id:nameEditor;objectName:row.editing?"fileManagerRenameField":""
                            anchors.fill:parent;visible:row.editing;enabled:!root.renameBusy;text:root.renameDraft
                            selectByMouse:true;color:root.c.ink;font.family:"Segoe UI";font.pixelSize:13*root.sdk.scale
                            padding:0;leftPadding:3*root.sdk.scale;rightPadding:3*root.sdk.scale
                            background:Rectangle {color:root.c.bg;border.color:root.renameError?root.c.danger:root.c.accent}
                            onVisibleChanged:if(visible)Qt.callLater(function(){root.focusRename(true)})
                            onTextEdited:{root.renameDraft=text;root.renameError=""}
                            onAccepted:root.submitRename()
                            Keys.onShortcutOverride:event=>{if(event.key===Qt.Key_Escape)event.accepted=true}
                            Keys.onEscapePressed:event=>{root.cancelRename(true);event.accepted=true}
                            ToolTip.visible:row.editing && !!root.renameError
                            ToolTip.text:root.renameError
                        }
                    }
                }
                MouseArea {
                    id:mouse;anchors.fill:parent;enabled:!row.editing && !root.renameBusy;hoverEnabled:true;cursorShape:Qt.PointingHandCursor;acceptedButtons:Qt.LeftButton|Qt.RightButton
                    onClicked:event=>{root.cancelRename(false);root.selectedPath=row.path;root.contextEntry={path:row.path,directory:row.directory};list.forceActiveFocus();if(event.button===Qt.RightButton){const p=mouse.mapToItem(root,event.x,event.y);menu.x=p.x;menu.y=p.y;menu.open()}else if(row.directory)root.toggle(row)}
                    onDoubleClicked:event=>{if(event.button===Qt.LeftButton && !row.directory)root.call("attach",{path:row.path})}
                }
            }
            Text {anchors.centerIn:parent;visible:list.count===0 && !root.loading && !root.error;text:"当前目录为空";color:root.c.muted;font.pixelSize:12*root.sdk.scale}
        }
        Text {visible:root.clipped;Layout.fillWidth:true;Layout.margins:10;wrapMode:Text.Wrap;text:"目录条目较多，已限制单层及总预览数量。刷新可重新加载。";color:root.c.muted;font.pixelSize:10*root.sdk.scale}
    }
    Menu {
        id:menu;objectName:"fileManagerContextMenu";parent:root;width:Math.min(340*root.sdk.scale,root.width-12);padding:4
        onClosed:if(root.renameEntry)Qt.callLater(function(){root.focusRename(false)})
        font.family:"Segoe UI";font.pixelSize:13*root.sdk.scale;palette.text:root.c.ink;palette.window:root.c.surface
        background:Rectangle {color:root.c.surface;radius:5;border.color:root.c.line}
        VsMenuItem {objectName:"fileManagerPreview";text:"预览文件";colors:root.c;uiScale:root.sdk.scale;enabled:!root.contextEntry.directory;onTriggered:root.call("preview",{path:root.contextEntry.path})}
        VsMenuItem {text:"打开方式…";colors:root.c;uiScale:root.sdk.scale;enabled:!root.contextEntry.directory;onTriggered:root.call("openWith",{path:root.contextEntry.path})}
        VsMenuItem {text:"在文件管理器中打开";colors:root.c;uiScale:root.sdk.scale;onTriggered:root.call("reveal",{path:root.contextEntry.path})}
        MenuSeparator {contentItem:Rectangle {implicitHeight:1;color:root.c.line}}
        VsMenuItem {text:"附加到聊天";colors:root.c;uiScale:root.sdk.scale;enabled:!root.contextEntry.directory;onTriggered:root.call("attach",{path:root.contextEntry.path})}
        MenuSeparator {contentItem:Rectangle {implicitHeight:1;color:root.c.line}}
        VsMenuItem {objectName:"fileManagerCut";text:"剪切";shortcutText:"Ctrl+X";colors:root.c;uiScale:root.sdk.scale;onTriggered:root.call("cut",{path:root.contextEntry.path})}
        VsMenuItem {objectName:"fileManagerCopy";text:"复制";shortcutText:"Ctrl+C";colors:root.c;uiScale:root.sdk.scale;onTriggered:root.call("copy",{path:root.contextEntry.path})}
        MenuSeparator {contentItem:Rectangle {implicitHeight:1;color:root.c.line}}
        VsMenuItem {text:"复制路径";shortcutText:"Shift+Alt+C";colors:root.c;uiScale:root.sdk.scale;onTriggered:root.call("copyPath",{path:root.contextEntry.path},"copyPath")}
        VsMenuItem {text:"复制相对路径";shortcutText:"Ctrl+K Ctrl+Shift+C";colors:root.c;uiScale:root.sdk.scale;onTriggered:root.sdk.copyText(root.contextEntry.path)}
        MenuSeparator {contentItem:Rectangle {implicitHeight:1;color:root.c.line}}
        VsMenuItem {objectName:"fileManagerRename";text:"重命名…";shortcutText:"F2";colors:root.c;uiScale:root.sdk.scale;onTriggered:root.renameSelected()}
        VsMenuItem {objectName:"fileManagerDelete";text:"永久删除";shortcutText:"Del";colors:root.c;uiScale:root.sdk.scale;onTriggered:root.deleteSelected()}
    }
    Dialog {
        id:deleteDialog;objectName:"fileManagerDeleteDialog";parent:root;anchors.centerIn:parent;modal:true
        width:Math.min(460*root.sdk.scale,parent.width-24);title:"永久删除？";palette.window:root.c.surface;palette.windowText:root.c.ink
        Overlay.modal:Rectangle {color:"transparent"}
        contentItem:Text {text:root.deleteEntry+"\n此操作无法撤销。";color:root.c.ink;textFormat:Text.PlainText;wrapMode:Text.Wrap;font.pixelSize:13*root.sdk.scale}
        footer:RowLayout {Item {Layout.fillWidth:true}Button {text:"取消";onClicked:deleteDialog.close()}Button {objectName:"fileManagerDeleteConfirm";text:"永久删除";palette.buttonText:root.c.danger;onClicked:{deleteDialog.close();root.call("delete",{path:root.deleteEntry})}}}
    }
}
