import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

ColumnLayout {
    id:root
    objectName:"desktopPetSettings"
    required property var sdk
    property var snapshot: ({config:{},appearances:[],state:{}})
    property string error:""
    property var pending: ({})
    property var items: []
    property bool completedFilter: false
    property bool editing: false
    property string editId: ""
    property bool editCompleted: false
    property string formError: ""
    property string deleteId: ""
    property int selectionSerial: -1
    property string originalDue: ""
    property string originalLocal: ""
    property var localCandidates: []
    readonly property string localSignature: dateField.text + " " + timeField.text
    readonly property bool pastDue: timed.checked && localCandidates.length > 0 && offsetPicker.currentIndex >= 0 && localCandidates[offsetPicker.currentIndex].epoch < Date.now()
    readonly property var cfg:snapshot.config || ({})
    readonly property var packs:snapshot.appearances || []
    implicitHeight:childrenRect.height
    spacing:14
    component PetButton:Button {
        id:control
        hoverEnabled:true;opacity:enabled?1:0.45
        font.pixelSize:12*root.sdk.scale
        implicitHeight:38*root.sdk.scale
        leftPadding:14*root.sdk.scale;rightPadding:14*root.sdk.scale
        HoverHandler {cursorShape:control.enabled?Qt.PointingHandCursor:Qt.ArrowCursor}
        background:Rectangle {radius:8;color:control.down?root.sdk.colors.accentBg:control.hovered?root.sdk.colors.hover:root.sdk.colors.surface;border.color:root.sdk.colors.line}
        contentItem:Text {text:control.text;font:control.font;color:root.sdk.colors.ink;verticalAlignment:Text.AlignVCenter;horizontalAlignment:Text.AlignHCenter}
    }
    function call(method,args) {
        const id=sdk.call(method,args || {})
        if(id) pending[id]=method
        return id
    }
    function refresh(){if(sdk.active){call("status",{});call("listItems",{status:completedFilter?"completed":"open"})}}
    function localText(value){return value?new Date(value).toLocaleString(Qt.locale(),"yyyy-MM-dd HH:mm"):sdk.t("无提醒时间")}
    function itemStatus(item){return sdk.t(item.completed?"已完成":!item.dueAt?"待办":item.overdue?"已到期":"待提醒")}
    function outcome(item){
        const labels={suppressed_hidden:"桌宠隐藏，未弹出",suppressed_preference:"到期气泡已关闭，未弹出",presentation_requested:"已请求显示气泡",claimed:"到期已处理"}
        return labels[item.notificationOutcome]?sdk.t(labels[item.notificationOutcome]):""
    }
    function beginEdit(item){
        editId=item?item.id:"";editCompleted=!!(item && item.completed)
        titleField.text=item?item.title:"";notesField.text=item?item.notes:""
        originalDue=item && item.dueAt?item.dueAt:""
        const date=originalDue?new Date(originalDue):new Date()
        dateField.text=Qt.formatDateTime(date,"yyyy-MM-dd");timeField.text=Qt.formatDateTime(date,"HH:mm")
        timed.checked=!!originalDue;originalLocal=localSignature;formError="";editing=true
        resolveLocalTime()
        if(originalDue)for(let i=0;i<localCandidates.length;i++)if(Math.abs(localCandidates[i].epoch-date.getTime())<60000)offsetPicker.currentIndex=i
    }
    function resolveLocalTime(){
        localCandidates=[];offsetPicker.currentIndex=-1
        const match=(dateField.text+" "+timeField.text).match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})$/)
        if(!match)return
        const y=Number(match[1]),m=Number(match[2]),d=Number(match[3]),h=Number(match[4]),minute=Number(match[5])
        if(y<100 || m<1 || m>12 || d<1 || d>31 || h>23 || minute>59)return
        const naive=Date.UTC(y,m-1,d,h,minute),offsets=[],candidates=[]
        // Gather the offsets on both sides of a transition, then round-trip every
        // candidate. Never allow Date to silently normalize an invalid wall time.
        for(let delta=-48;delta<=48;delta++){
            const off=new Date(naive+delta*3600000).getTimezoneOffset()
            if(offsets.indexOf(off)<0)offsets.push(off)
        }
        for(const off of offsets){
            const epoch=naive+off*60000,date=new Date(epoch)
            if(date.getFullYear()!==y || date.getMonth()!==m-1 || date.getDate()!==d || date.getHours()!==h || date.getMinutes()!==minute)continue
            const sign=off<=0?"+":"-",abs=Math.abs(off)
            candidates.push({epoch:epoch,label:"UTC"+sign+String(Math.floor(abs/60)).padStart(2,"0")+":"+String(abs%60).padStart(2,"0")})
        }
        candidates.sort((a,b)=>a.epoch-b.epoch);localCandidates=candidates
        if(candidates.length===1)offsetPicker.currentIndex=0
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
            due=originalDue && originalLocal===localSignature && new Date(originalDue).getTimezoneOffset()===new Date(localCandidates[offsetPicker.currentIndex].epoch).getTimezoneOffset()?originalDue:new Date(localCandidates[offsetPicker.currentIndex].epoch).toISOString()
        }
        const args={title:title,notes:notesField.text}
        if(due)args.dueAt=due
        else if(editId)args.clearDueAt=true
        if(editId)args.id=editId
        call(editId?"updateItem":"createItem",args)
    }
    Component.onCompleted:refresh()
    Connections {
        target:root.sdk
        function onResponse(id,value) {
            if(!root.pending[id])return
            const method=root.pending[id];delete root.pending[id]
            if(!value.ok){root.error=value.error || "";if(method==="createItem" || method==="updateItem")root.formError=root.error;return}
            const result=value.result || {}
            if(method==="status" || result.config){
                root.snapshot=result;root.error=""
                const selection=result.reminderSelection || {}
                if(selection.serial!==undefined && selection.serial!==root.selectionSerial){
                    root.selectionSerial=selection.serial
                    if(selection.create)root.beginEdit(null)
                    else if(selection.id)root.call("getItem",{id:selection.id})
                }
            } else if(method==="listItems")root.items=result.items || []
            else if(method==="getItem")root.beginEdit(result.item)
            else {if(method==="createItem" || method==="updateItem")root.editing=false;root.refresh()}
        }
    }
    Timer {interval:1500;repeat:true;running:root.visible && root.sdk.active;onTriggered:root.refresh()}
    FileDialog {
        id:picker;title:root.sdk.t("导入桌宠形象")
        nameFilters:["Pet appearance (*.zip *.json *.webp *.gif *.png)"]
        onAccepted:root.call("importAppearance",{path:String(selectedFile)})
    }
    RowLayout {
        Layout.fillWidth:true
        Label {text:root.sdk.t("显示桌面小宠物");color:root.sdk.colors.ink;font.pixelSize:14*root.sdk.scale;Layout.fillWidth:true}
        Switch {objectName:"desktopPetVisibleSwitch";checked:!!root.cfg.visible;enabled:root.sdk.active;onToggled:root.call("configure",{visible:checked})}
    }
    Label {Layout.fillWidth:true;wrapMode:Text.Wrap;text:root.sdk.t("后台观察已启用；隐藏桌宠时也会继续跟随任务状态。");color:root.sdk.colors.muted;font.pixelSize:12*root.sdk.scale}
    Rectangle {Layout.fillWidth:true;implicitHeight:1;color:root.sdk.colors.line}
    RowLayout {
        Layout.fillWidth:true
        Label {text:root.sdk.t("提醒与待办")+" ("+((root.snapshot.reminders || {}).openCount || 0)+")";color:root.sdk.colors.ink;font.bold:true;Layout.fillWidth:true}
        PetButton {objectName:"desktopPetNewReminder";text:root.sdk.t("新增事项");enabled:root.sdk.active;onClicked:root.beginEdit(null)}
    }
    RowLayout {
        Layout.fillWidth:true
        Label {text:root.sdk.t("到期气泡提示");color:root.sdk.colors.ink;Layout.fillWidth:true}
        Switch {objectName:"desktopPetReminderSwitch";checked:root.cfg.reminderNotificationsEnabled!==false;enabled:root.sdk.active;onToggled:root.call("configure",{reminderNotificationsEnabled:checked})}
    }
    Label {Layout.fillWidth:true;wrapMode:Text.Wrap;text:root.sdk.t("隐藏桌宠时不弹出；再次显示不会补播。暂停动作不影响提醒。");color:root.sdk.colors.muted;font.pixelSize:12*root.sdk.scale}
    RowLayout {
        PetButton {objectName:"desktopPetOpenFilter";text:root.sdk.t("未完成");highlighted:!root.completedFilter;onClicked:{root.completedFilter=false;root.refresh()}}
        PetButton {objectName:"desktopPetCompletedFilter";text:root.sdk.t("已完成");highlighted:root.completedFilter;onClicked:{root.completedFilter=true;root.refresh()}}
    }
    Label {Layout.fillWidth:true;visible:!!text;wrapMode:Text.Wrap;text:(root.snapshot.reminders || {}).error || "";color:root.sdk.colors.danger}
    ScrollView {
        objectName:"desktopPetReminderList";Layout.fillWidth:true;Layout.preferredHeight:Math.min(280*root.sdk.scale,Math.max(64*root.sdk.scale,reminderRows.implicitHeight));clip:true
        contentWidth:availableWidth
        ColumnLayout {
            id:reminderRows;width:parent.width;spacing:8
            Label {visible:root.items.length===0;text:root.sdk.t("暂无事项");color:root.sdk.colors.muted;padding:12}
            Repeater {
                model:root.items
                Rectangle {
                    required property var modelData
                    Layout.fillWidth:true;implicitHeight:itemContent.implicitHeight+20;radius:8;color:root.sdk.colors.surface;border.color:root.sdk.colors.line
                    ColumnLayout {
                        id:itemContent;anchors.left:parent.left;anchors.right:parent.right;anchors.top:parent.top;anchors.margins:10;spacing:4
                        Label {Layout.fillWidth:true;text:modelData.title;textFormat:Text.PlainText;wrapMode:Text.Wrap;color:root.sdk.colors.ink;font.bold:true}
                        Label {Layout.fillWidth:true;text:root.itemStatus(modelData)+" · "+root.localText(modelData.dueAt);wrapMode:Text.Wrap;color:root.sdk.colors.muted;font.pixelSize:12*root.sdk.scale}
                        Label {Layout.fillWidth:true;visible:!!text;text:root.outcome(modelData);wrapMode:Text.Wrap;color:root.sdk.colors.muted;font.pixelSize:12*root.sdk.scale}
                        RowLayout {
                            PetButton {text:root.sdk.t(modelData.completed?"查看":"编辑");onClicked:root.beginEdit(modelData)}
                            PetButton {visible:!modelData.completed;text:root.sdk.t("完成");onClicked:root.call("completeItem",{id:modelData.id})}
                            PetButton {text:root.sdk.t("删除");onClicked:{root.deleteId=modelData.id;deleteReminderDialog.open()}}
                        }
                    }
                }
            }
        }
    }
    Rectangle {
        visible:root.editing;Layout.fillWidth:true;implicitHeight:form.implicitHeight+24;radius:10;color:root.sdk.colors.surface;border.color:root.sdk.colors.line
        ColumnLayout {
            id:form;anchors.top:parent.top;anchors.left:parent.left;anchors.right:parent.right;anchors.margins:12;spacing:10
            Label {text:root.sdk.t(root.editId?"编辑事项":"新增事项");color:root.sdk.colors.ink;font.bold:true}
            TextField {id:titleField;objectName:"desktopPetReminderTitle";Layout.fillWidth:true;placeholderText:root.sdk.t("标题（必填，最多 200 字符）");readOnly:root.editCompleted;selectByMouse:true;color:root.sdk.colors.ink}
            ScrollView {
                Layout.fillWidth:true;Layout.preferredHeight:90*root.sdk.scale
                TextArea {id:notesField;objectName:"desktopPetReminderNotes";placeholderText:root.sdk.t("备注（最多 2000 字符）");textFormat:Text.PlainText;wrapMode:TextEdit.Wrap;readOnly:root.editCompleted;selectByMouse:true;color:root.sdk.colors.ink}
            }
            CheckBox {id:timed;objectName:"desktopPetReminderTimed";text:root.sdk.t("设置提醒时间");enabled:!root.editCompleted;palette.windowText:root.sdk.colors.ink}
            RowLayout {
                visible:timed.checked;Layout.fillWidth:true
                TextField {id:dateField;objectName:"desktopPetReminderDate";Layout.fillWidth:true;placeholderText:"YYYY-MM-DD";readOnly:root.editCompleted;selectByMouse:true;color:root.sdk.colors.ink;onTextChanged:root.resolveLocalTime()}
                TextField {id:timeField;objectName:"desktopPetReminderTime";Layout.preferredWidth:100*root.sdk.scale;placeholderText:"HH:mm";readOnly:root.editCompleted;selectByMouse:true;color:root.sdk.colors.ink;onTextChanged:root.resolveLocalTime()}
            }
            Label {visible:timed.checked;text:root.sdk.t("使用系统当前本地时区");color:root.sdk.colors.muted}
            ComboBox {id:offsetPicker;objectName:"desktopPetReminderOffset";visible:timed.checked && root.localCandidates.length>1;Layout.fillWidth:true;model:root.localCandidates;textRole:"label";enabled:!root.editCompleted;displayText:currentIndex<0?root.sdk.t("请选择 UTC 偏移"):currentText}
            Label {Layout.fillWidth:true;visible:root.pastDue;wrapMode:Text.Wrap;text:root.sdk.t("保存后将立即按逾期事项处理");color:root.sdk.colors.muted}
            Label {Layout.fillWidth:true;visible:!!root.formError;wrapMode:Text.Wrap;text:root.sdk.t(root.formError);textFormat:Text.PlainText;color:root.sdk.colors.danger}
            RowLayout {
                PetButton {objectName:"desktopPetReminderSave";visible:!root.editCompleted;text:root.sdk.t("保存");enabled:root.sdk.active;onClicked:root.saveItem()}
                PetButton {objectName:"desktopPetReminderCancel";text:root.sdk.t("关闭");onClicked:root.editing=false}
            }
        }
    }
    Rectangle {Layout.fillWidth:true;implicitHeight:1;color:root.sdk.colors.line}
    RowLayout {
        Layout.fillWidth:true
        Label {text:root.sdk.t("动画形象");color:root.sdk.colors.ink;font.pixelSize:13*root.sdk.scale}
        ComboBox {
            id:appearance;objectName:"desktopPetAppearancePicker";Layout.fillWidth:true
            model:root.packs;textRole:"name";valueRole:"id"
            font.pixelSize:12*root.sdk.scale
            palette.text:root.sdk.colors.ink;palette.buttonText:root.sdk.colors.ink;palette.base:root.sdk.colors.surface;palette.highlight:root.sdk.colors.accent
            background:Rectangle {radius:8;color:root.sdk.colors.surface;border.color:appearance.activeFocus?root.sdk.colors.accent:root.sdk.colors.line}
            currentIndex:root.packs.findIndex(p=>p.id===root.cfg.appearance)
            enabled:root.sdk.active
            onActivated:root.call("selectAppearance",{id:currentValue})
        }
    }
    Flow {
        Layout.fillWidth:true;spacing:8
        PetButton {objectName:"desktopPetImportAppearanceButton";text:root.sdk.t("导入形象…");enabled:root.sdk.active && !root.snapshot.state.importing;onClicked:picker.open()}
        PetButton {text:root.sdk.t("删除形象");enabled:root.sdk.active && !!root.packs[appearance.currentIndex] && !root.packs[appearance.currentIndex].builtin;onClicked:removeDialog.open()}
        PetButton {text:root.sdk.t("重置位置");enabled:root.sdk.active;onClicked:root.call("resetPosition",{})}
    }
    Label {visible:!!root.snapshot.state.importing;text:root.sdk.t("正在验证动画形象…");color:root.sdk.colors.muted;font.pixelSize:12*root.sdk.scale}
    Label {Layout.fillWidth:true;wrapMode:Text.Wrap;visible:!!text;text:root.error || root.snapshot.state.error || "";color:root.sdk.colors.danger;font.pixelSize:12*root.sdk.scale}
    Label {Layout.fillWidth:true;wrapMode:Text.Wrap;text:root.sdk.t("支持透明 WebP、GIF、PNG，或包含多种动作的形象 ZIP。");color:root.sdk.colors.muted;font.pixelSize:12*root.sdk.scale}
    RowLayout {
        Layout.fillWidth:true
        Label {text:root.sdk.t("桌宠大小");color:root.sdk.colors.ink;font.pixelSize:13*root.sdk.scale}
        Slider {objectName:"desktopPetSizeSlider";Layout.fillWidth:true;from:96;to:320;stepSize:8;value:root.cfg.size || 192;enabled:root.sdk.active;onPressedChanged:if(!pressed)root.call("configure",{size:Math.round(value)})}
        Label {text:String(root.cfg.size || 192)+" px";color:root.sdk.colors.muted;font.pixelSize:12*root.sdk.scale}
    }
    RowLayout {
        Layout.fillWidth:true
        CheckBox {text:root.sdk.t("保持置顶");checked:!!root.cfg.alwaysOnTop;enabled:root.sdk.active;palette.windowText:root.sdk.colors.ink;onToggled:root.call("configure",{alwaysOnTop:checked})}
        CheckBox {text:root.sdk.t("暂停动作");checked:!!root.cfg.paused;enabled:root.sdk.active;palette.windowText:root.sdk.colors.ink;onToggled:root.call("configure",{paused:checked})}
    }
    Dialog {
        id:deleteReminderDialog;objectName:"desktopPetDeleteReminderDialog";title:root.sdk.t("删除事项");width:320*root.sdk.scale;modal:true;standardButtons:Dialog.Ok | Dialog.Cancel
        Label {text:root.sdk.t("删除此事项？此操作无法撤销。");textFormat:Text.PlainText;wrapMode:Text.Wrap;width:280;color:root.sdk.colors.ink}
        onAccepted:{root.call("deleteItem",{id:root.deleteId});if(root.editId===root.deleteId)root.editing=false}
    }
    Dialog {
        id:removeDialog;title:root.sdk.t("删除形象");width:320*root.sdk.scale;modal:true;standardButtons:Dialog.Ok | Dialog.Cancel
        Label {text:root.sdk.t("删除所选形象？当前形象会先恢复为八奈见。");wrapMode:Text.Wrap;width:280;color:root.sdk.colors.ink}
        onAccepted:root.call("removeAppearance",{id:root.cfg.appearance})
    }
}
