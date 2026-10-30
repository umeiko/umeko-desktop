import QtQuick
import QtQuick.Controls
import QtQuick.Window

Window {
    id: root
    objectName: "desktopPetWindow"
    required property var pet
    readonly property var state: pet.state
    readonly property var config: pet.config
    property string caption: ""
    property bool placed: false
    property bool dragged: false
    property real pressX: 0
    property real pressY: 0
    property real startX: 0
    property real startY: 0
    property real tilt: 0
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
    onVisibleChanged: if (visible) { if (!placed) place(false); else constrain() }
    onWidthChanged: if (placed && visible) constrain()
    onHeightChanged: if (placed && visible) constrain()
    onClosing: close => { close.accepted = false; pet.ui("hide",{}) }
    Connections {
        target: root.pet
        function onReaction(text) { root.caption=text; speech.restart() }
        function onResetPositionRequested() { root.place(true) }
    }
    Connections {
        target:root.screen
        function onWidthChanged(){if(root.visible)root.constrain()}
        function onHeightChanged(){if(root.visible)root.constrain()}
        function onVirtualXChanged(){if(root.visible)root.constrain()}
        function onVirtualYChanged(){if(root.visible)root.constrain()}
    }
    Timer { id:speech; interval:2600; onTriggered:root.caption="" }
    SequentialAnimation {
        id:wiggle
        NumberAnimation {target:root;property:"tilt";to:-7;duration:85}
        NumberAnimation {target:root;property:"tilt";to:6;duration:130}
        NumberAnimation {target:root;property:"tilt";to:0;duration:200;easing.type:Easing.OutCubic}
    }
    Rectangle {
        id:bubble; objectName:"desktopPetSpeechBubble"; anchors.horizontalCenter:parent.horizontalCenter
        // Respect both letterboxing and the transparent margin inside the art.
        y:Math.max(4,art.y+art.height-(art.item?art.item.paintedHeight:art.height)*(1-(root.state.contentTop || 0))-height-8)
        width:Math.min(root.width,spoken.implicitWidth+24);height:spoken.implicitHeight+16;radius:12
        color:Theme.surface;border.color:Theme.line;visible:!!root.caption
        Text {id:spoken;anchors.centerIn:parent;width:Math.min(implicitWidth,root.width-24);text:root.caption;textFormat:Text.PlainText;wrapMode:Text.Wrap;color:Theme.ink;font.pixelSize:Theme.font(11)}
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
                    AnimatedImage {objectName:"desktopPetAnimation";readonly property bool ready:status===Image.Ready;source:root.state.source;fillMode:Image.PreserveAspectFit;verticalAlignment:Image.AlignBottom;cache:false;asynchronous:true;playing:root.visible && !root.config.paused;mipmap:false;onStatusChanged:if(status===Image.Error)root.caption=I18n.t("形象加载失败，请在桌宠设置中更换形象")}
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
            else {root.pet.interact("tap");wiggle.restart()}
        }
        onCanceled:if(root.dragged){root.constrain();root.pet.savePosition(root.x,root.y)}
    }
    Menu {
        id:menu;objectName:"desktopPetContextMenu";popupType:Popup.Window
        MenuItem {text:I18n.t("打开 Umeko");onTriggered:root.pet.restoreRequested()}
        MenuItem {text:I18n.t("桌宠设置");onTriggered:root.pet.settingsRequested()}
        MenuSeparator {}
        Menu {
            title:I18n.t("动画形象")
            Repeater {model:root.pet.appearances;MenuItem {required property var modelData;text:modelData.name;checkable:true;checked:root.config.appearance===modelData.id;onTriggered:root.pet.ui("selectAppearance",{id:modelData.id})}}
        }
        MenuItem {text:I18n.t("暂停动作");checkable:true;checked:root.config.paused;onTriggered:root.pet.ui("configure",{paused:!root.config.paused})}
        MenuItem {text:I18n.t("保持置顶");checkable:true;checked:root.config.alwaysOnTop;onTriggered:root.pet.ui("configure",{alwaysOnTop:!root.config.alwaysOnTop})}
        MenuItem {text:I18n.t("重置位置");onTriggered:root.pet.ui("resetPosition",{})}
        MenuSeparator {}
        MenuItem {text:I18n.t("隐藏桌宠");onTriggered:root.pet.ui("hide",{})}
    }
}
