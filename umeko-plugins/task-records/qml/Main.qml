import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Timeline.js" as Timeline

Rectangle {
    id: root
    objectName: "taskRecordsWidget"
    required property var sdk
    readonly property var c: sdk.colors
    readonly property bool sessionBusy: !!sdk.session.busy
    color: c.surface
    clip: true
    property string view: "list"
    property string request: ""
    property string error: ""
    property string notice: ""
    property bool refreshPending: false
    property bool loaded: false
    property string linked: ""
    property string linkedObjective: ""
    property string chatTitle: ""
    property var tasks: []
    property bool tasksMore: false
    property int taskOffset: 0
    property string taskId: ""
    property var task: null
    property bool canLink: false
    property var attempts: []
    property bool attemptsMore: false
    property int attemptOffset: 0
    property int attemptIndex: -1
    readonly property var attempt: attempts[attemptIndex] || null
    property int detailOffset: 0
    property var detail: null
    property bool deliveryMode: false
    readonly property var nodes: Timeline.nodes(detail).filter(row=>!deliveryMode || !!row.file || row.kind==="accepted")
    property bool confirmingDelete: false
    property bool confirmingAccept: false
    property bool technical: false
    property bool createAndLink: false
    property bool checking: false
    property var checkResult: null
    property int selectedNode: 0
    property bool navigationOpen: false
    property bool edgeReady: false
    property bool edgeAtEnd: false
    property bool keepDetailPosition: false
    property bool refreshingDetail: false

    function t(zh, en) { return sdk.language.indexOf("zh") === 0 ? zh : en }
    function timeText(value) {
        if (!value) return t("时间未记录", "Time not recorded")
        const date = new Date(value)
        return isNaN(date.getTime()) ? value : Qt.formatDateTime(date, "MM-dd hh:mm:ss")
    }
    function status(code) {
        return ({draft:t("尚未开始","Not started"), running:t("正在工作","Working"), pending:t("已中断，可继续","Interrupted · can continue"),
            failed:t("本次未完成","Not completed"), finished:t("本次已结束，待你确认","Finished · review needed"), accepted:t("你已确认完成","Confirmed by you"),
            available:t("文件未变化","File unchanged"), missing:t("已移动或缺失","Moved or missing"), changed:t("文件已变化","File changed"),
            unavailable:t("无法读取","Cannot read"), unsupported:t("仅记录路径","Path only"), unverified:t("未记录版本","No saved version")})[code] || code || ""
    }
    function tone(code) {
        if (code === "failed" || code === "missing" || code === "changed" || code === "unavailable") return c.dark ? "#ed9ba9" : "#af4159"
        if (code === "pending" || code === "unsupported" || code === "unverified" || code === "input") return c.dark ? "#e5c282" : "#966d2d"
        if (code === "accepted" || code === "finished" || code === "available") return c.dark ? "#85c7b2" : "#367f69"
        if (code === "running" || code === "tool") return c.dark ? "#9dbfe7" : "#487cab"
        if (code === "message") return c.dark ? "#c7abe2" : "#8960ab"
        return c.dark ? "#a6b3c4" : "#708397"
    }
    function shade(code,alpha) { const hex=tone(code); return Qt.rgba(parseInt(hex.slice(1,3),16)/255,parseInt(hex.slice(3,5),16)/255,parseInt(hex.slice(5,7),16)/255,alpha) }
    function tint(code) { return shade(code,c.dark?0.15:0.065) }
    function reason(code) {
        return ({"应用已重启":t("应用重启，工作已中断","App restarted; work interrupted"),"应用已退出":t("应用退出，工作已中断","App closed; work interrupted"),
            "Pi 未能启动尝试":t("未能开始，请检查聊天中的错误后重试","Could not start; check the chat error and retry"),
            "Pi 进程已退出":t("执行进程退出，可去聊天继续","Worker exited; continue in chat"),"用户已停止尝试":t("你已停止，可去聊天继续","Stopped by you; continue in chat"),
            "Pi 执行失败":t("执行失败，请在聊天中查看原因","Execution failed; check the chat for details"),"输出达到长度上限":t("输出达到上限，可去聊天继续","Output limit reached; continue in chat"),
            "部分交付失败":t("部分文件未能交付，请去聊天补充要求","Some files were not delivered; ask for a revision in chat"),"任务记录写入不完整":t("记录未能完整保存，请核对聊天","Record incomplete; check the chat")})[code] || code || ""
    }
    function nodeTitle(row) {
        if (row.file) return row.body.split(/[\\/]/).pop()
        return ({start:t("开始工作","Work started"), end:t("本次工作结束","Work ended"), accepted:t("你确认了结果","Result confirmed by you"),
            message:t("聊天消息","Chat message"), session:t("关联聊天","Linked chat"), tool:t("工具活动","Tool activity"),
            delivery_error:t("交付未完成","Delivery incomplete")})[row.kind] || row.kind
    }
    function nodeBody(row) {
        if (row.kind === "start") return t("由你发送的聊天消息开始，操作范围见记录信息。","Started by your chat message. See record information for scope.")
        if (row.kind === "file") return t("交付文件 · ","Delivered file · ") + status(row.code)
        if (row.kind === "input") return t("参考文件 · ","Reference file · ") + status(row.code)
        if (row.kind === "accepted") return t("用户手动确认；系统不会自动验收。","Confirmed manually by the user.")
        if (row.kind === "end") return reason(row.body) || status(row.code)
        if (row.kind === "delivery_error") return t("未能交付的条目：","Undelivered items: ") + row.body
        if (row.kind === "session") return t("本次工作关联的聊天，内部引用可展开查看。","Chat used for this work. Expand for references.")
        return row.kind === "message" ? (row.body === "user" ? t("你的消息","Your message") : t("助手的回复","Assistant reply")) : row.body
    }
    function call(operation, args) {
        if (!sdk.active || request) return false
        error = ""
        request = sdk.requestHost("tasks." + operation, args || {})
        if (!request) error = t("暂不可用，请重试。","Unavailable. Please retry.")
        return !!request
    }
    function showList(offset) { if (request) return; view="list"; taskOffset=offset; call("list",{offset:offset}) }
    function showTask(id, offset, preserve) {
        if (request) return
        refreshingDetail=!!preserve && taskId===id
        if (taskId !== id) { task=null; attempts=[]; detail=null; checkResult=null; technical=false }
        view="task"; taskId=id; attemptOffset=offset; confirmingDelete=false; confirmingAccept=false
        call("get",{taskId:id, offset:offset})
    }
    function showAttempt(index, offset, atEnd, preserve) {
        if (request) return
        if (attemptIndex !== index) checkResult=null
        keepDetailPosition=!!preserve && attemptIndex===index && detailOffset===offset && !!detail
        attemptIndex=index; detailOffset=offset; edgeReady=false; edgeAtEnd=!!atEnd
        if (!keepDetailPosition) { detail=null; selectedNode=0 }
        confirmingAccept=false
        if (attempt) call("detail",{taskId:taskId,attemptId:attempt.id,offset:offset,deliveriesOnly:deliveryMode})
    }
    function refresh() {
        if (!sdk.active || request || view==="create") return
        refreshPending=false
        if (view==="task") showTask(taskId,attemptOffset,true); else showList(taskOffset)
    }
    function linkState(result) { linked=result.linked || ""; linkedObjective=result.linkedObjective || ""; chatTitle=result.chatTitle || "" }
    function edgePage(direction) {
        if (!edgeReady || request || !detail) return
        if (direction > 0 && detail.hasMore) showAttempt(attemptIndex,detailOffset+8,false)
        else if (direction < 0 && detailOffset > 0) showAttempt(attemptIndex,detailOffset-8,true)
    }
    function jump(index) {
        selectedNode=index
        timeline.positionViewAtIndex(index,ListView.Beginning)
        navigationOpen=false
    }
    onSessionBusyChanged: { refreshPending=true; refresh() }
    Component.onCompleted: refresh()
    Connections {
        target: root.sdk
        function onActiveChanged() { if (root.sdk.active) root.refresh() }
        function onEvent(topic,data) { if (topic==="tasks.changed") { root.refreshPending=true; root.refresh() } }
        function onHostResponse(token,response) {
            if (token!==root.request) return
            root.request=""
            if (!response.ok) { root.checking=false; root.createAndLink=false; root.error=response.error || root.t("操作失败，请重试。","Could not complete. Please retry."); return }
            const result=response.result
            switch(response.operation) {
            case "tasks.list": root.loaded=true; root.tasks=result.tasks; root.tasksMore=result.hasMore; root.linkState(result); break
            case "tasks.get": {
                const previous=root.attempt ? root.attempt.id : 0
                root.task=result.task; root.attempts=result.attempts; root.attemptsMore=result.hasMore; root.canLink=result.canLink; root.linkState(result)
                const index=root.attempts.findIndex(row=>row.id===previous)
                if(previous===0 || index<0) root.deliveryMode=!!(root.attempts.length && root.attempts[0].state!=="running")
                root.showAttempt(index>=0?index:root.attempts.length?0:-1,index>=0?root.detailOffset:0,false,root.refreshingDetail && index>=0)
                break
            }
            case "tasks.detail": {
                const y=timeline.contentY
                const key=root.nodes[root.selectedNode] ? root.nodes[root.selectedNode].key : ""
                const preserve=root.keepDetailPosition
                root.detail=result.id?result:null
                Qt.callLater(function(){
                    if(preserve) {
                        timeline.contentY=Math.max(timeline.originY,Math.min(y,timeline.originY+Math.max(0,timeline.contentHeight-timeline.height)))
                        const index=root.nodes.findIndex(row=>row.key===key)
                        if(index>=0) root.selectedNode=index
                    } else if(root.edgeAtEnd) timeline.positionViewAtEnd(); else timeline.positionViewAtBeginning()
                    root.edgeReady=true
                })
                break
            }
            case "tasks.create":
                objective.clear(); scope.clear(); root.taskId=result.taskId; root.task=null; root.attempts=[]; root.detail=null; root.checkResult=null
                root.refreshPending=false; root.view="task"
                if(root.createAndLink) root.call("link",{taskId:result.taskId}); else root.showTask(result.taskId,0)
                break
            case "tasks.link":
                root.createAndLink=false; root.notice=root.t("已准备，尚未开始。去聊天输入要求并发送。","Ready, not started. Enter your request and send it in chat."); root.refreshPending=true; break
            case "tasks.unlink": root.notice=root.t("已取消准备，聊天草稿和附件保留。","Preparation cancelled. Chat draft and attachments kept."); root.refreshPending=true; break
            case "tasks.verify": root.checking=false; root.checkResult=result; root.showAttempt(root.attemptIndex,root.detailOffset,false); break
            case "tasks.accept": root.confirmingAccept=false; root.notice=root.t("已记录你的确认。","Your confirmation was saved."); root.refreshPending=true; break
            case "tasks.delete": root.refreshPending=false; root.showList(0); break
            }
            if(root.refreshPending && !root.request) root.refresh()
        }
    }
    component LabelText: Text {
        textFormat: Text.PlainText; color:root.c.ink; font.pixelSize:12*root.sdk.scale; wrapMode:Text.Wrap
    }
    component WidgetButton: Button {
        id: button
        property bool primary: false
        padding:8
        contentItem: LabelText {text:button.text;color:button.enabled?(button.primary?"white":root.c.ink):root.c.muted; horizontalAlignment:Text.AlignHCenter;verticalAlignment:Text.AlignVCenter}
        background:Rectangle {radius:8;color:button.primary && button.enabled?root.c.accent:button.down?root.c.accentBg:button.hovered?root.c.hover:root.c.surface;border.color:button.primary?root.c.accent:root.c.line}
    }
    component Card: Rectangle {
        property string code: "draft"
        radius:9; color:root.tint(code); border.color:root.shade(code,0.22)
    }
    ColumnLayout {
        anchors.fill:parent;anchors.margins:12;spacing:8; enabled:root.sdk.active
        RowLayout {
            Layout.fillWidth:true
            WidgetButton {visible:root.view!=="list";enabled:!root.request;text:root.t("返回","Back");onClicked:root.showList(root.taskOffset)}
            LabelText {Layout.fillWidth:true;text:root.t("任务记录","Task records");font.bold:true;font.pixelSize:14*root.sdk.scale}
            WidgetButton {objectName:"newTaskRecord";visible:root.view==="list";enabled:!root.request;primary:true;text:root.t("记录目标","Record a goal");onClicked:{root.notice="";root.view="create";objective.forceActiveFocus()}}
            WidgetButton {visible:root.view!=="create";enabled:!root.request;text:root.t("刷新","Refresh");onClicked:root.refresh()}
        }
        LabelText {visible:root.view==="list";Layout.fillWidth:true;color:root.c.muted;text:root.t("记录目标，在聊天中开始或继续工作，在这里查看交付并确认结果。","Record a goal, work in chat, then review deliveries and confirm the result here.")}
        Card {
            code:"pending";Layout.fillWidth:true;implicitHeight:pendingLayout.implicitHeight+18;visible:root.linked!==""
            ColumnLayout {
                id:pendingLayout;anchors.fill:parent;anchors.margins:9;spacing:5
                LabelText {objectName:"linkedTaskNotice";Layout.fillWidth:true;font.bold:true;text:root.t("尚未开始 · 待你发送消息","Not started · waiting for your message")}
                LabelText {Layout.fillWidth:true;text:root.linkedObjective+"\n"+root.t("将使用聊天：","Chat: ")+root.chatTitle}
                RowLayout {
                    WidgetButton {objectName:"goToTaskChat";primary:true;enabled:!root.request;text:root.t("去聊天输入并发送","Go to chat and send");onClicked:root.call("chat",{taskId:root.linked})}
                    WidgetButton {objectName:"cancelPreparedTask";enabled:!root.request;text:root.t("取消准备","Cancel");onClicked:root.call("unlink")}
                }
            }
        }
        LabelText {visible:root.error!=="";Layout.fillWidth:true;text:root.error;color:root.c.danger}
        LabelText {visible:root.notice!=="" && !root.linked;Layout.fillWidth:true;text:root.notice;color:root.c.accent}
        ColumnLayout {
            visible:root.view==="list";Layout.fillWidth:true;Layout.fillHeight:true
            LabelText {visible:!root.request && !root.tasks.length;Layout.fillWidth:true;text:root.t("还没有记录。先记录一个想完成的目标，再去聊天说明具体要求。","No records yet. Record a goal, then describe the request in chat.");color:root.c.muted}
            ListView {
                Layout.fillWidth:true;Layout.fillHeight:true;clip:true;model:root.tasks;spacing:8;ScrollBar.vertical:ScrollBar{}
                delegate:ItemDelegate {
                    id:entry;required property var modelData;objectName:"openTask_"+modelData.id;width:ListView.view.width;enabled:!root.request
                    topPadding:12;bottomPadding:12;leftPadding:14;rightPadding:12
                    background:Card {code:entry.modelData.state;Rectangle {x:1;y:10;width:3;height:parent.height-20;radius:2;color:root.tone(entry.modelData.state)}}
                    contentItem:Column {spacing:6;LabelText {width:parent.width;text:entry.modelData.objective;font.bold:true;maximumLineCount:2;elide:Text.ElideRight}
                        LabelText {width:parent.width;text:root.status(entry.modelData.state)+" · "+root.timeText(entry.modelData.updated);color:root.tone(entry.modelData.state)}}
                    onClicked:root.showTask(modelData.id,0)
                }
            }
            RowLayout {visible:root.taskOffset>0 || root.tasksMore
                WidgetButton {text:root.t("上一页","Previous");enabled:!root.request && root.taskOffset>0;onClicked:root.showList(root.taskOffset-12)}
                WidgetButton {text:root.t("下一页","Next");enabled:!root.request && root.tasksMore;onClicked:root.showList(root.taskOffset+12)}
            }
        }
        ColumnLayout {
            visible:root.view==="create";Layout.fillWidth:true;Layout.fillHeight:true;spacing:10
            LabelText {Layout.fillWidth:true;text:root.t("想完成什么？","What would you like to accomplish?");font.bold:true}
            TextField {id:objective;objectName:"taskObjective";Layout.fillWidth:true;maximumLength:1000;placeholderText:root.t("例如：整理资料并生成报告","For example: organize files and write a report");selectByMouse:true;color:root.c.ink}
            LabelText {Layout.fillWidth:true;text:root.t("允许处理的范围","What may be used or changed");font.bold:true}
            ScrollView {Layout.fillWidth:true;Layout.fillHeight:true;clip:true
                TextArea {id:scope;objectName:"taskScope";placeholderText:root.t("例如：读取本项目资料，生成报告，不修改原始文件。","For example: read project files and write a report; keep originals.");color:root.c.ink;wrapMode:TextEdit.Wrap;selectByMouse:true}}
            LabelText {Layout.fillWidth:true;color:root.c.muted;text:root.t("只记录目标和范围，不会授予新权限。下一步在当前聊天输入要求，发送后才开始。","Records the goal and scope without granting permissions. Next, enter your request in the current chat; work starts when you send it.")}
            WidgetButton {objectName:"saveTaskRecord";Layout.fillWidth:true;primary:true;enabled:!root.request && !root.sessionBusy && objective.text.trim().length>0 && scope.text.trim().length>0 && scope.length<=4000
                text:root.t("保存并准备到当前聊天","Save and prepare in this chat");onClicked:{root.createAndLink=true;root.call("create",{objective:objective.text,scope:scope.text})}}
            WidgetButton {visible:root.sessionBusy;enabled:!root.request && objective.text.trim().length>0 && scope.text.trim().length>0 && scope.length<=4000;text:root.t("仅保存目标","Save goal only");onClicked:{root.createAndLink=false;root.call("create",{objective:objective.text,scope:scope.text})}}
        }
        ColumnLayout {
            visible:root.view==="task";Layout.fillWidth:true;Layout.fillHeight:true;spacing:8
            LabelText {Layout.fillWidth:true;text:root.task?root.task.objective:"";font.bold:true;font.pixelSize:14*root.sdk.scale;maximumLineCount:2;elide:Text.ElideRight}
            WidgetButton {Layout.fillWidth:true;visible:root.attempts.length===0 && root.linked!==root.taskId;primary:true;objectName:"prepareNewTask";enabled:root.canLink && !root.request;text:root.t("准备到当前聊天","Prepare in this chat");onClicked:root.call("link",{taskId:root.taskId})}
            LabelText {Layout.fillWidth:true;visible:root.attempts.length===0;color:root.c.muted;text:root.t("目标已保存。准备到聊天后，输入要求并发送才会开始。","Goal saved. Prepare it in chat, then enter your request and send to start.")}
            ComboBox {
                id:selector;objectName:"taskAttemptSelector";Layout.fillWidth:true;visible:root.attempts.length>1 || root.attemptsMore || root.attemptOffset>0;enabled:!root.request
                palette.buttonText:root.c.ink;palette.button:root.c.surface;palette.base:root.c.surface;palette.text:root.c.ink
                model:root.attempts.map(row=>root.timeText(row.started)+" · "+root.status(row.accepted?"accepted":row.state));currentIndex:root.attemptIndex
                onActivated:index=>{root.deliveryMode=root.attempts[index].state!=="running";root.showAttempt(index,0,false)}
            }
            LabelText {visible:root.attempts.length===1 && !selector.visible;Layout.fillWidth:true;text:root.attempt?root.timeText(root.attempt.started)+" · "+root.status(root.attempt.accepted?"accepted":root.attempt.state):"";color:root.attempt?root.tone(root.attempt.state):root.c.muted}
            RowLayout {visible:root.attemptOffset>0 || root.attemptsMore
                WidgetButton {text:root.t("较新的工作","Newer work");enabled:!root.request && root.attemptOffset>0;onClicked:root.showTask(root.taskId,root.attemptOffset-12)}
                WidgetButton {text:root.t("较早的工作","Earlier work");enabled:!root.request && root.attemptsMore;onClicked:root.showTask(root.taskId,root.attemptOffset+12)}}
            LabelText {Layout.fillWidth:true;visible:root.attemptOffset>0 || root.attemptIndex>0;color:root.c.muted;text:root.t("正在查看只读历史；继续工作会新增一条记录，保留之前的结果。","Viewing read-only history. Continuing creates a new work record and keeps earlier results.")}
            RowLayout {
                visible:!!root.attempt;Layout.fillWidth:true
                WidgetButton {objectName:"showTaskDeliveries";primary:root.deliveryMode;text:root.t("交付文件","Delivered files");enabled:!root.request;onClicked:{root.deliveryMode=true;root.showAttempt(root.attemptIndex,0,false)}}
                WidgetButton {objectName:"showTaskProcess";primary:!root.deliveryMode;text:root.t("工作过程","Work history");enabled:!root.request;onClicked:{root.deliveryMode=false;root.showAttempt(root.attemptIndex,0,false)}}
            }
            LabelText {Layout.fillWidth:true;visible:root.deliveryMode && !!root.detail && !root.detail.hasDeliveries;color:root.c.muted;text:root.t("这次没有交付文件。请在聊天中查看回复，或切换到工作过程。","No files were delivered. Review the reply in chat or open Work history.")}
            LabelText {Layout.fillWidth:true;visible:!!root.request && !root.checking;text:root.t("正在读取…","Loading…");color:root.c.muted}
            RowLayout {
                Layout.fillWidth:true;Layout.fillHeight:true;spacing:4
                ListView {
                    id:timeline;objectName:"taskTimeline";Layout.fillWidth:true;Layout.fillHeight:true;clip:true;spacing:8;model:root.nodes
                    ScrollBar.vertical:ScrollBar{}
                    onContentYChanged:{const index=indexAt(20,contentY+10);if(index>=0)root.selectedNode=index}
                    onMovementEnded:{const end=atYEnd;const start=atYBeginning;if(end)root.edgePage(1);else if(start)root.edgePage(-1)}
                    WheelHandler {acceptedDevices:PointerDevice.Mouse;onWheel:event=>{if(timeline.atYEnd && event.angleDelta.y<0)root.edgePage(1);else if(timeline.atYBeginning && event.angleDelta.y>0)root.edgePage(-1)}}
                    delegate:Item {
                        id:node;required property var modelData;required property int index;width:ListView.view.width;height:nodeCard.height
                        property bool expanded:false
                        Rectangle {x:5;y:0;width:1;height:parent.height+timeline.spacing;color:root.c.line}
                        Rectangle {x:2;y:15;width:7;height:7;radius:4;color:root.tone(modelData.kind==="tool"?"tool":modelData.kind==="message"?"message":modelData.kind==="input"?"input":modelData.code)}
                        Card {
                            id:nodeCard;x:17;width:parent.width-20;implicitHeight:nodeContent.implicitHeight+20;code:node.modelData.kind==="message"?"message":node.modelData.kind==="tool"?"tool":node.modelData.kind==="input"?"input":node.modelData.code
                            border.width:root.selectedNode===node.index?2:1
                            ColumnLayout {id:nodeContent;anchors.left:parent.left;anchors.right:parent.right;anchors.top:parent.top;anchors.margins:10;spacing:5
                                LabelText {Layout.fillWidth:true;text:root.nodeTitle(node.modelData);font.bold:true}
                                LabelText {Layout.fillWidth:true;text:root.timeText(node.modelData.time);color:root.c.muted;font.pixelSize:10*root.sdk.scale}
                                LabelText {Layout.fillWidth:true;text:root.nodeBody(node.modelData);maximumLineCount:node.expanded?100:3;elide:Text.ElideRight}
                                LabelText {Layout.fillWidth:true;visible:node.expanded;text:(node.modelData.reference || "")+(node.modelData.file?"\n"+node.modelData.file.path+"\n"+root.t("上次检查：","Last check: ")+(node.modelData.file.checked?root.timeText(node.modelData.file.checked)+" · "+root.status(node.modelData.file.check_result):root.t("尚未检查","Not checked")):"");color:root.c.muted}
                                RowLayout {
                                    WidgetButton {objectName:node.modelData.file?"viewTaskFile_"+node.modelData.file.id:"";visible:!!node.modelData.file;enabled:!root.request;text:root.t("查看文件","View file");onClicked:root.call("preview",{taskId:root.taskId,attemptId:root.attempt.id,fileId:node.modelData.file.id})}
                                    WidgetButton {text:node.expanded?root.t("收起","Collapse"):root.t("详情","Details");onClicked:node.expanded=!node.expanded}
                                }
                            }
                        }
                    }
                }
                Item {
                    id:rail;objectName:"taskTimelineRail";Layout.preferredWidth:24;Layout.fillHeight:true;visible:root.nodes.length>0
                    Column {anchors.top:parent.top;anchors.topMargin:6;anchors.horizontalCenter:parent.horizontalCenter;spacing:4
                        Repeater {model:root.nodes
                            delegate:Rectangle {id:dot;required property var modelData;required property int index;objectName:"taskTimelineNode_"+index;width:20;height:Math.max(8,Math.min(16,(rail.height-20)/Math.max(1,root.nodes.length)-4));color:"transparent"
                                Rectangle {anchors.centerIn:parent;width:root.selectedNode===dot.index?9:5;height:width;radius:3;color:root.tone(dot.modelData.kind==="message"?"message":dot.modelData.kind==="tool"?"tool":dot.modelData.code)}
                                HoverHandler {id:dotHover;onHoveredChanged:if(hovered){root.navigationOpen=true;navList.positionViewAtIndex(dot.index,ListView.Contain)}}
                                TapHandler {onTapped:root.jump(dot.index)}
                                Accessible.role:Accessible.Button;Accessible.name:root.timeText(modelData.time)+" · "+root.nodeTitle(modelData);Accessible.onPressAction:root.jump(index)
                            }
                        }
                        WidgetButton {text:"≡";onClicked:root.navigationOpen=!root.navigationOpen;Accessible.name:root.t("时间节点导航","Timeline navigation")}
                    }
                }
            }
            LabelText {visible:root.detailOffset>0 || !!(root.detail && root.detail.hasMore);Layout.fillWidth:true;color:root.c.muted;text:root.t("滚动到边缘继续浏览；右侧节点可预览并跳转。","Scroll at an edge for more; preview and jump with the nodes on the right.")}
            Card {
                visible:root.checking || root.checkResult!==null;code:"running";Layout.fillWidth:true;implicitHeight:checkText.implicitHeight+16
                LabelText {id:checkText;objectName:"taskCheckResult";anchors.fill:parent;anchors.margins:8;text:root.checking?root.t("正在检查交付文件…","Checking delivered files…"):root.checkResult?root.t("已检查 ","Checked ")+root.checkResult.total+root.t(" 个文件 · "," files · ")+root.timeText(root.checkResult.checked)+"\n"+Timeline.checkSummary(root.checkResult).map(row=>root.status(row.code)+" "+row.count).join(" · "):""}
            }
            LabelText {Layout.fillWidth:true;visible:!!root.detail && root.detail.hasDeliveries;color:root.c.muted;font.pixelSize:10*root.sdk.scale;text:root.t("文件检查仅比较文件元信息，不能判断内容是否正确。请查看交付后再确认完成。","File checks compare metadata only. Review the content before confirming completion.")}
            RowLayout {
                Layout.fillWidth:true;visible:!!root.detail
                WidgetButton {objectName:"verifyTaskArtifacts";visible:!!root.detail && root.detail.hasDeliveries;enabled:!root.request; text:root.checking?root.t("检查中…","Checking…"):root.t("检查交付文件","Check delivered files");onClicked:{root.checking=true;if(!root.call("verify",{taskId:root.taskId,attemptId:root.attempt.id}))root.checking=false}}
                WidgetButton {objectName:"acceptTaskAttempt";primary:true;enabled:!root.request && !!root.attempt && root.attemptOffset===0 && root.attemptIndex===0 && root.attempt.state==="finished" && !root.attempt.accepted;text:root.t("确认完成…","Confirm completion…");onClicked:root.confirmingAccept=true}
            }
            ColumnLayout {
                visible:root.confirmingAccept;Layout.fillWidth:true
                LabelText {Layout.fillWidth:true;text:root.t("你已查看交付内容，并确认这次工作符合目标？这会记录你的确认时间。","Have you reviewed the delivery and confirmed it meets the goal? This records your confirmation time.")}
                RowLayout {
                    WidgetButton {objectName:"confirmTaskAcceptance";primary:true;enabled:!root.request;text:root.t("是，确认完成","Yes, confirm completion");onClicked:root.call("accept",{taskId:root.taskId,attemptId:root.attempt.id})}
                    WidgetButton {text:root.t("再看看","Review more");onClicked:root.confirmingAccept=false}
                }
            }
            WidgetButton {objectName:"prepareTaskAttempt";Layout.fillWidth:true;visible:root.attempts.length>0 && root.linked!==root.taskId;enabled:!root.request && !root.sessionBusy && root.canLink;primary:!(root.attempt && root.attempt.state==="finished" && !root.attempt.accepted)
                text:root.t("去当前聊天继续…","Continue in this chat…");onClicked:{root.call("link",{taskId:root.taskId})}}
            LabelText {visible:root.attempts.length>0 && root.linked!==root.taskId;Layout.fillWidth:true;color:root.c.muted;font.pixelSize:10*root.sdk.scale;text:root.canLink?root.t("继续时新增一条工作记录；若换了聊天，请在消息中提供所需上下文。","Continuing creates a new work record. If using another chat, include the context it needs."):root.t("请先切换到同一项目的空闲聊天，再打开此记录继续。","Open this record from an idle chat in the same project to continue.")}
            WidgetButton {Layout.fillWidth:true;text:root.technical?root.t("收起记录信息","Hide record information"):root.t("范围与记录信息…","Scope and record information…");onClicked:root.technical=!root.technical}
            ScrollView {visible:root.technical;Layout.fillWidth:true;Layout.preferredHeight:110;clip:true
                TextArea {objectName:"taskAttemptDetails";readOnly:true;selectByMouse:true;wrapMode:TextEdit.Wrap;color:root.c.muted;font.pixelSize:10*root.sdk.scale;text:root.task?root.t("允许处理的范围：","Scope: ")+root.task.scope+"\n"+root.task.project+"\n"+root.task.id+(root.detail?"\n"+root.detail.session_id+"\n"+root.detail.session_file+"\n"+root.detail.files.map(row=>row.path).join("\n"):""):""}}
            RowLayout {visible:root.technical
                WidgetButton {enabled:!root.request && !(root.attempts.length && root.attempts[0].state==="running");text:root.confirmingDelete?root.t("确认删除记录","Confirm deletion"):root.t("删除记录…","Delete record…");onClicked:{if(root.confirmingDelete)root.call("delete",{taskId:root.taskId});else root.confirmingDelete=true}}
                WidgetButton {visible:root.confirmingDelete;text:root.t("取消","Cancel");onClicked:root.confirmingDelete=false}}
            LabelText {visible:root.confirmingDelete;Layout.fillWidth:true;color:root.c.muted;text:root.t("只删除记录，聊天和项目文件将保留。","Deletes the record only. Chats and project files are kept.")}
        }
    }
    Rectangle {
        id:navPreview;objectName:"taskTimelinePreview";visible:root.navigationOpen && root.view==="task" && root.nodes.length>0;z:10
        anchors.right:parent.right;anchors.rightMargin:42;anchors.top:parent.top;anchors.topMargin:150
        width:Math.min(parent.width-56,310);height:Math.min(parent.height-175,360);radius:10;color:root.c.surface;border.color:root.c.line
        HoverHandler {id:previewHover}
        ColumnLayout {anchors.fill:parent;anchors.margins:8;spacing:5
            RowLayout {LabelText {Layout.fillWidth:true;text:root.t("本段时间节点 · 点击跳转","Page timeline · click to jump");font.bold:true}WidgetButton {text:"×";onClicked:root.navigationOpen=false}}
            ListView {id:navList;Layout.fillWidth:true;Layout.fillHeight:true;clip:true;model:root.nodes;ScrollBar.vertical:ScrollBar{}
                delegate:ItemDelegate {id:nav;required property var modelData;required property int index;width:ListView.view.width
                    background:Rectangle {radius:6;color:nav.hovered || root.selectedNode===nav.index?root.c.hover:"transparent"}
                    contentItem:Column {spacing:4;LabelText {width:parent.width;text:root.timeText(nav.modelData.time)+" · "+root.nodeTitle(nav.modelData);maximumLineCount:1;elide:Text.ElideRight}
                        LabelText {width:parent.width;text:root.nodeBody(nav.modelData);maximumLineCount:1;elide:Text.ElideRight;color:root.c.muted}}
                    onClicked:root.jump(index)}
            }
        }
    }
}
