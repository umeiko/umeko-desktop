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
        if (taskComposer.targetId !== root.assistant.id) { taskInput.clear(); taskComposer.projectMode = false }
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
                if (!taskWindow.active && !root.active && !timerPrompt.focusWithin
                        && !(projectMenu.visible && projectMenu.contentItem.Window.window.active)
                        && !taskInput.inputMethodComposing)
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
            property bool projectMode: false
            property string globalDraft: ""
            property string timerDraft: ""
            readonly property var timerState: root.pet.taskSchedule.state
            readonly property bool timerMode: timerState.opened
            readonly property var projectState: root.pet.projectEntry.state
            readonly property bool notificationBlocked: taskWindow.placement.blocked
            readonly property color inputBlue: Theme.dark ? "#83b7ff" : "#2463c4"
            readonly property bool controlFocused: taskInput.activeFocus || taskSend.activeFocus || taskDesktop.activeFocus || projectTarget.activeFocus
            opacity: notificationBlocked ? 0 : animationProgress
            onNotificationBlockedChanged: if (notificationBlocked && visible) close()
            modal: false
            width: Math.min(Theme.control(360), root.screen.width - 24)
            height: Math.max(52, taskInput.implicitHeight + 12)
            padding: 0
            // Native popups may extend beyond the small, masked pet window.
            // Fit to the work area ourselves instead of shrinking to its parent.
            margins: -1
            focus: true
            closePolicy: taskInput.inputMethodComposing || timerMode ? Popup.NoAutoClose : Popup.CloseOnEscape
            onAboutToHide: {
                Qt.inputMethod.reset()
                projectMenu.close()
                if (timerMode) { root.pet.taskSchedule.close(); taskInput.text = timerDraft }
                root.pet.projectEntry.close()
                taskInput.focus = false
            }
            onOpened: {
                if (projectMode) root.pet.projectEntry.openCommand("/项目", targetId)
                taskWindow.requestActivate()
                taskInput.forceActiveFocus(Qt.PopupFocusReason)
                Qt.inputMethod.update(Qt.ImQueryAll)
            }
            // Auxiliary surfaces share the capsule's screen and avoid urgent notices.
            function auxiliaryPlacement(surfaceHeight, preferBelow) {
                const area = root.bounds()
                const notice = reminder.visible ? reminder : bubble.visible && root.assistantCaption ? bubble : null
                const above = taskWindow.y - surfaceHeight - 6
                const below = taskWindow.y + taskWindow.height + 6
                const candidates = preferBelow ? [below, above] : [above, below]
                if (notice) candidates.push(root.y + notice.y - surfaceHeight - 6, root.y + notice.y + notice.height + 6)
                for (const y of candidates) {
                    if (y < area.y + 8 || y + surfaceHeight > area.y + area.height - 8) continue
                    if (y < taskWindow.y + taskWindow.height && y + surfaceHeight > taskWindow.y) continue
                    if (notice && y < root.y + notice.y + notice.height && y + surfaceHeight > root.y + notice.y) continue
                    return { y: Math.round(y), blocked: false }
                }
                return { y: Math.round(Math.max(area.y + 8, above)), blocked: true }
            }
            function focusTimerInput() {
                const window = taskWindow
                if (window) window.requestActivate()
                taskInput.forceActiveFocus(Qt.PopupFocusReason)
                Qt.inputMethod.update(Qt.ImQueryAll)
            }
            function chooseProject(identifier) {
                const result = root.pet.projectEntry.select(identifier)
                if (!result.ok) { error = result.error; return }
                if (!projectMode) globalDraft = taskInput.text
                projectMode = true
                taskInput.text = result.text
                error = ""
                projectMenu.close()
                focusTimerInput()
            }
            function projectChoices(command) {
                if (!desiredOpen) return
                if (projectMode) root.pet.projectEntry.setBody(taskInput.text)
                else root.pet.projectEntry.leaveProject()
                const result = root.pet.projectEntry.openCommand(command, targetId)
                if (!result.ok) { error = result.error; return }
                projectMenu.open()
            }
            function useDefaultTarget() {
                if (!projectMode) { projectMenu.close(); focusTimerInput(); return }
                if (projectMode) root.pet.projectEntry.setBody(taskInput.text)
                root.pet.projectEntry.leaveProject()
                projectMode = false
                taskInput.text = globalDraft
                projectMenu.close()
                focusTimerInput()
            }
            function submit() {
                if (!desiredOpen || sending || !taskInput.text.trim().length) return
                Qt.inputMethod.commit()
                if (taskInput.inputMethodComposing) return
                if (timerMode) {
                    const answer = root.pet.taskSchedule.answer(taskInput.text)
                    if (answer.ok) taskInput.text = answer.closed ? timerDraft : root.pet.taskSchedule.state.answer
                    taskInput.forceActiveFocus()
                    return
                }
                if (/^\/项目(?:\s|$)/.test(taskInput.text.trim())) {
                    if (!taskComposer.desiredOpen) return
                    projectChoices(taskInput.text)
                    return
                }
                if (/^\/定时任务(?:\s|$)/.test(taskInput.text.trim())) {
                    if (!taskComposer.desiredOpen) return
                    const prepared = root.pet.taskSchedule.openCommand(taskInput.text, targetId)
                    if (prepared.ok) {
                        if (projectMode && projectState.selected) root.pet.taskSchedule.selectOwner(projectState.selected)
                        timerDraft = taskInput.text; taskInput.text = root.pet.taskSchedule.state.answer; taskInput.forceActiveFocus()
                    }
                    else { error = prepared.error; taskInput.forceActiveFocus() }
                    return
                }
                sending = true
                if (projectMode && !desiredOpen) { sending = false; return }
                const result = projectMode ? root.pet.projectEntry.submitText(taskInput.text, targetId) : root.pet.sendTask(taskInput.text, targetId)
                sending = false
                if (result.ok) { taskInput.clear(); close() }
                else { error = I18n.t(result.error); taskInput.forceActiveFocus() }
            }
            background: Rectangle {
                radius: height / 2
                color: Theme.surface
                border.width: taskComposer.controlFocused ? 2 : 1
                border.color: taskComposer.error ? Theme.danger : Qt.alpha(taskComposer.inputBlue, taskComposer.controlFocused ? 1 : 0.45)
            }
            contentItem: Item {
                enabled: taskComposer.desiredOpen && !taskComposer.notificationBlocked
                InputField {
                    id: taskInput
                    objectName: "desktopPetTaskInput"
                    anchors.fill: parent
                    leftPadding: taskComposer.projectMode && !taskComposer.timerMode ? projectTarget.width + 22 : 18
                    rightPadding: parent.height + taskDesktop.width + 8
                    maximumLength: 16000
                    Accessible.name: I18n.t("给悬浮小助手派活")
                    Accessible.description: taskComposer.timerMode ? taskComposer.timerState.question.prompt : taskComposer.error
                    placeholderText: taskComposer.timerMode ? "输入回答…" : ""
                    onTextEdited: { taskComposer.error = ""; if (taskComposer.timerMode) root.pet.taskSchedule.setAnswer(text); else if (taskComposer.projectMode) root.pet.projectEntry.setBody(text) }
                    Keys.onEscapePressed: event => {
                        if (inputMethodComposing) { Qt.inputMethod.reset(); event.accepted = true }
                        else if (taskComposer.timerMode) { root.pet.taskSchedule.close(); text = taskComposer.timerDraft; event.accepted = true }
                        else event.accepted = false
                    }
                    onAccepted: if (!inputMethodComposing) taskComposer.submit()
                    background: null
                }
                Button {
                    id: projectTarget; objectName: "desktopPetProjectTarget"
                    visible: taskComposer.projectMode && !taskComposer.timerMode
                    x: 10; anchors.verticalCenter: parent.verticalCenter
                    width: Math.min(110, taskComposer.width * .32); height: parent.height - 18
                    padding: 6
                    hoverEnabled: true
                    text: taskComposer.projectState.label
                    Accessible.name: "选择项目会话：" + text
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                    // A quiet inline target, not a second grey input control.
                    background: Rectangle {
                        radius: height / 2
                        color: projectTarget.down ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, .14)
                            : projectTarget.hovered ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, .07) : "transparent"
                        border.width: projectTarget.visualFocus ? 1 : 0
                        border.color: Theme.accent
                    }
                    contentItem: Item {
                        Glyph { id: targetFolder; name: "folder"; width: 13; height: 13; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; color: Theme.accent }
                        Text {
                            anchors.left: targetFolder.right; anchors.leftMargin: 5
                            anchors.right: targetChevron.left; anchors.rightMargin: 3
                            anchors.verticalCenter: parent.verticalCenter
                            text: projectTarget.text; elide: Text.ElideRight
                            color: Theme.accent; font.pixelSize: Theme.font(11, visible)
                        }
                        Glyph { id: targetChevron; name: "chevron-down"; width: 10; height: 10; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; color: Theme.accent; opacity: .65 }
                    }
                    onClicked: taskComposer.projectChoices("/项目")
                    ToolTip.visible: hovered; ToolTip.text: taskComposer.projectState.label + "\n" + taskComposer.projectState.detail
                }
                Button {
                    id: taskDesktop
                    objectName: "desktopPetTaskDesktop"
                    width: parent.height - 16
                    height: width
                    anchors.right: taskSend.left
                    anchors.rightMargin: 4
                    anchors.verticalCenter: parent.verticalCenter
                    padding: 0
                    hoverEnabled: true
                    Accessible.name: I18n.t("打开 Umeko")
                    ToolTip.visible: hovered
                    ToolTip.delay: 700
                    ToolTip.text: Accessible.name
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                    background: Rectangle {
                        radius: width / 2
                        color: taskDesktop.down ? Theme.line : taskDesktop.hovered ? Theme.hover : "transparent"
                        border.width: taskDesktop.activeFocus ? 2 : 0
                        border.color: taskComposer.inputBlue
                    }
                    contentItem: Item {
                        Glyph { anchors.centerIn: parent; name: "external-link"; color: Theme.muted; width: Theme.icon(16); height: width }
                    }
                    onClicked: { taskComposer.close(); root.pet.restoreRequested() }
                }
                Button {
                    id: taskSend
                    objectName: "desktopPetTaskSend"
                    // Both circles share the right end cap's exact center.
                    width: parent.height - 16
                    height: width
                    x: parent.width - parent.height / 2 - width / 2
                    y: (parent.height - height) / 2
                    padding: 0
                    hoverEnabled: true
                    enabled: taskInput.text.trim().length > 0 && !taskComposer.sending
                    Accessible.name: I18n.t("发送")
                    ToolTip.visible: hovered
                    ToolTip.delay: 700
                    ToolTip.text: Accessible.name
                    HoverHandler { cursorShape: taskSend.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
                    background: Rectangle {
                        radius: width / 2
                        color: Qt.alpha(taskComposer.inputBlue, taskSend.down ? 0.22 : taskSend.hovered ? 0.15 : 0.08)
                        border.width: taskSend.activeFocus ? 2 : 0
                        border.color: taskComposer.inputBlue
                    }
                    contentItem: Item {
                        Glyph { anchors.centerIn: parent; name: "arrow-up"; color: Qt.alpha(taskComposer.inputBlue, taskSend.enabled ? 1 : 0.38); width: Theme.icon(18); height: width }
                    }
                    onClicked: taskComposer.submit()
                }
            }
            PetTimerPrompt {
                id: timerPrompt
                schedule: root.pet.taskSchedule
                composer: taskComposer
                onAnswered: { taskInput.text = root.pet.taskSchedule.state.answer; taskComposer.focusTimerInput() }
                onDismissed: { taskInput.text = taskComposer.timerDraft; taskComposer.focusTimerInput() }
            }
            FloatingMenu {
                id: projectMenu; objectName: "desktopPetProjectMenu"
                parent: taskComposer.contentItem
                popupType: Popup.Window; constrainToWindow: false
                width: Math.min(340, root.screen.width - 24)
                height: Math.min(implicitHeight, 320, root.screen.height - 32)
                readonly property var placement: taskComposer.auxiliaryPlacement(height, true)
                x: 0; y: placement.y - taskWindow.y
                function closeIfBlocked() {
                    Qt.callLater(function() { if (visible && placement.blocked) taskComposer.close() })
                }
                onPlacementChanged: closeIfBlocked()
                onVisibleChanged: if (visible) closeIfBlocked()
                onClosed: if (taskComposer.desiredOpen) taskComposer.focusTimerInput()
                ContextAction { objectName: "desktopPetProjectDefault"; text: "默认 · 悬浮小助手"; onTriggered: taskComposer.useDefaultTarget() }
                ContextAction { text: "暂无已有项目会话，请在 Desktop 准备"; visible: !taskComposer.projectState.options.length; enabled: false }
                Repeater {
                    model: taskComposer.projectState.options
                    ContextAction {
                        required property var modelData
                        objectName: "desktopPetProject_" + modelData.id
                        text: modelData.name; implicitWidth: 320
                        checkable: true; checked: taskComposer.projectMode && taskComposer.projectState.selected === modelData.id
                        onTriggered: taskComposer.chooseProject(modelData.id)
                        ToolTip.visible: hovered; ToolTip.text: modelData.detail
                    }
                }
                MenuSeparator {}
                ContextAction { text: taskComposer.projectState.submission.id ? "打开 Desktop · 上次发送会话" : "打开 Desktop 对应会话"; onTriggered: root.pet.projectEntry.openDesktop() }
                ContextAction { objectName: "desktopPetProjectAcknowledge"; text: "已核对上次结果，允许新发送"; visible: !!taskComposer.projectState.submission.id; onTriggered: { root.pet.projectEntry.acknowledge(); taskComposer.error = "" } }
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
