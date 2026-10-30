import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Popup {
    id: root
    objectName: "gitBranchPicker"
    required property var sdk
    property var entries: []
    property string mode: "checkout"
    property string source: "HEAD"
    readonly property var c: sdk.colors
    readonly property real s: sdk.scale
    signal referencesRequested()
    signal operation(string method,var arguments)
    readonly property var choices: {
        const query=search.text.trim().toLowerCase()
        const actions=mode==="checkout"?[{kind:"action",action:"create",name:"新建分支…",icon:"add"},{kind:"action",action:"createFrom",name:"从指定引用新建分支…",icon:"add"},{kind:"action",action:"detach",name:"以游离 HEAD 检出…",icon:"debug-disconnect"}]:[]
        return actions.filter(row=>!query||row.name.toLowerCase().includes(query)).concat(entries.filter(row=>(row.name+" "+row.hash+" "+row.subject).toLowerCase().includes(query)))
    }
    function age(timestamp) {const days=Math.floor((Date.now()/1000-Number(timestamp))/86400);return days<1?"今天":days<7?days+" 天前":days<30?Math.floor(days/7)+" 周前":Math.floor(days/30)+" 个月前"}
    function choose(row) {
        if(!row)return
        if(row.kind==="action") {
            if(row.action==="create"){source="HEAD";nameField.clear();close();createDialog.open()}
            else {mode=row.action;search.clear();list.currentIndex=0}
        } else if(mode==="createFrom"){source=row.ref;nameField.clear();close();createDialog.open()}
        else {close();operation("checkout",{ref:row.ref,detached:mode==="detach"})}
    }
    width:Math.max(1,parent.width-16)
    height:Math.max(1,Math.min(480*s,parent.height-16,(38+choices.reduce((total,row)=>total+(row.kind==="action"?25:45),0))*s+12))
    x:8;y:8;padding:6
    modal:false;focus:true;closePolicy:Popup.CloseOnEscape|Popup.CloseOnPressOutside
    background:Rectangle {color:root.c.surface;radius:6;border.color:root.c.line}
    onOpened:{mode="checkout";search.clear();list.currentIndex=0;referencesRequested();search.forceActiveFocus()}
    contentItem:ColumnLayout {
        spacing:5
        TextField {
            id:search;objectName:"gitBranchSearch";Layout.fillWidth:true;implicitHeight:28*root.s
            placeholderText:root.mode==="createFrom"?"选择新分支的起点":root.mode==="detach"?"选择引用或输入提交 ID":"搜索分支、远程分支或标签"
            color:root.c.ink;placeholderTextColor:root.c.muted;selectByMouse:true;font.family:"Segoe UI";font.pixelSize:13*root.s
            background:Rectangle {radius:3;color:root.c.bg;border.color:root.c.accent}
            onTextChanged:list.currentIndex=0
            Keys.onDownPressed:list.currentIndex=Math.min(list.count-1,list.currentIndex+1)
            Keys.onUpPressed:list.currentIndex=Math.max(0,list.currentIndex-1)
            onAccepted:{if(root.mode==="detach" && /^[a-fA-F0-9]{7,40}$/.test(text.trim())){root.close();root.operation("checkout",{ref:text.trim(),detached:true})}else root.choose(root.choices[list.currentIndex])}
        }
        ListView {
            id:list;objectName:"gitBranchList";Layout.fillWidth:true;Layout.fillHeight:true;clip:true;model:root.choices
            boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar {policy:ScrollBar.AsNeeded}
            delegate:ItemDelegate {
                id:row;required property var modelData;required property int index
                objectName:modelData.kind==="action"?"gitBranchAction_"+modelData.action:"gitBranchRef_"+modelData.ref
                width:list.width;height:(modelData.kind==="action"?25:45)*root.s;padding:5*root.s
                background:Rectangle {radius:3;color:list.currentIndex===row.index?root.c.accentBg:row.hovered?root.c.hover:"transparent"}
                contentItem:ColumnLayout {
                    spacing:1
                    RowLayout {
                        Layout.fillWidth:true;spacing:6*root.s
                        VsIcon {name:row.modelData.kind==="action"?row.modelData.icon:row.modelData.kind==="branch"?"git-branch":row.modelData.kind==="tag"?"tag":"cloud";size:16*root.s;color:root.c.muted}
                        Text {text:row.modelData.name;textFormat:Text.PlainText;color:root.c.ink;font.pixelSize:13*root.s;font.family:"Segoe UI";Layout.fillWidth:true;elide:Text.ElideRight}
                        Text {visible:row.modelData.kind!=="action";text:root.age(row.modelData.timestamp||0);color:root.c.muted;font.pixelSize:11*root.s}
                        Text {text:({branch:"分支",remote:"远程分支",tag:"标签"})[row.modelData.kind]||"";color:root.c.muted;font.pixelSize:11*root.s}
                    }
                    Text {visible:row.modelData.kind!=="action";text:(row.modelData.author||"")+" · "+(row.modelData.hash||"")+" · "+(row.modelData.subject||"");textFormat:Text.PlainText;color:root.c.muted;font.pixelSize:12*root.s;font.family:"Segoe UI";Layout.fillWidth:true;Layout.leftMargin:22*root.s;elide:Text.ElideRight}
                }
                onClicked:root.choose(modelData)
            }
        }
    }
    Dialog {
        id:createDialog;objectName:"gitCreateBranchDialog";parent:root.parent;anchors.centerIn:parent
        width:Math.min(440*root.s,parent.width-24);modal:false;focus:true;title:"新建分支";palette.window:root.c.surface;palette.windowText:root.c.ink
        onOpened:nameField.forceActiveFocus()
        contentItem:TextField {id:nameField;objectName:"gitNewBranchName";placeholderText:"输入分支名称";selectByMouse:true;color:root.c.ink;font.pixelSize:13*root.s;onAccepted:if(text.trim()){createDialog.close();root.operation("createBranch",{name:text.trim(),ref:root.source})}}
        footer:RowLayout {Item {Layout.fillWidth:true}Button {text:"取消";onClicked:createDialog.close()}Button {objectName:"gitCreateBranchConfirm";text:"创建";enabled:!!nameField.text.trim();onClicked:{createDialog.close();root.operation("createBranch",{name:nameField.text.trim(),ref:root.source})}}}
    }
}
