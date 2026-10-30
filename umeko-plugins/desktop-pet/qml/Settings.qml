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
    function refresh(){if(sdk.active)call("status",{})}
    Component.onCompleted:refresh()
    Connections {
        target:root.sdk
        function onResponse(id,value) {
            if(!root.pending[id])return
            const method=root.pending[id];delete root.pending[id]
            if(!value.ok){root.error=value.error || "";return}
            if(method==="status" || value.result.config){root.snapshot=value.result;root.error=""}
            else root.refresh()
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
        id:removeDialog;title:root.sdk.t("删除形象");modal:true;standardButtons:Dialog.Ok | Dialog.Cancel
        Label {text:root.sdk.t("删除所选形象？当前形象会先恢复为八奈见。");wrapMode:Text.Wrap;width:280;color:root.sdk.colors.ink}
        onAccepted:root.call("removeAppearance",{id:root.cfg.appearance})
    }
}
