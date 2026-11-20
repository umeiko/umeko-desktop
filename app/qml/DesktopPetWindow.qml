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
    readonly property var assistant: pet.assistantStatus
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
        if(!speech)return
        const keys=reminderCard.map(item=>item.id+":"+item.occurrence).join("|")
        if(keys && keys!==reminderKeys){caption="";speech.stop()}
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
    onVisibleChanged: {
        if (visible) { if (!placed) place(false); else constrain(); Qt.callLater(updateInputMask) }
        else if (taskComposer) taskComposer.close()
    }
    onAssistantChanged: {
        if (taskComposer && (!assistant.bound || taskComposer.targetId !== assistant.id)) taskComposer.close()
    }
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
    Timer { id:speech; objectName:"desktopPetSpeechTimer"; interval:root.assistantCaption ? root.pet.speechDuration(root.caption) : root.state.rareIdle ? 4200 : 2600; onTriggered:{root.caption="";root.assistantCaption=false} }
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
        color:Theme.surface;border.color:Theme.line;visible:!!root.caption && !root.reminderCard.length && (root.assistantCaption || !taskComposer.visible)
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
                ReminderButton {objectName:"desktopPetReminderView";text:I18n.t(root.reminderCard.length===1?"查看":"查看待办");font.pixelSize: Theme.font(10, visible);onClicked:root.viewReminderCard()}
            }
        }
    }
    Rectangle {
        objectName:"desktopPetReminderUnreadDot";z:6
        width:10*Theme.fontScale;height:width;radius:width/2;color:Theme.danger
        visible:root.reminderCard.length>0
        x:Math.min(root.width-width-2,reminder.x+reminder.width-width-2);y:Math.max(2,reminder.y-3)
        border.width:2;border.color:Theme.surface
        TapHandler {onTapped:root.viewReminderCard()}
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
            const cursor = root.pet.cursorPosition()
            root.pressX=cursor.x;root.pressY=cursor.y;root.startX=root.x;root.startY=root.y
            if(mouse.button===Qt.RightButton)menu.popup()
        }
        onPositionChanged:mouse => {
            if(!(pressedButtons & Qt.LeftButton))return
            const cursor = root.pet.cursorPosition()
            const dx=cursor.x-root.pressX,dy=cursor.y-root.pressY
            if(!root.dragged && Math.abs(dx)+Math.abs(dy)<7)return
            if(!root.dragged){root.dragged=true;root.pet.interact("drag")}
            root.x=root.startX+dx;root.y=root.startY+dy
        }
        onReleased:mouse => {
            if(mouse.button!==Qt.LeftButton)return
            if(root.dragged){root.constrain();root.pet.savePosition(root.x,root.y)}
            else root.pet.interact("tap")
        }
        onDoubleClicked: mouse => {
            if (mouse.button === Qt.LeftButton && !root.dragged) root.openTaskComposer()
        }
        onCanceled:if(root.dragged){root.constrain();root.pet.savePosition(root.x,root.y)}
    }
    function openTaskComposer() {
        if (!root.assistant.bound) return
        if (taskComposer.targetId !== root.assistant.id) taskInput.clear()
        taskComposer.targetId = root.assistant.id
        taskComposer.error = ""
        if (!taskWindow.placement.blocked) taskComposer.open()
    }
    // A non-modal tool window does not grab/rewrite pet mouse events.
    Window {
        id: taskWindow
        objectName: "desktopPetTaskWindow"
        transientParent: root
        color: "transparent"
        flags: Qt.Tool | Qt.FramelessWindowHint | (root.config.alwaysOnTop ? Qt.WindowStaysOnTopHint : 0)
        visible: taskComposer.visible
        width: taskComposer.width
        height: taskComposer.height
        readonly property var placement: {
            const area = root.bounds()
            const left = root.x + (root.width - width) / 2
            const notice = reminder.visible ? reminder : bubble.visible && root.assistantCaption ? bubble : null
            const top = notice ? root.y + notice.y - height - 8
                : root.y + art.y + art.height - (art.item ? art.item.paintedHeight : art.height) * (1 - (root.state.contentTop || 0)) - height - 8
            const minimum = area.y + 8
            const maximum = area.y + area.height - height - 8
            const below = notice ? root.y + notice.y + notice.height + 8 : top
            const aboveFits = top >= minimum && top <= maximum
            const belowFits = below >= minimum && below <= maximum
            // Prefer above the notice; use below near the top edge. Only
            // hide the capsule if neither placement can leave it readable.
            const preferred = notice && !aboveFits && belowFits ? below : top
            return {
                x: Math.round(Math.max(area.x + 8, Math.min(area.x + area.width - width - 8, left))),
                y: Math.round(Math.max(minimum, Math.min(maximum, preferred))),
                blocked: !!notice && !aboveFits && !belowFits
            }
        }
        x: placement.x
        y: placement.y
        onClosing: event => { event.accepted = false; taskComposer.close() }
        // Defer focus checks so pet-to-input transitions and IME composition
        // do not dismiss the draft. No global mouse grab is used.
        Timer {
            interval: 150; repeat: true; running: taskComposer.opened
            onTriggered: {
                if (!taskWindow.active && !root.active && !taskInput.inputMethodComposing)
                    taskComposer.close()
            }
        }
        PidPopup {
            id: taskComposer
            objectName: "desktopPetTaskComposer"
            parent: taskWindow.contentItem
            popupType: Popup.Item
            property string targetId: ""
            property string error: ""
            property bool sending: false
            readonly property bool notificationBlocked: taskWindow.placement.blocked
            readonly property color inputBlue: Theme.dark ? "#83b7ff" : "#2463c4"
            readonly property bool controlFocused: taskInput.activeFocus || taskSend.activeFocus || taskDesktop.activeFocus
            opacity: notificationBlocked ? 0 : animationProgress
            onNotificationBlockedChanged: if (notificationBlocked && visible) close()
            modal: false
            width: Math.min(Theme.control(400), root.bounds().width - 16)
            height: taskScroll.height + Theme.control(12)
            padding: 0
            // Native popups may extend beyond the small, masked pet window.
            // Fit to the work area ourselves instead of shrinking to its parent.
            margins: -1
            focus: true
            closePolicy: taskInput.inputMethodComposing ? Popup.NoAutoClose : Popup.CloseOnEscape
            onAboutToHide: Qt.inputMethod.reset()
            onOpened: {
                taskWindow.requestActivate()
                taskInput.forceActiveFocus(Qt.PopupFocusReason)
                Qt.inputMethod.update(Qt.ImQueryAll)
            }
            function submit() {
                if (sending || !taskInput.text.trim().length) return
                Qt.inputMethod.commit()
                if (taskInput.inputMethodComposing) return
                sending = true
                const result = root.pet.sendTask(taskInput.text, targetId)
                sending = false
                if (result.ok) { taskInput.clear(); close() }
                else { error = I18n.t(result.error); taskInput.forceActiveFocus() }
            }
            component ComposerButton: Button {
                id:key
                property bool primary:false
                property string glyph:""
                implicitWidth:Theme.control(primary?30:26)
                implicitHeight:implicitWidth
                padding:0;hoverEnabled:true
                Accessible.name:text
                ToolTip.visible:hovered;ToolTip.delay:700;ToolTip.text:Accessible.name
                HoverHandler {cursorShape:key.enabled?Qt.PointingHandCursor:Qt.ArrowCursor}
                background:Item {
                    MachinedButtonFace {anchors.fill:parent;visible:key.primary;pressed:key.down;focused:key.visualFocus;active:key.enabled}
                    Rectangle {
                        visible:!key.primary;y:key.down?1:0;width:parent.width;height:parent.height-1;radius:width/2
                        border.color:key.visualFocus?taskComposer.inputBlue:Theme.dark?"#232a33":"#b1b8c0"
                        gradient:Gradient {
                            GradientStop {position:0;color:key.down?Theme.dark?"#2e3640":"#ccd2d9":Theme.dark?"#555e69":"#fafcfd"}
                            GradientStop {position:1;color:Theme.dark?"#343e49":"#d1d8df"}
                        }
                        Rectangle {anchors.fill:parent;anchors.margins:1;radius:width/2;color:"transparent";border.color:Theme.dark?"#30ffffff":"#c0ffffff"}
                    }
                }
                contentItem:Item {
                    // A light lower cut edge, a dark upper recess and blue ink.
                    Glyph {anchors.centerIn:parent;anchors.verticalCenterOffset:(key.down?1:0)+0.8;name:key.glyph;width:Theme.icon(key.primary?16:13);height:width;color:Theme.dark?"#c5d3df":"#ffffff";opacity:key.enabled?0.95:0.5}
                    Glyph {anchors.centerIn:parent;anchors.verticalCenterOffset:(key.down?1:0)-0.4;name:key.glyph;width:Theme.icon(key.primary?16:13);height:width;color:"#465767";opacity:key.enabled?0.8:0.35}
                    Glyph {anchors.centerIn:parent;anchors.verticalCenterOffset:key.down?1:0;name:key.glyph;width:Theme.icon(key.primary?16:13);height:width;color:key.primary?(key.enabled?"#355d80":"#84929e"):Theme.dark?"#d2d9df":"#6e7e8d"}
                }
            }
            background:Rectangle {
                objectName:"desktopPetTaskSurface"
                radius:height/2;border.width:1
                border.color:taskComposer.error?Theme.danger:Theme.dark?"#202329":"#aab1ba"
                gradient:Gradient {GradientStop {position:0;color:Theme.dark?"#4b5058":"#f5f6f8"} GradientStop {position:1;color:Theme.dark?"#363a41":"#dce0e5"}}
                Rectangle {anchors.fill:parent;anchors.margins:1;radius:height/2;color:"transparent";border.color:Theme.dark?"#18ffffff":"#c0ffffff"}
            }
            contentItem:Item {
                enabled:taskComposer.desiredOpen && !taskComposer.notificationBlocked
                ScrollView {
                    id: taskScroll
                    anchors.left:parent.left;anchors.right:taskDesktop.left
                    anchors.leftMargin:6*Theme.fontScale;anchors.rightMargin:5*Theme.fontScale;anchors.verticalCenter:parent.verticalCenter
                    readonly property real singleLineHeight: Theme.control(28)
                    readonly property real verticalInset: Math.max(0, (singleLineHeight - taskFont.height) / 2)
                    height: taskInput.lineCount <= 1 ? singleLineHeight
                        : Math.min(taskInput.contentHeight + 2 * verticalInset, Theme.control(104))
                    clip: true
                    contentWidth: availableWidth
                    FontMetrics { id: taskFont; font: taskInput.font }
                    ChatInput {
                        id: taskInput; objectName: "desktopPetTaskInput"
                        leftPadding: 9*Theme.fontScale; rightPadding: 8*Theme.fontScale
                        topPadding: taskScroll.verticalInset; bottomPadding: taskScroll.verticalInset
                        font.family: Theme.fontFamily; font.pixelSize: Theme.font(13, true)
                        color: Theme.ink; wrapMode: TextArea.Wrap; selectByMouse: true
                        background: null
                        Accessible.name: I18n.t("给悬浮小助手派活")
                        Accessible.description: taskComposer.error
                        onTextChanged: taskComposer.error = ""
                        KeyNavigation.priority: KeyNavigation.BeforeItem
                        KeyNavigation.tab: taskDesktop
                        Keys.onEscapePressed: event => {
                            if (inputMethodComposing) { Qt.inputMethod.reset(); event.accepted = true }
                            else event.accepted = false
                        }
                        onSubmitted: taskComposer.submit()
                    }
                    background:Rectangle {
                        radius:Math.min(height/2,Theme.control(14));color:Theme.dark?"#25292f":"#fdfefe"
                        border.color:taskComposer.error?Theme.danger:taskInput.activeFocus?Qt.alpha(taskComposer.inputBlue,0.75):Theme.dark?"#181b20":"#a8afb7"
                        Rectangle {x:8;y:1;width:parent.width-16;height:2;radius:1;gradient:Gradient {GradientStop {position:0;color:Theme.dark?"#40000000":"#20000000"} GradientStop {position:1;color:"transparent"}}}
                        Rectangle {x:5;y:parent.height-1;width:parent.width-10;height:1;color:Theme.dark?"#20ffffff":"#e0ffffff"}
                    }
                }
                ComposerButton {
                    id:taskDesktop;objectName:"desktopPetTaskDesktop"
                    anchors.right:taskSend.left;anchors.rightMargin:5*Theme.fontScale;anchors.verticalCenter:parent.verticalCenter
                    glyph:"external-link";Accessible.name:I18n.t("打开 Umeko")
                    onClicked:{taskComposer.close();root.pet.restoreRequested()}
                }
                ComposerButton {
                    id:taskSend;objectName:"desktopPetTaskSend"
                    anchors.right:parent.right;anchors.rightMargin:Theme.control(5);anchors.verticalCenter:parent.verticalCenter
                    primary:true;glyph:"arrow-up";text:I18n.t("发送")
                    enabled:taskInput.text.trim().length>0 && !taskComposer.sending
                    onClicked:taskComposer.submit()
                }
            }
            ToolTip {
                parent: taskComposer.contentItem
                x: 0
                y: -height - 8
                width: Math.min(implicitWidth, taskComposer.width)
                visible: taskComposer.opened && taskComposer.error.length > 0
                text: taskComposer.error
                padding: 10
                background: Rectangle { radius: 10; color: Theme.surface; border.color: Theme.danger }
                contentItem: Text {
                    text: taskComposer.error; textFormat: Text.PlainText
                    font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible)
                    color: Theme.ink; wrapMode: Text.Wrap
                }
            }
        }
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
    PetAgentEntryWindow { pet: root.pet; petWindow: root }
    PetMenu {
        id: menu; objectName: "desktopPetContextMenu"
        ContextAction { objectName: "desktopPetAgentEntry"; text: I18n.t("发送给已有全局智能体…"); glyph: "chat"; onTriggered: root.pet.agentEntry.open() }
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
