import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Umeko.Text 1.0
Rectangle {
    id:root
    objectName:"gitViewerPluginPage"
    required property var sdk
    readonly property var c:sdk.colors
    color:c.surface
    property var requests:({})
    property var changes:[]
    property var commits:[]
    property string branch:""
    property string error:""
    property string diff:""
    property string diffPath:""
    property bool truncated:false
    property int loading:0
    property int tab:0
    readonly property int stagedCount:changes.filter(x=>x.group==="staged").length
    function call(method,args,kind){const token=sdk.call(method,args || {});if(!token){error="插件暂时繁忙，请稍后重试";return}const pending=Object.assign({},requests);pending[token]={kind:kind || method};requests=pending;loading++}
    function refresh(){error="";call("status",{});if(tab===1)call("history",{})}
    function rebuild(){rows.clear();const titles={staged:"暂存的更改",changes:"更改",untracked:"未跟踪"};for(const group of ["staged","changes","untracked"]){const items=changes.filter(x=>x.group===group);if(items.length){rows.append({header:true,name:titles[group],path:"",directory:"",group:group,status:String(items.length)});for(const item of items)rows.append({header:false,name:item.name,path:item.path,directory:item.directory==="."?"":item.directory,group:group,status:item.status})}}}
    Component.onCompleted:refresh()
    Connections {target:root.sdk;function onResponse(token,value){
        const request=root.requests[token];if(!request)return;const pending=Object.assign({},root.requests);delete pending[token];root.requests=pending;root.loading=Math.max(0,root.loading-1)
        if(!value.ok){root.error=value.error || "Git 操作失败";return}const result=value.result || {}
        if(request.kind==="status"){root.changes=result.entries || [];root.branch=result.branch || "HEAD";root.truncated=!!result.truncated;root.rebuild()}
        else if(request.kind==="history")root.commits=result.entries || []
        else if(request.kind==="diff"){root.diff=result.text || "";root.truncated=!!result.truncated}
        else if(["stage","unstage","commit"].includes(request.kind)){if(request.kind==="commit")message.clear();root.diff="";root.diffPath="";root.refresh()}
    }}
    ListModel {id:rows}
    ColumnLayout {
        anchors.fill:parent;spacing:0
        RowLayout {
            Layout.fillWidth:true;Layout.margins:10
            Text {text:"源代码管理";color:root.c.muted;font.pixelSize:11*root.sdk.scale;Layout.fillWidth:true}
            Text {text:"⑂ "+root.branch;color:root.c.accent;font.pixelSize:11*root.sdk.scale;elide:Text.ElideRight;Layout.maximumWidth:180}
            ToolButton { implicitWidth:28*root.sdk.scale;implicitHeight:26*root.sdk.scale;palette.buttonText:root.c.ink;background:Rectangle {radius:4;color:parent.hovered?root.c.hover:"transparent"} objectName:"gitViewerRefresh";text:"↻";ToolTip.visible:hovered;ToolTip.text:"刷新";enabled:!root.loading;onClicked:root.refresh()}
        }
        RowLayout {Layout.fillWidth:true;Layout.leftMargin:12;Layout.rightMargin:12
            Button {font.pixelSize:12*root.sdk.scale;palette.buttonText:root.c.ink;background:Rectangle {radius:5;color:parent.checked?root.c.accentBg:parent.hovered?root.c.hover:"transparent"} text:"更改";flat:true;checked:root.tab===0;checkable:true;onClicked:root.tab=0}
            Button {font.pixelSize:12*root.sdk.scale;palette.buttonText:root.c.ink;background:Rectangle {radius:5;color:parent.checked?root.c.accentBg:parent.hovered?root.c.hover:"transparent"} text:"提交历史";flat:true;checked:root.tab===1;checkable:true;onClicked:{root.tab=1;root.call("history",{})}}
            Item {Layout.fillWidth:true}
        }
        ColumnLayout {
            visible:root.tab===0 && !root.diffPath;Layout.fillWidth:true;Layout.margins:12;spacing:8
            TextArea {id:message;objectName:"gitCommitMessage";Layout.fillWidth:true;Layout.preferredHeight:70*root.sdk.scale;placeholderText:"提交说明";selectByMouse:true;wrapMode:TextEdit.Wrap;onTextChanged: if (text.length>4000) text=text.slice(0,4000);color:root.c.ink;font.pixelSize:12*root.sdk.scale;background:Rectangle {color:root.c.bg;radius:5;border.color:root.c.line}}
            Button {font.pixelSize:12*root.sdk.scale;palette.buttonText:enabled?"white":root.c.muted;background:Rectangle {radius:5;color:parent.enabled?root.c.accent:root.c.hover} objectName:"gitCommitButton";text:"✓  提交暂存的更改";Layout.fillWidth:true;enabled:root.stagedCount>0 && message.text.trim().length>0 && !root.loading;onClicked:root.call("commit",{message:message.text})}
        }
        Text {visible:!!root.error;Layout.fillWidth:true;Layout.margins:12;text:root.error;textFormat:Text.PlainText;wrapMode:Text.Wrap;color:root.c.danger;font.pixelSize:11*root.sdk.scale}
        RowLayout {visible:!!root.diffPath;Layout.fillWidth:true;Layout.margins:8
            ToolButton { implicitWidth:28*root.sdk.scale;implicitHeight:26*root.sdk.scale;palette.buttonText:root.c.ink;background:Rectangle {radius:4;color:parent.hovered?root.c.hover:"transparent"} text:"‹";onClicked:{root.diffPath="";root.diff=""}}
            Text {text:root.diffPath;textFormat:Text.PlainText;color:root.c.ink;Layout.fillWidth:true;elide:Text.ElideMiddle;font.pixelSize:12*root.sdk.scale}
            ToolButton { implicitWidth:28*root.sdk.scale;implicitHeight:26*root.sdk.scale;palette.buttonText:root.c.ink;background:Rectangle {radius:4;color:parent.hovered?root.c.hover:"transparent"} text:"⧉";ToolTip.text:"复制差异";ToolTip.visible:hovered;onClicked:root.sdk.copyText(root.diff)}
        }
        ScrollView {
            id:diffScroll;visible:!!root.diffPath;Layout.fillWidth:true;Layout.fillHeight:true;clip:true;contentWidth:availableWidth
            TextArea {id:diffText;objectName:"gitDiffText";width:diffScroll.availableWidth;text:root.diff;readOnly:true;selectByMouse:true;textFormat:TextEdit.PlainText;wrapMode:TextEdit.WrapAnywhere;font.family:"monospace";font.pixelSize:11*root.sdk.scale;color:root.c.ink;background:null;leftPadding:12;rightPadding:12
                SyntaxHighlighter {document:diffText.textDocument;language:"diff";dark:root.c.dark;enabled:root.diff.length<=24000 && root.diff.split("\n").length<=500}
            }
        }
        ListView {
            id:files;objectName:"gitChangesList";visible:root.tab===0 && !root.diffPath;Layout.fillWidth:true;Layout.fillHeight:true;model:rows;clip:true;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar{}
            delegate:Rectangle {
                id:row
                objectName:"gitChange_"+group+"_"+path
                required property bool header
                required property string name
                required property string path
                required property string directory
                required property string group
                required property string status
                width:files.width;height:29*root.sdk.scale;color:header?root.c.hover:mouse.containsMouse?root.c.hover:"transparent"
                RowLayout {
                    anchors.fill:parent;anchors.leftMargin:12;anchors.rightMargin:10;spacing:7
                    Text {text:row.header?"⌄":"≡";color:root.c.muted;font.pixelSize:12*root.sdk.scale}
                    Text {text:row.name;textFormat:Text.PlainText;color:row.status==="D"?root.c.danger:root.c.ink;font.strikeout:!row.header&&row.status==="D";font.weight:row.header?Font.DemiBold:Font.Normal;font.pixelSize:12*root.sdk.scale;elide:Text.ElideRight;Layout.maximumWidth:row.header?100000:160}
                    Text {text:row.directory;textFormat:Text.PlainText;color:root.c.muted;font.pixelSize:10*root.sdk.scale;Layout.fillWidth:true;elide:Text.ElideMiddle}
                    ToolButton { implicitWidth:28*root.sdk.scale;implicitHeight:26*root.sdk.scale;palette.buttonText:root.c.ink;background:Rectangle {radius:4;color:parent.hovered?root.c.hover:"transparent"} objectName:"gitStage_"+row.path;text:row.group==="staged"?"−":"+";visible:!row.header;enabled:!root.loading;ToolTip.text:row.group==="staged"?"取消暂存":"暂存文件";ToolTip.visible:hovered;onClicked:root.call(row.group==="staged"?"unstage":"stage",{path:row.path})}
                    Text {text:row.status;color:row.header?root.c.muted:row.status==="U"?"#73a66b":root.c.accent;font.pixelSize:11*root.sdk.scale;horizontalAlignment:Text.AlignHCenter;Layout.preferredWidth:22}
                }
                MouseArea {id:mouse;anchors.fill:parent;acceptedButtons:Qt.LeftButton;hoverEnabled:true;z:-1;onClicked:if(!row.header){root.diffPath=row.path;root.diff="";root.call("diff",{path:row.path,group:row.group})}}
            }
            Text {anchors.centerIn:parent;visible:files.count===0 && !root.loading && !root.error;text:"✓  工作区干净";color:root.c.muted;font.pixelSize:12*root.sdk.scale}
        }
        ListView {
            id:history;objectName:"gitHistoryList";visible:root.tab===1 && !root.diffPath;Layout.fillWidth:true;Layout.fillHeight:true;model:root.commits;clip:true;ScrollBar.vertical:ScrollBar{}
            delegate:Item {required property var modelData;width:history.width;height:59*root.sdk.scale
                Column {anchors.fill:parent;anchors.margins:12;spacing:5
                    Text {width:parent.width;text:"●  "+modelData.subject;textFormat:Text.PlainText;elide:Text.ElideRight;color:root.c.ink;font.pixelSize:12*root.sdk.scale}
                    Text {text:modelData.hash+"   "+modelData.date;color:root.c.muted;font.family:"monospace";font.pixelSize:10*root.sdk.scale}
                }
            }
        }
        Text {visible:root.truncated;Layout.fillWidth:true;Layout.margins:10;text:"内容较多，已限制预览大小。";color:root.c.muted;font.pixelSize:10*root.sdk.scale}
        Text {Layout.fillWidth:true;Layout.margins:10;text:root.sdk.session.workspace || "未选择工作目录";textFormat:Text.PlainText;color:root.c.muted;elide:Text.ElideMiddle;font.pixelSize:10*root.sdk.scale}
    }
}
