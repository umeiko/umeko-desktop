import QtQuick
import QtQuick.Controls
import QtQuick.Window

Window {
    id:root
    objectName:"desktopPetReminderWindow"
    required property var pet
    width:Math.min(500*Theme.fontScale,Screen.desktopAvailableWidth-48)
    height:Math.min(680*Theme.fontScale,Screen.desktopAvailableHeight-64)
    minimumWidth:360;minimumHeight:420
    title:I18n.t("提醒与待办")
    color:Theme.bg
    flags:Qt.Window | Qt.FramelessWindowHint | (pet.config.alwaysOnTop ? Qt.WindowStaysOnTopHint : 0)
    transientParent:null
    function present(){panel.syncSelection();show();raise();requestActivate()}
    Component.onCompleted:Qt.callLater(present)
    onVisibleChanged:if(!visible)panel.endVisit()
    Item {
        id:chrome;objectName:"desktopPetReminderTitleBar";width:parent.width;height:38*Theme.fontScale
        TitleBarDrag {anchors.fill:parent;targetWindow:root}
        Text {anchors.left:parent.left;anchors.leftMargin:24*Theme.fontScale;anchors.verticalCenter:parent.verticalCenter;text:"Umeko";font.family:Theme.fontFamily;font.pixelSize:Theme.font(11,true);color:Theme.muted}
        Row {
            anchors.right:parent.right;anchors.rightMargin:10;anchors.verticalCenter:parent.verticalCenter;spacing:2
            WindowControlButton {objectName:"desktopPetReminderWindowMinimize";operation:"minimize";hint:I18n.t("最小化");onClicked:root.showMinimized()}
            WindowControlButton {objectName:"desktopPetReminderWindowClose";operation:"close";hint:I18n.t("关闭");onClicked:root.close()}
        }
    }
    DesktopPetReminders {id:panel;anchors.left:parent.left;anchors.right:parent.right;anchors.top:chrome.bottom;anchors.bottom:parent.bottom;pet:root.pet}
    Rectangle {anchors.fill:parent;color:"transparent";border.color:Theme.line;z:30}
    WindowResizeHandles {anchors.fill:parent;targetWindow:root;z:100}
}
