import QtQuick
import QtQuick.Controls
import QtQuick.Controls.impl
import QtQuick.Layouts
Rectangle {
    id: root
    objectName: "globalAgentsPage"
    required property var sdk
    readonly property var c: sdk.colors
    property var state: ({agents:[],targets:[],projects:[],appearances:[],models:[],requests:[],messages:[],queue:[]})
    property string selected: ""
    property string section: "agents"
    property string error: ""
    property string snapshotSelection: ""
    property bool polling: false
    property var pending: ({})
    property string editing: ""
    property string chosenCharacter: ""
    property string deleteId: ""
    property string proposalId: ""
    property string proposalSource: ""
    property string dismissedProposalId: ""
    property bool formSubmitting: false
    property var collapsedProjects: ({})
    property string busSessionId: ""
    readonly property var busSession: state.targets.find(row=>row.id===busSessionId) || ({})
    property var queuePreview: ({})
    QtObject {
        id:busQueueController
        readonly property var queuedMessages:root.state.queue || []
        function steerQueued(id){root.call("prioritizeRequest",{id:id})}
        function removeQueued(id){root.call("cancelRequest",{id:id})}
        function copy(text){root.sdk.copyText(text)}
        function editQueued(id){}
    }
    property double clock: Date.now()
    function activityText(row) {
        const seconds=row.busySince?Math.max(0,Math.floor((clock-row.busySince)/1000)):0
        return row.busy?"busy: "+Math.floor(seconds/60)+"min"+String(seconds%60).padStart(2,"0")+"s":"idle"
    }
    Timer {interval:1000;repeat:true;running:root.sdk.active;onTriggered:root.clock=Date.now()}
    readonly property var current: state.agents.find(row => row.id===selected) || ({})
    readonly property string helpTitle: selected?"与子智能体对话":section==="bridge"?"Agent Bus（智能体总线）":section==="requests"?"请求":"全局子智能体"
    readonly property string helpText: selected?"连接的会话可双向发送任务和回复。总线消息按到达顺序排队，聊天上方可删除待处理消息或移到队首，优先处理不打断当前任务。输入框可手动 steering；停止会取消其未完成请求。":section==="bridge"?"展开项目并点击会话，进入二级列表。勾选对应的全局子智能体，建立与该会话的一条双向链路；双方均可发送任务并接收回复。关闭会取消这条链路上的未完成请求。":section==="requests"?"记录通过智能体总线分派的任务，查看投递状态、执行进度和返回结果。已投递不代表已完成；取消未完成的请求不会撤销已执行的操作。":"创建拥有独立上下文的子智能体，向已授权的对话分派任务。开启‘允许自动被创建’后，模型请求直接创建；关闭时需要你在预填表单中确认。模型未指定形象时随机分配，创建成功后自动连接来源对话。"
    color: c.surface
    function bridgeTree(projects, targets, query, collapsed) {
        // Pi returns native paths; saved projects may use forward slashes.
        const pathKey=path=>{
            let value=String(path || "").replace(/\\/g,"/")
            if(value.length>1)value=value.replace(/\/+$/,"")
            return Qt.platform.os==="windows"?value.toLowerCase():value
        }
        const names=Object.create(null), groups=Object.create(null)
        for(const project of projects)if(project.path)names[pathKey(project.path)]=project.name || ""
        for(const target of targets) {
            if(target.kind!=="session")continue
            const key=pathKey(target.workspace)
            if(!groups[key]) {
                const parts=key.replace(/\\/g,"/").split("/").filter(Boolean)
                groups[key]={key:key,name:names[key] || parts[parts.length-1] || (key?key:"未选择项目"),path:key,chats:[]}
            }
            groups[key].chats.push(target)
        }
        const needle=(query || "").trim().toLowerCase(), rows=[]
        const ordered=Object.values(groups).sort((a,b)=>a.name.localeCompare(b.name) || a.key.localeCompare(b.key))
        for(const group of ordered) {
            const projectMatches=!needle || (group.name+" "+group.path).toLowerCase().includes(needle)
            const chats=group.chats.filter(row=>projectMatches || (row.title || "新会话").toLowerCase().includes(needle))
            if(!chats.length)continue
            const closed=!needle && !!collapsed[group.key]
            rows.push({kind:"project",key:group.key,title:group.name,path:group.path,count:chats.length,collapsed:closed})
            if(!closed)for(const chat of chats)rows.push(Object.assign({},chat,{kind:"session",key:chat.id}))
        }
        return rows
    }
    function toggleProject(key) {
        const next=Object.assign({},collapsedProjects);next[key]=!next[key];collapsedProjects=next
    }
    ListModel {id:busRows;dynamicRoles:true}
    function updateBusTree() {
        const rows=bridgeTree(state.projects || [],state.targets,bridgeSearch.text,collapsedProjects)
        // Keep delegates and the visible project anchored while a background
        // snapshot changes status or the user expands/collapses a long tree.
        for(let i=0;i<rows.length;i++) {
            let existing=i
            while(existing<busRows.count && busRows.get(existing).rowData.key!==rows[i].key)existing++
            if(existing===busRows.count)busRows.insert(i,{rowData:rows[i]})
            else {
                if(existing!==i)busRows.move(existing,i,1)
                if(JSON.stringify(busRows.get(i).rowData)!==JSON.stringify(rows[i]))busRows.setProperty(i,"rowData",rows[i])
            }
        }
        if(busRows.count>rows.length)busRows.remove(rows.length,busRows.count-rows.length)
    }
    onStateChanged:updateBusTree()
    onCollapsedProjectsChanged:updateBusTree()
    function call(method,args) {
        const id=sdk.call(method,args || {})
        if(!id){error="服务忙，请稍后重试";return}
        const next=Object.assign({},pending);next[id]=method;pending=next
        return id
    }
    ListModel {id:chatRows;dynamicRoles:true}
    function updateMessages(rows) {
        while(chatRows.count>rows.length)chatRows.remove(chatRows.count-1)
        for(let i=0;i<rows.length;i++) {
            const row=rows[i]
            if(i>=chatRows.count)chatRows.append({rowData:row})
            else if(JSON.stringify(chatRows.get(i).rowData)!==JSON.stringify(row))chatRows.setProperty(i,"rowData",row)
        }
    }
    function refresh() {if(!polling){snapshotSelection=selected;polling=!!call("snapshot",{selected:selected,revision:state.selectedId===selected?state.revision:-1})}}
    function openAgent(id) {chatRows.clear();selected=id;section="agents";conversation.following=true;refresh()}
    function form(id) {
        proposalId="";proposalSource="";formSubmitting=false
        editing=id || ""
        const row=state.agents.find(value=>value.id===editing) || ({})
        nameInput.text=row.autoName?"":row.name || ""
        instructions.text=row.instructions || ""
        chosenCharacter=state.appearances.some(value=>value.id===row.character)?row.character:(state.defaultCharacter || "")
        let index=state.models.findIndex(value=>value.id===(row.model || state.defaultModel))
        modelPicker.currentIndex=Math.max(0,index)
        formError.text="";createDialog.open()
    }
    function showCreationDraft() {
        const draft=state.creationDraft || ({})
        if(proposalId && proposalId!==draft.requestId && !formSubmitting){proposalId="";proposalSource="";createDialog.close()}
        if(!draft.requestId || draft.requestId===dismissedProposalId || createDialog.opened || formSubmitting)return
        form("")
        proposalId=draft.requestId;proposalSource=draft.sourceTitle || "会话"
        nameInput.text=draft.name || "";instructions.text=draft.instructions || "";chosenCharacter=draft.character
        modelPicker.currentIndex=state.models.findIndex(row=>row.id===draft.model)
    }
    function abandonCreation() {
        if(proposalId && !formSubmitting){const request=proposalId;dismissedProposalId=request;proposalId="";proposalSource="";call("cancelCreation",{requestId:request})}
    }
    function submitForm() {
        if(formSubmitting)return
        const model=state.models[modelPicker.currentIndex]
        if(!model){formError.text="请先在设置中添加模型供应商";return}
        formSubmitting=!!call(editing?"update":proposalId?"confirmCreation":"create",{id:editing,requestId:proposalId,name:nameInput.text,character:chosenCharacter,model:model.id,instructions:instructions.text})
    }
    function send() {
        const text=input.text.trim();if(!text || !selected)return
        call("send",{id:selected,text:text})
    }
    Component.onCompleted: refresh()
    Timer {interval:650;repeat:true;running:root.sdk.active;onTriggered:root.refresh()}
    Connections {
        target:root.sdk
        function onResponse(id,value) {
            if(!root.pending[id])return
            const method=root.pending[id];const next=Object.assign({},root.pending);delete next[id];root.pending=next
            if(["create","update","confirmCreation"].includes(method))root.formSubmitting=false
            if(method==="snapshot")root.polling=false
            if(!value.ok){root.error=value.error || "操作失败";if(createDialog.opened)formError.text=root.error;return}
            root.error=""
            if(method==="snapshot") {
                if(root.snapshotSelection!==root.selected){Qt.callLater(root.refresh);return}
                const data=value.result
                if(data.unchanged)return
                root.updateMessages(data.messages)
                if(root.state.revision!==data.revision || root.state.currentTarget!==data.currentTarget || JSON.stringify(root.state.messages)!==JSON.stringify(data.messages) || JSON.stringify(root.state.targets)!==JSON.stringify(data.targets) || JSON.stringify(root.state.projects)!==JSON.stringify(data.projects) || root.state.defaultCharacter!==data.defaultCharacter || JSON.stringify(root.state.appearances)!==JSON.stringify(data.appearances) || JSON.stringify(root.state.models)!==JSON.stringify(data.models) || JSON.stringify(root.state.approval)!==JSON.stringify(data.approval))root.state=data
                // The first snapshot initializes defaults even at revision zero.
                if(!root.state.defaultCharacter)root.state=data
                Qt.callLater(root.showCreationDraft)
            } else {
                if(method==="create" || method==="confirmCreation"){root.dismissedProposalId=root.proposalId;root.proposalId="";root.proposalSource="";root.selected=value.result.id;root.section="agents";createDialog.close()}
                if(method==="update")createDialog.close()
                if(method==="send")input.clear()
                if(method==="delete"){root.selected="";deleteDialog.close()}
                root.refresh()
            }
        }
    }
    component LabelText: Text {
        color:root.c.ink;font.pixelSize:14*root.sdk.scale;textFormat:Text.PlainText
        elide:Text.ElideRight
    }
    component SmallButton: Button {
        id:button
        property bool primary:false
        property bool dangerous:false
        font.pixelSize:13*root.sdk.scale
        implicitHeight:36;leftPadding:12;rightPadding:12
        contentItem:Text {text:button.text;color:button.dangerous?root.c.danger:button.primary?"white":root.c.ink;font:button.font;horizontalAlignment:Text.AlignHCenter;verticalAlignment:Text.AlignVCenter;opacity:button.enabled?1:0.4}
        background:Rectangle {radius:10;color:button.primary?root.c.accent:button.down?root.c.hover:root.c.bg;border.color:button.primary?root.c.accent:root.c.line;border.width:1;opacity:button.enabled?1:0.6}
    }
    component Field: TextField {
        color:root.c.ink;selectionColor:root.c.accent;selectedTextColor:"white";font.pixelSize:14*root.sdk.scale
        placeholderTextColor:root.c.muted;implicitHeight:42;leftPadding:12;rightPadding:12
        background:Rectangle {radius:10;color:root.c.bg;border.color:parent.activeFocus?root.c.accent:root.c.line}
    }
    component TreeIcon: IconImage {
        property string iconName
        source:"../assets/"+iconName+".svg";color:root.c.muted
        sourceSize:Qt.size(32,32);Layout.preferredWidth:16*root.sdk.scale;Layout.preferredHeight:16*root.sdk.scale
    }
    component CompactCheckBox: CheckBox {
        id:check
        implicitHeight:28*root.sdk.scale;spacing:8*root.sdk.scale;padding:0
        contentItem:Text {text:check.text;color:root.c.ink;font.pixelSize:12*root.sdk.scale;leftPadding:24*root.sdk.scale;verticalAlignment:Text.AlignVCenter}
        indicator:Rectangle {
            x:2*root.sdk.scale;anchors.verticalCenter:parent.verticalCenter;width:16*root.sdk.scale;height:width;radius:3
            color:check.checked?root.c.accent:root.c.surface;border.color:check.checked || check.activeFocus?root.c.accent:root.c.muted
            TreeIcon {anchors.fill:parent;anchors.margins:1;iconName:"check";color:"white";visible:check.checked}
        }
    }
    ColumnLayout {
        anchors.fill:parent;anchors.margins:18;spacing:14
        RowLayout {
            Layout.fillWidth:true;spacing:10
            SmallButton {visible:!!root.selected;text:"‹";onClicked:{root.selected="";root.refresh()}}
            Image {visible:!!root.selected;source:root.current.portrait || "";Layout.preferredWidth:38;Layout.preferredHeight:38;fillMode:Image.PreserveAspectFit;sourceSize.width:76;sourceSize.height:76}
            ColumnLayout {
                Layout.fillWidth:true;spacing:3
                RowLayout {Layout.fillWidth:true;spacing:6
                    LabelText {objectName:"globalSubagentsHeading";text:root.selected?(root.current.name || "全局子智能体"):"全局子智能体";font.pixelSize:19*root.sdk.scale;font.weight:Font.DemiBold;Layout.fillWidth:true}
                    ToolButton {
                        id:helpButton;objectName:"globalSubagentsHelpButton";Layout.preferredWidth:28;Layout.preferredHeight:28
                        Accessible.name:"使用说明"
                        background:Rectangle {radius:8;color:helpButton.hovered?root.c.hover:"transparent"}
                        contentItem:Item {Rectangle {anchors.centerIn:parent;width:16;height:16;radius:8;color:"transparent";border.color:root.c.muted
                            Text {anchors.centerIn:parent;text:"?";color:root.c.muted;font.pixelSize:12}
                        }}
                        onClicked:helpPopup.open()
                    }
                }
                LabelText {visible:!!root.selected;text:root.activityText(root.current);color:root.c.muted;font.pixelSize:12*root.sdk.scale;Layout.fillWidth:true}
            }
            SmallButton {objectName:"newGlobalAgentButton";visible:!root.selected;text:"＋ 创建";primary:true;onClicked:root.form("")}
            SmallButton {visible:!!root.selected;text:"设置";onClicked:root.form(root.selected)}
        }
        RowLayout {
            visible:!root.selected;spacing:8
            SmallButton {objectName:"globalSubagentsTabButton";text:"子智能体  "+root.state.agents.length;primary:root.section==="agents";onClicked:root.section="agents"}
            SmallButton {objectName:"agentBusTabButton";text:"智能体总线";primary:root.section==="bridge";onClicked:root.section="bridge"}
            SmallButton {objectName:"agentBusRequestsTabButton";text:"请求";primary:root.section==="requests";onClicked:root.section="requests"}
        }
        CompactCheckBox {objectName:"allowAutomaticGlobalCreation";visible:!root.selected && root.section==="agents";text:"允许自动被创建";checked:!!root.state.allowAutomaticCreation;onToggled:root.call("setAutomaticCreation",{enabled:checked})}
        LabelText {visible:!!root.error || !!root.state.error;text:root.error || root.state.error || "";color:root.c.danger;wrapMode:Text.Wrap;elide:Text.ElideNone;Layout.fillWidth:true}
        StackLayout {
            Layout.fillWidth:true;Layout.fillHeight:true
            currentIndex:root.selected?3:root.section==="agents"?0:root.section==="bridge"?1:2
            Item {
                ColumnLayout {anchors.centerIn:parent;spacing:12;visible:!root.state.agents.length
                    LabelText {text:"暂无全局子智能体";color:root.c.muted;Layout.alignment:Qt.AlignHCenter}
                    SmallButton {objectName:"createFirstGlobalAgentButton";text:"创建第一个全局子智能体";primary:true;Layout.alignment:Qt.AlignHCenter;onClicked:root.form("")}
                }
                ListView {
                    objectName:"globalAgentsList"
                    // An empty Flickable still grabs presses over the empty-state button.
                    visible:count>0
                    anchors.fill:parent;spacing:10;clip:true;model:root.state.agents
                    delegate:Rectangle {
                        required property var modelData
                        width:ListView.view.width;height:88;radius:14;color:agentHover.hovered?root.c.hover:root.c.bg;border.color:root.c.line
                        HoverHandler {id:agentHover}
                        TapHandler {onTapped:root.openAgent(modelData.id)}
                        RowLayout {anchors.fill:parent;anchors.margins:14;spacing:14
                            Image {source:modelData.portrait;Layout.preferredWidth:54;Layout.preferredHeight:54;fillMode:Image.PreserveAspectFit;sourceSize.width:108;sourceSize.height:108}
                            ColumnLayout {Layout.fillWidth:true;spacing:5
                                LabelText {text:modelData.name;Layout.fillWidth:true;font.weight:Font.Medium}
                                LabelText {text:root.activityText(modelData)+(modelData.queued?" · 待处理 "+modelData.queued:"");color:root.c.accent;font.pixelSize:12*root.sdk.scale;Layout.fillWidth:true}
                            }
                            LabelText {text:"›";color:root.c.muted;font.pixelSize:24}
                        }
                    }
                }
            }
            ColumnLayout {
                spacing:8
                RowLayout {
                    visible:!!root.busSessionId;Layout.fillWidth:true;spacing:8
                    SmallButton {objectName:"agentBusBackButton";text:"‹";onClicked:root.busSessionId=""}
                    LabelText {objectName:"agentBusConnectionHeading";text:root.busSession.title || "新会话";font.pixelSize:13*root.sdk.scale;Layout.fillWidth:true}
                    TreeIcon {iconName:"link"}
                    LabelText {text:"全局子智能体";font.pixelSize:12*root.sdk.scale;color:root.c.muted}
                }
                Field {id:bridgeSearch;objectName:"agentBusSearch";visible:!root.busSessionId;Layout.fillWidth:true;implicitHeight:32*root.sdk.scale;font.pixelSize:13*root.sdk.scale;placeholderText:"搜索项目或对话";onTextChanged:root.updateBusTree()}
                ListView {
                    objectName:"agentBusProjectTree";visible:!root.busSessionId
                    Layout.fillWidth:true;Layout.fillHeight:true;clip:true;spacing:0
                    boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar{}
                    model:busRows
                    delegate:Item {
                        id:treeRow
                        required property var rowData
                        readonly property var modelData:rowData
                        readonly property bool project:modelData.kind==="project"
                        objectName:project?"agentBusProject_"+modelData.key:"agentBusConversation_"+modelData.id
                        width:ListView.view.width;height:28*root.sdk.scale
                        Rectangle {anchors.fill:parent;radius:3;color:treeHover.hovered?root.c.hover:"transparent"}
                        Rectangle {visible:!treeRow.project;x:12*root.sdk.scale;width:1;height:parent.height;color:root.c.line;opacity:0.6}
                        HoverHandler {id:treeHover}
                        TapHandler {onTapped:{if(treeRow.project)root.toggleProject(modelData.key);else root.busSessionId=modelData.id}}
                        ToolTip.visible:treeHover.hovered && treeRow.project && !!modelData.path
                        ToolTip.delay:600;ToolTip.timeout:5000;ToolTip.text:modelData.path || ""
                        RowLayout {
                            anchors.fill:parent;anchors.leftMargin:(treeRow.project?2:26)*root.sdk.scale;anchors.rightMargin:4*root.sdk.scale;spacing:5*root.sdk.scale
                            TreeIcon {visible:treeRow.project;iconName:modelData.collapsed?"chevron-right":"chevron-down"}
                            TreeIcon {iconName:treeRow.project?"folder":"chat";color:!treeRow.project && !!modelData.busy?root.c.accent:root.c.muted}
                            LabelText {text:modelData.title || "新会话";font.pixelSize:13*root.sdk.scale;font.weight:treeRow.project?Font.Medium:Font.Normal;Layout.fillWidth:true}
                            LabelText {text:treeRow.project?String(modelData.count):String((modelData.bridgeAgents || []).length);color:root.c.muted;font.pixelSize:12*root.sdk.scale}
                            LabelText {visible:!treeRow.project;text:"›";color:root.c.muted}
                        }
                    }
                    LabelText {anchors.centerIn:parent;visible:parent.count===0;text:bridgeSearch.text?"没有匹配的项目或对话":"暂无对话";color:root.c.muted}
                }
                ListView {
                    objectName:"agentBusConnectionsList";visible:!!root.busSessionId
                    Layout.fillWidth:true;Layout.fillHeight:true;clip:true;spacing:2
                    model:root.state.agents
                    delegate:RowLayout {
                        required property var modelData
                        width:ListView.view.width;height:40*root.sdk.scale;spacing:8
                        Image {source:modelData.portrait;Layout.preferredWidth:26*root.sdk.scale;Layout.preferredHeight:26*root.sdk.scale;fillMode:Image.PreserveAspectFit;sourceSize.width:52;sourceSize.height:52}
                        TreeIcon {iconName:"link";color:root.c.muted}
                        LabelText {text:modelData.name;Layout.fillWidth:true;font.pixelSize:13*root.sdk.scale}
                        LabelText {text:root.activityText(modelData);color:root.c.muted;font.pixelSize:11*root.sdk.scale}
                        CompactCheckBox {
                            objectName:"agentBusCheckbox_"+root.busSessionId+"_"+modelData.id
                            checked:!!root.busSession.bridgeAll || (root.busSession.bridgeAgents || []).includes(modelData.id)
                            text:"";Layout.preferredWidth:24*root.sdk.scale
                            Accessible.name:(root.busSession.title || "会话")+" 与 "+modelData.name+"的双向连接"
                            onToggled:root.call("setBridge",{id:root.busSessionId,agentId:modelData.id,enabled:checked})
                        }
                    }
                    LabelText {anchors.centerIn:parent;visible:!root.state.agents.length;text:"暂无全局子智能体";color:root.c.muted}
                }
            }
            ListView {
                clip:true;spacing:10;model:root.state.requests.slice().reverse()
                delegate:Rectangle {
                    required property var modelData
                    width:ListView.view.width;height:requestText.implicitHeight+56;radius:12;color:root.c.bg;border.color:root.c.line
                    ColumnLayout {anchors.fill:parent;anchors.margins:12;spacing:7
                        RowLayout {Layout.fillWidth:true
                            LabelText {text:({queued:"等待投递",sending:"投递中",running:"已投递 · 等待结果",completed:"已完成",failed:"失败",cancelled:"已取消",interrupted:"已中断"})[modelData.status] || modelData.status;color:modelData.status==="failed"?root.c.danger:root.c.accent;Layout.fillWidth:true;font.pixelSize:12*root.sdk.scale}
                            LabelText {text:modelData.id.slice(0,8);color:root.c.muted;font.pixelSize:11*root.sdk.scale}
                            SmallButton {visible:!(["completed","failed","cancelled","interrupted"].includes(modelData.status));text:"取消";onClicked:root.call("cancelRequest",{id:modelData.id})}
                        }
                        LabelText {id:requestText;text:(modelData.result || modelData.text || "").slice(0,500);wrapMode:Text.Wrap;elide:Text.ElideNone;Layout.fillWidth:true;font.pixelSize:12*root.sdk.scale}
                    }
                }
                LabelText {anchors.centerIn:parent;visible:!root.state.requests.length;text:"暂无请求";color:root.c.muted}
            }
            ColumnLayout {
                spacing:12
                ListView {
                    id:conversation;objectName:"globalAgentConversation"
                    Layout.fillWidth:true;Layout.fillHeight:true;clip:true;spacing:16
                    model:chatRows
                    property bool following:true
                    onMovementEnded:following=atYEnd
                    onCountChanged:if(following)Qt.callLater(()=>positionViewAtEnd())
                    onContentHeightChanged:if(following)Qt.callLater(()=>positionViewAtEnd())
                    delegate:Loader {
                        id:messageRenderer
                        required property var rowData
                        required property int index
                        width:conversation.width;height:item?item.implicitHeight:0
                        sourceComponent:root.sdk.chatMessageComponent
                        onLoaded: {
                            item.message=Qt.binding(()=>messageRenderer.rowData)
                            item.messageIndex=Qt.binding(()=>messageRenderer.index)
                            item.assistantName=Qt.binding(()=>root.current.name || "子智能体")
                            item.portrait=Qt.binding(()=>root.current.portrait || "")
                            item.replyPortrait=Qt.binding(()=>root.current.replyPortrait || root.current.portrait || "")
                            item.busy=Qt.binding(()=>!!root.current.busy)
                            item.last=Qt.binding(()=>messageRenderer.index===chatRows.count-1)
                        }
                    }
                }
                Rectangle {
                    visible:!!root.state.approval && !!root.state.approval.id
                    Layout.fillWidth:true;implicitHeight:approvalBox.implicitHeight+24;radius:12;color:root.c.accentBg;border.color:root.c.accent
                    ColumnLayout {id:approvalBox;anchors.fill:parent;anchors.margins:12;spacing:8
                        LabelText {text:(root.state.approval || {}).title || "等待你的确认";font.weight:Font.Medium;Layout.fillWidth:true}
                        ScrollView {Layout.fillWidth:true;Layout.preferredHeight:Math.min(120,approvalDetail.implicitHeight);clip:true
                            TextArea {id:approvalDetail;text:((root.state.approval || {}).detail || "").slice(0,16000);readOnly:true;selectByMouse:true;wrapMode:TextArea.Wrap;color:root.c.ink;font.pixelSize:12*root.sdk.scale;background:null;padding:0}
                        }
                        Field {id:approvalInput;visible:["input","editor"].includes((root.state.approval || {}).method);Layout.fillWidth:true;placeholderText:"回复"}
                        ComboBox {id:approvalChoice;visible:(root.state.approval || {}).method==="select";model:(root.state.approval || {}).options || [];Layout.fillWidth:true}
                        RowLayout {Layout.fillWidth:true;Item {Layout.fillWidth:true}
                            SmallButton {text:"拒绝";onClicked:root.call("respond",{id:root.selected,requestId:root.state.approval.id,value:root.state.approval.method==="confirm"?false:null})}
                            SmallButton {objectName:"confirmGlobalAgentApproval";text:"确认";primary:true;onClicked:root.call("respond",{id:root.selected,requestId:root.state.approval.id,value:root.state.approval.method==="confirm"?true:root.state.approval.method==="select"?approvalChoice.currentText:approvalInput.text})}
                        }
                    }
                }
                ColumnLayout {
                    Layout.fillWidth:true;spacing:0
                    Loader {
                        id:busQueue;objectName:"globalAgentPendingQueue"
                        Layout.fillWidth:true;Layout.preferredHeight:item?item.implicitHeight:0
                        visible:Layout.preferredHeight>0
                        sourceComponent:root.sdk.queuedMessagesComponent
                        onLoaded:{item.controller=busQueueController;item.objectPrefix="global_bus_";item.primaryActionText="优先";item.showSourceNames=true;item.editEnabled=false;item.heightLimit=170*root.sdk.scale}
                        Connections {target:busQueue.item;function onInspected(message){root.queuePreview=message;queueMessageDialog.open()}}
                    }
                Rectangle {
                    Layout.fillWidth:true;implicitHeight:Math.min(180,Math.max(88,input.contentHeight+24));radius:14;color:root.c.bg;border.color:input.activeFocus?root.c.accent:root.c.line
                    ScrollView {anchors.fill:parent;anchors.margins:10;clip:true
                        TextArea {id:input;objectName:"globalAgentInput";placeholderText:root.current.busy?"补充或引导当前任务…":"输入任务…";color:root.c.ink;placeholderTextColor:root.c.muted;selectionColor:root.c.accent;selectedTextColor:"white";wrapMode:TextArea.Wrap;font.pixelSize:14*root.sdk.scale;background:null;Keys.onPressed:event=>{if((event.key===Qt.Key_Return || event.key===Qt.Key_Enter) && !input.inputMethodComposing && !(event.modifiers&Qt.ShiftModifier)){root.send();event.accepted=true}}}
                    }
                }
                }
                RowLayout {Layout.fillWidth:true;spacing:8
                    SmallButton {visible:root.current.busy || root.state.requests.some(row=>!(["completed","failed","cancelled","interrupted"].includes(row.status)) && row.source==="agent:"+root.selected);text:"停止";dangerous:true;onClicked:root.call("stop",{id:root.selected})}
                    Item {Layout.fillWidth:true}
                    LabelText {text:"Shift + Enter 换行";font.pixelSize:10*root.sdk.scale;color:root.c.muted}
                    SmallButton {objectName:"sendGlobalAgentButton";text:root.current.busy?"引导":"发送";primary:true;enabled:!!input.text.trim();onClicked:root.send()}
                }
            }
        }
    }
    Dialog {
        id:queueMessageDialog;objectName:"globalBusQueueMessageDialog";anchors.centerIn:parent
        width:Math.min(460,root.width-28);height:Math.min(420,root.height-28);modal:true;padding:16
        background:Rectangle {radius:14;color:root.c.surface;border.color:root.c.line}
        contentItem:ColumnLayout {spacing:10
            LabelText {text:root.queuePreview.sourceTitle || "待处理消息";font.weight:Font.Medium;Layout.fillWidth:true}
            ScrollView {Layout.fillWidth:true;Layout.fillHeight:true;clip:true
                TextArea {objectName:"globalBusQueuePreviewText";text:root.queuePreview.text || "";readOnly:true;selectByMouse:true;wrapMode:TextArea.Wrap;color:root.c.ink;font.pixelSize:13*root.sdk.scale;background:null}
            }
            SmallButton {text:"关闭";Layout.alignment:Qt.AlignRight;onClicked:queueMessageDialog.close()}
        }
    }
    Popup {
        id:helpPopup;objectName:"globalSubagentsHelpPopup";parent:root
        width:Math.min(340,root.width-36);x:Math.max(18,root.width-width-18);y:64
        padding:14;focus:true;closePolicy:Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background:Rectangle {radius:12;color:root.c.surface;border.color:root.c.line}
        contentItem:ColumnLayout {spacing:8
            LabelText {objectName:"globalSubagentsHelpTitle";text:root.helpTitle;font.weight:Font.Medium;Layout.fillWidth:true}
            LabelText {objectName:"globalSubagentsHelpText";text:root.helpText;wrapMode:Text.Wrap;elide:Text.ElideNone;Layout.fillWidth:true;font.pixelSize:12*root.sdk.scale}
        }
    }
    Dialog {
        id:createDialog;objectName:"createGlobalAgentDialog"
        anchors.centerIn:parent;width:Math.min(460,root.width-28);modal:true;closePolicy:Popup.CloseOnEscape
        padding:20;background:Rectangle {radius:18;color:root.c.surface;border.color:root.c.line}
        onClosed:{root.abandonCreation();Qt.callLater(root.showCreationDraft)}
        contentItem:ColumnLayout {
            spacing:14
            RowLayout {Layout.fillWidth:true
                LabelText {text:root.editing?"子智能体设置":"创建全局子智能体";font.pixelSize:18*root.sdk.scale;font.weight:Font.DemiBold;Layout.fillWidth:true}
                ToolButton {
                    id:closeForm;objectName:"cancelGlobalCreation";Layout.preferredWidth:28;Layout.preferredHeight:28
                    background:Rectangle {radius:6;color:closeForm.hovered?root.c.hover:"transparent"}
                    contentItem:Text {text:"×";font.pixelSize:20;color:root.c.muted;horizontalAlignment:Text.AlignHCenter;verticalAlignment:Text.AlignVCenter}
                    onClicked:createDialog.close()
                }
            }
            LabelText {objectName:"globalCreationSource";visible:!!root.proposalId;text:root.proposalSource?"来自 "+root.proposalSource:"";color:root.c.muted;font.pixelSize:12*root.sdk.scale;Layout.fillWidth:true}
            Field {id:nameInput;objectName:"globalAgentName";Layout.fillWidth:true;placeholderText:"名称（可选，留空使用人物名）";maximumLength:60}
            LabelText {text:"形象";font.pixelSize:12*root.sdk.scale;color:root.c.muted}
            ScrollView {
                Layout.fillWidth:true;Layout.preferredHeight:Math.min(180,appearanceFlow.implicitHeight)
                clip:true;ScrollBar.horizontal.policy:ScrollBar.AlwaysOff
                Flow {
                id:appearanceFlow;width:parent.width;spacing:8
                Repeater {model:root.state.appearances
                    delegate:Rectangle {
                        required property var modelData
                        width:80;height:90;radius:12;color:root.chosenCharacter===modelData.id?root.c.accentBg:root.c.bg;border.color:root.chosenCharacter===modelData.id?root.c.accent:root.c.line
                        TapHandler {onTapped:root.chosenCharacter=modelData.id}
                        Column {anchors.centerIn:parent;spacing:5
                            Image {anchors.horizontalCenter:parent.horizontalCenter;source:modelData.portrait;width:52;height:52;fillMode:Image.PreserveAspectFit;sourceSize.width:104;sourceSize.height:104}
                            LabelText {text:modelData.name;font.pixelSize:11*root.sdk.scale;width:72;horizontalAlignment:Text.AlignHCenter}
                        }
                    }
                }
            }
            }
            LabelText {text:"模型";font.pixelSize:12*root.sdk.scale;color:root.c.muted}
            ComboBox {id:modelPicker;objectName:"globalAgentModel";Layout.fillWidth:true;model:root.state.models;textRole:"id";font.pixelSize:13*root.sdk.scale
                implicitHeight:42;leftPadding:12;rightPadding:30
                contentItem:Text {text:modelPicker.displayText;color:root.c.ink;verticalAlignment:Text.AlignVCenter;font:modelPicker.font;elide:Text.ElideRight}
                indicator:Text {text:"⌄";color:root.c.muted;x:parent.width-24;y:parent.height/2-height/2}
                background:Rectangle {radius:10;color:root.c.bg;border.color:modelPicker.activeFocus?root.c.accent:root.c.line}
            }
            Rectangle {Layout.fillWidth:true;implicitHeight:100;radius:10;color:root.c.bg;border.color:root.c.line
                ScrollView {anchors.fill:parent;anchors.margins:8;clip:true
                    TextArea {id:instructions;objectName:"globalAgentInstructions";placeholderText:"职责与偏好（可选）";color:root.c.ink;placeholderTextColor:root.c.muted;wrapMode:TextArea.Wrap;font.pixelSize:13*root.sdk.scale;background:null}
                }
            }
            LabelText {id:formError;visible:!!text;color:root.c.danger;wrapMode:Text.Wrap;elide:Text.ElideNone;Layout.fillWidth:true}
            RowLayout {Layout.fillWidth:true;spacing:8
                SmallButton {visible:!!root.editing;text:"删除";dangerous:true;onClicked:{root.deleteId=root.editing;deleteDialog.open()}}
                Item {Layout.fillWidth:true}
                SmallButton {text:"取消";onClicked:createDialog.close()}
                SmallButton {objectName:"confirmCreateGlobalAgent";text:root.editing?"保存":"创建";primary:true;enabled:!root.formSubmitting;onClicked:root.submitForm()}
            }
        }
    }
    Dialog {
        id:deleteDialog;anchors.centerIn:parent;width:Math.min(380,root.width-28);modal:true;padding:20
        background:Rectangle {radius:16;color:root.c.surface;border.color:root.c.line}
        contentItem:ColumnLayout {spacing:18
            LabelText {text:"删除这个全局子智能体？\n正在运行的任务会停止，原始上下文文件会保留。";wrapMode:Text.Wrap;elide:Text.ElideNone;Layout.fillWidth:true}
            RowLayout {Item {Layout.fillWidth:true}
                SmallButton {text:"取消";onClicked:deleteDialog.close()}
                SmallButton {text:"删除";dangerous:true;onClicked:{createDialog.close();root.call("delete",{id:root.deleteId})}}
            }
        }
    }
}
