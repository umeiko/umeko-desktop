import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../app/qml" as Umeko
import "../../file-tree/qml" as FileTree

FocusScope {
    id: root
    objectName: "skillManagerWidget"
    required property var sdk
    clip: true
    focus: true
    property bool initialized: false
    property var skills: []
    property var roots: ({})
    property var collapsedScopes: []
    property string query: ""
    property string route: "main"
    property string selectedId: ""
    property string selectedScope: "project"
    property var contextRow: null
    property bool menuOpen: false
    property real menuX: 0
    property real menuY: 0
    property var renameRow: null
    property string notice: ""
    property bool noticeError: false
    property string importFailure: ""
    property string dragScope: ""
    property var listPosition: null
    property var pending: ({})
    property string job: ""
    property string jobOperation: ""
    property bool polling: false
    property int pageOffset: 0
    property var pageRows: []
    property bool importProject: true
    property var importPreview: ({})
    property var importDecisions: ({})
    property var importResult: ({})
    property var preview: ({})
    property var previewCache: ({})
    property var previewOrder: []
    property string previewError: ""
    property string previewRequest: ""
    property string previewJob: ""
    property string previewSkill: ""
    property int previewGeneration: 0
    property int requestedGeneration: 0
    readonly property bool working: !!job || Object.keys(pending).length > 0
    readonly property bool sessionBusy: !!(sdk.session && sdk.session.busy)
    readonly property real rowHeight: 56 * sdk.scale
    readonly property var selected: skills.filter(row => row.id === selectedId)[0] || null
    readonly property var entries: folderEntries()
    readonly property bool importReady: !!importPreview.id && !(importPreview.errors || []).length
        && (importPreview.skills || []).some(row => !row.error && importDecisions[row.name] !== "skip" && (!row.conflict || row.replaceable))
    function t(zh,en) {return sdk.language.indexOf("zh")===0 ? zh : en}
    function scopeLabel(scope) {return scope==="project" ? t("工作区","Workspace") : t("全局","Global")}
    function description(row){return row ? (row.descriptions || {})[sdk.language] || row.description || "" : ""}
    function loadPreview() {
        if(!selected || !sdk.active)return
        if(previewCache[selectedId]){preview=previewCache[selectedId];previewError="";return}
        if(previewRequest || previewJob)return
        if(!sdk.hostCapabilities.operations["skills.preview"])return
        previewSkill=selectedId;requestedGeneration=previewGeneration
        previewRequest=sdk.requestHost("skills.preview",{id:selectedId})
    }
    function previewResponse(value) {
        previewRequest=""
        if(value.jobId){previewJob=value.jobId;previewPollSoon.restart();return}
        const item=(value.jobs || [])[0]
        if(item && item.status==="running")return
        previewJob=""
        if(requestedGeneration===previewGeneration){
            const result=item ? item.result || {} : value
            if(value.ok===false || (item && item.status!=="completed") || result.ok===false){
                if(previewSkill===selectedId)previewError=errorText(result.error || value.error || t("无法读取 Skill。","Could not read the Skill."))
            } else {
                const details=result.details || {}
                let cache=Object.assign({},previewCache);cache[previewSkill]=details
                let order=previewOrder.filter(id=>id!==previewSkill);order.push(previewSkill)
                while(order.length>8)delete cache[order.shift()]
                previewCache=cache;previewOrder=order
                if(previewSkill===selectedId){preview=details;previewError=""}
            }
        }
        if(previewSkill!==selectedId || requestedGeneration!==previewGeneration)previewDelay.restart()
    }
    onSelectedIdChanged:{previewError="";previewDelay.restart()}
    Timer {
        id:previewPollSoon;interval:0;repeat:false
        onTriggered:if(root.sdk.active && root.previewJob && !root.previewRequest)
            root.previewRequest=root.sdk.requestHost("skills.job",{id:root.previewJob,wait:true})
    }
    Timer{id:previewDelay;interval:80;onTriggered:root.loadPreview()}
    Timer{interval:80;repeat:true;running:root.sdk.active && !!root.previewJob;onTriggered:if(!root.previewRequest)root.previewRequest=root.sdk.requestHost("skills.job",{id:root.previewJob})}
    function folderEntries() {
        let result=[]
        for(const scope of ["project","global"]) {
            const rows=skills.filter(row=>row.scope===scope && (row.name+" "+description(row)+" "+(row.description || "")).toLowerCase().indexOf(query.toLowerCase())>=0)
                .sort((a,b)=>a.name.localeCompare(b.name) || a.id.localeCompare(b.id))
            result.push({kind:"scope",scope:scope,count:rows.length})
            if(collapsedScopes.indexOf(scope)>=0)continue
            if(!rows.length)result.push({kind:"empty",scope:scope})
            for(const row of rows)result.push({kind:"skill",scope:scope,skill:row})
        }
        return result
    }
    function collapse(scope) {
        let next=collapsedScopes.slice();const index=next.indexOf(scope)
        if(index<0)next.push(scope);else next.splice(index,1)
        collapsedScopes=next;selectedScope=scope
    }
    function request(operation,args) {
        if(!sdk.active || (working && operation!=="skills.job"))return false
        if(!sdk.hostCapabilities || !sdk.hostCapabilities.operations[operation]) {
            fail(operation,t("此操作需要更新版本的 Umeko。","This operation needs a newer Umeko version."));return false
        }
        const id=sdk.requestHost(operation,args || {})
        if(!id){fail(operation,t("请稍后重试。","Please retry shortly."));return false}
        let next=Object.assign({},pending);next[id]={operation:operation};pending=next
        return true
    }
    function reload(keepPosition){if(keepPosition)listPosition={y:list.contentY,index:list.currentIndex,scope:selectedScope};previewGeneration++;previewCache={};previewOrder=[];preview={};previewError="";notice="";noticeError=false;menuOpen=false;request("skills.browse",{})}
    function initialize(){if(sdk.active && !initialized){initialized=true;reload()}}
    function setEnabled(row,enabled){if(row && !working && !sessionBusy)request("skills.attach",{id:row.id,enabled:enabled})}
    function pollJob(){if(sdk.active && job && !polling){polling=true;if(!request("skills.job",{id:job,offset:pageOffset,limit:100,wait:true}))polling=false}}
    function insert(row){if(row)request("skills.insert",{id:row.id})}
    function showMenu(row,scope,point){if(working)return;contextRow=row;selectedScope=scope;if(row)selectedId=row.id;menuX=point.x;menuY=point.y;menuOpen=true}
    function action(name) {
        const row=contextRow;menuOpen=false
        if(name==="paste"){paste(selectedScope);return}
        if(!row)return
        if(name==="rename"){renameRow=row;renameName.text=row.folderName || row.name;renameName.forceActiveFocus();renameName.selectAll();return}
        if(name==="insert")insert(row)
        else if(name==="delete")request("skills.delete",{id:row.id})
        else if(name==="copy" || name==="copyPath")request("skills.copy",{id:row.id,kind:name==="copy" ? "folder" : "path"})
        else request("skills.open",{id:row.id,mode:name})
    }
    function currentEntry(){return entries[list.currentIndex]}
    function clearImportPreview(){importPreview={};importDecisions={};importResult={}}
    function localImportSource(source) {
        const value=String(source).trim()
        if(!value)return false
        if(/^file:/i.test(value))return /^file:\/\/(?:\/|localhost\/)/i.test(value)
        return !/^[a-z][a-z0-9+.-]*:/i.test(value) || /^[a-z]:[\\/]/.test(value)
    }
    function acceptsImportUrls(urls){return urls && urls.length===1 && /^file:/i.test(String(urls[0])) && localImportSource(urls[0])}
    function directImport(operation){return operation==="skills.paste" || operation==="skills.importLocal"}
    function fail(operation,message) {
        if(directImport(operation)){notice="";noticeError=false;menuOpen=false;importFailure=errorText(message)}
        else {notice=errorText(message);noticeError=true}
    }
    function validScope(scope){return (scope==="project" || scope==="global") && !!roots[scope]}
    function paste(scope) {
        if(working || importFailure)return false
        if(!validScope(scope)){fail("skills.paste",t("请先选择工作区。","Select a workspace first."));return false}
        notice="";menuOpen=false
        return request("skills.paste",{project:scope==="project"})
    }
    function dropScope(x,y) {
        if(route!=="main" || importFailure)return ""
        const point=list.mapFromItem(root,x,y)
        if(point.x<0 || point.x>=list.width || point.y<0 || point.y>=list.height)return ""
        const index=list.indexAt(point.x+list.contentX,point.y+list.contentY)
        if(index>=0)return entries[index].scope
        // Blank space below the last row belongs to the last section, never
        // to the previously selected section (including collapsed sections).
        return point.y+list.contentY>=list.contentHeight && entries.length ? entries[entries.length-1].scope : ""
    }
    function dropLocalUrls(urls,scope) {
        if(working || importFailure || !acceptsImportUrls(urls) || !scope)return false
        if(!validScope(scope)){fail("skills.importLocal",t("请先选择工作区。","Select a workspace first."));return false}
        notice="";menuOpen=false
        return request("skills.importLocal",{source:String(urls[0]),project:scope==="project"})
    }
    function openImport(){importProject=selectedScope==="project" && !!roots.project;route="import";clearImportPreview();importSource.text="";notice="";menuOpen=false}
    function previewImport() {
        if(working)return
        clearImportPreview();notice="";noticeError=false
        if(!localImportSource(importSource.text)){notice=t("请选择本地 Skill 文件夹、ZIP 或 .skill 文件。","Choose a local Skill folder, ZIP or .skill file.");noticeError=true;return}
        request("skills.importPreview",{source:importSource.text.trim(),project:importProject})
    }
    function decideImport(name,choice){let next=Object.assign({},importDecisions);next[name]=choice;importDecisions=next}
    function submitImport(){if(importReady)request("skills.import",{id:importPreview.id,decisions:importDecisions})}
    function errorText(value) {
        const message=String(value || "")
        if(sdk.language.indexOf("zh")===0 || !/[\u3400-\u9fff]/.test(message))return message
        return "The operation failed. Check the selected folder and retry."
    }
    function complete(operation,result,success) {
        if(directImport(operation)) {
            const errors=result.errors || []
            if(!success || result.ok===false || errors.length)fail(operation,result.error || (errors.length ? errors.map(row=>(row.name || "")+": "+row.error).join("\n") : t("导入失败，请重试。","Import failed; retry.")))
            // Keep the directory view, search and fold state. Also refresh on
            // partial write errors so any completed folders are reflected.
            reload(true)
            return
        }
        noticeError=!success || result.ok===false
        notice=errorText(result.error || (noticeError ? t("操作失败，请重试。","Operation failed; retry.") : ""))
        if(noticeError)return
        if(operation==="skills.browse") {
            skills=result.skills || [];roots=result.roots || {};if(!roots.project)selectedScope="global"
            if(!selected)selectedId=skills.length ? skills[0].id : ""
            previewDelay.restart()
            if(listPosition){const position=listPosition;listPosition=null;Qt.callLater(()=>{list.currentIndex=Math.max(0,Math.min(position.index,entries.length-1));list.contentY=Math.max(0,Math.min(position.y,list.contentHeight-list.height));selectedScope=position.scope})}
            else Qt.callLater(()=>{const index=entries.findIndex(entry=>entry.skill && entry.skill.id===selectedId);if(index>=0){list.currentIndex=index;list.positionViewAtIndex(index,ListView.Contain)}})
            if(result.stateError){notice=root.errorText(result.stateError);noticeError=true}
            if(result.truncated)notice=t("目录较大，仅显示部分 Skill；可在文件管理器中继续查看。","This folder is large; some Skills are omitted. Open it in your file manager to see all items.")
        } else if(operation==="skills.importPreview") {
            importPreview=result.preview || {};let choices={}
            for(const row of importPreview.skills || [])choices[row.name]=row.conflict || row.error ? "skip" : "replace"
            importDecisions=choices
        } else if(operation==="skills.import") {
            importResult=result;importPreview={};importDecisions={}
            notice=t("已导入 ","Imported ")+(result.imported || []).length+t(" 项，跳过 ","; skipped ")+(result.skipped || []).length
            noticeError=!!(result.errors || []).length
        } else if(operation==="skills.attach"){
            skills=skills.map(row=>row.path===result.path ? Object.assign({},row,{enabled:result.enabled}) : row)
        }
        else if(operation==="skills.rename" || operation==="skills.delete"){renameRow=null;reload()}
        else if(operation==="skills.insert")notice=t("已附加到输入框","Attached to the composer")
        else if(operation==="skills.copy")notice=t("已复制","Copied")
    }
    Component.onCompleted:initialize()
    Keys.onPressed:event=>{
        if((event.modifiers & Qt.ControlModifier) && event.key===Qt.Key_F){search.forceActiveFocus();search.selectAll();event.accepted=true}
        else if(event.key===Qt.Key_Escape){menuOpen=false;renameRow=null;if(importFailure)importFailure="";else if(!working && route!=="main"){route="main";reload()}event.accepted=true}
    }
    Rectangle{anchors.fill:parent;color:root.sdk.colors.surface;z:-1}
    component Label:Text{color:root.sdk.colors.ink;font.family:Umeko.Theme.fontFamily;font.pixelSize:Umeko.Theme.font(12);textFormat:Text.PlainText;elide:Text.ElideRight;verticalAlignment:Text.AlignVCenter}
    component SmallButton:Button {
        id:button
        property bool selected:false
        font.family:Umeko.Theme.fontFamily
        implicitHeight:28*root.sdk.scale;implicitWidth:Math.max(28*root.sdk.scale,label.implicitWidth+18*root.sdk.scale)
        background:Rectangle{radius:5*root.sdk.scale;color:button.selected ? root.sdk.colors.accentBg : button.hovered ? root.sdk.colors.hover : "transparent";border.color:button.selected ? root.sdk.colors.accent : root.sdk.colors.line}
        contentItem:Label{id:label;text:button.text;font.pixelSize:Umeko.Theme.font(11);horizontalAlignment:Text.AlignHCenter;color:button.enabled ? root.sdk.colors.ink : root.sdk.colors.muted}
    }
    component Input:TextField {
        selectByMouse:true;color:root.sdk.colors.ink;font.family:Umeko.Theme.fontFamily;font.pixelSize:Umeko.Theme.font(12)
        implicitHeight:34*root.sdk.scale;placeholderTextColor:root.sdk.colors.muted
        background:Rectangle{radius:5*root.sdk.scale;color:root.sdk.colors.surface;border.color:parent.activeFocus ? root.sdk.colors.accent : root.sdk.colors.line}
    }
    ColumnLayout {
        anchors.fill:parent;anchors.margins:12*root.sdk.scale;spacing:9*root.sdk.scale;enabled:!root.importFailure
        RowLayout {
            Layout.fillWidth:true
            SmallButton{objectName:"skillManagerBack";visible:root.route!=="main";text:"‹";enabled:!root.working;onClicked:{root.route="main";root.clearImportPreview();root.reload()} Accessible.name:root.t("返回","Back")}
            Image{source:"../assets/skill-package.svg";sourceSize.width:22;sourceSize.height:22;Layout.preferredWidth:22*root.sdk.scale;Layout.preferredHeight:22*root.sdk.scale}
            Label{text:root.route==="main" ? "Skills" : root.t("导入 Skill","Import Skill");font.bold:true;font.pixelSize:Umeko.Theme.font(16);Layout.fillWidth:true}
            Umeko.HelpButton {
                objectName:"skillManagerDiscoveryHelp"
                help:root.t("启用后，全局和当前工作区中可用 Skill 的名称、简介和路径会自动提供给智能体；任务匹配时才读取正文和附带资料，无需先双击。每个 Skill 行尾的复选框单独控制当前会话是否启用，自动保存，不修改全局或工作区的 Pi 默认配置。双击只把文件夹附加到输入框。停用此 Widget 会关闭相应范围的技能发现与加载；重新启用后恢复原配置。收起面板不影响启用状态。运行中的任务在本轮结束后应用开关。",
                    "When enabled, available Skills in Global and the current workspace are advertised to the agent by name, description and path. Instructions and references are read only when needed; no double-click is required. Each checkbox controls availability in this chat and saves automatically, without changing Pi defaults. Double-click only attaches the folder to the composer. Disabling this Widget turns off skill discovery and loading in that scope; enabling it restores the existing configuration. Closing the panel does not disable Skills. Running tasks apply the change after their current turn.")
            }
            SmallButton{objectName:"skillManagerImport";visible:root.route==="main";text:root.t("导入","Import");enabled:!root.working;onClicked:root.openImport()}
            SmallButton{objectName:"skillManagerRefresh";visible:root.route==="main";text:"↻";enabled:!root.working;onClicked:root.reload();Accessible.name:root.t("刷新","Refresh")}
        }
        Label{objectName:"skillManagerNotice";Layout.fillWidth:true;visible:text!=="";text:root.notice;wrapMode:Text.Wrap;maximumLineCount:3;color:root.noticeError ? root.sdk.colors.danger : root.sdk.colors.muted;font.pixelSize:Umeko.Theme.font(10)}
        ProgressBar{visible:root.working;Layout.fillWidth:true;indeterminate:true}
        ColumnLayout {
            visible:root.route==="main";Layout.fillWidth:true;Layout.fillHeight:true;spacing:8*root.sdk.scale
            Input{id:search;objectName:"skillManagerSearch";Layout.fillWidth:true;placeholderText:root.t("搜索 Skill…","Find Skills…");onTextChanged:root.query=text}
            SplitView {
                id:skillSplit;objectName:"skillManagerSplit";orientation:Qt.Vertical
                Layout.fillWidth:true;Layout.fillHeight:true
                handle:Rectangle {
                    objectName:"skillManagerSplitHandle";implicitHeight:10*(root.sdk ? root.sdk.scale : 1);color:"transparent"
                    Rectangle{anchors.centerIn:parent;width:42*(root.sdk ? root.sdk.scale : 1);height:3;radius:2;color:!root.sdk ? "transparent" : SplitHandle.hovered || SplitHandle.pressed ? root.sdk.colors.accent : root.sdk.colors.line}
                    HoverHandler{cursorShape:Qt.SplitVCursor}
                }
            ListView {
                id:list;objectName:"skillManagerList";SplitView.fillHeight:true;SplitView.preferredHeight:skillSplit.height*.52;SplitView.minimumHeight:Math.min(100*root.sdk.scale,skillSplit.height*.25);clip:true;reuseItems:true;spacing:0
                model:root.entries;currentIndex:0;boundsBehavior:Flickable.StopAtBounds
                ScrollBar.vertical:ScrollBar{policy:ScrollBar.AsNeeded}
                DropArea {
                    parent:list;anchors.fill:parent
                    function scopeAt(drag){const point=mapToItem(root,drag.x,drag.y);return root.dropScope(point.x,point.y)}
                    onEntered:drag=>{root.dragScope=scopeAt(drag);drag.accepted=!root.working && root.acceptsImportUrls(drag.urls) && !!root.dragScope}
                    onPositionChanged:drag=>{root.dragScope=scopeAt(drag);drag.accepted=!root.working && root.acceptsImportUrls(drag.urls) && !!root.dragScope}
                    onExited:root.dragScope=""
                    onDropped:drop=>{drop.accepted=root.dropLocalUrls(drop.urls,scopeAt(drop));root.dragScope=""}
                }
                Keys.onPressed:event=>{
                    const entry=root.currentEntry(),row=entry && entry.skill
                    if((event.key===Qt.Key_Return || event.key===Qt.Key_Enter) && row){root.insert(row);event.accepted=true}
                    else if(event.key===Qt.Key_F2 && row){root.contextRow=row;root.action("rename");event.accepted=true}
                    else if(event.key===Qt.Key_Delete && row){root.contextRow=row;root.action("delete");event.accepted=true}
                    else if((event.modifiers & Qt.ControlModifier) && event.key===Qt.Key_C && row){root.contextRow=row;root.action("copy");event.accepted=true}
                    else if((event.modifiers & Qt.ControlModifier) && event.key===Qt.Key_V){root.paste(root.selectedScope);event.accepted=true}
                    else if(entry && entry.kind==="scope" && (event.key===Qt.Key_Left || event.key===Qt.Key_Right)){root.collapse(entry.scope);event.accepted=true}
                }
                onCurrentIndexChanged:{const entry=root.currentEntry();if(entry){root.selectedScope=entry.scope;if(entry.skill)root.selectedId=entry.skill.id}}
                delegate:Rectangle {
                    id:entry;required property var modelData;required property int index
                    readonly property bool skill:modelData.kind==="skill"
                    objectName:skill ? "skillManagerEntry_"+modelData.skill.id : modelData.kind==="scope" ? "skillManagerScope_"+modelData.scope : "skillManagerEmpty_"+modelData.scope
                    width:list.width;height:skill ? root.rowHeight : 22*root.sdk.scale
                    color:root.dragScope===modelData.scope || skill && root.selectedId===modelData.skill.id ? root.sdk.colors.accentBg : hover.hovered ? root.sdk.colors.hover : "transparent"
                    HoverHandler{id:hover}
                    MouseArea {
                        anchors.fill:parent;acceptedButtons:Qt.LeftButton | Qt.RightButton
                        onClicked:mouse=>{
                            list.currentIndex=entry.index;list.forceActiveFocus();root.selectedScope=entry.modelData.scope
                            if(mouse.button===Qt.RightButton){root.showMenu(entry.skill ? entry.modelData.skill : null,entry.modelData.scope,mapToItem(root,mouse.x,mouse.y));return}
                            root.menuOpen=false
                            if(entry.skill)root.selectedId=entry.modelData.skill.id
                            else if(entry.modelData.kind==="scope")root.collapse(entry.modelData.scope)
                        }
                        onDoubleClicked:mouse=>{if(mouse.button===Qt.LeftButton && entry.skill)root.insert(entry.modelData.skill)}
                    }
                    ToolTip.visible:entry.modelData.kind==="scope" && hover.hovered && !!root.roots[entry.modelData.scope]
                    ToolTip.delay:500
                    ToolTip.text:root.roots[entry.modelData.scope] || ""
                    RowLayout {
                        anchors.fill:parent;anchors.leftMargin:entry.skill ? 22*root.sdk.scale : 3*root.sdk.scale;anchors.rightMargin:6*root.sdk.scale;spacing:4*root.sdk.scale
                        FileTree.VsIcon {
                            objectName:entry.modelData.kind==="scope" ? "skillManagerChevron_"+entry.modelData.scope : ""
                            visible:entry.modelData.kind==="scope";Layout.preferredWidth:16*root.sdk.scale;Layout.preferredHeight:16*root.sdk.scale
                            name:root.collapsedScopes.indexOf(entry.modelData.scope)>=0 ? "chevron-right" : "chevron-down"
                            size:16*root.sdk.scale;color:root.sdk.colors.ink
                        }
                        Image{visible:entry.skill;source:"../assets/skill-package.svg";sourceSize.width:16;sourceSize.height:16;Layout.preferredWidth:16*root.sdk.scale;Layout.preferredHeight:16*root.sdk.scale}
                        ColumnLayout {
                            Layout.fillWidth:entry.modelData.kind!=="scope";spacing:2*root.sdk.scale
                            Label {
                                Layout.fillWidth:entry.modelData.kind!=="scope";Layout.preferredWidth:entry.modelData.kind==="scope" ? implicitWidth : -1
                                text:entry.skill ? entry.modelData.skill.name : entry.modelData.kind==="scope" ? root.scopeLabel(entry.modelData.scope) : !root.roots[entry.modelData.scope] ? root.t("未选择工作区","No workspace selected") : root.query ? root.t("没有匹配的 Skill","No matching Skills") : root.t("暂无 Skill","No Skills")
                                font.weight:entry.modelData.kind==="scope" ? Font.DemiBold : Font.Normal;font.pixelSize:Umeko.Theme.font(11);color:entry.modelData.kind==="empty" ? root.sdk.colors.muted : root.sdk.colors.ink
                            }
                            Label {
                                objectName:entry.skill ? "skillManagerDescription_"+entry.modelData.skill.id : ""
                                visible:entry.skill && !!text;Layout.fillWidth:true;text:root.description(entry.modelData.skill)
                                font.pixelSize:Umeko.Theme.font(10);color:root.sdk.colors.muted;wrapMode:Text.Wrap;maximumLineCount:2
                            }
                        }
                        Label{visible:entry.modelData.kind==="scope";text:entry.modelData.count === undefined ? "" : entry.modelData.count;color:root.sdk.colors.muted;font.pixelSize:Umeko.Theme.font(10);leftPadding:2*root.sdk.scale}
                        Item{visible:entry.modelData.kind==="scope";Layout.fillWidth:true}
                        CheckBox {
                            id:skillEnabled;objectName:entry.skill ? "skillManagerEnabled_"+entry.modelData.skill.id : ""
                            visible:entry.skill;Layout.preferredWidth:20*root.sdk.scale;Layout.preferredHeight:22*root.sdk.scale
                            padding:0;spacing:0;checked:entry.skill && !!entry.modelData.skill.enabled
                            enabled:entry.skill && entry.modelData.skill.canToggle!==false && !root.working && !root.sessionBusy
                            indicator:Rectangle {width:15*root.sdk.scale;height:15*root.sdk.scale;x:(skillEnabled.width-width)/2;y:(skillEnabled.height-height)/2;radius:3*root.sdk.scale;color:skillEnabled.checked ? root.sdk.colors.accent : "transparent";border.color:skillEnabled.enabled ? skillEnabled.checked ? root.sdk.colors.accent : root.sdk.colors.muted : root.sdk.colors.line
                                Umeko.Glyph {anchors.centerIn:parent;name:"check";visible:skillEnabled.checked;color:root.sdk.colors.surface;width:13*root.sdk.scale;height:13*root.sdk.scale}
                            }
                            contentItem:Item {}
                            onClicked:{const next=checked;checked=Qt.binding(()=>entry.skill && !!entry.modelData.skill.enabled);root.setEnabled(entry.modelData.skill,next)}
                            Accessible.name:entry.skill ? root.t("启用 ","Enable ")+entry.modelData.skill.name : ""
                            ToolTip.visible:hovered;ToolTip.delay:450
                            ToolTip.text:root.sessionBusy ? root.t("任务结束后可调整","Available after the current task finishes") : entry.skill && entry.modelData.skill.canToggle===false ? root.t("当前不可用，请检查 Skill 格式或恢复模式后刷新。","Unavailable; check the Skill format or recovery mode and refresh.") : root.t("在当前会话中启用此 Skill","Enable this Skill in the current chat")
                            HoverHandler {cursorShape:skillEnabled.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor}
                        }
                    }
                }
            }
            Rectangle {
                objectName:"skillManagerPreviewPane";color:root.sdk.colors.surface;border.color:root.sdk.colors.line;radius:6
                SplitView.minimumHeight:Math.min(130*root.sdk.scale,skillSplit.height*.3);SplitView.preferredHeight:skillSplit.height*.48
                ColumnLayout {
                    anchors.fill:parent;anchors.margins:10*root.sdk.scale;spacing:6
                    RowLayout {
                        Layout.fillWidth:true
                        Label {Layout.fillWidth:true;font.bold:true;text:root.selected ? root.selected.name+" · SKILL.md" : root.t("Skill 预览","Skill preview")}
                        SmallButton {text:root.t("打开","Open");visible:!!root.selected;onClicked:root.request("skills.open",{id:root.selectedId,mode:"edit"})}
                    }
                    Label {Layout.fillWidth:true;visible:!!root.selected && !!text;text:root.description(root.selected);wrapMode:Text.Wrap;maximumLineCount:3;color:root.sdk.colors.muted;font.pixelSize:Umeko.Theme.font(10)}
                    ScrollView {
                        id:skillPreviewScroll;objectName:"skillManagerPreviewScroll";Layout.fillWidth:true;Layout.fillHeight:true;clip:true;contentWidth:availableWidth
                        Umeko.MessageBody {
                            objectName:"skillManagerPreviewMarkdown";width:skillPreviewScroll.availableWidth
                            text:root.preview.id===root.selectedId && !root.previewError ? (root.preview.markdown || "").replace(/^\uFEFF?---[^\S\n]*\r?\n[\s\S]*?\r?\n---[^\S\n]*\r?\n/,"") : ""
                            markdown:true
                            onTextChanged:if(skillPreviewScroll.contentItem)skillPreviewScroll.contentItem.contentY=0
                        }
                    }
                    Label {Layout.fillWidth:true;visible:!!text;text:root.previewError || (!root.selected ? root.t("选择一个 Skill 查看说明。","Select a Skill to read its instructions.") : root.preview.id!==root.selectedId ? root.t("正在读取…","Reading…") : root.preview.truncated ? root.t("预览已截断，可打开完整文件。","Preview truncated; open the full file to continue.") : "");wrapMode:Text.Wrap;color:root.previewError ? root.sdk.colors.danger : root.sdk.colors.muted;font.pixelSize:Umeko.Theme.font(10)}
                }
            }
            }
            RowLayout {
                objectName:"skillManagerRenameForm";visible:!!root.renameRow;Layout.fillWidth:true
                Input{id:renameName;objectName:"skillManagerRenameName";Layout.fillWidth:true;enabled:!root.working;onAccepted:if(root.renameRow)root.request("skills.rename",{id:root.renameRow.id,name:text})}
                SmallButton{objectName:"skillManagerRenameSave";text:root.t("重命名","Rename");enabled:!root.working && renameName.text.trim()!=="";onClicked:root.request("skills.rename",{id:root.renameRow.id,name:renameName.text})}
                SmallButton{text:root.t("取消","Cancel");enabled:!root.working;onClicked:root.renameRow=null}
            }
        }
        ColumnLayout {
            visible:root.route==="import";Layout.fillWidth:true;Layout.fillHeight:true;spacing:9*root.sdk.scale
            Label{Layout.fillWidth:true;text:root.t("输入本地文件夹、ZIP 或 .skill 路径。","Enter a local folder, ZIP or .skill path.");wrapMode:Text.Wrap;color:root.sdk.colors.muted;font.pixelSize:Umeko.Theme.font(11)}
            Input{id:importSource;objectName:"skillManagerImportSource";Layout.fillWidth:true;placeholderText:root.t("本地路径","Local path");enabled:!root.working;onTextChanged:root.clearImportPreview();onAccepted:root.previewImport()}
            RowLayout {
                Layout.fillWidth:true
                SmallButton{objectName:"skillManagerImportProject";text:root.t("工作区","Workspace");selected:root.importProject;enabled:!root.working && !!root.roots.project;onClicked:{root.importProject=true;root.clearImportPreview()}}
                SmallButton{objectName:"skillManagerImportGlobal";text:root.t("全局","Global");selected:!root.importProject;enabled:!root.working;onClicked:{root.importProject=false;root.clearImportPreview()}}
                Item{Layout.fillWidth:true}
                SmallButton{objectName:"skillManagerImportPreview";text:root.t("预览","Preview");enabled:!root.working && importSource.text.trim()!=="";onClicked:root.previewImport()}
            }
            Repeater{model:(root.importPreview.errors || []).slice(0,12);delegate:Label{required property var modelData;Layout.fillWidth:true;text:root.errorText(modelData);wrapMode:Text.Wrap;color:root.sdk.colors.danger;font.pixelSize:Umeko.Theme.font(11);maximumLineCount:4}}
            ListView {
                objectName:"skillManagerImportList";Layout.fillWidth:true;Layout.fillHeight:true;clip:true;model:root.importPreview.skills || [];spacing:7*root.sdk.scale
                ScrollBar.vertical:ScrollBar{policy:ScrollBar.AsNeeded}
                delegate:Rectangle {
                    id:importEntry;required property var modelData
                    width:ListView.view.width;height:importBody.implicitHeight+16*root.sdk.scale;color:root.sdk.colors.bg;radius:5*root.sdk.scale
                    ColumnLayout {
                        id:importBody;x:8*root.sdk.scale;y:8*root.sdk.scale;width:parent.width-16*root.sdk.scale;spacing:5*root.sdk.scale
                        Label{Layout.fillWidth:true;text:importEntry.modelData.name;font.bold:true}
                        Label{visible:!!importEntry.modelData.error;Layout.fillWidth:true;text:root.errorText(importEntry.modelData.error);wrapMode:Text.Wrap;maximumLineCount:4;color:root.sdk.colors.danger;font.pixelSize:Umeko.Theme.font(10)}
                        Label{visible:!!importEntry.modelData.conflict;Layout.fillWidth:true;text:root.t("同名 Skill 已存在","A Skill with this name already exists");color:root.sdk.colors.muted;font.pixelSize:Umeko.Theme.font(10)}
                        RowLayout {
                            SmallButton{objectName:"skillManagerImportSkip_"+importEntry.modelData.name;text:root.t("跳过","Skip");selected:root.importDecisions[importEntry.modelData.name]==="skip";enabled:!root.working;onClicked:root.decideImport(importEntry.modelData.name,"skip")}
                            SmallButton{objectName:"skillManagerImportReplace_"+importEntry.modelData.name;text:importEntry.modelData.conflict ? root.t("替换","Replace") : root.t("导入","Import");selected:root.importDecisions[importEntry.modelData.name]==="replace";enabled:!root.working && !importEntry.modelData.error && (!importEntry.modelData.conflict || importEntry.modelData.replaceable);onClicked:root.decideImport(importEntry.modelData.name,"replace")}
                        }
                    }
                }
            }
            Repeater{model:(root.importResult.errors || []).slice(0,12);delegate:Label{required property var modelData;Layout.fillWidth:true;text:(modelData.name || "")+": "+root.errorText(modelData.error);wrapMode:Text.Wrap;maximumLineCount:4;color:root.sdk.colors.danger}}
            SmallButton{objectName:"skillManagerImportSubmit";text:root.t("导入…","Import…");enabled:!root.working && root.importReady;onClicked:root.submitImport()}
        }
    }
    MouseArea{anchors.fill:parent;visible:!!root.importFailure;z:30;acceptedButtons:Qt.AllButtons;onWheel:wheel=>wheel.accepted=true}
    Rectangle {
        objectName:"skillManagerImportError";visible:!!root.importFailure;z:31
        anchors.centerIn:parent;width:Math.max(0,root.width-24*root.sdk.scale);height:Math.max(0,Math.min(260*root.sdk.scale,root.height-24*root.sdk.scale))
        color:root.sdk.colors.surface;border.color:root.sdk.colors.line;radius:7*root.sdk.scale
        ColumnLayout {
            anchors.fill:parent;anchors.margins:12*root.sdk.scale;spacing:10*root.sdk.scale
            Label{text:root.t("导入失败","Import failed");font.bold:true;Layout.fillWidth:true}
            ScrollView {
                Layout.fillWidth:true;Layout.fillHeight:true;clip:true;contentWidth:availableWidth
                TextArea{width:parent.width;text:root.importFailure;readOnly:true;selectByMouse:true;wrapMode:TextEdit.Wrap;textFormat:TextEdit.PlainText;color:root.sdk.colors.ink;font.family:Umeko.Theme.fontFamily;font.pixelSize:Umeko.Theme.font(11);background:null}
            }
            SmallButton{objectName:"skillManagerImportErrorClose";text:root.t("确定","OK");Layout.alignment:Qt.AlignRight;onClicked:{root.importFailure="";list.forceActiveFocus()}}
        }
    }
    MouseArea{anchors.fill:parent;visible:root.menuOpen;z:20;acceptedButtons:Qt.LeftButton | Qt.RightButton;onClicked:root.menuOpen=false}
    Rectangle {
        id:contextMenu;objectName:"skillManagerContextMenu";visible:root.menuOpen;z:21;clip:true
        width:Math.min(210*root.sdk.scale,root.width);height:Math.min(root.height,menuColumn.implicitHeight+8*root.sdk.scale)
        x:Math.max(0,Math.min(root.menuX,root.width-width));y:Math.max(0,Math.min(root.menuY,root.height-height))
        color:root.sdk.colors.surface;border.color:root.sdk.colors.line;radius:6*root.sdk.scale
        Flickable {
          id:menuViewport;objectName:"skillManagerMenuViewport";anchors.fill:parent;anchors.margins:4*root.sdk.scale
          clip:true;contentWidth:width;contentHeight:menuColumn.implicitHeight;boundsBehavior:Flickable.StopAtBounds
          ScrollBar.vertical:ScrollBar{policy:ScrollBar.AsNeeded}
          Column {
            id:menuColumn;width:menuViewport.width
            Repeater {
                model:root.contextRow ? ["insert","preview","edit","reveal","copy","copyPath","paste","rename","delete"] : ["paste"]
                delegate:Button {
                    required property string modelData
                    objectName:"skillManagerMenu_"+modelData;width:menuColumn.width;height:29*root.sdk.scale
                    text:({insert:root.t("附加到聊天","Attach to chat"),preview:root.t("预览","Preview"),edit:root.t("编辑 SKILL.md","Edit SKILL.md"),reveal:root.t("在文件管理器中查看","Show in file manager"),copy:root.t("复制","Copy"),copyPath:root.t("复制路径","Copy path"),paste:root.t("粘贴到此分区","Paste into this section"),rename:root.t("重命名","Rename"),delete:root.t("删除","Delete")})[modelData]
                    enabled:!root.working && (modelData!=="paste" || !!root.roots[root.selectedScope])
                    background:Rectangle{radius:3*root.sdk.scale;color:parent.hovered ? root.sdk.colors.hover : "transparent"}
                    contentItem:Label{text:parent.text;leftPadding:7*root.sdk.scale;font.pixelSize:Umeko.Theme.font(11);color:modelData==="delete" ? root.sdk.colors.danger : root.sdk.colors.ink}
                    onClicked:root.action(modelData)
                }
            }
          }
        }
    }
    Timer {
        interval:200;repeat:true;running:root.sdk.active && !!root.job
        onTriggered:root.pollJob()
    }
    Connections {
        target:root.sdk;ignoreUnknownSignals:true
        function onActiveChanged(){root.initialize()}
        function onHostResponse(id,value) {
            if(id===root.previewRequest){root.previewResponse(value);return}
            const entry=root.pending[id];if(!entry)return
            let next=Object.assign({},root.pending);delete next[id];root.pending=next
            const operation=entry.operation
            if(operation==="skills.job")root.polling=false
            if(value.ok===false){const failedOperation=operation==="skills.job" ? root.jobOperation : operation;root.job="";root.jobOperation="";root.pageRows=[];root.fail(failedOperation,value.error || value.status);return}
            if(value.jobId){root.job=value.jobId;root.jobOperation=operation;root.pageOffset=0;root.pageRows=[];Qt.callLater(root.pollJob);return}
            if(operation!=="skills.job"){root.complete(operation,value,true);return}
            const item=(value.jobs || [])[0];if(!item || item.status==="running")return
            const result=item.result || {},page=result.skillsPage
            if(page) {
                const rows=page.field==="skills" ? result.skills : (result.preview || {}).skills
                if(page.offset!==root.pageOffset || !rows || typeof rows.length!=="number" || (page.nextOffset!=null && page.nextOffset!==page.offset+rows.length)) {
                    root.notice=root.t("分页响应无效，请刷新重试。","Invalid page; refresh to retry.");root.noticeError=true;root.job="";root.pageRows=[];return
                }
                root.pageRows=root.pageRows.concat(Array.from(rows))
                if(page.nextOffset!=null){root.pageOffset=page.nextOffset;Qt.callLater(root.pollJob);return}
                if(page.field==="skills")result.skills=root.pageRows;else result.preview.skills=root.pageRows
            }
            const original=root.jobOperation;root.job="";root.jobOperation="";root.pageRows=[]
            root.complete(original,result,item.status==="completed")
        }
    }
}
