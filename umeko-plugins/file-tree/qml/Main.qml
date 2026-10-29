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
    property var contextEntry:({})
    function call(method,args,kind) {
        const token=sdk.call(method,args)
        if (!token) {error="插件暂时繁忙，请稍后重试";return}
        const pending=Object.assign({},requests);pending[token]={kind:kind || method,path:args.path || "."};requests=pending;loading++
    }
    function refresh() {cache=({});expanded=({".":true});tree.clear();clipped=false;error="";call("list",{path:".",showHidden:hidden},"list")}
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
        append(".",0)
    }
    function toggle(row) {
        if(!row.directory) {call("preview",{path:row.path});return}
        const next=Object.assign({},expanded);next[row.path]=!next[row.path];expanded=next
        if(next[row.path] && !cache[row.path])call("list",{path:row.path,showHidden:hidden},"list")
        rebuild()
    }
    function icon(ext,dir,open) { if(dir)return open?"▱":"▰";return ({py:"Py",js:"JS",mjs:"JS",ts:"TS",tsx:"TS",json:"{}",md:"M↓",cpp:"C+",hpp:"H+",h:"H",c:"C",qml:"Q",rs:"Rs",go:"Go",html:"<>"})[ext] || "≡" }
    function iconColor(ext,dir) { if(dir)return c.accent;return ({py:"#d9b34a",js:"#d8ba43",mjs:"#d8ba43",ts:"#519aba",tsx:"#519aba",json:"#c9a849",md:"#519aba",cpp:"#8196ce",qml:"#73a764",rs:"#bf7b58"})[ext] || c.muted }
    Component.onCompleted:refresh()
    Connections {target:root.sdk;function onResponse(token,value) {
        const request=root.requests[token];if(!request)return
        const pending=Object.assign({},root.requests);delete pending[token];root.requests=pending;root.loading=Math.max(0,root.loading-1)
        if(!value.ok){root.error=value.error || "插件操作失败";return}
        const result=value.result || {}
        if(request.kind==="list") {const cache=Object.assign({},root.cache);let total=0;for (const key of Object.keys(cache)) if(key!==request.path)total+=cache[key].length;const incoming=result.entries || [];cache[request.path]=incoming.slice(0,Math.max(0,10000-total));if(cache[request.path].length<incoming.length)root.clipped=true;root.cache=cache;root.rootName=result.root || root.rootName;root.clipped=root.clipped || !!result.truncated;root.rebuild()}
        if(request.kind==="copyPath")root.sdk.copyText(result.path || "")
    }}
    ListModel {id:tree;dynamicRoles:true}
    ColumnLayout {
        anchors.fill:parent;spacing:0
        RowLayout {
            Layout.fillWidth:true;Layout.margins:10;spacing:5
            Text {text:"资源管理器";color:root.c.muted;font.pixelSize:11*root.sdk.scale;Layout.fillWidth:true}
            ToolButton { implicitWidth:28*root.sdk.scale;implicitHeight:26*root.sdk.scale;palette.buttonText:root.c.ink;background:Rectangle {radius:4;color:parent.hovered?root.c.hover:"transparent"} text:"◌";ToolTip.text:"显示隐藏文件";ToolTip.visible:hovered;checkable:true;checked:root.hidden;onClicked:{root.hidden=checked;root.refresh()}}
            ToolButton { implicitWidth:28*root.sdk.scale;implicitHeight:26*root.sdk.scale;palette.buttonText:root.c.ink;background:Rectangle {radius:4;color:parent.hovered?root.c.hover:"transparent"} text:"⊟";ToolTip.text:"全部折叠";ToolTip.visible:hovered;onClicked:{root.expanded=({".":true});root.rebuild()}}
            ToolButton { implicitWidth:28*root.sdk.scale;implicitHeight:26*root.sdk.scale;palette.buttonText:root.c.ink;background:Rectangle {radius:4;color:parent.hovered?root.c.hover:"transparent"} objectName:"fileTreeRefresh";text:"↻";ToolTip.text:"刷新";ToolTip.visible:hovered;onClicked:root.refresh()}
        }
        TextField {
            id:filter;objectName:"fileTreeFilter";Layout.fillWidth:true;Layout.leftMargin:12;Layout.rightMargin:12;Layout.bottomMargin:8
            placeholderText:"筛选已加载的文件";font.pixelSize:11*root.sdk.scale;color:root.c.ink;selectByMouse:true
            background:Rectangle {color:root.c.bg;border.color:root.c.line;radius:5}
            onTextChanged:root.rebuild()
        }
        Rectangle {
            Layout.fillWidth:true;implicitHeight:28*root.sdk.scale;color:root.c.hover
            Text {anchors.verticalCenter:parent.verticalCenter;x:12;width:parent.width-24;text:"⌄  "+(root.rootName || root.sdk.session.workspace.split(/[\\/]/).pop() || "工作目录").toUpperCase();elide:Text.ElideRight;color:root.c.ink;font.pixelSize:11*root.sdk.scale;font.weight:Font.DemiBold;textFormat:Text.PlainText}
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
                width:list.width;height:27*root.sdk.scale
                color:root.selectedPath===path?root.c.accentBg:mouse.containsMouse?root.c.hover:"transparent"
                Repeater {model:row.depth;Rectangle {required property int index;x:19+index*16;y:0;width:1;height:row.height;color:root.c.line;opacity:0.6}}
                Row {
                    x:8+row.depth*16;anchors.verticalCenter:parent.verticalCenter;spacing:5
                    Text {width:12;text:row.directory?(row.expanded?"⌄":"›"):"";color:root.c.muted;font.pixelSize:15*root.sdk.scale}
                    Text {width:23;text:root.icon(row.extension,row.directory,row.expanded);color:root.iconColor(row.extension,row.directory);font.pixelSize:11*root.sdk.scale;font.weight:Font.DemiBold;anchors.verticalCenter:parent.verticalCenter}
                    Text {width:Math.max(0,row.width-parent.x-55);text:row.name+(row.symlink?" ↗":"");textFormat:Text.PlainText;color:root.c.ink;elide:Text.ElideRight;font.pixelSize:12*root.sdk.scale;anchors.verticalCenter:parent.verticalCenter}
                }
                MouseArea {
                    id:mouse;anchors.fill:parent;hoverEnabled:true;acceptedButtons:Qt.LeftButton|Qt.RightButton
                    onClicked:event=>{root.selectedPath=row.path;if(event.button===Qt.RightButton){root.contextEntry={path:row.path,directory:row.directory};menu.popup()}else root.toggle(row)}
                }
            }
            Text {anchors.centerIn:parent;visible:list.count===0 && !root.loading && !root.error;text:"当前目录为空";color:root.c.muted;font.pixelSize:12*root.sdk.scale}
        }
        Text {visible:root.clipped;Layout.fillWidth:true;Layout.margins:10;wrapMode:Text.Wrap;text:"目录条目较多，已限制单层及总预览数量。刷新可重新加载。";color:root.c.muted;font.pixelSize:10*root.sdk.scale}
        Text {Layout.fillWidth:true;Layout.margins:10;elide:Text.ElideMiddle;text:root.sdk.session.workspace || "未选择工作目录";textFormat:Text.PlainText;color:root.c.muted;font.pixelSize:10*root.sdk.scale}
    }
    Menu {
        id:menu
        MenuItem {text:"预览文件";enabled:!root.contextEntry.directory;onTriggered:root.call("preview",{path:root.contextEntry.path})}
        MenuItem {text:"附加到当前聊天";enabled:!root.contextEntry.directory;onTriggered:root.call("attach",{path:root.contextEntry.path})}
        MenuItem {text:"复制文件路径";onTriggered:root.call("copyPath",{path:root.contextEntry.path},"copyPath")}
    }
}
