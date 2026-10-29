import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Item {
    id:root
    property var manager:backend.desktopPlugins
    readonly property bool popupVisible: menu.visible
    visible:manager.sessionPlugins.length>0
    onVisibleChanged: if (!visible) menu.close()
    Connections {target:backend;function onViewChanged() {menu.close()}}
    implicitWidth:button.implicitWidth;implicitHeight:button.implicitHeight
    ActionButton {id:button;objectName:"desktopPluginMenuButton";text:I18n.t("插件");glyph:"puzzle";quiet:true;height:Theme.control(28);onClicked:menu.open()}
    Popup {
        id:menu;objectName:"desktopPluginSessionMenu";parent:root
        x:Math.min(0,root.width-width);y:-height-10;width:Math.max(230,content.implicitWidth+24);padding:8;focus:true;closePolicy:Popup.CloseOnEscape|Popup.CloseOnPressOutside
        background:Rectangle {radius:10;color:Theme.surface;border.color:Theme.line}
        contentItem:ColumnLayout {id:content;spacing:3
            Repeater {
                model:root.manager.sessionPlugins
                ActionButton {required property var modelData;objectName:"openDesktopPlugin_"+modelData.id;text:modelData.name;quiet:true;Layout.fillWidth:true;onClicked:{const id=modelData.id;menu.close();root.manager.openPage(id)}}
            }
        }
    }
}
