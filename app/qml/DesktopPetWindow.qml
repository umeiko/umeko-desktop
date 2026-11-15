import QtQuick
import QtQuick.Controls
import QtQuick.Window
import QtQuick.Layouts

Window {
    id: root
    objectName: "desktopPetWindow"
    required property var pet
    readonly property var state: pet.state
    readonly property var config: pet.config
    property string caption: ""
    property bool assistantCaption: false
    property bool placed: false
    property bool dragged: false
    property real pressX: 0
    property real pressY: 0
    property real startX: 0
    property real startY: 0
    readonly property real tilt: 0
    readonly property var reminderCard: pet.reminderCard || []
    property string reminderKeys: ""
    readonly property url spriteSource: state.source
    readonly property rect artRect: Qt.rect(art.x, art.y, art.width, art.height)
    readonly property rect bubbleRect: bubble.visible ? Qt.rect(bubble.x, bubble.y, bubble.width, bubble.height) : Qt.rect(0, 0, 0, 0)
    readonly property rect reminderRect: reminder.visible ? Qt.rect(reminder.x, reminder.y, reminder.width, reminder.height) : Qt.rect(0, 0, 0, 0)
    function updateInputMask() {
        if (visible) pet.inputMask.update(root, spriteSource, artRect, tilt, bubbleRect, reminderRect)
    }
    onSpriteSourceChanged: Qt.callLater(updateInputMask)
    onArtRectChanged: Qt.callLater(updateInputMask)
    onBubbleRectChanged: Qt.callLater(updateInputMask)
    onReminderRectChanged: Qt.callLater(updateInputMask)
    onTiltChanged: Qt.callLater(updateInputMask)
    Connections {
        target: root.pet.inputMask
        function onChanged() { Qt.callLater(root.updateInputMask) }
    }
    function syncReminderCard() {
        if(!speech || !reminderTimeout)return
        const keys=reminderCard.map(item=>item.id+":"+item.occurrence).join("|")
        if(keys && keys!==reminderKeys){caption="";speech.stop();reminderTimeout.restart()}
        if(!keys)reminderTimeout.stop()
        reminderKeys=keys
    }
    function closeReminderCard(){caption="";speech.stop();pet.dismissReminders()}
    function viewReminderCard(){const id=reminderCard.length===1?reminderCard[0].id:"";closeReminderCard();pet.openReminders(id,false)}
    function localTime(value){return value?new Date(value).toLocaleString(Qt.locale(),"yyyy-MM-dd HH:mm"):I18n.t("无提醒时间")}
    onReminderCardChanged:syncReminderCard()
    Component.onCompleted: {
        syncReminderCard()
        updateInputMask()
    }
    width: config.size + 32
    height: config.size * 1.5 + 72
    color: "transparent"
    visible: pet.visible
    transientParent: null
    flags: Qt.Tool | Qt.FramelessWindowHint | (config.alwaysOnTop ? Qt.WindowStaysOnTopHint : 0)
    title: I18n.t("桌面小宠物")
    function bounds() {
        const area=pet.screenBounds(Math.round(x+width/2),Math.round(y+height/2))
        return Qt.rect(area.x,area.y,area.width,area.height)
    }
    function place(reset) {
        const area = bounds()
        const pos = pet.position()
        const saved = !reset && (pos.x !== -1 || pos.y !== -1)
        x = saved ? pos.x : area.x + area.width - width - 32
        y = saved ? pos.y : area.y + area.height - height - 28
        constrain()
        placed = true
    }
    function constrain() {
        const area = bounds()
        x = Math.round(Math.max(area.x, Math.min(area.x+area.width-width,x)))
        y = Math.round(Math.max(area.y, Math.min(area.y+area.height-height,y)))
    }
    onVisibleChanged: if (visible) { if (!placed) place(false); else constrain(); Qt.callLater(updateInputMask) }
    onWidthChanged: if (placed && visible) constrain()
    onHeightChanged: if (placed && visible) constrain()
    onClosing: close => { close.accepted = false; pet.ui("hide",{}) }
    Connections {
        target: root.pet
        function onReaction(text) {
            if(!text){root.caption="";root.assistantCaption=false;speech.stop();return}
            if(root.reminderCard.length || root.assistantCaption && speech.running)return
            root.assistantCaption=false;root.caption=text;speech.restart()
        }
        function onAssistantSpeech(text) {
            if(!text){root.assistantCaption=false;root.caption="";speech.stop();return}
            if(root.reminderCard.length)return
            root.assistantCaption=true;root.caption=text.slice(0,1024);speech.restart()
        }
        function onResetPositionRequested() { root.place(true) }
    }
    Connections {
        target:root.screen
        function onWidthChanged(){if(root.visible)root.constrain()}
        function onHeightChanged(){if(root.visible)root.constrain()}
        function onVirtualXChanged(){if(root.visible)root.constrain()}
        function onVirtualYChanged(){if(root.visible)root.constrain()}
    }
    Timer { id:speech; interval:root.assistantCaption ? 8000 : root.state.rareIdle ? 4200 : 2600; onTriggered:{root.caption="";root.assistantCaption=false} }
    Timer {id:reminderTimeout;interval:8000;onTriggered:root.closeReminderCard()}
    // Owned by the window so hiding it cancels pending loop callbacks.
    Timer { id:idleCycleCompletion; interval:0; onTriggered:root.pet.idleCycle() }
    // Compatibility for imported still images; built-in rare scenes are animated.
    Timer {
        interval: 4200; repeat: true
        running: root.visible && !root.config.paused && root.state.action === "idle" && !root.state.animated
        onTriggered: root.pet.idleCycle()
    }
    Rectangle {
        id:bubble; objectName:"desktopPetSpeechBubble"; anchors.horizontalCenter:parent.horizontalCenter
        // Respect both letterboxing and the transparent margin inside the art.
        y:Math.max(4,art.y+art.height-(art.item?art.item.paintedHeight:art.height)*(1-(root.state.contentTop || 0))-height-8)
        width:Math.min(root.width,spoken.implicitWidth+24);height:spoken.implicitHeight+16;radius:12
        color:Theme.surface;border.color:Theme.line;visible:!!root.caption && !root.reminderCard.length
        Text { font.family: Theme.fontFamily;id:spoken;anchors.centerIn:parent;width:Math.min(implicitWidth,root.width-24);text:root.caption;textFormat:Text.PlainText;wrapMode:Text.Wrap;maximumLineCount:4;elide:Text.ElideRight;color:Theme.ink;font.pixelSize: Theme.font(11, visible)}
    }
    Rectangle {
        id:reminder;objectName:"desktopPetReminderCard";z:4;anchors.horizontalCenter:parent.horizontalCenter
        y:Math.max(4,art.y+art.height-(art.item?art.item.paintedHeight:art.height)*(1-(root.state.contentTop || 0))-height-8)
        width:root.width;height:reminderContents.implicitHeight+20;radius:12
        color:Theme.surface;border.color:Theme.line;visible:root.reminderCard.length>0
        ColumnLayout {
            id:reminderContents;anchors.left:parent.left;anchors.right:parent.right;anchors.top:parent.top;anchors.margins:10;spacing:6
            Text { font.family: Theme.fontFamily;Layout.fillWidth:true;text:root.reminderCard.length===1?I18n.t("提醒到期"):I18n.t("有 {count} 项提醒已到期").replace("{count}",root.reminderCard.length);textFormat:Text.PlainText;wrapMode:Text.Wrap;color:Theme.ink;font.bold:true;font.pixelSize: Theme.font(11, visible)}
            Text { font.family: Theme.fontFamily;objectName:"desktopPetReminderCardTitle";Layout.fillWidth:true;text:root.reminderCard.length?root.reminderCard[0].title:"";textFormat:Text.PlainText;wrapMode:Text.Wrap;maximumLineCount:3;elide:Text.ElideRight;color:Theme.ink;font.pixelSize: Theme.font(11, visible)}
            Text { font.family: Theme.fontFamily;Layout.fillWidth:true;visible:root.reminderCard.length===1;text:root.reminderCard.length?root.localTime(root.reminderCard[0].dueAt):"";textFormat:Text.PlainText;wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize: Theme.font(10, visible)}
            Flow {
                Layout.fillWidth:true;spacing:4
                Button {objectName:"desktopPetReminderComplete";visible:root.reminderCard.length===1;text:I18n.t("完成");font.pixelSize: Theme.font(10, visible);onClicked:if(root.reminderCard.length===1){const item=root.reminderCard[0];root.pet.completeReminder(item.id,item.revision)}}
                Button {objectName:"desktopPetReminderView";text:I18n.t(root.reminderCard.length===1?"查看":"查看待办");font.pixelSize: Theme.font(10, visible);onClicked:root.viewReminderCard()}
                Button {objectName:"desktopPetReminderClose";text:I18n.t("关闭");font.pixelSize: Theme.font(10, visible);onClicked:root.closeReminderCard()}
            }
        }
    }
    Loader {
        id:art;objectName:"desktopPetAnimationLoader"
        anchors.horizontalCenter:parent.horizontalCenter;anchors.bottom:parent.bottom
        width:root.config.size;height:width*1.5
        active:root.visible
        sourceComponent:Component {
            Item {
                rotation:root.tilt
                readonly property real paintedHeight:picture.item && picture.item.paintedHeight>0?picture.item.paintedHeight:height
                Loader {
                    id:picture
                    anchors.fill:parent
                    sourceComponent:root.state.animated ? animation : still
                }
                Component {
                    id:animation
                    AnimatedImage {objectName:"desktopPetAnimation";
                        property int previousFrame: -1
                        onSourceChanged: previousFrame = -1
                        onCurrentFrameChanged: {
                            if (previousFrame > currentFrame && root.visible && !root.config.paused)
                                idleCycleCompletion.restart()
                            previousFrame = currentFrame
                        }
                        readonly property bool ready:status===Image.Ready;source:root.state.source;fillMode:Image.PreserveAspectFit;verticalAlignment:Image.AlignBottom;cache:false;asynchronous:true;playing:root.visible && !root.config.paused;mipmap:false;onStatusChanged:if(status===Image.Error)root.caption=I18n.t("形象加载失败，请在桌宠设置中更换形象")}
                }
                Component {id:still;Image {source:root.state.source;fillMode:Image.PreserveAspectFit;verticalAlignment:Image.AlignBottom;asynchronous:true;cache:false;mipmap:true}}
            }
        }
    }
    MouseArea {
        id:pointer;objectName:"desktopPetPointer";anchors.fill:art
        acceptedButtons:Qt.LeftButton | Qt.RightButton;hoverEnabled:true;cursorShape:pressed?Qt.ClosedHandCursor:Qt.PointingHandCursor
        onEntered:root.pet.interact("hover")
        onPressed:mouse => {
            root.dragged=false
            root.pressX=mouse.x;root.pressY=mouse.y;root.startX=root.x;root.startY=root.y
            if(mouse.button===Qt.RightButton)menu.popup()
        }
        onPositionChanged:mouse => {
            if(!(pressedButtons & Qt.LeftButton))return
            const dx=mouse.x-root.pressX,dy=mouse.y-root.pressY
            if(!root.dragged && Math.abs(dx)+Math.abs(dy)<7)return
            if(!root.dragged){root.dragged=true;root.pet.interact("drag")}
            root.x+=dx;root.y+=dy
        }
        onReleased:mouse => {
            if(mouse.button!==Qt.LeftButton)return
            if(root.dragged){root.constrain();root.pet.savePosition(root.x,root.y)}
            else root.pet.interact("tap")
        }
        onCanceled:if(root.dragged){root.constrain();root.pet.savePosition(root.x,root.y)}
    }
    component PetMenu: FloatingMenu {
        id: petMenu
        popupType: Popup.Window
        constrainToWindow: false
        delegate: ContextAction {
            glyph: subMenu && subMenu.objectName === "desktopPetReminderMenu" ? "clock" : "pet"
        }
        Connections {
            target: petMenu
            function onAboutToShow() {
                // Retain stacking after toggling the pet's always-on-top flag.
                const popupWindow = petMenu.contentItem.Window.window
                popupWindow.flags |= Qt.WindowStaysOnTopHint
                popupWindow.raise()
            }
        }
    }
    component PetSeparator: MenuSeparator {
        contentItem: Rectangle { implicitHeight: 1; color: Theme.line }
    }
    PetMenu {
        id: menu; objectName: "desktopPetContextMenu"
        ContextAction { text: I18n.t("打开 Umeko"); glyph: "external-link"; onTriggered: root.pet.restoreRequested() }
        PetMenu {
            objectName: "desktopPetReminderMenu"; title: I18n.t("提醒与待办") + " (" + root.pet.reminderItems.length + ")"
            ContextAction { visible: root.pet.reminderItems.length === 0; text: I18n.t("暂无待办"); enabled: false }
            Repeater {
                model: root.pet.reminderItems.slice(0, 3)
                ContextAction {
                    required property var modelData
                    text: modelData.title + " · " + root.localTime(modelData.dueAt)
                    implicitWidth: Theme.control(300)
                    onTriggered: root.pet.openReminders(modelData.id, false)
                }
            }
            PetSeparator {}
            ContextAction { objectName: "desktopPetReminderNewMenu"; text: I18n.t("新增事项…"); glyph: "plus"; onTriggered: root.pet.openReminders("", true) }
            ContextAction { objectName: "desktopPetReminderManageMenu"; text: I18n.t("管理全部…"); glyph: "sliders"; onTriggered: root.pet.openReminders("", false) }
        }
        ContextAction { text: I18n.t("桌宠设置"); glyph: "settings"; onTriggered: root.pet.settingsRequested() }
        PetSeparator {}
        PetMenu {
            objectName: "desktopPetAppearanceMenu"; title: I18n.t("动画形象")
            Repeater {
                model: root.pet.appearances
                ContextAction {
                    required property var modelData
                    objectName: "desktopPetAppearance_" + modelData.id
                    text: modelData.name; glyph: "pet"
                    checkable: true; checked: root.config.appearance === modelData.id
                    onTriggered: root.pet.ui("selectAppearance", {id: modelData.id})
                }
            }
        }
        ContextAction { objectName: "desktopPetPauseAction"; text: I18n.t("暂停动作"); glyph: "stop"; checkable: true; checked: root.config.paused; onTriggered: root.pet.ui("configure", {paused: !root.config.paused}) }
        ContextAction { objectName: "desktopPetPinAction"; text: I18n.t("保持置顶"); glyph: "pin"; checkable: true; checked: root.config.alwaysOnTop; onTriggered: root.pet.ui("configure", {alwaysOnTop: !root.config.alwaysOnTop}) }
        ContextAction { text: I18n.t("重置位置"); glyph: "refresh"; onTriggered: root.pet.ui("resetPosition", {}) }
        PetSeparator {}
        ContextAction { text: I18n.t("隐藏桌宠"); glyph: "eye-off"; onTriggered: root.pet.ui("hide", {}) }
    }
}
