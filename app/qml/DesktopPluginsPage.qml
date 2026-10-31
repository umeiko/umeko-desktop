import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
Item {
    id: root
    objectName: "desktopPluginsPage"
    property var manager: backend.desktopPlugins
    property string selectedId: ""
    readonly property var allRows: manager.rows
    readonly property var filteredRows: allRows.filter(p=>(p.name+" "+p.id+" "+p.description).toLowerCase().includes(search.text.toLowerCase()))
    onFilteredRowsChanged: if (!filteredRows.some(p=>p.id===selectedId)) selectedId=filteredRows.length?filteredRows[0].id:""
    readonly property var selected: allRows.find(p=>p.id===selectedId) || null
    readonly property var detail: selected && I18n.language ? manager.details(selectedId) : ({})
    Component.onCompleted: if (allRows.length) selectedId=allRows[0].id
    onAllRowsChanged: if (!allRows.some(p=>p.id===selectedId)) selectedId=allRows.length ? allRows[0].id : ""
    FileDialog {id:picker;title:I18n.t("导入 Umeko 插件");nameFilters:["Umeko plugins (*.zip)"];onAccepted:root.manager.importZip(String(selectedFile))}
    FileDialog {id:sdkPicker;title:I18n.t("导出插件 SDK 和示例");fileMode:FileDialog.SaveFile;defaultSuffix:"zip";nameFilters:["ZIP (*.zip)"];onAccepted:root.manager.exportSdk(String(selectedFile))}
    QtObject {
        id:settingsSdk
        readonly property var colors: ({bg:Theme.bg,surface:Theme.surface,ink:Theme.ink,muted:Theme.muted,line:Theme.line,hover:Theme.hover,accent:Theme.accent,accentBg:Theme.accentBg,danger:Theme.danger})
        readonly property real scale:Theme.fontScale
        readonly property bool active:root.visible && !!root.selected && root.selected.enabled
        readonly property var config:root.detail.configText ? JSON.parse(root.detail.configText) : ({})
        signal response(string request,var value)
        signal configSaved(string request,var value)
        function t(text){return I18n.t(text)}
        function call(method,args){return root.manager.settingsCall(root.selectedId,method,JSON.stringify(args || {}))}
        function saveConfig(value){return root.manager.saveConfig(root.selectedId,JSON.stringify(value))}
    }
    Connections {
        target:root.manager
        function onResponse(request,value){settingsSdk.response(request,value)}
        function onManaged(request,value){settingsSdk.configSaved(request,value)}
    }
    ColumnLayout {
        anchors.fill:parent;spacing:16
        RowLayout {
            Layout.fillWidth:true;spacing:12
            InputField {id:search;objectName:"desktopPluginSearch";Layout.fillWidth:true;placeholderText:I18n.t("搜索已安装插件…")}
            ActionButton {objectName:"desktopPluginIconCatalogButton";text:I18n.t("内置图标");quiet:true;onClicked:iconCatalog.open()}
            ActionButton {objectName:"exportDesktopPluginSdkButton";text:I18n.t("导出 SDK 和示例");quiet:true;onClicked:sdkPicker.open()}
            ActionButton {objectName:"importDesktopPluginButton";text:I18n.t("导入 ZIP");glyph:"plus";enabled:!root.manager.busy;onClicked:picker.open()}
        }
        Text { font.family: Theme.fontFamily;visible:!!root.manager.status;text:root.manager.status;textFormat:Text.PlainText;color:Theme.muted;Layout.fillWidth:true;wrapMode:Text.Wrap;font.pixelSize:Theme.font(11)}
        Rectangle {
            Layout.fillWidth:true;Layout.fillHeight:true;color:Theme.surface;radius:12;border.color:Theme.line
            RowLayout {
                anchors.fill:parent;anchors.margins:1;spacing:0
                Item {
                    Layout.preferredWidth:230;Layout.fillHeight:true
                    ListView {
                        id:list;objectName:"desktopPluginInstalledList";anchors.fill:parent;anchors.margins:10;clip:true;spacing:4
                        model:root.filteredRows
                        delegate:Rectangle {
                            required property var modelData
                            width:list.width;height:78;radius:8
                            color:root.selectedId===modelData.id?Theme.accentBg:rowMouse.containsMouse?Theme.hover:"transparent"
                            WidgetIcon {x:12;y:12;plugin:modelData;width:Theme.icon(18);height:Theme.icon(18)}
                            Column {
                                anchors.fill:parent;anchors.margins:12;anchors.leftMargin:22+Theme.icon(18);spacing:7
                                Text { font.family: Theme.fontFamily;width:parent.width;text:I18n.widgetText(modelData,modelData.name);textFormat:Text.PlainText;color:Theme.ink;font.pixelSize:Theme.font(12);font.weight:Font.DemiBold;elide:Text.ElideRight}
                                Text { font.family: Theme.fontFamily;text:(modelData.builtin?I18n.t("官方内置"):"v"+modelData.version)+" · "+(modelData.enabled?I18n.t("已启用"):I18n.t("已停用"));color:Theme.muted;font.pixelSize:Theme.font(10)}
                            }
                            MouseArea {id:rowMouse;anchors.fill:parent;hoverEnabled:true;cursorShape:Qt.PointingHandCursor;onClicked:root.selectedId=modelData.id}
                        }
                        Text { font.family: Theme.fontFamily;anchors.centerIn:parent;visible:list.count===0;text:I18n.t("没有匹配的插件");color:Theme.muted;font.pixelSize:Theme.font(11)}
                    }
                }
                Rectangle {Layout.preferredWidth:1;Layout.fillHeight:true;color:Theme.line}
                ScrollView {
                    id:details;objectName:"desktopPluginDetails";Layout.fillWidth:true;Layout.fillHeight:true;clip:true;contentWidth:availableWidth
                    ColumnLayout {
                        width:details.availableWidth;spacing:18
                        Item {height:4}
                        ColumnLayout {
                            Layout.fillWidth:true;Layout.leftMargin:24;Layout.rightMargin:24;spacing:16;visible:!!root.selected
                            RowLayout {
                                Layout.fillWidth:true
                                WidgetIcon {plugin:root.selected || ({});Layout.preferredWidth:Theme.icon(24);Layout.preferredHeight:Theme.icon(24)}
                                Text { font.family: Theme.fontFamily;text:root.selected ? I18n.widgetText(root.selected,root.selected.name) : "";textFormat:Text.PlainText;color:Theme.ink;font.pixelSize:Theme.font(20);font.weight:Font.DemiBold;Layout.fillWidth:true;wrapMode:Text.Wrap}
                                Switch {palette.windowText:Theme.ink;palette.buttonText:Theme.ink;palette.dark:Theme.accent;objectName:"desktopPluginGlobalSwitch";checked:!!root.selected && !!root.selected.enabled;onToggled:root.manager.setEnabled(root.selectedId,checked)}
                            }
                            Text { font.family: Theme.fontFamily;text:root.selected?"v"+root.selected.version+"  ·  "+(root.selected.author || root.selected.id):"";textFormat:Text.PlainText;color:Theme.muted;font.pixelSize:Theme.font(11)}
                            Text { font.family: Theme.fontFamily;visible:!!root.selected && root.selected.lifecycle==="application";text:I18n.t(root.selected.hasPage?"应用级插件":"应用级后台服务")+" · "+I18n.t(root.selected && root.selected.running?"运行中":root.selected && root.selected.starting?"正在启动":"已停止");color:Theme.muted;font.pixelSize:Theme.font(11)}
                            Text { font.family: Theme.fontFamily;text:root.selected?I18n.widgetText(root.selected,root.selected.description || ""):"";textFormat:Text.PlainText;color:Theme.ink;Layout.fillWidth:true;wrapMode:Text.Wrap;font.pixelSize:Theme.font(12)}
                            RowLayout {
                                Layout.fillWidth:true;spacing:8
                                CheckBox {visible:!!root.selected && root.selected.lifecycle!=="application";palette.windowText:Theme.ink;palette.buttonText:Theme.ink;font.pixelSize:Theme.font(12);objectName:"desktopPluginSessionSwitch";text:I18n.t("在当前会话启用");checked:!!root.selected && !!root.selected.sessionEnabled;enabled:!!root.selected && !!root.selected.enabled;onToggled:root.manager.setSessionEnabled(root.selectedId,checked)}
                                Text { font.family: Theme.fontFamily;visible:!!root.selected && root.selected.lifecycle==="application";text:I18n.t("启用后随应用启动，跨聊天常驻");color:Theme.muted;font.pixelSize:Theme.font(12)}
                                Item {Layout.fillWidth:true}
                                ActionButton {objectName:"openDesktopPluginPageButton";text:I18n.t("打开页面");glyph:"panel-right";visible:!!root.selected && !!root.selected.hasPage;enabled:!!root.selected && root.selected.enabled && root.selected.sessionEnabled;onClicked:root.manager.openPage(root.selectedId)}
                            }
                            Text { font.family: Theme.fontFamily;visible:!!root.selected && (root.selected.permissions || []).length>0;text:I18n.t("声明的能力")+"\n"+(root.selected?(root.selected.permissions || []).join(" · "):"");textFormat:Text.PlainText;Layout.fillWidth:true;wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.font(10)}
                            Rectangle {objectName:"desktopPluginSettingsDivider";Layout.fillWidth:true;height:1;color:Theme.line}
                            Loader {
                                id:widgetSettings;objectName:"desktopPluginSettingsLoader";Layout.fillWidth:true
                                active:root.visible && !!root.selected && root.selected.enabled && !!root.detail.settingsUrl
                                visible:active
                                Layout.preferredHeight:active && item ? item.implicitHeight : 0
                                onActiveChanged:if(active)setSource(root.detail.settingsUrl,{sdk:settingsSdk})
                                property string settingsUrl:root.detail.settingsUrl || ""
                                onSettingsUrlChanged:if(active)setSource(settingsUrl,{sdk:settingsSdk})
                                Component.onCompleted:if(active)setSource(settingsUrl,{sdk:settingsSdk})
                            }
                            Text { font.family: Theme.fontFamily;objectName:"desktopPluginReadmeHeading";text:I18n.t("功能说明");color:Theme.ink;font.pixelSize:Theme.font(13);font.weight:Font.DemiBold}
                            TextEdit { font.family: Theme.fontFamily;objectName:"desktopPluginReadme";Layout.fillWidth:true;text:String(root.detail.readmeText || "").replace(/!\[[^\]]*\]\([^)]*\)/g,"[图片]").replace(/<[^>]+>/g,"");textFormat:text.length>24000 || text.split("\n").length>400 || text.split("|").length>256 || text.split("[").length>256 ? TextEdit.PlainText : TextEdit.MarkdownText;readOnly:true;selectByMouse:true;wrapMode:TextEdit.Wrap;color:Theme.ink;font.pixelSize:Theme.font(12)}
                            Rectangle {Layout.fillWidth:true;height:1;color:Theme.line}
                            Text { font.family: Theme.fontFamily;visible:!root.detail.settingsUrl;text:I18n.t("插件配置");color:Theme.ink;font.pixelSize:Theme.font(13);font.weight:Font.DemiBold}
                            TextArea {visible:!root.detail.settingsUrl;id:config;objectName:"desktopPluginConfig";Layout.fillWidth:true;Layout.preferredHeight:160;text:root.detail.configText || "{}";textFormat:TextEdit.PlainText;wrapMode:TextEdit.WrapAnywhere;selectByMouse:true;font.family:"monospace";font.pixelSize:Theme.font(11);color:Theme.ink;background:Rectangle {color:Theme.bg;radius:8;border.color:Theme.line}}
                            RowLayout {
                                Layout.fillWidth:true
                                ActionButton {visible:!root.detail.settingsUrl;objectName:"saveDesktopPluginConfigButton";text:I18n.t("保存配置");enabled:!root.manager.busy;onClicked:root.manager.saveConfig(root.selectedId,config.text)}
                                Item {Layout.fillWidth:true}
                                ActionButton {objectName:"uninstallDesktopPluginButton";text:I18n.t("卸载插件");visible:!!root.selected && !root.selected.builtin;enabled:!root.manager.busy;destructive:true;onClicked:uninstall.open()}
                            }
                            Text { font.family: Theme.fontFamily;text:I18n.t("插件包含本机执行的 Python、QML 或可执行文件，请仅导入可信来源的 ZIP。");Layout.fillWidth:true;wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.font(10)}
                        }
                        Item {height:20}
                    }
                }
            }
        }
    }
    Popup {
        id:iconCatalog;objectName:"desktopPluginIconCatalog";parent:Overlay.overlay;anchors.centerIn:parent
        width:Math.min(480,parent.width-32);padding:18;modal:true;focus:true
        closePolicy:Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background:Rectangle {color:Theme.surface;radius:12;border.color:Theme.line}
        contentItem:ColumnLayout {
            spacing:12
            RowLayout {
                Layout.fillWidth:true
                Text { font.family: Theme.fontFamily;text:I18n.t("Widget 内置图标");color:Theme.ink;font.pixelSize:Theme.font(15);font.weight:Font.DemiBold;Layout.fillWidth:true}
                ActionButton {text:I18n.t("关闭");quiet:true;onClicked:iconCatalog.close()}
            }
            GridView {
                id:iconGrid;objectName:"desktopPluginIconGrid";Layout.fillWidth:true
                Layout.preferredHeight:Math.min(5*Theme.control(66),Math.max(100,iconCatalog.parent.height-140))
                readonly property int columns:Math.max(2,Math.floor(width/Theme.control(100)))
                cellWidth:width/columns;cellHeight:Theme.control(66);clip:true;model:root.manager.iconCatalog
                ScrollBar.vertical:ScrollBar {policy:ScrollBar.AsNeeded}
                delegate:ItemDelegate {
                    id:iconOption;required property var modelData;width:iconGrid.cellWidth-4;height:iconGrid.cellHeight-4
                    HoverHandler {cursorShape:Qt.PointingHandCursor}
                    background:Rectangle {color:iconOption.hovered?Theme.hover:"transparent";radius:7}
                    contentItem:Column {
                        spacing:5
                        Glyph {name:iconOption.modelData.glyph;anchors.horizontalCenter:parent.horizontalCenter;width:Theme.icon(22);height:Theme.icon(22);color:Theme.ink}
                        Text { font.family: Theme.fontFamily;anchors.horizontalCenter:parent.horizontalCenter;text:iconOption.modelData.id;color:Theme.ink;font.pixelSize:Theme.font(11)}
                    }
                    HoverTip {active:iconOption.hovered;text:I18n.t("点击复制图标清单配置")}
                    onClicked:{backend.copy('"icon": "'+modelData.id+'"');backend.toast(I18n.t("已复制图标清单配置"))}
                }
            }
        }
    }
    Popup {
        id:uninstall;parent:Overlay.overlay;anchors.centerIn:parent;width:Math.min(420,parent.width-48);padding:24;modal:true;focus:true
        background:Rectangle {color:Theme.surface;radius:12;border.color:Theme.line}
        contentItem:ColumnLayout {spacing:18
            Text { font.family: Theme.fontFamily;Layout.fillWidth:true;wrapMode:Text.Wrap;text:I18n.t("卸载所选插件及其配置？插件创建的会话和工作文件会保留。");color:Theme.ink;font.pixelSize:Theme.font(13)}
            RowLayout {Item {Layout.fillWidth:true} ActionButton {text:I18n.t("取消");onClicked:uninstall.close()} ActionButton {text:I18n.t("卸载插件");destructive:true;onClicked:{root.manager.uninstall(root.selectedId);uninstall.close()}}}
        }
    }
}
