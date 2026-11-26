import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../app/qml" as Umeko
Menu {
    id: root
    objectName:"gitFileContextMenu"
    required property var sdk
    property bool readOnly: false
    property var entry: ({})
    property var discardEntry: ({})
    readonly property var c: sdk.colors
    readonly property real s: sdk.scale
    signal operation(string method,var arguments)
    width:250*s;padding:4
    background:Rectangle {radius:5;color:root.c.surface;border.color:root.c.line}
    VsMenuItem {objectName:"gitContextOpenChanges";text:Umeko.I18n.t("打开更改");colors:root.c;uiScale:root.s;onTriggered:root.operation("diff",{path:root.entry.path,group:root.entry.group})}
    VsMenuItem {objectName:"gitContextAttach";text:Umeko.I18n.t("附加到聊天");colors:root.c;uiScale:root.s;enabled:root.entry.status!=="D";onTriggered:root.operation("attach",{path:root.entry.path})}
    VsMenuItem {visible:!root.readOnly;height:visible?implicitHeight:0;text:Umeko.I18n.t("打开文件（HEAD）");colors:root.c;uiScale:root.s;enabled:root.entry.group!=="untracked";onTriggered:root.operation("headFile",{path:root.entry.path})}
    MenuSeparator {visible:!root.readOnly;height:visible?implicitHeight:0;contentItem:Rectangle {implicitHeight:1;color:root.c.line}}
    VsMenuItem {objectName:"gitContextDiscard";visible:!root.readOnly;height:visible?implicitHeight:0;text:Umeko.I18n.t("放弃更改");colors:root.c;uiScale:root.s;enabled:root.entry.group!=="staged";onTriggered:{root.discardEntry=root.entry;confirmDiscard.open()}}
    VsMenuItem {visible:!root.readOnly;height:visible?implicitHeight:0;text:root.entry.group==="staged"?Umeko.I18n.t("取消暂存更改"):Umeko.I18n.t("暂存更改");colors:root.c;uiScale:root.s;onTriggered:root.operation(root.entry.group==="staged"?"unstage":"stage",{path:root.entry.path})}
    VsMenuItem {objectName:"gitContextIgnore";visible:!root.readOnly;height:visible?implicitHeight:0;text:Umeko.I18n.t("添加到 .gitignore");colors:root.c;uiScale:root.s;onTriggered:root.operation("ignore",{path:root.entry.path})}
    MenuSeparator {visible:!root.readOnly;height:visible?implicitHeight:0;contentItem:Rectangle {implicitHeight:1;color:root.c.line}}
    VsMenuItem {objectName:"gitContextReveal";text:Umeko.I18n.t("在文件管理器中打开");colors:root.c;uiScale:root.s;onTriggered:root.operation("reveal",{path:root.entry.path})}
    VsMenuItem {objectName:"gitContextExplorer";text:Umeko.I18n.t("在资源管理器视图中显示");colors:root.c;uiScale:root.s;onTriggered:root.operation("explorer",{path:root.entry.path})}
    Dialog {
        id:confirmDiscard;objectName:"gitDiscardDialog";parent:root.parent;anchors.centerIn:parent
        width:Math.min(460*root.s,parent.width-24);modal:true;title:Umeko.I18n.t("放弃此文件的更改？");palette.window:root.c.surface;palette.windowText:root.c.ink
        Overlay.modal:Rectangle {color:"transparent"}
        contentItem:Text {text:root.discardEntry.path||"";textFormat:Text.PlainText;color:root.c.ink;wrapMode:Text.Wrap;font.pixelSize:13*root.s}
        footer:RowLayout {Item {Layout.fillWidth:true}Button {text:Umeko.I18n.t("取消");onClicked:confirmDiscard.close()}Button {text:Umeko.I18n.t("放弃更改");onClicked:{confirmDiscard.close();root.operation("discard",{path:root.discardEntry.path,group:root.discardEntry.group})}}}
    }
}
