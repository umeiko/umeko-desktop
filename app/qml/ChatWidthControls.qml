import QtQuick
import QtQuick.Controls
import QtQuick.Window

Item {
    id: root
    objectName: "chatWidthControls"
    property bool expandedLeft: false
    property bool expandedRight: false
    readonly property var hostWindow: root.Window.window
    readonly property bool canReveal: enabled && visible && expandable && !!hostWindow && hostWindow.active
    property point pointerPosition: Qt.point(-1, -1)
    property bool pointerValid: false
    property var pointerSource: null
    property bool keyboardNavigation: false
    function forgetPointer() { pointerValid = false; pointerSource = null; keyboardNavigation = false }
    function recordPointer(handler) {
        keyboardNavigation = false
        pointerSource = handler
        pointerPosition = handler.parent.mapToItem(root, handler.point.position.x, handler.point.position.y)
        pointerValid = canReveal && handler.hovered
    }
    function inside(item) {
        const origin = item.mapToItem(root, 0, 0)
        return pointerValid && pointerPosition.x >= origin.x && pointerPosition.x < origin.x + item.width
                && pointerPosition.y >= origin.y && pointerPosition.y < origin.y + item.height
    }
    onCanRevealChanged: if (!canReveal) forgetPointer()
    onEnabledChanged: forgetPointer()
    onVisibleChanged: forgetPointer()
    onWidthChanged: forgetPointer()
    onHeightChanged: forgetPointer()
    Connections { target: backend; function onViewChanged() { root.forgetPointer() } }
    Connections { target: root.hostWindow; function onActiveChanged() { root.forgetPointer() } }
    // Sample only the margins: a full-chat HoverHandler suppresses MouseArea
    // hover beneath it, including file feedback and message action buttons.
    component MarginHover: HoverHandler {
        id: handler; blocking: false
        onPointChanged: root.recordPointer(handler)
        onHoveredChanged: { if (hovered) root.recordPointer(handler); else if (root.pointerSource === handler) root.forgetPointer() }
    }
    readonly property real edgeInset: Math.max(108, Theme.control(76) + 32)
    readonly property bool expandable: width >= 850 + 2 * (edgeInset + 64)
    readonly property real defaultComposerMargin: Math.max(47, (width - 850) / 2)
    readonly property real defaultConversationMargin: Math.max(38, (width - 830) / 2)
    property real leftReveal: expandable && expandedLeft ? 1 : 0
    property real rightReveal: expandable && expandedRight ? 1 : 0
    readonly property real composerLeft: defaultComposerMargin - leftReveal * (defaultComposerMargin - edgeInset)
    readonly property real composerRight: defaultComposerMargin - rightReveal * (defaultComposerMargin - edgeInset)
    readonly property real conversationLeft: defaultConversationMargin - leftReveal * (defaultConversationMargin - edgeInset - 10)
    readonly property real conversationRight: defaultConversationMargin - rightReveal * (defaultConversationMargin - edgeInset - 10)
    Behavior on leftReveal { enabled: root.expandable; NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
    Behavior on rightReveal { enabled: root.expandable; NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

    component EdgeButton: Button {
        id: control
        property string hint: ""
        property bool nearby: false
        property bool leftSide: false
        property bool collapsing: false
        property real effort: 0
        readonly property bool revealed: root.canReveal && (nearby || root.keyboardNavigation && visualFocus)
        readonly property real effortDirection: (leftSide ? -1 : 1) * (collapsing ? -1 : 1)
        width: Theme.control(76); height: Theme.control(70)
        visible: root.expandable
        opacity: revealed ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: control.revealed ? 120 : 180 } }
        y: root.height * 0.47 - height / 2
        padding: 0; hoverEnabled: true; focusPolicy: Qt.TabFocus
        onVisualFocusChanged: if (visualFocus && root.canReveal) root.keyboardNavigation = true
        Keys.onPressed: event => { root.keyboardNavigation = true; event.accepted = false }
        scale: down ? 0.96 : nearby ? 1.04 : 1
        Behavior on scale { NumberAnimation { duration: 100 } }
        Accessible.name: hint
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        contentItem: Image {
            objectName: control.objectName + "Mascot"
            readonly property bool loaded: status === Image.Ready
            source: root.expandable ? "../icons/yanami-" + (control.collapsing ? "pull" : "push") + ".png" : ""
            mirror: control.leftSide; fillMode: Image.PreserveAspectFit
            sourceSize: Qt.size(320, 320); asynchronous: true; cache: true; mipmap: true
            transform: Translate { x: control.effort }
        }
        background: Rectangle {
            radius: 12; color: Theme.accentBg; border.color: Theme.accent
            opacity: control.visualFocus ? 0.5 : 0
        }
        SequentialAnimation on effort {
            running: root.canReveal && control.nearby && control.opacity > 0.95
            loops: Animation.Infinite
            NumberAnimation { to: control.effortDirection * 1.5; duration: 380; easing.type: Easing.InOutSine }
            NumberAnimation { to: 0; duration: 380; easing.type: Easing.InOutSine }
            onStopped: control.effort = 0
        }
        HoverTip { active: root.canReveal && control.nearby && root.inside(control) && !control.down; text: control.hint }
    }
    Item {
        id: leftZone
        objectName: "chatWidthLeftHoverZone"
        x: 0; y: 0; width: root.composerLeft; height: root.height
        visible: root.expandable
        MarginHover { objectName: "chatWidthLeftPointer" }
        EdgeButton {
            id: leftButton
            objectName: "expandChatLeft"
            nearby: root.canReveal && root.inside(leftZone)
            leftSide: true; collapsing: root.expandedLeft
            x: (root.composerLeft - width) / 2
            text: root.expandedLeft ? "\u25b6" : "\u25c0"
            hint: root.expandedLeft ? I18n.t("收起左侧") : I18n.t("向左展开")
            onClicked: root.expandedLeft = !root.expandedLeft
        }
    }
    Item {
        id: rightZone
        objectName: "chatWidthRightHoverZone"
        x: root.width - root.composerRight; y: 0
        // Leave the outer 24 pixels available to the question navigation rail.
        width: Math.max(0, root.composerRight - 24); height: root.height; visible: root.expandable
        MarginHover { objectName: "chatWidthRightPointer" }
        EdgeButton {
            id: rightButton
            objectName: "expandChatRight"
            nearby: root.canReveal && root.inside(rightZone)
            collapsing: root.expandedRight
            x: (parent.width - width) / 2
            text: root.expandedRight ? "\u25c0" : "\u25b6"
            hint: root.expandedRight ? I18n.t("收起右侧") : I18n.t("向右展开")
            onClicked: root.expandedRight = !root.expandedRight
        }
    }
}
