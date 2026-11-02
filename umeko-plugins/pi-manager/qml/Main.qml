import QtQuick
import QtQuick.Controls
import QtQuick.Controls.impl
import QtQuick.Layouts
import "Commands.js" as Commands

Rectangle {
    id: root
    objectName: "piManagerWidget"
    required property var sdk
    color: sdk.colors.surface
    clip: true
    property bool initialized: false
    property string sessionKey: ""
    property bool inventoryRequested:false
    property bool inventoryLoading:false
    property var rows: []
    property var selected: null
    property var details: ({})
    property var profile: ({preset:"full"})
    readonly property bool sessionBusy: !!sdk.session.busy
    onSessionBusyChanged:if(initialized && !sessionBusy && sdk.active && Object.keys(pending).length===0)status(false)
    property string expandedId: ""
    property var toolPages: ({})
    function loadTools(id,append) {
        if(!id || !sdk.active || !sdk.hostCapabilities.operations["pi.tools"])return
        const page=toolPages[id] || {}
        request("pi.tools",{id:id,query:query,offset:append ? (page.tools || []).length : 0,limit:60},append ? "tools-append" : "tools")
    }
    function expand(row) {expandedId=expandedId===row.id ? "" : row.id;if(expandedId)loadTools(row.id,false)}
    function presetHint(id) {
        if(id==="standard")return t("8 个 Pi 原生工具，关闭桌面和其他插件能力。","Eight native Pi tools; desktop and extension capabilities are off.")
        if(id==="minimal")return "read · bash · edit · write"
        if(id==="full")return t("保留目前配置的全部 Pi、Umeko 与插件能力。","Keep your configured Pi, Umeko and extension capabilities.")
        return t("逐插件、逐工具调整，仅保存到当前会话。","Per-extension and per-tool choices, saved only for this chat.")
    }
    property var update: ({})
    property var pending: ({})
    property string notice: ""
    property bool lastError:false
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
        const next=Object.assign({},pending);next[id]={operation:operation,kind:kind || "",detail:root.selected ? root.selected.id : "",query:root.query,args:args || {}};pending=next
    }
    function status(append) {
        const args=selected ? {details:selected.id,limit:1} : {query:query,offset:append ? rows.length : 0,limit:12}
        request("pi.status",args,append ? "append" : "status")
    }
    function scan() { selected=null; inventoryRequested=false; notice=""; request("pi.scan") }
    function select(row) {
        selected=row;details={};update={};notice=""
        if(row.id==="builtin:pi-tools")status(false);else request("pi.details",{id:row.id})
        loadTools(row.id,false)
    }
    function back() { selected=null;notice="";status(false) }
    function openLink(url) { if(/^https?:\/\//i.test(url)) Qt.openUrlExternally(url) }
    function initialize() {
        const key=JSON.stringify([sdk.session.token,sdk.session.workspace])
        if(sessionKey!==key){sessionKey=key;initialized=false;selected=null;rows=[];toolPages={};pending={};job="";hostBusy=false;inventoryRequested=false;inventoryLoading=false;expandedId=""}
        if(sdk.active && !initialized){initialized=true;status(false)}
    }
    Component.onCompleted: initialize()
    component SmallButton: Button {
        id: button
        property string iconName: ""
        padding: 9
        implicitHeight: 36
        background: Rectangle {radius:8;color:button.down ? root.sdk.colors.accentBg : button.hovered ? root.sdk.colors.hover : "transparent";border.color:root.sdk.colors.line}
        contentItem:Item {implicitWidth:buttonLabel.implicitWidth+(button.iconName ? 20*root.sdk.scale : 0);implicitHeight:Math.max(buttonLabel.implicitHeight,18*root.sdk.scale)
            IconImage {visible:button.iconName!=="";source:button.iconName ? "assets/ui/"+button.iconName+".svg" : "";color:root.sdk.colors.muted;width:18*root.sdk.scale;height:width;x:button.text ? 0 : (parent.width-width)/2;anchors.verticalCenter:parent.verticalCenter}
            Text {id:buttonLabel;visible:!!button.text;anchors.fill:parent;anchors.leftMargin:button.iconName ? 20*root.sdk.scale : 0;text:button.text;textFormat:Text.PlainText;color:button.enabled ? root.sdk.colors.ink : root.sdk.colors.muted;font.pixelSize:12*root.sdk.scale;horizontalAlignment:Text.AlignHCenter;verticalAlignment:Text.AlignVCenter;elide:Text.ElideRight}
        }
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
    component SessionSwitch: Switch {
        id:toggle
        implicitWidth:40*root.sdk.scale;implicitHeight:28*root.sdk.scale;padding:0;spacing:0
        indicator:Rectangle {width:34*root.sdk.scale;height:19*root.sdk.scale;x:3*root.sdk.scale;y:(toggle.height-height)/2;radius:height/2;color:toggle.checked ? root.sdk.colors.accent : root.sdk.colors.line
            Rectangle {width:15*root.sdk.scale;height:15*root.sdk.scale;radius:height/2;x:toggle.checked ? parent.width-width-2*root.sdk.scale : 2*root.sdk.scale;y:2*root.sdk.scale;color:root.sdk.colors.surface;Behavior on x {NumberAnimation {duration:100}}}}
        contentItem:Item {}
        HoverHandler {cursorShape:parent.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor}
    }
    component ToolGroup: Column {
        id:group
        required property string pluginId
        property bool pluginEnabled:true
        readonly property var page:root.toolPages[pluginId] || {}
        spacing:2
        Repeater {
            model:group.page.tools || []
            delegate:ItemDelegate {
                id:toolRow
                required property var modelData
                objectName:"piTool_"+modelData.name
                width:group.width;height:36*root.sdk.scale;padding:0
                background:Rectangle {radius:5;color:toolRow.hovered ? root.sdk.colors.hover : "transparent"}
                contentItem:RowLayout {
                    spacing:8
                    Text {Layout.leftMargin:12;Layout.fillWidth:true;text:toolRow.modelData.name;textFormat:Text.PlainText;elide:Text.ElideMiddle;color:group.pluginEnabled ? root.sdk.colors.ink : root.sdk.colors.muted;font.pixelSize:12*root.sdk.scale}
                    SessionSwitch {objectName:"piToolSwitch_"+toolRow.modelData.name;Layout.rightMargin:4;checked:!!toolRow.modelData.enabled;enabled:group.pluginEnabled && !root.working && !root.sessionBusy;onClicked:root.request("pi.tool",{name:toolRow.modelData.name,enabled:checked})}
                }
                onClicked:if(group.pluginEnabled && !root.working && !root.sessionBusy)root.request("pi.tool",{name:modelData.name,enabled:!modelData.enabled})
                ToolTip.visible:hovered;ToolTip.delay:450;ToolTip.timeout:12000
                ToolTip.text:modelData.description || modelData.name
                HoverHandler {cursorShape:Qt.PointingHandCursor}
            }
        }
        Text {width:parent.width;visible:!(group.page.tools || []).length;text:group.page.loading ? root.t("正在读取工具…","Loading tools…") : group.pluginEnabled ? root.t("此插件未注册工具","This extension has no registered tools") : root.t("启用插件后可查看其工具","Enable this extension to discover its tools");wrapMode:Text.Wrap;color:root.sdk.colors.muted;font.pixelSize:12*root.sdk.scale;leftPadding:12;topPadding:8;bottomPadding:8}
        SmallButton {width:parent.width;visible:!!group.page.hasMore;text:root.t("更多工具","More tools");enabled:!root.working;onClicked:root.loadTools(group.pluginId,true)}
    }
    ColumnLayout {
        anchors.fill: parent;anchors.margins:12;spacing:10
        RowLayout {
            Layout.fillWidth:true
            SmallButton {objectName:"piManagerBack";visible:!!root.selected;text:root.t("‹ 返回","‹ Back");onClicked:root.back()}
            IconImage {visible:!root.selected;source:"assets/pi.svg";color:root.sdk.colors.muted;sourceSize:Qt.size(48,48);Layout.preferredWidth:24;Layout.preferredHeight:24}
            Text {Layout.fillWidth:true;text:root.selected ? "" : root.t("Pi 能力","Pi capabilities");textFormat:Text.PlainText;elide:Text.ElideRight;color:root.sdk.colors.ink;font.pixelSize:16*root.sdk.scale;font.bold:true}
            SmallButton {objectName:"piManagerCancelInstall";visible:root.jobOperation==="pi.install" && !!root.job;enabled:root.canCancel;text:root.t("取消安装","Cancel install");onClicked:{root.canCancel=false;root.request("pi.cancel",{id:root.job})}}
            SmallButton {objectName:"piManagerInstall";visible:!root.selected;iconName:"add";text:"";ToolTip.text:root.t("安装插件","Install extension");enabled:!root.working;onClicked:install.open()}
            SmallButton {objectName:"piManagerRefresh";visible:!root.selected;iconName:"refresh";text:"";ToolTip.text:root.t("刷新本地列表","Refresh local inventory");enabled:!root.working;onClicked:root.scan()}
        }
        RowLayout {
            objectName:"piCapabilityPresets";Layout.fillWidth:true;spacing:3
            Repeater {
                model:[{id:"standard",label:"标准 Pi",en:"Standard"},{id:"minimal",label:"极简",en:"Minimal"},{id:"full",label:"默认",en:"Default"},{id:"custom",label:"自定义",en:"Custom"}]
                delegate:Button {
                    id:presetButton
                    required property var modelData
                    objectName:"piPreset_"+modelData.id
                    Layout.fillWidth:true;Layout.preferredWidth:1;implicitHeight:34*root.sdk.scale;padding:4
                    enabled:!root.working && !root.sessionBusy
                    background:Rectangle {radius:6;color:root.profile.preset===presetButton.modelData.id ? root.sdk.colors.accentBg : presetButton.hovered ? root.sdk.colors.hover : "transparent";border.color:root.profile.preset===presetButton.modelData.id ? root.sdk.colors.accent : root.sdk.colors.line}
                    contentItem:Text {text:root.t(presetButton.modelData.label,presetButton.modelData.en);color:root.profile.preset===presetButton.modelData.id ? root.sdk.colors.accent : root.sdk.colors.ink;font.pixelSize:12*root.sdk.scale;horizontalAlignment:Text.AlignHCenter;verticalAlignment:Text.AlignVCenter;elide:Text.ElideRight}
                    onClicked:root.request("pi.preset",{preset:modelData.id})
                    ToolTip.visible:hovered;ToolTip.delay:350;ToolTip.text:root.sessionBusy ? root.t("任务结束后可调整","Available after the current task finishes") : root.presetHint(modelData.id)
                    HoverHandler {cursorShape:parent.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor}
                }
            }
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
                    placeholderText:root.t("搜索插件或工具…","Search extensions or tools…")
                    color:root.sdk.colors.ink;font.pixelSize:12*root.sdk.scale
                    background:Rectangle {radius:8;color:root.sdk.colors.bg;border.color:search.activeFocus ? root.sdk.colors.accent : root.sdk.colors.line}
                    onTextChanged:filterTimer.restart()
                    onAccepted:{filterTimer.stop();root.query=text;root.status(false)}
                }
                SmallButton {objectName:"piManagerSearchButton";iconName:"search";text:"";ToolTip.text:root.t("搜索本地插件","Search installed extensions");onClicked:{filterTimer.stop();root.query=search.text;root.status(false)}}
            }
            ListView {
                id:list;objectName:"piManagerList";Layout.fillWidth:true;Layout.fillHeight:true;clip:true;reuseItems:true
                model:root.rows;spacing:4
                ScrollBar.vertical:ScrollBar {}
                delegate:Column {
                    id:entry
                    required property var modelData
                    width:list.width;spacing:2
                    ItemDelegate {
                        id:header
                        objectName:"piExtension_"+entry.modelData.id
                        width:parent.width;height:48*root.sdk.scale;padding:6
                        background:Rectangle {radius:7;color:header.hovered ? root.sdk.colors.hover : "transparent"}
                        contentItem:RowLayout {
                            spacing:7
                            IconImage {source:"assets/ui/chevron.svg";color:root.sdk.colors.muted;Layout.preferredWidth:12*root.sdk.scale;Layout.preferredHeight:12*root.sdk.scale;rotation:root.expandedId===entry.modelData.id ? 90 : 0;Behavior on rotation {NumberAnimation {duration:120}}}
                            ExtensionIcon {colors:root.paletteColors;iconName:entry.modelData.info.icon || "package";Layout.preferredWidth:25;Layout.preferredHeight:25}
                            ColumnLayout {Layout.fillWidth:true;spacing:1
                                Text {Layout.fillWidth:true;text:entry.modelData.id==="builtin:pi-tools" ? root.t("Pi 原生工具","Native Pi tools") : entry.modelData.name;elide:Text.ElideRight;textFormat:Text.PlainText;color:root.sdk.colors.ink;font.pixelSize:12*root.sdk.scale}
                                Text {visible:entry.modelData.toolCount>0;text:entry.modelData.enabledToolCount+" / "+entry.modelData.toolCount;color:root.sdk.colors.muted;font.pixelSize:11*root.sdk.scale}
                            }
                            SessionSwitch {objectName:"piPluginSwitch_"+entry.modelData.id;checked:!!entry.modelData.sessionEnabled;enabled:!root.working && !root.sessionBusy;onClicked:root.request("pi.plugin",{id:entry.modelData.id,enabled:checked})}
                            SmallButton {objectName:"piExtensionDetails_"+entry.modelData.id;visible:entry.modelData.id!=="builtin:pi-tools";iconName:"more";text:"";padding:4*root.sdk.scale;horizontalPadding:4*root.sdk.scale;verticalPadding:4*root.sdk.scale;implicitWidth:28*root.sdk.scale;implicitHeight:28*root.sdk.scale;Layout.minimumWidth:implicitWidth;Layout.maximumWidth:implicitWidth;Layout.preferredHeight:implicitHeight;Layout.alignment:Qt.AlignVCenter;ToolTip.text:root.t("说明与管理","Details and management");onClicked:root.select(entry.modelData)}
                        }
                        onClicked:root.expand(entry.modelData)
                        HoverHandler {cursorShape:Qt.PointingHandCursor}
                    }
                    ToolGroup {width:parent.width;visible:root.expandedId===entry.modelData.id;height:visible ? implicitHeight : 0;pluginId:entry.modelData.id;pluginEnabled:!!entry.modelData.sessionEnabled}
                    Rectangle {width:parent.width;height:1;color:root.sdk.colors.line;opacity:0.65}
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
                RowLayout {width:parent.width
                    Text {Layout.fillWidth:true;text:root.t("当前会话","Current chat");color:root.sdk.colors.ink;font.pixelSize:13*root.sdk.scale}
                    SessionSwitch {objectName:"piManagerSessionSwitch";checked:!!(root.selected && root.selected.sessionEnabled);enabled:!root.working && !root.sessionBusy;onClicked:root.request("pi.plugin",{id:root.selected.id,enabled:checked})}
                }
                ToolGroup {width:parent.width;pluginId:root.selected ? root.selected.id : "";pluginEnabled:!!(root.selected && root.selected.sessionEnabled)}
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
                Item {width:1;height:8}
            }
        }
    }
    Timer {interval:450;repeat:true;running:root.sdk.active && !!((root.toolPages[root.selected ? root.selected.id : root.expandedId] || {}).loading);onTriggered:if(Object.keys(root.pending).length===0)root.loadTools(root.selected ? root.selected.id : root.expandedId,false)}
    Timer {id:filterTimer;interval:180;onTriggered:{root.query=search.text;root.status(false)}}
    Timer {interval:400;repeat:true;running:root.sdk.active && (!!root.job || root.hostBusy || root.inventoryLoading);onTriggered:{if(root.job && !root.polling){root.polling=true;root.request("pi.job",{id:root.job})}else if(!root.job && (root.hostBusy || root.inventoryLoading) && Object.keys(root.pending).length===0)root.status(false)}}
    Connections {
        target:root.sdk;ignoreUnknownSignals:true
        function onActiveChanged() { root.initialize() }
        function onSessionChanged() {root.initialize()}
        function onHostResponse(id,value) {
            const entry=root.pending[id];if(!entry)return
            const next=Object.assign({},root.pending);delete next[id];root.pending=next
            const op=entry.operation
            if(op==="pi.job")root.polling=false
            if(!value.ok){root.lastError=true;root.notice=value.error || value.status;root.job="";root.inventoryLoading=false;if(["pi.preset","pi.tool","pi.plugin"].indexOf(op)>=0)root.status(false);return}
            if(value.jobId){root.job=value.jobId;root.jobOperation=op;root.notice=root.t("处理中…","Working…");return}
            if(op==="pi.tools") {
                const id=entry.args.id,result=value.result || {},old=root.toolPages[id] || {},pages=Object.assign({},root.toolPages)
                pages[id]={tools:entry.kind==="tools-append" ? (old.tools || []).concat(result.tools || []) : result.tools || [],total:result.total,hasMore:result.hasMore,loading:result.loading}
                root.toolPages=pages
                return
            }
            if(["pi.preset","pi.tool","pi.plugin"].indexOf(op)>=0) {root.lastError=false;root.notice="";root.profile=value.result.profile;root.status(false);return}
            if(op==="pi.status") {
                if(entry.detail!==(root.selected ? root.selected.id : "") || (!root.selected && entry.query!==root.query))return
                const result=value.result
                root.hostBusy=!!result.busy;root.profile=result.profile || {preset:"full"}
                const inventoryFailed=!result.inventoryReady && !!result.inventoryFailed && root.inventoryRequested
                if(result.inventoryReady || inventoryFailed)root.inventoryLoading=false
                if(result.contextCurrent && !result.inventoryReady && !root.inventoryRequested && !result.agentBusy && !root.hostBusy && root.sdk.hostCapabilities.operations["pi.inventory"]){root.inventoryRequested=true;root.inventoryLoading=true;root.request("pi.inventory")}
                if(!result.contextCurrent){if(!root.job && !root.hostBusy)root.request("pi.scan");return}
                if(root.hostBusy && !root.job)root.notice=root.t("正在同步本地插件…","Synchronizing installed extensions…");else if(inventoryFailed){root.lastError=true;root.notice=root.t("工具列表加载失败，请刷新重试。","Tool inventory failed to load; refresh to retry.")}else if(!root.lastError)root.notice=""
                if(root.selected) {
                    const row=(result.extensions || [])[0];if(row)root.selected=row
                    root.details=result.details || {}
                    root.update=result.extensionUpdate && result.extensionUpdate.id===root.selected.id ? result.extensionUpdate : {}
                } else {root.rows=entry.kind==="append" ? root.rows.concat(result.extensions || []) : result.extensions || [];root.total=result.total;root.hasMore=result.hasMore}
                const openId=root.selected ? root.selected.id : root.expandedId
                if(openId && ((result.extensions || []).some(row=>row.id===openId) || root.selected))root.loadTools(openId,false)
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
