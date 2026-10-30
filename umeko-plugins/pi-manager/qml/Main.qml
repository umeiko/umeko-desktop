import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Commands.js" as Commands

Rectangle {
    id: root
    objectName: "piManagerWidget"
    required property var sdk
    color: sdk.colors.surface
    clip: true
    property bool initialized: false
    property var rows: []
    property var selected: null
    property var details: ({})
    property var tools: []
    property var modes: ({})
    property var update: ({})
    property var pending: ({})
    property string notice: ""
    property string job: ""
    property string jobOperation: ""
    property bool hostBusy: false
    property bool canCancel: false
    property bool polling: false
    property bool hasMore: false
    property int total: 0
    property string query: ""
    readonly property bool working: job!=="" || hostBusy || Object.keys(pending).length>0
    readonly property var paletteColors: sdk.colors
    function t(zh,en) { return sdk.language.indexOf("zh")===0 ? zh : en }
    function request(operation,args,kind) {
        if (!sdk.active) return
        if (!sdk.hostCapabilities || !sdk.hostCapabilities.operations[operation]) {
            notice=t("请升级到支持此 Widget 的 Umeko 版本","Please upgrade Umeko to use this Widget"); return
        }
        const id=sdk.requestHost(operation,args || {})
        if (!id) {notice=t("宿主忙碌，请稍后重试","Host is busy; please retry");return}
        const next=Object.assign({},pending);next[id]={operation:operation,kind:kind || "",detail:root.selected ? root.selected.id : "",query:root.query};pending=next
    }
    function status(append) {
        const args=selected ? {details:selected.id,limit:1} : {query:query,offset:append ? rows.length : 0,limit:12}
        request("pi.status",args,append ? "append" : "status")
    }
    function scan() { selected=null; notice=""; request("pi.scan") }
    function select(row) {
        selected=row;details={};tools=[];update={};notice=""
        request("pi.details",{id:row.id})
    }
    function back() { selected=null;notice="";status(false) }
    function openLink(url) { if(/^https?:\/\//i.test(url)) Qt.openUrlExternally(url) }
    function modeIndex() {
        if(!selected) return -1
        if(selected.info.required) return 0
        const mode=modes[selected.path]
        if(mode==="session") return 1
        if(mode==="disabled") return 2
        return selected.enabled && selected.scope==="global" ? 0 : -1
    }
    function activate(index) { if(!selected || selected.info.required)return; request("pi.activation",{id:selected.id,mode:["global","session","disabled"][index]}) }
    function initialize() { if (sdk.active && !initialized) {initialized=true;status(false)} }
    Component.onCompleted: initialize()
    component SmallButton: Button {
        id: button
        padding: 9
        implicitHeight: 36
        background: Rectangle {radius:8;color:button.down ? root.sdk.colors.accentBg : button.hovered ? root.sdk.colors.hover : "transparent";border.color:root.sdk.colors.line}
        contentItem: Text {text:button.text;textFormat:Text.PlainText;color:button.enabled ? root.sdk.colors.ink : root.sdk.colors.muted;font.pixelSize:12*root.sdk.scale;horizontalAlignment:Text.AlignHCenter;verticalAlignment:Text.AlignVCenter;elide:Text.ElideRight}
        ToolTip.visible: hovered && ToolTip.text!==""
    }
    component ScopePicker: ComboBox {
        id: picker
        implicitHeight: 38; leftPadding: 12; rightPadding: 30
        palette.buttonText: root.sdk.colors.ink
        palette.text: root.sdk.colors.ink
        palette.window: root.sdk.colors.surface
        palette.base: root.sdk.colors.surface
        palette.highlight: root.sdk.colors.accentBg
        palette.highlightedText: root.sdk.colors.ink
        background: Rectangle {radius:8;color:picker.enabled ? root.sdk.colors.bg : root.sdk.colors.hover;border.color:picker.activeFocus ? root.sdk.colors.accent : root.sdk.colors.line}
        contentItem: Text {text:picker.displayText;textFormat:Text.PlainText;elide:Text.ElideRight;color:picker.enabled ? root.sdk.colors.ink : root.sdk.colors.muted;font.pixelSize:12*root.sdk.scale;verticalAlignment:Text.AlignVCenter}
        indicator:Text {x:picker.width-width-12;y:(picker.height-height)/2;text:"⌄";color:root.sdk.colors.muted;font.pixelSize:16}
    }
    ColumnLayout {
        anchors.fill: parent;anchors.margins:16;spacing:12
        RowLayout {
            Layout.fillWidth:true
            SmallButton {objectName:"piManagerBack";visible:!!root.selected;text:root.t("‹ 返回","‹ Back");onClicked:root.back()}
            Image {visible:!root.selected;source:"assets/pi.svg";sourceSize.width:36;sourceSize.height:36;Layout.preferredWidth:28;Layout.preferredHeight:28}
            Text {Layout.fillWidth:true;text:root.selected ? "" : root.t("本地已安装","Installed locally")+" · "+root.total;textFormat:Text.PlainText;elide:Text.ElideRight;color:root.sdk.colors.ink;font.pixelSize:16*root.sdk.scale;font.bold:true}
            SmallButton {objectName:"piManagerCancelInstall";visible:root.jobOperation==="pi.install" && !!root.job;enabled:root.canCancel;text:root.t("取消安装","Cancel install");onClicked:{root.canCancel=false;root.request("pi.cancel",{id:root.job})}}
            SmallButton {objectName:"piManagerInstall";visible:!root.selected;text:"＋";ToolTip.text:root.t("安装插件","Install extension");enabled:!root.working;onClicked:install.open()}
            SmallButton {objectName:"piManagerRefresh";visible:!root.selected;text:"↻";ToolTip.text:root.t("刷新本地列表","Refresh local inventory");enabled:!root.working;onClicked:root.scan()}
        }
        Text {
            objectName:"piManagerNotice";visible:text!=="";Layout.fillWidth:true
            text:root.notice;textFormat:Text.PlainText;color:root.sdk.colors.muted;font.pixelSize:12*root.sdk.scale
            wrapMode:Text.Wrap;maximumLineCount:3;elide:Text.ElideRight
        }
        ColumnLayout {
            visible:!root.selected;Layout.fillWidth:true;Layout.fillHeight:true;spacing:12
            RowLayout {
                Layout.fillWidth:true
                TextField {
                    id:search;objectName:"piManagerSearch";Layout.fillWidth:true;selectByMouse:true
                    placeholderText:root.t("搜索本地插件…","Search installed extensions…")
                    color:root.sdk.colors.ink;font.pixelSize:12*root.sdk.scale
                    background:Rectangle {radius:8;color:root.sdk.colors.bg;border.color:search.activeFocus ? root.sdk.colors.accent : root.sdk.colors.line}
                    onTextChanged:filterTimer.restart()
                    onAccepted:{filterTimer.stop();root.query=text;root.status(false)}
                }
                SmallButton {objectName:"piManagerSearchButton";text:"⌕";ToolTip.text:root.t("搜索本地插件","Search installed extensions");onClicked:{filterTimer.stop();root.query=search.text;root.status(false)}}
            }
            ListView {
                id:list;objectName:"piManagerList";Layout.fillWidth:true;Layout.fillHeight:true;clip:true;reuseItems:true
                model:root.rows;spacing:4
                ScrollBar.vertical:ScrollBar {}
                delegate:ItemDelegate {
                    id:entry;required property var modelData
                    objectName:"piManagerEntry_"+modelData.id
                    width:list.width;height:80
                    padding:8
                    background:Rectangle {radius:10;color:entry.hovered ? root.sdk.colors.hover : "transparent"}
                    contentItem:RowLayout {
                        spacing:12
                        ExtensionIcon {colors:root.paletteColors;iconName:entry.modelData.info.icon || "package";Layout.preferredWidth:40;Layout.preferredHeight:40}
                        ColumnLayout {
                            Layout.fillWidth:true;spacing:4
                            Text {text:entry.modelData.name;textFormat:Text.PlainText;elide:Text.ElideRight;Layout.fillWidth:true;color:root.sdk.colors.ink;font.pixelSize:13*root.sdk.scale;font.bold:true}
                            Text {text:entry.modelData.info.description || entry.modelData.path;textFormat:Text.PlainText;elide:Text.ElideRight;Layout.fillWidth:true;color:root.sdk.colors.muted;font.pixelSize:11*root.sdk.scale}
                            Text {text:(entry.modelData.info.version || (entry.modelData.info.bundled ? root.t("内置","Bundled") : root.t("本地","Local")))+" · "+(entry.modelData.enabled ? root.t("已启用","Enabled") : root.t("已停用","Disabled"));textFormat:Text.PlainText;color:root.sdk.colors.muted;font.pixelSize:10*root.sdk.scale}
                        }
                        Text {text:"›";color:root.sdk.colors.muted;font.pixelSize:20}
                    }
                    onClicked:root.select(modelData)
                }
                footer:SmallButton {visible:root.hasMore;width:list.width;text:root.t("加载更多","Load more");enabled:!root.working;onClicked:root.status(true)}
            }
        }
        ScrollView {
            id:detailScroll;objectName:"piManagerDetailScroll";visible:!!root.selected
            Layout.fillWidth:true;Layout.fillHeight:true;clip:true
            contentWidth:availableWidth
            ScrollBar.horizontal.policy:ScrollBar.AlwaysOff
            Column {
                id:detailBody;objectName:"piManagerDetailBody";width:detailScroll.availableWidth;spacing:16
                RowLayout {
                    width:parent.width;spacing:12
                    ExtensionIcon {colors:root.paletteColors;iconName:root.selected ? root.selected.info.icon || "package" : "package";Layout.preferredWidth:52;Layout.preferredHeight:52}
                    ColumnLayout {
                        Layout.fillWidth:true;spacing:4
                        Text {objectName:"piManagerName";text:root.selected ? root.selected.name : "";Layout.fillWidth:true;wrapMode:Text.WrapAnywhere;textFormat:Text.PlainText;color:root.sdk.colors.ink;font.pixelSize:20*root.sdk.scale;font.bold:true}
                        Text {text:root.selected ? root.selected.info.version || root.t("Umeko 内置扩展","Bundled with Umeko") : "";Layout.fillWidth:true;wrapMode:Text.Wrap;textFormat:Text.PlainText;color:root.sdk.colors.muted;font.pixelSize:11*root.sdk.scale}
                    }
                }
                Text {width:parent.width;text:root.selected ? root.selected.info.description || "" : "";textFormat:Text.PlainText;wrapMode:Text.Wrap;color:root.sdk.colors.muted;font.pixelSize:12*root.sdk.scale}
                ScopePicker {
                    id:activation;objectName:"piManagerActivation";width:parent.width
                    model:[root.t("全局启用","Enable globally"),root.t("本对话中启用","Enable in this chat"),root.t("本对话暂时禁用","Disable in this chat")]
                    currentIndex:root.modeIndex();enabled:!root.working && !!root.selected && !root.selected.info.required
                    displayText:root.selected && root.selected.info.required ? root.t("基础能力 · 固定启用","Required · always enabled") : currentIndex<0 ? (root.selected && root.selected.enabled ? root.t("项目中已启用","Enabled for this project") : root.t("已停用 · 选择启用范围","Disabled · choose a scope")) : currentText
                    onActivated:index=>root.activate(index)
                }
                Text {objectName:"piManagerActivationHint";width:parent.width;text:root.selected && root.selected.info.required ? root.t("Umeko 运行所需，无法停用。","Required by Umeko and cannot be disabled.") : root.t("任务结束后生效；对话设置仅影响当前对话。","Changes apply after the task; chat overrides affect only this chat.");wrapMode:Text.Wrap;color:root.sdk.colors.muted;font.pixelSize:11*root.sdk.scale}
                Flow {
                    width:parent.width;spacing:8
                    SmallButton {objectName:"piManagerHomepage";visible:!!(root.selected && root.selected.info.homepage);text:root.t("↗ 主页","↗ Homepage");onClicked:root.openLink(root.selected.info.homepage)}
                    SmallButton {objectName:"piManagerRepository";visible:!!(root.selected && root.selected.info.repository);text:"↗ GitHub";onClicked:root.openLink(root.selected.info.repository)}
                    SmallButton {objectName:"piManagerCheckUpdate";visible:!!(root.selected && ["npm","git"].indexOf(root.selected.info.updateKind)>=0);enabled:!root.working;text:root.t("检查更新","Check for updates");onClicked:root.request("pi.checkUpdate",{id:root.selected.id})}
                }
                Text {objectName:"piManagerUpdate";width:parent.width;visible:text!=="";text:root.update.message ? root.update.message+(root.update.latest ? " · "+root.update.latest : "") : (root.selected && root.selected.info.updateKind==="desktop" ? root.t("随 Umeko 更新","Updated with Umeko") : "");textFormat:Text.PlainText;wrapMode:Text.Wrap;color:root.sdk.colors.muted;font.pixelSize:12*root.sdk.scale}
                Rectangle {width:parent.width;height:1;color:root.sdk.colors.line}
                TextEdit {
                    objectName:"piManagerReadme";width:parent.width;height:Math.max(32,contentHeight)
                    text:root.details.markdown || root.t("正在读取本地说明…","Reading local documentation…")
                    textFormat:TextEdit.MarkdownText;readOnly:true;selectByMouse:true;wrapMode:TextEdit.WrapAnywhere
                    color:root.sdk.colors.ink;selectionColor:root.sdk.colors.accentBg;font.pixelSize:13*root.sdk.scale
                    onLinkActivated:link=>root.openLink(link)
                }
                Text {visible:root.tools.length>0;text:root.t("当前已加载的工具","Currently loaded tools");color:root.sdk.colors.ink;font.pixelSize:14*root.sdk.scale;font.bold:true}
                Repeater {
                    model:root.tools
                    delegate:Column {
                        required property var modelData;width:detailBody.width;spacing:6
                        Text {width:parent.width;text:modelData.name;textFormat:Text.PlainText;wrapMode:Text.WrapAnywhere;color:root.sdk.colors.accent;font.pixelSize:12*root.sdk.scale}
                        Text {width:parent.width;text:modelData.description;textFormat:Text.PlainText;wrapMode:Text.WrapAnywhere;color:root.sdk.colors.muted;font.pixelSize:12*root.sdk.scale}
                    }
                }
                Item {width:1;height:8}
            }
        }
    }
    Timer {id:filterTimer;interval:180;onTriggered:{root.query=search.text;root.status(false)}}
    Timer {interval:400;repeat:true;running:root.sdk.active && (!!root.job || root.hostBusy);onTriggered:{if(root.job && !root.polling){root.polling=true;root.request("pi.job",{id:root.job})}else if(!root.job && root.hostBusy && Object.keys(root.pending).length===0)root.status(false)}}
    Connections {
        target:root.sdk;ignoreUnknownSignals:true
        function onActiveChanged() { root.initialize() }
        function onHostResponse(id,value) {
            const entry=root.pending[id];if(!entry)return
            const next=Object.assign({},root.pending);delete next[id];root.pending=next
            const op=entry.operation
            if(op==="pi.job")root.polling=false
            if(!value.ok){root.notice=value.error || value.status;root.job="";return}
            if(value.jobId){root.job=value.jobId;root.jobOperation=op;root.notice=root.t("处理中…","Working…");return}
            if(op==="pi.status") {
                if(entry.detail!==(root.selected ? root.selected.id : "") || (!root.selected && entry.query!==root.query))return
                const result=value.result
                root.hostBusy=!!result.busy
                if(!result.contextCurrent){if(!root.job && !root.hostBusy)root.request("pi.scan");return}
                root.notice=root.hostBusy && !root.job ? root.t("正在同步本地插件…","Synchronizing installed extensions…") : ""
                if(root.selected) {
                    const row=(result.extensions || [])[0];if(row)root.selected=row
                    root.details=result.details || {};root.tools=result.tools || [];root.modes=result.activationModes || {}
                    root.update=result.extensionUpdate && result.extensionUpdate.id===root.selected.id ? result.extensionUpdate : {}
                } else {root.rows=entry.kind==="append" ? root.rows.concat(result.extensions || []) : result.extensions || [];root.total=result.total;root.hasMore=result.hasMore}
            } else if(op==="pi.job") {
                if(value.progress){root.notice=value.progress.message;root.canCancel=value.progress.cancellable}
                const item=(value.jobs || [])[0]
                if(item && (item.status==="done" || item.status==="failed")) {
                    root.job="";root.notice=item.result.error || ""
                    if(item.status==="done")root.status(false)
                }
            }
        }
    }
    Popup {
        id:install;objectName:"piManagerInstaller";parent:Overlay.overlay
        anchors.centerIn:parent;width:Math.min(480,parent.width-32);padding:20
        modal:true;focus:true;closePolicy:Popup.CloseOnEscape
        background:Rectangle {radius:14;color:root.sdk.colors.surface;border.color:root.sdk.colors.line}
        onOpened:{installError.text="";command.forceActiveFocus()}
        ColumnLayout {
            width:parent.width;spacing:14
            Text {text:root.t("安装 Pi 插件","Install a Pi extension");color:root.sdk.colors.ink;font.pixelSize:18*root.sdk.scale}
            Text {Layout.fillWidth:true;text:root.t("粘贴安装命令，或输入 npm、Git、本地来源。","Paste a Pi install command, npm, Git or local source.");wrapMode:Text.Wrap;color:root.sdk.colors.muted;font.pixelSize:12*root.sdk.scale}
            TextField {id:command;objectName:"piManagerInstallCommand";Layout.fillWidth:true;selectByMouse:true;placeholderText:"pi install npm:package";onAccepted:installNow.clicked()}
            ScopePicker {id:scope;objectName:"piManagerInstallScope";Layout.fillWidth:true;model:[root.t("全局 · 所有项目","Global · all projects"),root.t("当前项目","Current project")];property bool forced:false;enabled:!forced}
            Text {id:installError;Layout.fillWidth:true;visible:text!=="";textFormat:Text.PlainText;wrapMode:Text.Wrap;color:root.sdk.colors.danger;font.pixelSize:12*root.sdk.scale}
            SmallButton {objectName:"piManagerCatalog";text:root.t("↗ Pi 官方插件目录","↗ Official Pi packages");onClicked:root.openLink("https://pi.dev/packages")}
            RowLayout {
                Layout.fillWidth:true
                Item {Layout.fillWidth:true}
                SmallButton {objectName:"piManagerInstallCancel";text:root.t("取消","Cancel");onClicked:install.close()}
                SmallButton {
                    id:installNow;objectName:"piManagerInstallConfirm";text:root.t("安装","Install");enabled:command.text.trim()!=="" && !root.working
                    onClicked:{try{const args=Commands.parse(command.text,scope.currentIndex===1);delete args.forcedProject;root.request("pi.install",args);install.close()}catch(error){installError.text=error.message}}
                }
            }
        }
        Connections {target:command;function onTextChanged(){try{const args=Commands.parse(command.text,false);scope.forced=args.forcedProject;if(args.forcedProject)scope.currentIndex=1}catch(error){scope.forced=false}}}
    }
}
