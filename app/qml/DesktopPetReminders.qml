import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "UmekoStyle" as Soft

Item {
    id:root
    objectName:"desktopPetReminderManagerContent"
    required property var pet
    readonly property color paper:Theme.dark?Theme.bg:Qt.tint(Theme.bg,"#06a8783d")
    property var snapshot: ({config:{}})
    property string error:""
    readonly property var cfg:snapshot.config || ({})
    property QtObject sdk: QtObject {
        readonly property bool active: true
        readonly property real scale: Theme.fontScale
        readonly property var colors: Theme
        function t(text){return I18n.t(text)}
    }
    property var items: []
    // Persist completion immediately, but keep checked rows in this list visit.
    property var retainedCompletedIds: []
    property bool completedFilter: false
    property bool editing: false
    property string editId: ""
    property bool editCompleted: false
    property string formError: ""
    property string deleteId: ""
    property bool clearingCompleted:false
    property int selectionSerial: -1
    property bool daily:false
    property string originalZone:""
    property string originalDue: ""
    property string originalLocal: ""
    property var localCandidates: []
    readonly property string localSignature: dateField.text + " " + timeField.text
    readonly property bool pastDue: timed.checked && localCandidates.length > 0 && offsetPicker.currentIndex >= 0 && localCandidates[offsetPicker.currentIndex].epoch < Date.now()

    component ReminderField:TextField {
        font.family:Theme.fontFamily;font.pixelSize:Theme.font(13,true)
        implicitHeight:42*Theme.fontScale;padding:12*Theme.fontScale
        color:Theme.ink;placeholderTextColor:Theme.muted;selectionColor:Theme.selectionBg;selectedTextColor:Theme.selectionText
        background:Rectangle {radius:6;color:Theme.hover;border.width:parent.activeFocus?1:0;border.color:Theme.accent}
    }
    function call(method,args) {
        args=args || {}
        const retain=method==="completeItem" && args.completed!==false && !completedFilter && !editing && items.some(item=>item.id===args.id && !item.completed)
        const value=pet.ui(method,args || {})
        if(!value.ok){error=value.error || "";formError=error;return false}
        error=""
        if(retain && retainedCompletedIds.indexOf(args.id)<0)retainedCompletedIds=retainedCompletedIds.concat([args.id])
        if(method==="createItem" || method==="updateItem") {
            if(editCompleted && value.result.item && !value.result.item.completed)completedFilter=false
            editing=false
        }
        refresh()
        return true
    }
    function refresh(){
        const value=pet.ui("status",{})
        if(value.ok)snapshot=value.result
        const result=pet.ui("listItems",{status:retainedCompletedIds.length?"all":completedFilter?"completed":"open"})
        if(!result.ok)return
        const rows=result.result.items || []
        const byId={}
        rows.forEach(item=>byId[item.id]=item)
        retainedCompletedIds=retainedCompletedIds.filter(id=>byId[id] && byId[id].completed)
        const retained={}
        retainedCompletedIds.forEach(id=>retained[id]=true)
        const visibleRows=rows.filter(item=>item.completed===completedFilter || retained[item.id])
        if(retainedCompletedIds.length) {
            // Keep neighboring rows in place when multiple items are checked.
            const remaining={}
            visibleRows.forEach(item=>remaining[item.id]=item)
            const ordered=[]
            items.forEach(item=>{if(remaining[item.id]){ordered.push(remaining[item.id]);delete remaining[item.id]}})
            visibleRows.forEach(item=>{if(remaining[item.id])ordered.push(item)})
            items=ordered
        } else items=visibleRows
    }
    function endVisit(){retainedCompletedIds=[]}
    function syncSelection(){
        refresh()
        const selection=snapshot.reminderSelection || {}
        if(selection.serial===selectionSerial)return
        selectionSerial=selection.serial
        endVisit()
        if(selection.create)beginEdit(null)
        else {
            editing=false;completedFilter=false;editId="";formError="";refresh()
            const index=items.findIndex(item=>item.id===selection.id)
            if(index>=0)Qt.callLater(()=>list.positionViewAtIndex(index,ListView.Contain))
        }
    }
    function localText(value){return value?new Date(value).toLocaleString(Qt.locale(),"yyyy-MM-dd HH:mm"):sdk.t("无提醒时间")}
    function itemStatus(item){return sdk.t(item.completed?"已完成":!item.dueAt?"待办":item.overdue?"已到期":"待提醒")}
    function outcome(item){
        const labels={suppressed_hidden:"桌宠隐藏，未弹出",suppressed_preference:"到期气泡已关闭，未弹出",presentation_requested:"已请求显示气泡",restored_overdue:"恢复时已逾期",claimed:"到期已处理"}
        return labels[item.notificationOutcome]?sdk.t(labels[item.notificationOutcome]):""
    }
    function beginEdit(item){
        editId=item?item.id:"";editCompleted=!!(item && item.completed)
        titleField.text=item?item.title:"";notesField.text=item?item.notes:""
        daily=!!item && item.repeat==="daily";originalZone=item && item.timeZone?item.timeZone:""
        originalDue=item && item.dueAt?item.dueAt:""
        const date=originalDue?new Date(originalDue):new Date()
        dateField.text=item && item.localDate?item.localDate:Qt.formatDateTime(date,"yyyy-MM-dd");timeField.text=item && item.localTime?item.localTime:Qt.formatDateTime(date,"HH:mm")
        timed.checked=!!originalDue;originalLocal=localSignature;formError="";editing=true;Qt.callLater(()=>titleField.forceActiveFocus())
        resolveLocalTime()
        if(originalDue)for(let i=0;i<localCandidates.length;i++)if(Math.abs(localCandidates[i].epoch-date.getTime())<60000)offsetPicker.currentIndex=i
    }
    function resolveLocalTime(){
        localCandidates=[];offsetPicker.currentIndex=-1
        if(!dateField || !timeField)return
        const value=pet.ui("resolveReminderTime",{date:dateField.text,time:timeField.text,timeZone:originalZone || snapshot.timeZone || "UTC"})
        if(value.ok)localCandidates=value.result.candidates || []
        if(localCandidates.length===1)offsetPicker.currentIndex=0
    }
    function saveItem(){
        formError=""
        const title=titleField.text.trim()
        if(!title || title.length>200){formError="标题须为 1–200 个字符";return}
        if(notesField.text.length>2000){formError="备注最多 2000 个字符";return}
        let due=null
        if(timed.checked){
            if(!localCandidates.length){formError="日期无效或该本地时间不存在";return}
            if(offsetPicker.currentIndex<0){formError="该时间出现两次，请选择 UTC 偏移";return}
            due=originalDue && originalLocal===localSignature && Math.abs(new Date(originalDue).getTime()-localCandidates[offsetPicker.currentIndex].epoch)<60000?originalDue:new Date(localCandidates[offsetPicker.currentIndex].epoch).toISOString()
        }
        const args={title:title,notes:notesField.text,repeat:timed.checked && daily?"daily":"once"}
        if(due){args.dueAt=due;if(daily)args.timeZone=originalZone || snapshot.timeZone || "UTC"}
        else if(editId)args.clearDueAt=true
        if(editId)args.id=editId
        call(editId?"updateItem":"createItem",args)
    }


    function isDue(item){return !item.completed && (item.overdue || Number(item.firedOccurrence || 0)>0)}
    function shortTime(value){
        if(!value)return ""
        const date=new Date(value),today=new Date(),tomorrow=new Date()
        tomorrow.setDate(today.getDate()+1)
        const day=Qt.formatDateTime(date,"yyyy-MM-dd")
        return (day===Qt.formatDateTime(today,"yyyy-MM-dd")?I18n.t("今天"):day===Qt.formatDateTime(tomorrow,"yyyy-MM-dd")?I18n.t("明天"):Qt.formatDateTime(date,I18n.language==="en"?"MMM d":"M月d日"))+"  "+Qt.formatDateTime(date,"HH:mm")
    }
    Component.onCompleted:syncSelection()
    Connections {target:root.pet;function onChanged(){if(root.visible && root.Window.window && root.Window.window.visible)Qt.callLater(root.refresh)}}
    onCompletedFilterChanged:{endVisit();refresh()}
    onEditingChanged:{endVisit();refresh()}
    Rectangle {anchors.fill:parent;color:root.paper}
    ColumnLayout {
        anchors.fill:parent;anchors.margins:24*Theme.fontScale;spacing:20*Theme.fontScale
        RowLayout {
            Layout.fillWidth:true;spacing:8
            ReminderButton {objectName:"desktopPetReminderCancel";visible:root.editing;glyph:"arrow-left";quiet:true;hint:I18n.t("返回");onClicked:root.editing=false}
            Text {
                Layout.fillWidth:true
                text:root.editing?I18n.t(root.editId?"编辑事项":"新增事项"):I18n.t("提醒事项")
                font.family:Theme.fontFamily;font.pixelSize:Theme.font(22,true);font.weight:Font.DemiBold;color:Theme.ink
            }
            ReminderButton {visible:!root.editing;glyph:"sliders";quiet:true;hint:I18n.t("设置");onClicked:preferences.open()}
            ReminderButton {objectName:"desktopPetNewReminder";visible:!root.editing;glyph:"plus";primary:true;hint:I18n.t("新增事项");onClicked:root.beginEdit(null)}
            ReminderButton {objectName:"desktopPetReminderSave";visible:root.editing;text:I18n.t("保存");primary:true;onClicked:root.saveItem()}
        }
        StackLayout {
            Layout.fillWidth:true;Layout.fillHeight:true;currentIndex:root.editing?1:0
            ColumnLayout {
                spacing:12
                RowLayout {
                    Layout.fillWidth:true;spacing:20*Theme.fontScale
                    Repeater {
                        model:[I18n.t("未完成"),I18n.t("已完成")]
                        AbstractButton {
                            required property int index
                            required property string modelData
                            objectName:index===0?"desktopPetOpenFilter":"desktopPetCompletedFilter"
                            implicitHeight:32*Theme.fontScale;implicitWidth:filterText.implicitWidth
                            readonly property bool selected:root.completedFilter===(index===1)
                            onClicked:root.completedFilter=index===1
                            HoverHandler {cursorShape:Qt.PointingHandCursor}
                            contentItem:Text {id:filterText;text:modelData;font.family:Theme.fontFamily;font.pixelSize:Theme.font(12,true);font.weight:parent.selected?Font.DemiBold:Font.Normal;color:parent.selected?Theme.ink:Theme.muted;verticalAlignment:Text.AlignVCenter}
                            background:Item {Rectangle {anchors.bottom:parent.bottom;width:parent.width;height:2;radius:1;visible:parent.parent.selected;color:Theme.accent}}
                        }
                    }
                    Item {Layout.fillWidth:true}
                    Text {text:String(root.items.length);font.family:Theme.fontFamily;font.pixelSize:Theme.font(12,true);color:Theme.muted}
                }
                ListView {
                    id:list;objectName:"desktopPetReminderList";Layout.fillWidth:true;Layout.fillHeight:true
                    model:root.items;clip:true;reuseItems:true;cacheBuffer:height
                    ScrollBar.vertical:ScrollBar {policy:ScrollBar.AsNeeded}
                    delegate:Item {
                        id:row;required property var modelData
                        width:list.width;height:Math.max(70*Theme.fontScale,rowText.implicitHeight+28*Theme.fontScale)
                        HoverHandler {id:rowHover}
                        Rectangle {anchors.fill:parent;radius:6;color:Theme.hover;opacity:rowHover.hovered?0.55:0}
                        RowLayout {
                            anchors.fill:parent;anchors.leftMargin:4;anchors.rightMargin:8;spacing:14*Theme.fontScale
                            AbstractButton {
                                objectName:"desktopPetReminderComplete_"+row.modelData.id
                                implicitWidth:24*Theme.fontScale;implicitHeight:32*Theme.fontScale
                                onClicked:root.call("completeItem",{id:row.modelData.id,completed:!row.modelData.completed})
                                HoverHandler {cursorShape:parent.enabled?Qt.PointingHandCursor:Qt.ArrowCursor}
                                background:Item {}
                                contentItem:Item {Soft.SelectionIndicator {anchors.centerIn:parent;round:true;checkState:row.modelData.completed?Qt.Checked:Qt.Unchecked;pressed:parent.parent.down;focused:parent.parent.visualFocus}}
                            }
                            ColumnLayout {
                                id:rowText;Layout.fillWidth:true;spacing:5
                                Text {objectName:"desktopPetReminderTitle_"+row.modelData.id;Layout.fillWidth:true;text:row.modelData.title;textFormat:Text.PlainText;wrapMode:Text.Wrap;maximumLineCount:2;elide:Text.ElideRight;font.family:Theme.fontFamily;font.pixelSize:Theme.font(14,true);font.strikeout:row.modelData.completed;color:row.modelData.completed?Theme.muted:root.isDue(row.modelData)?Theme.danger:Theme.ink}
                                Text {Layout.fillWidth:true;visible:!!row.modelData.dueAt;text:row.modelData.repeat==="daily"?I18n.t("每日")+" · "+(row.modelData.localTime || "")+(row.modelData.timeZone!==root.snapshot.timeZone?" ("+row.modelData.timeZone+")":""):root.shortTime(row.modelData.dueAt);elide:Text.ElideRight;font.family:Theme.fontFamily;font.pixelSize:Theme.font(11,true);color:root.isDue(row.modelData)?Theme.danger:Theme.muted}
                                TapHandler {onTapped:root.beginEdit(row.modelData)}
                                HoverHandler {cursorShape:Qt.PointingHandCursor}
                            }
                            ReminderButton {
                                objectName:"desktopPetReminderDelete_"+row.modelData.id
                                visible:root.completedFilter && row.modelData.completed;text:I18n.t("删除");glyph:"trash";dangerFill:true
                                implicitHeight:Theme.control(32)
                                onClicked:{root.clearingCompleted=false;root.deleteId=row.modelData.id;deleteReminderDialog.open()}
                            }
                        }
                        Rectangle {anchors.bottom:parent.bottom;anchors.left:parent.left;anchors.leftMargin:42*Theme.fontScale;anchors.right:parent.right;height:1;color:Theme.line;opacity:0.6}
                    }
                    Column {
                        anchors.centerIn:parent;spacing:12;visible:root.items.length===0
                        Glyph {anchors.horizontalCenter:parent.horizontalCenter;name:"check";width:28*Theme.fontScale;height:width;color:Theme.muted;opacity:0.45}
                        Text {text:I18n.t(root.completedFilter?"还没有已完成的事项":"暂无事项");font.family:Theme.fontFamily;font.pixelSize:Theme.font(13,true);color:Theme.muted}
                    }
                }
                Rectangle {visible:root.completedFilter;Layout.fillWidth:true;implicitHeight:1;color:Theme.line}
                ReminderButton {
                    objectName:"desktopPetClearCompleted";visible:root.completedFilter;Layout.alignment:Qt.AlignHCenter
                    text:I18n.t("清空已完成");glyph:"trash";destructive:true;enabled:root.items.length>0
                    onClicked:{root.clearingCompleted=true;deleteReminderDialog.open()}
                }
            }
            ScrollView {
                clip:true;contentWidth:availableWidth
                ColumnLayout {
                    width:parent.width;spacing:20*Theme.fontScale
                    TextField {
                        id:titleField;objectName:"desktopPetReminderTitle";Layout.fillWidth:true
                        placeholderText:I18n.t("要记得做什么？");maximumLength:200;selectByMouse:true
                        font.family:Theme.fontFamily;font.pixelSize:Theme.font(18,true);color:Theme.ink;placeholderTextColor:Theme.muted
                        padding:2;topPadding:8;bottomPadding:16
                        background:Item {Rectangle {anchors.bottom:parent.bottom;width:parent.width;height:1;color:Theme.line}}
                    }
                    TextArea {
                        id:notesField;objectName:"desktopPetReminderNotes";Layout.fillWidth:true;Layout.minimumHeight:120*Theme.fontScale
                        placeholderText:I18n.t("备注");textFormat:Text.PlainText;wrapMode:TextEdit.Wrap;selectByMouse:true
                        font.family:Theme.fontFamily;font.pixelSize:Theme.font(13,true);color:Theme.ink;placeholderTextColor:Theme.muted;padding:2
                        background:Item {}
                    }
                    Rectangle {Layout.fillWidth:true;implicitHeight:1;color:Theme.line}
                    RowLayout {
                        Layout.fillWidth:true;spacing:10
                        Glyph {name:"clock";width:18*Theme.fontScale;height:width}
                        Text {Layout.fillWidth:true;text:I18n.t("设置提醒时间");font.family:Theme.fontFamily;font.pixelSize:Theme.font(13,true);color:Theme.ink}
                        Switch {id:timed;objectName:"desktopPetReminderTimed";palette.highlight:Theme.accent}
                    }
                    RowLayout {
                        visible:timed.checked;Layout.fillWidth:true;spacing:8
                        ReminderButton {objectName:"desktopPetReminderOnce";text:I18n.t("单次");primary:!root.daily;quiet:root.daily;onClicked:root.daily=false}
                        ReminderButton {objectName:"desktopPetReminderDaily";text:I18n.t("每日");primary:root.daily;quiet:!root.daily;onClicked:root.daily=true}
                    }
                    ColumnLayout {
                        visible:timed.checked;Layout.fillWidth:true;spacing:0
                        AbstractButton {
                            objectName:"desktopPetReminderDateButton";Layout.fillWidth:true;implicitHeight:48*Theme.fontScale
                            onClicked:dateTimePicker.openFor("date",dateField.text,timeField.text)
                            HoverHandler {cursorShape:Qt.PointingHandCursor}
                            contentItem:RowLayout {
                                Text {Layout.fillWidth:true;text:I18n.t(root.daily?"开始日期":"日期");font.family:Theme.fontFamily;font.pixelSize:Theme.font(13,true);color:Theme.ink}
                                Text {text:dateField.text;font.family:Theme.fontFamily;font.pixelSize:Theme.font(13,true);color:Theme.muted}
                                Glyph {name:"chevron-right";width:14*Theme.fontScale;height:width}
                            }
                        }
                        Rectangle {Layout.fillWidth:true;implicitHeight:1;color:Theme.line;opacity:0.6}
                        AbstractButton {
                            objectName:"desktopPetReminderTimeButton";Layout.fillWidth:true;implicitHeight:48*Theme.fontScale
                            onClicked:dateTimePicker.openFor("time",dateField.text,timeField.text)
                            HoverHandler {cursorShape:Qt.PointingHandCursor}
                            contentItem:RowLayout {
                                Text {Layout.fillWidth:true;text:I18n.t("时间");font.family:Theme.fontFamily;font.pixelSize:Theme.font(13,true);color:Theme.ink}
                                Text {text:timeField.text;font.family:Theme.fontFamily;font.pixelSize:Theme.font(17,true);color:Theme.ink}
                                Glyph {name:"chevron-right";width:14*Theme.fontScale;height:width}
                            }
                        }
                    }
                    ComboBox {id:offsetPicker;objectName:"desktopPetReminderOffset";visible:timed.checked && root.localCandidates.length>1;Layout.fillWidth:true;model:root.localCandidates;textRole:"label";displayText:currentIndex<0?I18n.t("请选择 UTC 偏移"):currentText}
                    Text {Layout.fillWidth:true;visible:root.pastDue;wrapMode:Text.Wrap;text:I18n.t("保存后将立即按逾期事项处理");font.family:Theme.fontFamily;font.pixelSize:Theme.font(11,true);color:Theme.muted}
                    ReminderButton {visible:!!root.editId;text:I18n.t("删除");glyph:"trash";quiet:true;destructive:true;onClicked:{root.clearingCompleted=false;root.deleteId=root.editId;deleteReminderDialog.open()}}
                }
            }
        }
        Text {Layout.fillWidth:true;visible:!!text;text:root.formError || root.error || (root.snapshot.reminders || {}).error || "";textFormat:Text.PlainText;wrapMode:Text.Wrap;font.family:Theme.fontFamily;font.pixelSize:Theme.font(12,true);color:Theme.danger}
    }
    TextField {id:dateField;objectName:"desktopPetReminderDate";visible:false;onTextChanged:root.resolveLocalTime()}
    TextField {id:timeField;objectName:"desktopPetReminderTime";visible:false;onTextChanged:root.resolveLocalTime()}
    ReminderDateTimePicker {id:dateTimePicker;parent:root;onChosen:(dateText,timeText)=>{dateField.text=dateText;timeField.text=timeText}}
    Popup {
        id:preferences;x:root.width-width-24;y:64*Theme.fontScale;width:260*Theme.fontScale;padding:16
        closePolicy:Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background:Rectangle {radius:10;color:Theme.surface;border.color:Theme.line}
        RowLayout {
            width:parent.width
            Text {Layout.fillWidth:true;text:I18n.t("到期气泡提示");font.family:Theme.fontFamily;font.pixelSize:Theme.font(12,true);color:Theme.ink}
            Switch {objectName:"desktopPetReminderSwitch";checked:root.cfg.reminderNotificationsEnabled!==false;palette.highlight:Theme.accent;onToggled:root.call("configure",{reminderNotificationsEnabled:checked})}
        }
    }
    Dialog {
        id:deleteReminderDialog;objectName:"desktopPetDeleteReminderDialog";title:I18n.t(root.clearingCompleted?"清空已完成事项":"删除事项");width:Math.min(320*Theme.fontScale,root.width-24);modal:true;anchors.centerIn:parent
        footer:Item {
            implicitHeight:62*Theme.fontScale
            RowLayout {
                anchors.fill:parent;anchors.margins:12*Theme.fontScale;spacing:8
                Item {Layout.fillWidth:true}
                ReminderButton {text:I18n.t("取消");onClicked:deleteReminderDialog.reject()}
                ReminderButton {objectName:"desktopPetConfirmDelete";text:I18n.t(root.clearingCompleted?"清空":"删除");glyph:"trash";dangerFill:true;onClicked:deleteReminderDialog.accept()}
            }
        }
        Label {text:I18n.t(root.clearingCompleted?"清空所有已完成事项？此操作无法撤销。":"删除此事项？此操作无法撤销。");textFormat:Text.PlainText;wrapMode:Text.Wrap;width:parent.width;color:Theme.ink}
        onAccepted:{if(root.clearingCompleted)root.call("clearCompleted",{});else root.call("deleteItem",{id:root.deleteId});if(root.clearingCompleted || root.editId===root.deleteId)root.editing=false}
    }
}
