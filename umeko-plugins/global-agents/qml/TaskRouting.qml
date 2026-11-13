import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id:root
    objectName:"taskRoutingPage"
    required property var sdk
    required property var roster
    readonly property var c:sdk.colors
    property var history:[]
    property var tasks:[]
    property var pending:({})
    property bool ready:false
    property bool polling:false
    property bool sending:false
    property string error:""
    property string coordinatorChoice:""
    property string directoryChoice:""
    property string taskChoice:""
    property string requestKey:""
    property string payloadKey:""
    property string expandedId:""
    property int revision:-1
    property int offset:0
    property int revisionOffset:0
    property bool more:false
    readonly property var coordinator:roster.agents[coordinatorPicker.currentIndex] || ({})
    readonly property var directories:[...new Set(roster.targets.filter(row=>row.kind==="session" && row.backend!=="dsh" && row.workspace &&
        (row.bridgeAll || (row.bridgeAgents || []).includes(coordinator.id))).map(row=>row.workspace))]
    readonly property var associations:[{id:"",name:root.t("由协调者判断关联","Let coordinator choose")},{id:"new",name:root.t("明确创建新任务","Create a new task")}].concat(
        tasks.filter(row=>row.project===directoryPicker.currentText).map(row=>({id:row.id,name:row.objective+" · "+row.id.slice(0,8)})))
    function t(zh,en) { return sdk.language.indexOf("zh")===0?zh:en }
    function call(method,args) {
        const id=sdk.call(method,args || {})
        if(!id){error=root.t("服务忙，请稍后重试","Service busy. Please retry.");return ""}
        const next=Object.assign({},pending);next[id]=method;pending=next;return id
    }
    function refresh() {if(ready && visible && !polling)polling=!!call("taskRoutes",{revision:revision,offset:offset,revisionOffset:revisionOffset})}
    function page(value){offset=Math.max(0,value);revision=-1;refresh()}
    function submit() {
        if(sending)return
        const args={coordinator:coordinator.id || "",cwd:directoryPicker.currentText,
            requestedTask:taskChoice,objective:objective.text.trim(),scope:scope.text.trim()}
        const encoded=JSON.stringify(args)
        if(!requestKey || encoded!==payloadKey){requestKey=Date.now().toString(36)+"-"+Math.random().toString(36).slice(2)+"-"+Math.random().toString(36).slice(2);payloadKey=encoded}
        args.requestKey=requestKey;sending=!!call("submitTask",args)
    }
    function revise(row) {
        coordinatorChoice=row.coordinator;directoryChoice=row.cwd;taskChoice=row.taskId || row.requestedTask || ""
        objective.text=row.objective;scope.text=row.scope;requestKey="";payloadKey="";objective.forceActiveFocus()
    }
    function status(row) {
        const route={routing:root.t("正在判断路由","Choosing a route"),clarify:root.t("需要澄清","Clarification needed"),rejected:root.t("路由拒绝","Route rejected"),cancelled:root.t("路由已停止","Route stopped"),interrupted:root.t("路由已中断","Route interrupted")}
        if(row.status!=="accepted")return route[row.status] || row.status
        const execution={queued:root.t("等待投递","Waiting for delivery"),sending:root.t("投递中","Delivering"),running:root.t("已接收，待结果","Received; awaiting result"),completed:root.t("执行者报告完成","Executor reported completion"),failed:row.failurePhase==="delivery"?root.t("投递失败","Delivery failed"):root.t("执行失败","Execution failed"),cancelled:root.t("已停止","Stopped"),interrupted:root.t("已中断，未重发","Interrupted; not replayed")}
        return root.t("已接受路由 · ","Route accepted · ")+(execution[row.execution] || row.execution)
    }
    function details(row) {
        return [root.t("任务 · ","Task · ")+(row.taskId || root.t("尚未关联","Not linked yet")),root.t("请求 · ","Request · ")+row.id,root.t("执行会话 · ","Execution chat · ")+(row.targetId || root.t("尚未选择","Not selected")),
            root.t("实际目录 · ","Actual directory · ")+row.cwd,root.t("范围 · ","Scope · ")+row.scope,row.reason?root.t("路由说明 · ","Routing reason · ")+row.reason:"",row.result?root.t("执行者回报 · ","Executor report · ")+row.result:""].filter(Boolean).join("\n")
    }
    function tone(row) {
        if(row.status==="rejected" || row.execution==="failed")return c.danger
        if(row.status==="clarify" || row.status==="interrupted" || row.execution==="interrupted")return c.dark?"#e5c282":"#966d2d"
        if(row.execution==="completed")return c.dark?"#85c7b2":"#367f69"
        return c.accent
    }
    spacing:9
    Component.onCompleted:{ready=true;refresh()}
    onVisibleChanged:if(ready && visible){revision=-1;refresh()}
    Timer {interval:1000;repeat:true;running:root.visible && root.sdk.active;onTriggered:root.refresh()}
    Connections {
        target:root.sdk
        function onResponse(id,value) {
            const method=root.pending[id];if(!method)return
            const next=Object.assign({},root.pending);delete next[id];root.pending=next
            if(method==="taskRoutes")root.polling=false
            if(method==="submitTask")root.sending=false
            if(!value.ok){root.error=value.error || root.t("操作失败","Could not complete");return}
            root.error=""
            if(method==="taskRoutes") {
                const data=value.result
                if(!data.unchanged){
                    if(JSON.stringify(root.history)!==JSON.stringify(data.routes))root.history=data.routes
                    if(JSON.stringify(root.tasks)!==JSON.stringify(data.tasks))root.tasks=data.tasks
                    root.more=data.hasMore;root.revision=data.revision;root.revisionOffset=data.offset
                }
            } else {root.expandedId=value.result.id || "";root.revision=-1;root.refresh()}
        }
    }
    component Caption:Text {color:root.c.ink;font.pixelSize:12*root.sdk.scale;textFormat:Text.PlainText;wrapMode:Text.Wrap;Layout.fillWidth:true;Layout.minimumWidth:0}
    component Action:Button {
        id:control;font.pixelSize:12*root.sdk.scale;palette.buttonText:root.c.ink
        background:Rectangle {radius:7;color:control.down?root.c.hover:root.c.bg;border.color:root.c.line}
    }
    component Picker:ComboBox {
        id:control;Layout.fillWidth:true;Layout.minimumWidth:0;implicitHeight:36;leftPadding:10;rightPadding:28
        palette.buttonText:root.c.ink;palette.text:root.c.ink;palette.base:root.c.surface;palette.button:root.c.bg
        contentItem:Text {text:control.displayText;color:root.c.ink;font.pixelSize:12*root.sdk.scale;verticalAlignment:Text.AlignVCenter;elide:Text.ElideRight}
        indicator:Text {x:parent.width-22;y:(parent.height-height)/2;text:"⌄";color:root.c.muted;font.pixelSize:16}
        background:Rectangle {radius:7;color:root.c.bg;border.color:control.activeFocus?root.c.accent:root.c.line}
    }
    Caption {text:root.t("明确交代目标与范围，由协调者关联任务并选择已有会话。路由接受后仍需等待执行结果，完成报告由你另行验收。","State your goal and scope. The coordinator links a task to an existing chat. Route acceptance awaits execution; review the reported result separately.");color:root.c.muted}
    RowLayout {Layout.fillWidth:true
        ColumnLayout {Layout.fillWidth:true;Layout.minimumWidth:0
            Caption {text:root.t("协调者","Coordinator");color:root.c.muted}
            Picker {id:coordinatorPicker;objectName:"taskCoordinatorPicker";model:root.roster.agents;textRole:"name";displayText:currentText || root.t("请选择协调者","Choose a coordinator")
                currentIndex:root.coordinatorChoice?model.findIndex(row=>row.id===root.coordinatorChoice):model.length?0:-1
                onActivated:index=>{root.coordinatorChoice=model[index].id;root.directoryChoice="";root.taskChoice=""}
            }
        }
        ColumnLayout {Layout.fillWidth:true;Layout.minimumWidth:0
            Caption {text:root.t("实际目录（已授权会话）","Directory (authorized Pi chats)");color:root.c.muted}
            Picker {id:directoryPicker;objectName:"taskDirectoryPicker";model:root.directories;displayText:currentText || root.t("暂无已授权目录","No authorized Pi directories")
                currentIndex:root.directoryChoice?model.indexOf(root.directoryChoice):model.length?0:-1
                onActivated:index=>{root.directoryChoice=model[index];root.taskChoice=""}
                ToolTip.visible:hovered;ToolTip.text:currentText
            }
        }
    }
    Picker {id:associationPicker;objectName:"taskAssociationPicker";model:root.associations;textRole:"name"
        currentIndex:model.findIndex(row=>row.id===root.taskChoice);displayText:currentText || root.t("所选任务不可用，请重新选择","Task unavailable; choose again")
        onActivated:index=>root.taskChoice=model[index].id
    }
    TextField {id:objective;objectName:"taskRoutingObjective";Layout.fillWidth:true;implicitHeight:38;leftPadding:10;rightPadding:10
        placeholderText:root.t("任务目标或补充要求","Task goal or follow-up");maximumLength:1000;color:root.c.ink;selectByMouse:true;font.pixelSize:13*root.sdk.scale
        background:Rectangle {radius:7;color:root.c.bg;border.color:objective.activeFocus?root.c.accent:root.c.line}
    }
    ScrollView {Layout.fillWidth:true;Layout.preferredHeight:64
        background:Rectangle {radius:7;color:root.c.bg;border.color:scope.activeFocus?root.c.accent:root.c.line}
        TextArea {id:scope;objectName:"taskRoutingScope";placeholderText:root.t("允许处理的范围，例如只读检查当前目录","Allowed scope, e.g. read-only review of this directory");color:root.c.ink;wrapMode:TextEdit.Wrap;selectByMouse:true;font.pixelSize:13*root.sdk.scale;background:null}
    }
    Caption {visible:!!root.taskChoice && root.taskChoice!=="new";text:root.t("提交新范围会停止该任务的旧请求；已经执行的操作无法撤销。","A new scope stops old requests for this task. Completed actions cannot be undone.");color:root.c.muted}
    RowLayout {Layout.fillWidth:true
        Action {objectName:"submitTaskRoute";text:root.sending?root.t("正在提交…","Submitting…"):root.t("交给协调者","Send to coordinator");enabled:!root.sending && !!root.coordinator.id && !!directoryPicker.currentText && associationPicker.currentIndex>=0 && !!objective.text.trim() && !!scope.text.trim() && scope.length<=4000;onClicked:root.submit()}
        Action {objectName:"resetTaskRoute";text:root.t("新请求","New request");enabled:!root.sending;onClicked:{root.requestKey="";root.payloadKey="";root.taskChoice="";objective.clear();scope.clear()}}
        Caption {text:root.coordinator.taskRouter?root.t("任务协调模式","Task routing mode"):root.t("提交后协调者仅路由入口请求","Submitting restricts the coordinator to intake routing");color:root.c.muted}
    }
    Caption {visible:!!root.error;text:root.error;color:root.c.danger}
    Caption {text:root.t("路由记录","Routing history");font.bold:true}
    ListView {objectName:"taskRouteHistory";Layout.fillWidth:true;Layout.fillHeight:true;clip:true;spacing:8;model:root.history
        ScrollBar.vertical:ScrollBar{}
        delegate:Rectangle {
            required property var modelData
            id:card;width:ListView.view.width;height:content.implicitHeight+20;radius:9;color:root.c.bg
            border.color:root.expandedId===modelData.id?root.c.accent:root.c.line
            ColumnLayout {id:content;anchors.left:parent.left;anchors.right:parent.right;anchors.top:parent.top;anchors.margins:10;spacing:5
                RowLayout {Layout.fillWidth:true
                    Caption {text:card.modelData.objective;font.bold:true}
                    Action {text:root.expandedId===card.modelData.id?root.t("收起","Collapse"):root.t("详情","Details");onClicked:root.expandedId=root.expandedId===card.modelData.id?"":card.modelData.id}
                }
                Caption {text:root.status(card.modelData);color:root.tone(card.modelData)}
                Caption {visible:root.expandedId===card.modelData.id;text:root.details(card.modelData)}
                RowLayout {
                    Action {text:card.modelData.status==="clarify"?root.t("在入口澄清","Clarify in intake"):root.t("补充 / 修改范围","Follow up / revise scope");onClicked:root.revise(card.modelData)}
                    Action {objectName:"stopTaskRoute_"+card.modelData.id;text:root.t("停止此请求","Stop request");visible:card.modelData.status==="routing" || card.modelData.status==="accepted" && ["queued","sending","running"].includes(card.modelData.execution);onClicked:root.call("stopTaskRoute",{routeId:card.modelData.id})}
                }
            }
        }
        Caption {anchors.centerIn:parent;visible:root.history.length===0;text:root.t("尚无任务路由","No task routes yet");color:root.c.muted;horizontalAlignment:Text.AlignHCenter}
    }
    RowLayout {visible:root.offset>0 || root.more
        Action {text:root.t("较新路由","Newer routes");enabled:root.offset>0 && !root.polling;onClicked:root.page(root.offset-20)}
        Action {text:root.t("较早路由","Older routes");enabled:root.more && !root.polling;onClicked:root.page(root.offset+20)}
    }
    RowLayout {Layout.fillWidth:true
        Caption {text:root.t("仅使用已有连接与实际目录，执行者保留原权限。停止会拦截后续投递，已执行操作无法撤销。","Uses existing connections and actual directories. Executor permissions remain in place. Stop prevents later delivery; completed actions cannot be undone.");color:root.c.muted}
        Action {text:root.t("退出任务模式","Exit routing mode");visible:!!root.coordinator.taskRouter;onClicked:root.call("leaveTaskMode",{id:root.coordinator.id})}
    }
}
