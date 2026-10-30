import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Rectangle {
    id: root
    objectName: "globalAgentsPage"
    required property var sdk
    readonly property var c: sdk.colors
    property var state: ({agents:[],targets:[],projects:[],appearances:[],models:[],requests:[],messages:[]})
    property string selected: ""
    property string section: "agents"
    property string error: ""
    property string snapshotSelection: ""
    property bool polling: false
    property var pending: ({})
    property string editing: ""
    property string chosenCharacter: ""
    property string deleteId: ""
    property var collapsedProjects: ({})
    readonly property var current: state.agents.find(row => row.id===selected) || ({})
    color: c.surface
    function bridgeTree(projects, targets, query, collapsed) {
        const names=Object.create(null), groups=Object.create(null)
        for(const project of projects)if(project.path)names[project.path]=project.name || ""
        for(const target of targets) {
            if(target.kind!=="session")continue
            const key=target.workspace || ""
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
    function call(method,args) {
        const id=sdk.call(method,args || {})
        if(!id){error="服务忙，请稍后重试";return}
        const next=Object.assign({},pending);next[id]=method;pending=next
        return id
    }
    ListModel {id:chatRows}
    function updateMessages(rows) {
        while(chatRows.count>rows.length)chatRows.remove(chatRows.count-1)
        for(let i=0;i<rows.length;i++) {
            const row=rows[i]
            if(i>=chatRows.count)chatRows.append(row)
            else for(const key of Object.keys(row))if(chatRows.get(i)[key]!==row[key])chatRows.setProperty(i,key,row[key])
        }
    }
    function refresh() {if(!polling){snapshotSelection=selected;polling=!!call("snapshot",{selected:selected,revision:state.selectedId===selected?state.revision:-1})}}
    function openAgent(id) {chatRows.clear();selected=id;section="agents";conversation.following=true;refresh()}
    function form(id) {
        editing=id || ""
        const row=state.agents.find(value=>value.id===editing) || ({})
        nameInput.text=row.name || ""
        instructions.text=row.instructions || ""
        chosenCharacter=state.appearances.some(value=>value.id===row.character)?row.character:(state.defaultCharacter || "")
        let index=state.models.findIndex(value=>value.id===(row.model || state.defaultModel))
        modelPicker.currentIndex=Math.max(0,index)
        formError.text="";createDialog.open()
    }
    function submitForm() {
        if(!nameInput.text.trim()){formError.text="给子智能体起个名字吧";return}
        const model=state.models[modelPicker.currentIndex]
        if(!model){formError.text="请先在设置中添加模型供应商";return}
        call(editing ? "update" : "create",{id:editing,name:nameInput.text,character:chosenCharacter,model:model.id,instructions:instructions.text})
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
            } else {
                if(method==="create"){root.selected=value.result.id;root.section="agents";createDialog.close()}
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
                LabelText {visible:root.selected && !!root.current.busy;text:root.current.status || "运行中";color:root.c.muted;font.pixelSize:12*root.sdk.scale;Layout.fillWidth:true}
            }
            SmallButton {objectName:"newGlobalAgentButton";visible:!root.selected;text:"＋ 创建";primary:true;onClicked:root.form("")}
            SmallButton {visible:!!root.selected;text:"设置";onClicked:root.form(root.selected)}
        }
        RowLayout {
            visible:!root.selected;spacing:8
            SmallButton {objectName:"globalSubagentsTabButton";text:"子智能体  "+root.state.agents.length;primary:root.section==="agents";onClicked:root.section="agents"}
            SmallButton {objectName:"agentBusTabButton";text:"智能体总线";primary:root.section==="bridge";onClicked:root.section="bridge"}
            SmallButton {text:"请求";primary:root.section==="requests";onClicked:root.section="requests"}
        }
        LabelText {visible:!!root.error || !!root.state.error;text:root.error || root.state.error || "";color:root.c.danger;wrapMode:Text.Wrap;elide:Text.ElideNone;Layout.fillWidth:true}
        StackLayout {
            Layout.fillWidth:true;Layout.fillHeight:true
            currentIndex:root.selected?3:root.section==="agents"?0:root.section==="bridge"?1:2
            Item {
                ColumnLayout {anchors.centerIn:parent;spacing:12;visible:!root.state.agents.length
                    LabelText {text:"暂无全局子智能体";color:root.c.muted;Layout.alignment:Qt.AlignHCenter}
                    SmallButton {text:"创建第一个全局子智能体";primary:true;Layout.alignment:Qt.AlignHCenter;onClicked:root.form("")}
                }
                ListView {
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
                                LabelText {visible:!!modelData.busy;text:"运行中";color:root.c.accent;font.pixelSize:12*root.sdk.scale;Layout.fillWidth:true}
                            }
                            LabelText {text:"›";color:root.c.muted;font.pixelSize:24}
                        }
                    }
                }
            }
            ColumnLayout {
                spacing:10
                Field {id:bridgeSearch;objectName:"agentBusSearch";Layout.fillWidth:true;placeholderText:"搜索项目或对话"}
                ListView {
                    objectName:"agentBusProjectTree"
                    Layout.fillWidth:true;Layout.fillHeight:true;clip:true;spacing:2
                    model:root.bridgeTree(root.state.projects || [],root.state.targets,bridgeSearch.text,root.collapsedProjects)
                    delegate:Item {
                        id:treeRow
                        required property var modelData
                        readonly property bool project:modelData.kind==="project"
                        objectName:project?"agentBusProject_"+modelData.key:"agentBusConversation_"+modelData.id
                        width:ListView.view.width;height:project?44:56
                        Rectangle {anchors.fill:parent;radius:10;color:treeHover.hovered?root.c.hover:"transparent"}
                        HoverHandler {id:treeHover}
                        TapHandler {enabled:treeRow.project;onTapped:root.toggleProject(modelData.key)}
                        ToolTip.visible:treeHover.hovered && treeRow.project && !!modelData.path
                        ToolTip.delay:600;ToolTip.timeout:5000;ToolTip.text:modelData.path || ""
                        RowLayout {
                            anchors.fill:parent;anchors.leftMargin:treeRow.project?8:30;anchors.rightMargin:8;spacing:8
                            LabelText {visible:treeRow.project;text:modelData.collapsed?"▸":"▾";color:root.c.muted;Layout.preferredWidth:16}
                            Rectangle {visible:!treeRow.project && !!modelData.busy;Layout.preferredWidth:6;Layout.preferredHeight:6;radius:3;color:root.c.accent}
                            LabelText {text:modelData.title || "新会话";font.weight:treeRow.project?Font.Medium:Font.Normal;Layout.fillWidth:true}
                            LabelText {visible:treeRow.project;text:treeRow.project?String(modelData.count):"";color:root.c.muted;font.pixelSize:12*root.sdk.scale}
                            Switch {
                                objectName:treeRow.project?"":"agentBusSwitch_"+modelData.id
                                visible:!treeRow.project;checked:!!modelData.bridge
                                Accessible.name:(modelData.title || "新会话")+" · 智能体总线授权"
                                onToggled:root.call("setBridge",{id:modelData.id,enabled:checked})
                            }
                        }
                    }
                    LabelText {anchors.centerIn:parent;visible:parent.count===0;text:bridgeSearch.text?"没有匹配的项目或对话":"暂无对话";color:root.c.muted}
                }
            }
            ListView {
                clip:true;spacing:10;model:root.state.requests.slice().reverse()
                delegate:Rectangle {
                    required property var modelData
                    width:ListView.view.width;height:requestText.implicitHeight+56;radius:12;color:root.c.bg;border.color:root.c.line
                    ColumnLayout {anchors.fill:parent;anchors.margins:12;spacing:7
                        RowLayout {Layout.fillWidth:true
                            LabelText {text:({queued:"等待投递",running:"已投递 · 等待结果",completed:"已完成",failed:"失败",cancelled:"已取消",interrupted:"已中断"})[modelData.status] || modelData.status;color:modelData.status==="failed"?root.c.danger:root.c.accent;Layout.fillWidth:true;font.pixelSize:12*root.sdk.scale}
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
                    delegate:ColumnLayout {
                        required property string role
                        required property string text
                        required property string thinking
                        required property string name
                        required property string toolsText
                        required property bool error
                        readonly property var modelData:({role:role,text:text,thinking:thinking,name:name,toolsText:toolsText,error:error})
                        width:conversation.width;spacing:6
                        LabelText {text:modelData.role==="user"?"你":modelData.role==="assistant"?(root.current.name || "子智能体"):modelData.role==="custom"?"智能体总线":(modelData.name || "工具");color:root.c.muted;font.pixelSize:11*root.sdk.scale;Layout.fillWidth:true}
                        ToolButton {id:thoughtButton;background:null;visible:!!modelData.thinking;checkable:true;text:checked?"收起思考":"查看思考";font.pixelSize:11*root.sdk.scale;palette.buttonText:root.c.muted}
                        Text {visible:thoughtButton.checked && !!modelData.thinking;text:modelData.thinking || "";textFormat:Text.PlainText;color:root.c.muted;font.pixelSize:12*root.sdk.scale;wrapMode:Text.Wrap;Layout.fillWidth:true}
                        ToolButton {id:toolsButton;background:null;visible:!!modelData.toolsText;checkable:true;text:checked?"收起工具过程":"查看工具过程";font.pixelSize:11*root.sdk.scale;palette.buttonText:root.c.muted}
                        Text {visible:toolsButton.checked && !!modelData.toolsText;text:modelData.toolsText || "";textFormat:Text.PlainText;color:root.c.muted;font.family:"monospace";font.pixelSize:11*root.sdk.scale;wrapMode:Text.Wrap;Layout.fillWidth:true}
                        TextEdit {visible:!!modelData.text;text:modelData.text || "";textFormat:modelData.role==="assistant"?TextEdit.MarkdownText:TextEdit.PlainText;readOnly:true;selectByMouse:true;color:modelData.error?root.c.danger:root.c.ink;selectionColor:root.c.accent;selectedTextColor:"white";font.pixelSize:14*root.sdk.scale;wrapMode:TextEdit.Wrap;Layout.fillWidth:true;onLinkActivated:root.sdk.copyText(link)}
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
                Rectangle {
                    Layout.fillWidth:true;implicitHeight:Math.min(180,Math.max(88,input.contentHeight+24));radius:14;color:root.c.bg;border.color:input.activeFocus?root.c.accent:root.c.line
                    ScrollView {anchors.fill:parent;anchors.margins:10;clip:true
                        TextArea {id:input;objectName:"globalAgentInput";placeholderText:root.current.busy?"补充或引导当前任务…":"输入任务…";color:root.c.ink;placeholderTextColor:root.c.muted;selectionColor:root.c.accent;selectedTextColor:"white";wrapMode:TextArea.Wrap;font.pixelSize:14*root.sdk.scale;background:null;Keys.onPressed:event=>{if((event.key===Qt.Key_Return || event.key===Qt.Key_Enter) && !(event.modifiers&Qt.ShiftModifier)){root.send();event.accepted=true}}}
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
    Popup {
        id:helpPopup;objectName:"globalSubagentsHelpPopup";parent:root
        width:Math.min(340,root.width-36);x:Math.max(18,root.width-width-18);y:64
        padding:14;focus:true;closePolicy:Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background:Rectangle {radius:12;color:root.c.surface;border.color:root.c.line}
        contentItem:ColumnLayout {spacing:8
            LabelText {text:root.section==="bridge"?"Agent Bus（智能体总线）":"全局子智能体";font.weight:Font.Medium;Layout.fillWidth:true}
            LabelText {text:root.section==="bridge"?"按项目展开对话，开启开关后允许全局子智能体向该对话分派任务。任务仍遵守原对话的权限。":"创建拥有独立上下文的子智能体，通过智能体总线向已授权的对话分派任务。";wrapMode:Text.Wrap;elide:Text.ElideNone;Layout.fillWidth:true;font.pixelSize:12*root.sdk.scale}
        }
    }
    Dialog {
        id:createDialog;objectName:"createGlobalAgentDialog"
        anchors.centerIn:parent;width:Math.min(460,root.width-28);modal:true;closePolicy:Popup.CloseOnEscape
        padding:20;background:Rectangle {radius:18;color:root.c.surface;border.color:root.c.line}
        contentItem:ColumnLayout {
            spacing:14
            RowLayout {Layout.fillWidth:true
                LabelText {text:root.editing?"子智能体设置":"创建全局子智能体";font.pixelSize:18*root.sdk.scale;font.weight:Font.DemiBold;Layout.fillWidth:true}
                ToolButton {text:"×";palette.buttonText:root.c.muted;onClicked:createDialog.close()}
            }
            Field {id:nameInput;objectName:"globalAgentName";Layout.fillWidth:true;placeholderText:"名称，例如：项目协调员";maximumLength:60}
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
                SmallButton {objectName:"confirmCreateGlobalAgent";text:root.editing?"保存":"创建";primary:true;onClicked:root.submitForm()}
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
