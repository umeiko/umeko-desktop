import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Rectangle {
    id: root
    objectName: "terminalPluginPage"
    required property var sdk
    readonly property var c: Object.assign({},sdk.colors,sdk.colors.dark ?
        {surface:"#1e1e1e",ink:"#d4d4d4",line:"#333333",hover:"#2a2d2e",accent:"#2684ff",accentBg:"#30343b"} :
        {surface:"#ffffff",ink:"#202020",muted:"#747474",line:"#e5e5e5",hover:"#f5f5f5",accent:"#2684ff",accentBg:"#f0f0f0"})
    readonly property real s: sdk.scale
    property var requests: ({})
    property var terminals: []
    readonly property var groupedTerminals: {
        const groups=[]
        for(const row of terminals) {
            let group=groups.find(items=>items[0].group===row.group)
            if(!group){group=[];groups.push(group)}
            group.push(row)
        }
        const rows=[]
        for(const group of groups)for(let index=0;index<group.length;index++)rows.push(Object.assign({},group[index],{splitIndex:index,splitCount:group.length}))
        return rows
    }
    property var profiles: []
    property string activeId: ""
    property string pendingSelection: ""
    property var visibleIds: []
    property string menuId: ""
    property string renameId: ""
    property string error: ""
    color: c.surface
    function t(zh,en) { return sdk.language === "en" ? en : zh }
    function call(method,args,kind) {
        const token = sdk.call(method,args || {})
        if (!token) { if(method!=="input")error = t("终端正在处理输入，请稍后重试","Terminal is busy; try again shortly"); return "" }
        const next = Object.assign({},requests); next[token] = {kind:kind || method,terminalId:(args || {}).terminalId || ""}; requests = next
        return token
    }
    function refresh(ensure) { call("list",{ensure:!!ensure},"list") }
    function canSplit(id) { const selected=terminals.find(row=>row.id===id);return !!selected && terminals.filter(row=>row.group===selected.group).length<2 }
    function isSplit(id) { const selected=terminals.find(row=>row.id===id);return !!selected && terminals.filter(row=>row.group===selected.group).length>1 }
    function toggleSplit(id) { if(isSplit(id))call("unsplit",{terminalId:id});else call("create",{splitFrom:id}) }
    function pane(id) { for (let i=0;i<panes.count;i++) { const item=panes.itemAt(i); if (item && item.terminalId===id)return item }; return null }
    function select(id) {
        const selected = terminals.find(row=>row.id===id)
        if (!selected) { activeId=""; visibleIds=[]; return }
        activeId=id
        const ids=terminals.filter(row=>row.group===selected.group).map(row=>row.id)
        if (JSON.stringify(ids)!==JSON.stringify(visibleIds)) visibleIds=ids
        Qt.callLater(refreshViews)
    }
    function refreshViews() { if (visibleIds.length) call("view",{ids:visibleIds},"view") }
    function menuAt(id,item,x,y) { menuId=id; const point=item.mapToItem(root,x,y); terminalMenu.x=point.x;terminalMenu.y=point.y;terminalMenu.open() }
    function rename(id) { select(id);renameId=id }
    Component.onCompleted: refresh(true)
    Connections {
        target: root.sdk
        function onEvent(topic,data) {
            if(topic==="terminal.list") {if(data.activeId)root.pendingSelection=data.activeId;root.refresh(false)}
            else if(topic==="terminal.select") {root.pendingSelection=data.terminalId;root.select(data.terminalId)}
        }
        function onResponse(token,value) {
            const request=root.requests[token]; if(!request)return
            const next=Object.assign({},root.requests);delete next[token];root.requests=next
            if(!value.ok) {root.error=value.error || root.t("终端操作失败","Terminal operation failed");return}
            const result=value.result || {}
            if(request.kind==="list") {
                root.terminals=result.terminals || [];root.profiles=result.profiles || []
                const selected=root.pendingSelection || root.activeId || result.activeId
                root.pendingSelection=""
                root.select(root.terminals.some(row=>row.id===selected)?selected:result.activeId)
            } else if(request.kind==="view") {
                for(const frame of result.frames || []) {const item=root.pane(frame.terminalId);if(item)item.snapshot(frame)}
                const item=root.pane(root.activeId);if(item && !root.renameId)item.focusTerminal()
            } else if(request.kind==="create") {root.pendingSelection=result.id;root.refresh(false)}
            else if(request.kind==="unsplit") {root.pendingSelection=result.terminalId;root.refresh(false)}
            else if(request.kind==="clear") {const item=root.pane(request.terminalId);if(item)item.snapshot(result.frame)}
            else if(["kill","rename","attach"].includes(request.kind))root.refresh(false)
        }
    }
    Shortcut { sequence:"Ctrl+Shift+5"; enabled:root.sdk.active && root.canSplit(root.activeId); onActivated:root.call("create",{splitFrom:root.activeId}) }
    Shortcut { sequence:"F2"; enabled:root.sdk.active && !!root.activeId && (terminalList.activeFocus || terminalMenu.visible); onActivated:{const id=terminalMenu.visible?root.menuId:root.activeId;terminalMenu.close();root.rename(id)} }
    Shortcut { sequence:"Del"; enabled:terminalMenu.visible; onActivated:{terminalMenu.close();root.call("kill",{terminalId:root.menuId})} }
    ColumnLayout {
        anchors.fill:parent;spacing:0
        RowLayout {
            Layout.fillWidth:true;Layout.preferredHeight:32*root.s;Layout.leftMargin:12*root.s;Layout.rightMargin:6*root.s;spacing:2*root.s
            Text { text:root.t("终端","TERMINAL");color:root.c.ink;font.family:"Segoe UI";font.pixelSize:11*root.s;font.weight:Font.Medium;Layout.fillWidth:true }
            VsButton {objectName:"terminalNewButton";uiScale:root.s;iconName:"add";foreground:root.c.ink;hoverColor:root.c.hover;hint:root.t("新建终端","New Terminal");onClicked:root.call("create",{})}
            VsButton {id:profileButton;uiScale:root.s;iconName:"chevron-down";foreground:root.c.muted;hoverColor:root.c.hover;hint:root.t("选择 Shell","Select Shell");onClicked:{const point=mapToItem(root,0,height);profileMenu.x=Math.max(0,point.x-profileMenu.width+width);profileMenu.y=point.y;profileMenu.open()}}
            Rectangle {Layout.preferredWidth:1;Layout.preferredHeight:16*root.s;color:root.c.line;Layout.leftMargin:5*root.s;Layout.rightMargin:5*root.s}
            VsButton {objectName:"terminalSplitButton";uiScale:root.s;iconName:root.isSplit(root.activeId)?"layout-panel-off":"split-vertical";foreground:root.c.ink;hoverColor:root.c.hover;enabled:!!root.activeId;hint:root.isSplit(root.activeId)?root.t("取消分栏","Unsplit Terminals"):root.t("上下拆分终端","Split Terminal Vertically");onClicked:root.toggleSplit(root.activeId)}
            VsButton {uiScale:root.s;iconName:"trash";foreground:root.c.ink;hoverColor:root.c.hover;enabled:!!root.activeId;hint:root.t("关闭终端","Kill Terminal");onClicked:root.call("kill",{terminalId:root.activeId})}
        }
        Rectangle {Layout.fillWidth:true;implicitHeight:1;color:root.c.line}
        SplitView {
            id:terminalLayout;objectName:"terminalListContentSplit"
            Layout.fillWidth:true;Layout.fillHeight:true;orientation:Qt.Vertical
            handle:Rectangle {
                id:listHandle
                readonly property bool engaged:SplitHandle.hovered || SplitHandle.pressed
                implicitHeight:6*root.s;color:root.c.surface
                Rectangle {anchors.centerIn:parent;width:parent.width;height:1;color:listHandle.engaged?root.c.accent:root.c.line}
                HoverHandler {cursorShape:Qt.SplitVCursor}
            }
            ListView {
                id:terminalList;objectName:"terminalTabs"
                SplitView.minimumHeight:24*root.s
                SplitView.preferredHeight:Math.min(96,Math.max(24,root.terminals.length*24))*root.s
                SplitView.maximumHeight:Math.max(24*root.s,terminalLayout.height-120*root.s)
                clip:true;model:root.groupedTerminals;boundsBehavior:Flickable.StopAtBounds
                delegate:Rectangle {
                    id:tab;required property var modelData
                    width:terminalList.width;height:24*root.s
                    color:root.activeId===modelData.id?root.c.accentBg:tabMouse.containsMouse?root.c.hover:"transparent"
                    Rectangle {visible:tab.modelData.splitCount>1;x:13*root.s;y:tab.modelData.splitIndex===0?parent.height/2:0;width:root.s;height:parent.height/2;color:root.c.muted;opacity:.65}
                    Rectangle {visible:tab.modelData.splitCount>1;x:13*root.s;anchors.verticalCenter:parent.verticalCenter;width:7*root.s;height:root.s;color:root.c.muted;opacity:.65}
                    VsIcon {x:(tab.modelData.splitCount>1?23:7)*root.s;anchors.verticalCenter:parent.verticalCenter;name:"terminal";size:16*root.s;color:tab.modelData.alive?root.c.muted:root.c.danger}
                    Text {x:(tab.modelData.splitCount>1?44:28)*root.s;anchors.verticalCenter:parent.verticalCenter;width:parent.width-x-(tabMouse.containsMouse?46:7)*root.s;visible:root.renameId!==tab.modelData.id;text:tab.modelData.name;textFormat:Text.PlainText;color:root.c.ink;font.family:"Segoe UI";font.pixelSize:12*root.s;elide:Text.ElideRight}
                    MouseArea {id:tabMouse;anchors.fill:parent;hoverEnabled:true;acceptedButtons:Qt.LeftButton|Qt.RightButton;enabled:root.renameId!==tab.modelData.id
                        onClicked:event=>{root.select(tab.modelData.id);if(event.button===Qt.RightButton)root.menuAt(tab.modelData.id,tab,event.x,event.y)}
                        ToolTip.visible:containsMouse;ToolTip.text:tab.modelData.id+"\n"+tab.modelData.cwd;ToolTip.delay:650
                    }
                    TextField {
                        id:renameField;visible:root.renameId===tab.modelData.id;x:(tab.modelData.splitCount>1?43:27)*root.s;width:parent.width-x-3*root.s;height:parent.height
                        text:tab.modelData.name;color:root.c.ink;font.pixelSize:12*root.s;padding:2*root.s;selectByMouse:true
                        background:Rectangle {color:root.c.bg;border.color:root.c.accent}
                        onVisibleChanged:if(visible)Qt.callLater(function(){renameField.forceActiveFocus();renameField.selectAll()})
                        onAccepted:{root.call("rename",{terminalId:tab.modelData.id,name:text});root.renameId=""}
                        Keys.onEscapePressed:root.renameId=""
                    }
                    Row {anchors.right:parent.right;anchors.verticalCenter:parent.verticalCenter;visible:tabMouse.containsMouse && root.renameId!==tab.modelData.id;spacing:0
                        VsButton {uiScale:root.s;iconName:tab.modelData.splitCount>1?"layout-panel-off":"split-vertical";foreground:root.c.muted;hoverColor:root.c.hover;hint:tab.modelData.splitCount>1?root.t("取消分栏","Unsplit Terminals"):root.t("上下拆分终端","Split Terminal Vertically");onClicked:root.toggleSplit(tab.modelData.id)}
                        VsButton {uiScale:root.s;iconName:"trash";foreground:root.c.muted;hoverColor:root.c.hover;hint:root.t("关闭终端","Kill Terminal");onClicked:root.call("kill",{terminalId:tab.modelData.id})}
                    }
                }
            }
            Item {
                SplitView.fillHeight:true;SplitView.minimumHeight:100*root.s
                SplitView {
                    id:split;objectName:"terminalContentSplit";anchors.fill:parent;orientation:Qt.Vertical
                    handle:Rectangle {
                        id:terminalHandle
                        readonly property bool engaged:SplitHandle.hovered || SplitHandle.pressed
                        implicitHeight:6*root.s;color:root.c.surface
                        Rectangle {anchors.centerIn:parent;width:parent.width;height:1;color:terminalHandle.engaged?root.c.accent:root.c.line}
                        HoverHandler {cursorShape:Qt.SplitVCursor}
                    }
                    Repeater {
                        id:panes;objectName:"terminalPanes";model:root.visibleIds
                        TerminalPane {
                            id:terminalPane
                            required property string modelData
                            terminalId:modelData;sdk:root.sdk
                            sendRequest:(method,args)=>root.call(method,args)
                            SplitView.minimumHeight:60*root.s;SplitView.preferredHeight:split.height/Math.max(1,root.visibleIds.length);SplitView.fillHeight:true
                            onReloadRequested:root.refreshViews()
                            onFailed:message=>root.error=message
                            onMenuRequested:(x,y)=>root.menuAt(terminalId,terminalPane,x,y)
                            onActivated:root.activeId=terminalId
                        }
                    }
                }
                Column {anchors.centerIn:parent;spacing:12;visible:!root.terminals.length
                    Text {anchors.horizontalCenter:parent.horizontalCenter;text:root.t("没有正在运行的终端","No terminals");color:root.c.muted;font.pixelSize:12*root.s}
                    Button {anchors.horizontalCenter:parent.horizontalCenter;text:root.t("新建终端","New Terminal");onClicked:root.call("create",{})}
                }
            }
        }
        RowLayout {visible:!!root.error;Layout.fillWidth:true;Layout.margins:8*root.s
            Text {Layout.fillWidth:true;text:root.error;textFormat:Text.PlainText;wrapMode:Text.Wrap;color:root.c.danger;font.pixelSize:11*root.s}
            VsButton {uiScale:root.s;iconName:"close";foreground:root.c.muted;hoverColor:root.c.hover;onClicked:root.error=""}
        }
    }
    Menu {
        id:profileMenu;parent:root;width:Math.min(260*root.s,root.width-12);padding:4
        background:Rectangle {color:root.c.surface;radius:5;border.color:root.c.line}
        Instantiator {model:root.profiles;delegate:VsMenuItem {required property var modelData;text:modelData.name;colors:root.c;uiScale:root.s;onTriggered:root.call("create",{profile:modelData.id})}onObjectAdded:(index,object)=>profileMenu.insertItem(index,object);onObjectRemoved:(index,object)=>profileMenu.removeItem(object)}
    }
    Menu {
        id:terminalMenu;objectName:"terminalContextMenu";parent:root;width:Math.min(294*root.s,root.width-12);padding:4
        background:Rectangle {color:root.c.surface;radius:5;border.color:root.c.line}
        VsMenuItem {text:root.t("上下拆分终端","Split Terminal Vertically");shortcutText:"Ctrl+Shift+5";colors:root.c;uiScale:root.s;enabled:root.canSplit(root.menuId);onTriggered:root.call("create",{splitFrom:root.menuId})}
        VsMenuItem {text:root.t("取消分栏","Unsplit Terminals");colors:root.c;uiScale:root.s;enabled:root.isSplit(root.menuId);onTriggered:root.call("unsplit",{terminalId:root.menuId})}
        MenuSeparator {contentItem:Rectangle {implicitHeight:1;color:root.c.line}}
        VsMenuItem {objectName:"terminalAttachToChat";text:root.t("附加到当前聊天中","Attach to Current Chat");colors:root.c;uiScale:root.s;onTriggered:root.call("attach",{terminalId:root.menuId})}
        VsMenuItem {text:root.t("复制终端 ID","Copy Terminal ID");colors:root.c;uiScale:root.s;onTriggered:root.sdk.copyText(root.menuId)}
        MenuSeparator {contentItem:Rectangle {implicitHeight:1;color:root.c.line}}
        VsMenuItem {text:root.t("复制","Copy");shortcutText:"Ctrl+Shift+C";colors:root.c;uiScale:root.s;enabled:!!root.pane(root.menuId) && root.pane(root.menuId).hasSelection;onTriggered:root.pane(root.menuId).copy()}
        VsMenuItem {text:root.t("粘贴","Paste");shortcutText:"Ctrl+Shift+V";colors:root.c;uiScale:root.s;enabled:!!root.pane(root.menuId);onTriggered:root.pane(root.menuId).paste()}
        VsMenuItem {text:root.t("全选","Select All");colors:root.c;uiScale:root.s;enabled:!!root.pane(root.menuId);onTriggered:root.pane(root.menuId).selectAll()}
        VsMenuItem {text:root.t("清空终端","Clear Terminal");colors:root.c;uiScale:root.s;onTriggered:root.call("clear",{terminalId:root.menuId})}
        MenuSeparator {contentItem:Rectangle {implicitHeight:1;color:root.c.line}}
        VsMenuItem {text:root.t("重命名…","Rename…");shortcutText:"F2";colors:root.c;uiScale:root.s;onTriggered:root.rename(root.menuId)}
        VsMenuItem {text:root.t("关闭终端","Kill Terminal");shortcutText:"Del";colors:root.c;uiScale:root.s;onTriggered:root.call("kill",{terminalId:root.menuId})}
    }
}
