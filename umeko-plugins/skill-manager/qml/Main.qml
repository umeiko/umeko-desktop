import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

FocusScope {
    id: root
    objectName: "skillManagerWidget"
    required property var sdk
    clip: true
    focus: true
    property bool initialized: false
    property var skills: []
    property string selectedId: ""
    property var details: ({})
    property bool detailOpen: false
    property bool filesOpen: false
    property string route: "main"
    property bool allSkills: false
    property bool descending: false
    property bool groupBySource: false
    property string sourceFilter: "all"
    property string defaultFilter: "all"
    property string openMenu: ""
    property var collapsedGroups: []
    property string query: ""
    property var pending: ({})
    property string job: ""
    property string jobOperation: ""
    property bool polling: false
    property bool canCancel: false
    property string notice: ""
    property bool noticeError: false
    property bool installProject: true
    property bool importProject: true
    property var importPreview: ({})
    property var importDecisions: ({})
    property var importResult: ({})
    property bool dropPreview: false
    readonly property real rowHeight: 26 * sdk.scale
    readonly property var sourceKeys: ["global", "project", "package", "extension", "extra"]
    readonly property var selected: skills.filter(s => s.id === selectedId)[0] || null
    readonly property int attachedCount: skills.filter(s => s.attached).length
    readonly property bool working: !!job || Object.keys(pending).length > 0
    readonly property var entries: filteredEntries()
    readonly property bool importReady: !!importPreview.id && !(importPreview.errors || []).length
        && (importPreview.skills || []).some(s => !s.error && importDecisions[s.name]!=="skip" && (!s.conflict || s.replaceable))
    readonly property bool importSupported: !!(sdk.hostCapabilities && sdk.hostCapabilities.operations
        && sdk.hostCapabilities.operations["skills.importPreview"] && sdk.hostCapabilities.operations["skills.import"])
    function t(zh, en) { return sdk.language.indexOf("zh") === 0 ? zh : en }
    function sourceLabel(key) {
        const index = sourceKeys.indexOf(key)
        return index < 0 ? key : [t("全局","Global"),t("项目","Project"),t("来源包","Package"),t("扩展","Extension"),t("额外","Extra")][index]
    }
    function filteredEntries() {
        let result = skills.filter(s => (allSkills || s.attached) && (sourceFilter === "all" || s.source === sourceFilter)
            && (defaultFilter === "all" || (defaultFilter === "on") === !!s.enabled)
            && (s.name + " " + (s.description || "")).toLowerCase().indexOf(query.toLowerCase()) >= 0)
        result = result.slice().sort((a,b) => a.name.localeCompare(b.name) * (descending ? -1 : 1) || a.id.localeCompare(b.id))
        if (!groupBySource) return result.map(s => ({kind:"skill", skill:s}))
        let groups = []
        for (let key of sourceKeys) {
            const rows = result.filter(s => s.source === key)
            if (!rows.length) continue
            groups.push({kind:"group", key:key, count:rows.length})
            if (collapsedGroups.indexOf(key) < 0) for (let s of rows) groups.push({kind:"skill", skill:s})
        }
        return groups
    }
    function collapse(key) {
        let next = collapsedGroups.slice(); const i = next.indexOf(key)
        if (i < 0) next.push(key); else next.splice(i, 1)
        collapsedGroups = next
    }
    function request(operation, args) {
        if (!sdk.active) return false
        if (!sdk.hostCapabilities || !sdk.hostCapabilities.operations || !sdk.hostCapabilities.operations[operation]) {
            notice = t("当前版本尚不支持此操作，请升级 Umeko。","This operation needs a newer Umeko version."); noticeError = true; return false
        }
        const poll = operation === "skills.job" || operation === "pi.job"
        if (working && !poll && operation !== "pi.cancel") return false
        const id = sdk.requestHost(operation, args || {})
        if (!id) { notice=t("宿主忙碌，请稍后重试。","Host is busy; retry shortly."); noticeError=true; return false }
        let next = Object.assign({}, pending); next[id] = {operation:operation, skill:args && args.id || ""}; pending=next
        return true
    }
    function reload() { notice=""; noticeError=false; request("skills.list", {}) }
    function initialize() { if (sdk.active && !initialized) { initialized=true; reload() } }
    function choose(row, open) {
        selectedId=row.id; list.forceActiveFocus()
        if (open) { detailOpen=true; filesOpen=false; readDetails() }
    }
    function readDetails() {
        if (!selectedId || working) return
        details={}; request("skills.details", {id:selectedId})
    }
    function toggle(row) { if (row) request("skills.attach", {id:row.id, enabled:!row.attached}) }
    function currentEntry() { return entries[list.currentIndex] }
    function openCurrent() { const e=currentEntry(); if (e && e.kind==="skill") choose(e.skill,true) }
    function sizeLabel(size) { return (size || 0).toLocaleString(Qt.locale("en_US"), "f", 0) + t(" 字节"," bytes") }
    function defaultLabel() {
        if (!selected) return ""
        const scope=selected.source==="project" || selected.scope==="project" ? t("项目默认","Project default")
            : selected.source==="global" && selected.defaultMutable===true ? t("全局默认","Global default") : t("来源默认","Source default")
        return scope + (selected.enabled ? t("：启用",": on") : t("：停用",": off"))
    }
    function defaultExplanation() {
        if (!selected || selected.defaultMutable===true) return ""
        if (sdk.language.indexOf("zh")===0 && selected.defaultReason) return selected.defaultReason
        if (selected.source==="project" || selected.scope==="project")
            return t("此项目来源不支持在这里更改默认状态。","This project source does not support changing its default here.")
        if (selected.source==="extension")
            return t("此 Skill 遵循所属扩展的默认设置，请在扩展设置中更改。","This skill follows its extension's defaults. Change them in the extension settings.")
        return t("此来源不支持在这里更改默认状态。","This source does not support changing its default here.")
    }
    function displayMarkdown(value) {
        // The local document viewer displays text without fetching image URLs.
        return String(value || "").replace(/<img\b[^>]*>/gi, "")
            .replace(/!\[([^\]]*)\]\s*\([^)]*\)/g, "$1")
            .replace(/!\[([^\]]*)\](?:\[[^\]]*\])?/g, "$1")
    }
    function clearImportPreview() { importPreview={}; importDecisions={}; importResult={} }
    function localImportSource(source) {
        const value=String(source).trim()
        if (!value) return false
        if (/^file:/i.test(value)) return /^file:\/\/(?:\/|localhost\/)/i.test(value)
        return !/^[a-z][a-z0-9+.-]*:/i.test(value) || /^[a-z]:[\\/]/i.test(value)
    }
    function acceptsImportUrls(urls) { return urls && urls.length===1 && /^file:/i.test(String(urls[0])) && localImportSource(urls[0]) }
    function dropLocalUrls(urls) {
        if (working || !acceptsImportUrls(urls)) return false
        beginImport(String(urls[0])); return true
    }
    function beginImport(source) {
        if (working) return
        route="import";openMenu="";clearImportPreview();notice="";noticeError=false
        importSource.text=String(source);previewImport()
    }
    function previewImport() {
        if (working) return
        clearImportPreview();notice="";noticeError=false
        if (!importSupported) {notice=t("本地导入需要更新版本的 Umeko。","Local import needs a newer Umeko version.");noticeError=true;return}
        if (!localImportSource(importSource.text)) {notice=t("请输入本地文件夹、ZIP 或 .skill 文件的路径。","Enter a local folder, ZIP or .skill file path.");noticeError=true;return}
        request("skills.importPreview",{source:importSource.text.trim(),project:importProject})
    }
    function decideImport(name, decision) {let next=Object.assign({},importDecisions);next[name]=decision;importDecisions=next}
    function submitImport() {if(!working && importReady)request("skills.import",{id:importPreview.id,decisions:importDecisions})}
    function importError(value) {
        const message=String(value || "")
        if (sdk.language.indexOf("zh")===0 || !/[\u3400-\u9fff]/.test(message)) return message
        const reasons={
            "同名技能来自包或扩展，只能跳过；请先在对应管理入口处理。":"This name belongs to a package or extension skill. Skip it and manage its source separately.",
            "同名技能不在所选标准技能目录内，只能跳过。":"The existing skill is outside the selected standard skills directory and must be skipped.",
            "同名技能位于所选目录之外，只能跳过。":"The existing skill is outside the selected directory and must be skipped.",
            "存在多个同名技能，只能跳过；请先处理已有冲突。":"Several existing skills share this name. Skip it and resolve those conflicts first.",
            "导入批次中存在多个同名技能，请分开处理。":"Several skills in this import share a name. Import them separately.",
            "技能名称不能作为安全的目标文件夹名称。":"The skill name cannot be used as a safe destination folder name.",
            "技能包存在重复、大小写或文件与目录冲突的路径":"The package contains duplicate, case-conflicting or file/directory-conflicting paths.",
            "不支持符号链接或目录联接，请选择实际文件夹或压缩包":"Links and directory junctions are unsupported. Select a real folder or archive.",
            "技能包超过 128 MiB 或 2048 个条目的限制":"The package exceeds the 128 MiB or 2,048-entry limit.",
            "技能文件夹不支持链接或特殊文件":"Skill folders cannot contain links or special files.",
            "技能源文件在读取期间发生变化，请重新预览":"The source changed while it was being read. Preview it again.",
            "技能压缩包超过 128 MiB 限制":"The archive exceeds the 128 MiB limit.",
            "技能压缩包不支持链接或特殊文件":"Skill archives cannot contain links or special files.",
            "不支持加密的技能压缩包":"Encrypted skill archives are unsupported.",
            "技能压缩包只支持 ZIP stored/deflate 压缩":"Skill archives must use ZIP stored or deflate compression.",
            "技能压缩包内容大小无效":"An archive entry has an invalid content size.",
            "请选择包含 SKILL.md 的文件夹、ZIP 或 .skill 压缩包":"Select a folder containing SKILL.md, a ZIP or a .skill archive.",
            "技能目标目录不能使用符号链接或目录联接":"The destination cannot use links or directory junctions.",
            "没有找到 SKILL.md":"No SKILL.md was found.",
            "导入预览已关闭或被新的预览替代，请重新预览":"This preview is no longer available. Preview the source again.",
            "技能目标目录与已确认的预览不一致":"The destination differs from the confirmed preview.",
            "导入决定只能为 skip 或 replace":"Import decisions must be skip or replace."
        }
        if (reasons[message]) return reasons[message]
        const prefix="SKILL.md 必须为 UTF-8 且通过 Pi 原生格式验证。"
        if (message.indexOf(prefix)===0) {
            const details=message.slice(prefix.length).split("；").filter(part=>part && !/[\u3400-\u9fff]/.test(part)).join("; ")
            return "SKILL.md must use UTF-8 and pass Pi's native format validation."+(details ? " "+details : "")
        }
        return "Could not import this item. Review its local source and preview again."
    }
    function complete(operation, result, success) {
        noticeError=!success || result.ok===false
        notice=result.error || result.message || (noticeError ? t("操作失败，请重试。","Operation failed; retry.") : "")
        if (operation.indexOf("skills.import")===0) notice=importError(notice)
        if (noticeError) return
        if (operation==="skills.importPreview") {
            importPreview=result.preview || {};importResult={}
            let choices={};for(let row of importPreview.skills || [])choices[row.name]=row.conflict || row.error ? "skip" : "replace"
            importDecisions=choices
        } else if (operation==="skills.import") {
            importResult=result;importPreview={};importDecisions={}
            notice=t("已导入 ","Imported ")+(result.imported || []).length+t(" 项，跳过 ","; skipped ")+(result.skipped || []).length
            noticeError=!!(result.errors || []).length
        } else if (operation==="skills.list") {
            skills=result.skills || []
            if (!selected && skills.length) selectedId=""
            if (detailOpen && selected) readDetails()
        } else if (operation==="skills.details") {
            if (result.details && result.details.id===selectedId) details=result.details
            else if (detailOpen && selected) readDetails()
        } else if (operation!=="skills.reveal") {
            if (operation==="pi.install") route="main"
            reload()
        }
    }
    Component.onCompleted: initialize()
    onSelectedIdChanged: if (detailOpen) {details={}; if (!working && selected) readDetails()}
    onEntriesChanged: { if (list.currentIndex >= entries.length) list.currentIndex=entries.length-1 }
    Keys.onPressed: event => {
        if ((event.modifiers & Qt.ControlModifier) && event.key===Qt.Key_F && route==="main") {
            search.forceActiveFocus(); search.selectAll(); event.accepted=true
        } else if (event.key===Qt.Key_Escape) { openMenu=""; if (!working) route="main"; event.accepted=true }
    }
    Rectangle { anchors.fill:parent; color:root.sdk.colors.surface; z:-1 }
    component Label: Text {
        color:root.sdk.colors.ink; font.pixelSize:12*root.sdk.scale; textFormat:Text.PlainText
        verticalAlignment:Text.AlignVCenter; elide:Text.ElideRight
    }
    component SmallButton: Button {
        id:button
        property bool selected:false
        implicitHeight:28*root.sdk.scale; implicitWidth:Math.max(26*root.sdk.scale, label.implicitWidth+18*root.sdk.scale)
        padding:5*root.sdk.scale; leftPadding:8*root.sdk.scale; rightPadding:8*root.sdk.scale
        background:Rectangle {radius:5*root.sdk.scale; color:button.selected ? root.sdk.colors.accentBg : button.hovered ? root.sdk.colors.hover : "transparent"; border.color:button.selected ? root.sdk.colors.accent : root.sdk.colors.line}
        contentItem:Label {id:label;text:button.text;font.pixelSize:11*root.sdk.scale;horizontalAlignment:Text.AlignHCenter;color:!button.enabled ? root.sdk.colors.muted : button.selected ? root.sdk.colors.accent : root.sdk.colors.ink}
    }
    component SourceBadge: Rectangle {
        property string text:""
        implicitHeight:17*root.sdk.scale; implicitWidth:Math.min(74*root.sdk.scale,badge.implicitWidth+10*root.sdk.scale)
        radius:4*root.sdk.scale; color:root.sdk.colors.bg
        Label {id:badge;anchors.centerIn:parent;width:parent.width-8*root.sdk.scale;text:parent.text;font.pixelSize:9*root.sdk.scale;color:root.sdk.colors.muted;horizontalAlignment:Text.AlignHCenter}
    }
    component Input: TextField {
        id:field
        implicitHeight:32*root.sdk.scale; selectByMouse:true; color:root.sdk.colors.ink
        font.pixelSize:12*root.sdk.scale; leftPadding:9*root.sdk.scale
        background:Rectangle {radius:6*root.sdk.scale;color:root.sdk.colors.bg;border.color:field.activeFocus ? root.sdk.colors.accent : root.sdk.colors.line}
    }
    ColumnLayout {
        anchors.fill:parent; anchors.margins:12*root.sdk.scale; spacing:7*root.sdk.scale
        RowLayout {
            Layout.fillWidth:true; spacing:7*root.sdk.scale
            Image {source:"../assets/layers.svg";Layout.preferredWidth:18*root.sdk.scale;Layout.preferredHeight:18*root.sdk.scale;sourceSize.width:36;sourceSize.height:36}
            Label {text:root.route==="install" ? root.t("安装 Skill 包","Install a skill package") : root.route==="import" ? root.t("导入本地 Skill","Import local skills") : root.t("当前聊天","This chat");font.pixelSize:16*root.sdk.scale;font.bold:true;Layout.fillWidth:true}
            Label {visible:root.route==="main";text:root.attachedCount+root.t(" 项可用 / "," available / ")+root.skills.length;font.pixelSize:10*root.sdk.scale;color:root.sdk.colors.muted}
            SmallButton {objectName:"skillManagerInstall";visible:root.route==="main";text:"＋";enabled:!root.working;Accessible.name:root.t("安装 Skill 包","Install skill package");onClicked:{root.openMenu="";root.route="install";root.notice="";installSource.forceActiveFocus()}}
            SmallButton {objectName:"skillManagerImport";visible:root.route==="main";text:root.t("导入","Import");enabled:!root.working;onClicked:{root.openMenu="";root.route="import";root.notice="";root.noticeError=false;root.clearImportPreview();importSource.forceActiveFocus()}}
            SmallButton {objectName:"skillManagerRefresh";visible:root.route==="main";text:"↻";enabled:!root.working;Accessible.name:root.t("刷新","Refresh");onClicked:root.reload()}
            SmallButton {objectName:"skillManagerBack";visible:root.route!=="main";text:root.t("返回","Back");enabled:!root.working;onClicked:{const imported=root.route==="import" && Object.keys(root.importResult).length>0;root.route="main";if(imported)root.reload()}}
        }
        RowLayout {
            visible:root.notice!==""; Layout.fillWidth:true
            Label {objectName:"skillManagerNotice";text:root.notice;Layout.fillWidth:true;wrapMode:Text.Wrap;maximumLineCount:3;color:root.noticeError ? root.sdk.colors.danger : root.sdk.colors.muted;font.pixelSize:11*root.sdk.scale}
            SmallButton {objectName:"skillManagerRetry";visible:root.noticeError && !root.working;text:root.t("重试","Retry");onClicked:root.route==="import" ? root.previewImport() : root.route==="install" ? root.startInstall() : (root.detailOpen && root.selected ? root.readDetails() : root.reload())}
        }
        ColumnLayout {
            visible:root.route==="main";Layout.fillWidth:true;Layout.fillHeight:true;spacing:7*root.sdk.scale
            RowLayout {
                Layout.fillWidth:true;spacing:6*root.sdk.scale
                SmallButton {objectName:"skillManagerAttached";text:root.t("已附带 ","Available ")+root.attachedCount;selected:!root.allSkills;onClicked:root.allSkills=false}
                SmallButton {objectName:"skillManagerAll";text:root.t("全部 ","All ")+root.skills.length;selected:root.allSkills;onClicked:root.allSkills=true}
                Item {Layout.fillWidth:true}
                SmallButton {objectName:"skillManagerGroup";text:root.t("按来源分组","Group sources");selected:root.groupBySource;onClicked:root.groupBySource=!root.groupBySource}
            }
            Input {id:search;objectName:"skillManagerSearch";Layout.fillWidth:true;placeholderText:root.t("搜索名称或简介…  Ctrl+F","Find name or description…  Ctrl+F");onTextChanged:root.query=text;onAccepted:{list.forceActiveFocus();if(list.currentIndex<0 && root.entries.length)list.currentIndex=0}}
            RowLayout {
                Layout.fillWidth:true;spacing:5*root.sdk.scale
                SmallButton {objectName:"skillManagerSourceFilter";text:root.sourceFilter==="all" ? root.t("全部来源","All sources") : root.sourceLabel(root.sourceFilter);onClicked:root.openMenu=root.openMenu==="source" ? "" : "source"}
                SmallButton {objectName:"skillManagerDefaultFilter";text:root.defaultFilter==="all" ? root.t("默认：全部","Default: all") : root.defaultFilter==="on" ? root.t("默认：启用","Default: on") : root.t("默认：停用","Default: off");onClicked:root.openMenu=root.openMenu==="defaults" ? "" : "defaults"}
                Item {Layout.fillWidth:true}
                SmallButton {objectName:"skillManagerSort";text:root.descending ? root.t("名称 Z–A","Name Z–A") : root.t("名称 A–Z","Name A–Z");onClicked:root.descending=!root.descending}
            }
            RowLayout {
                Layout.fillWidth:true;Layout.preferredHeight:17*root.sdk.scale
                Label {text:root.t("名称","Name");font.pixelSize:10*root.sdk.scale;color:root.sdk.colors.muted;Layout.fillWidth:true;Layout.leftMargin:23*root.sdk.scale}
                Label {text:root.t("来源","Source");font.pixelSize:10*root.sdk.scale;color:root.sdk.colors.muted;Layout.preferredWidth:70*root.sdk.scale}
                Label {text:root.t("附带","Use");font.pixelSize:10*root.sdk.scale;color:root.sdk.colors.muted;Layout.preferredWidth:30*root.sdk.scale;horizontalAlignment:Text.AlignHCenter}
            }
            ListView {
                id:list;objectName:"skillManagerList";Layout.fillWidth:true;Layout.fillHeight:true;Layout.minimumHeight:52*root.sdk.scale
                clip:true;reuseItems:true;spacing:0;model:root.entries;currentIndex:0;keyNavigationEnabled:true;boundsBehavior:Flickable.StopAtBounds
                ScrollBar.vertical:ScrollBar {policy:ScrollBar.AsNeeded}
                Keys.onPressed:event=>{
                    const row=root.currentEntry()
                    if (event.key===Qt.Key_Return || event.key===Qt.Key_Enter) {root.openCurrent();event.accepted=true}
                    else if (event.key===Qt.Key_Space && row) {if(row.kind==="skill")root.toggle(row.skill);else root.collapse(row.key);event.accepted=true}
                    else if ((event.key===Qt.Key_Left || event.key===Qt.Key_Right) && row && row.kind==="group") {root.collapse(row.key);event.accepted=true}
                }
                onCurrentIndexChanged:{const row=root.currentEntry();if(row && row.kind==="skill")root.selectedId=row.skill.id}
                delegate:Rectangle {
                    id:entry;required property var modelData;required property int index
                    readonly property bool group:modelData.kind==="group"
                    width:list.width;height:root.rowHeight
                    objectName:group ? "skillManagerGroup_"+modelData.key : "skillManagerEntry_"+modelData.skill.id
                    color:group ? root.sdk.colors.bg : modelData.skill.id===root.selectedId ? root.sdk.colors.accentBg : hover.hovered ? root.sdk.colors.hover : "transparent"
                    HoverHandler {id:hover}
                    MouseArea {anchors.fill:parent;onClicked:{list.currentIndex=entry.index;list.forceActiveFocus();if(entry.group)root.collapse(entry.modelData.key);else root.choose(entry.modelData.skill,false)} onDoubleClicked:if(!entry.group)root.choose(entry.modelData.skill,true)}
                    RowLayout {
                        visible:entry.group;anchors.fill:parent;anchors.leftMargin:6*root.sdk.scale;anchors.rightMargin:8*root.sdk.scale
                        Label {text:root.collapsedGroups.indexOf(entry.modelData.key)>=0 ? "›" : "⌄";color:root.sdk.colors.muted}
                        Label {text:entry.group ? root.sourceLabel(entry.modelData.key) : "";font.pixelSize:11*root.sdk.scale;font.bold:true;Layout.fillWidth:true}
                        Label {text:entry.modelData.count || "";font.pixelSize:10*root.sdk.scale;color:root.sdk.colors.muted}
                    }
                    RowLayout {
                        visible:!entry.group;anchors.fill:parent;anchors.leftMargin:4*root.sdk.scale;anchors.rightMargin:4*root.sdk.scale;spacing:6*root.sdk.scale
                        Image {source:"../assets/layers.svg";Layout.preferredWidth:13*root.sdk.scale;Layout.preferredHeight:13*root.sdk.scale;sourceSize.width:26;sourceSize.height:26}
                        Label {text:entry.group ? "" : entry.modelData.skill.name;Layout.fillWidth:true;font.pixelSize:12*root.sdk.scale}
                        SourceBadge {text:entry.group ? "" : root.sourceLabel(entry.modelData.skill.source);Layout.preferredWidth:70*root.sdk.scale}
                        Button {
                            id:mark;objectName:entry.group ? "" : "skillManagerAttach_"+entry.modelData.skill.id
                            Layout.preferredWidth:26*root.sdk.scale;Layout.preferredHeight:root.rowHeight;padding:0;enabled:!root.working;focusPolicy:Qt.NoFocus
                            Accessible.name:(entry.group ? "" : entry.modelData.skill.name)+root.t("：附带到当前聊天",": available in this chat")
                            background:Item {}
                            contentItem:Item {
                                Rectangle {width:14*root.sdk.scale;height:14*root.sdk.scale;anchors.centerIn:parent;radius:3*root.sdk.scale;color:!entry.group && entry.modelData.skill.attached ? root.sdk.colors.accent : root.sdk.colors.surface;border.color:root.sdk.colors.line
                                    Label {anchors.centerIn:parent;text:!entry.group && entry.modelData.skill.attached ? "✓" : "";font.pixelSize:11*root.sdk.scale;color:"white"}
                                }
                            }
                            onClicked:root.toggle(entry.modelData.skill)
                        }
                    }
                }
                Label {anchors.centerIn:parent;width:parent.width;horizontalAlignment:Text.AlignHCenter;visible:root.entries.length===0 && !root.working;text:root.skills.length===0 ? root.t("暂无本地 Skill。可安装来源包后刷新。","No local skills. Install a package, then refresh.") : root.t("没有匹配的 Skill","No matching skills");wrapMode:Text.Wrap;color:root.sdk.colors.muted;font.pixelSize:11*root.sdk.scale}
            }
            Rectangle {
                id:detailPanel;objectName:"skillManagerDetails";visible:root.detailOpen && !!root.selected
                Layout.fillWidth:true;Layout.preferredHeight:Math.min(322*root.sdk.scale,root.height*0.46);Layout.minimumHeight:Math.min(240*root.sdk.scale,root.height*0.40)
                color:root.sdk.colors.bg;clip:true
                Rectangle {width:parent.width;height:1;color:root.sdk.colors.line}
                ColumnLayout {
                    anchors.fill:parent;anchors.margins:9*root.sdk.scale;spacing:5*root.sdk.scale
                    RowLayout {
                        Layout.fillWidth:true
                        Label {objectName:"skillManagerName";text:root.selected ? root.selected.name : "";font.pixelSize:15*root.sdk.scale;font.bold:true;Layout.fillWidth:true}
                        SourceBadge {text:root.selected ? root.sourceLabel(root.selected.source) : ""}
                        SmallButton {objectName:"skillManagerCloseDetails";text:"×";onClicked:root.detailOpen=false;Accessible.name:root.t("关闭详情","Close details")}
                    }
                    Label {objectName:"skillManagerDescription";Layout.fillWidth:true;text:root.selected ? root.selected.description || "" : "";wrapMode:Text.Wrap;maximumLineCount:2;color:root.sdk.colors.muted;font.pixelSize:11*root.sdk.scale}
                    RowLayout {
                        Layout.fillWidth:true
                        SmallButton {objectName:"skillManagerMarkdownTab";text:"SKILL.md";selected:!root.filesOpen;onClicked:root.filesOpen=false}
                        SmallButton {objectName:"skillManagerFilesTab";text:root.t("文件 ","Files ")+(root.details.files || []).length;selected:root.filesOpen;onClicked:root.filesOpen=true}
                        Item {Layout.fillWidth:true}
                        Label {objectName:"skillManagerSize";text:root.t("所列文件：","Listed files: ")+root.sizeLabel(root.details.size);font.pixelSize:10*root.sdk.scale;color:root.sdk.colors.muted}
                    }
                    ScrollView {
                        id:detailScroll;Layout.fillWidth:true;Layout.fillHeight:true;clip:true;contentWidth:availableWidth;ScrollBar.horizontal.policy:ScrollBar.AlwaysOff
                        Column {
                            width:detailScroll.availableWidth;spacing:3*root.sdk.scale
                            TextEdit {objectName:"skillManagerMarkdown";visible:!root.filesOpen;width:parent.width;height:visible ? Math.max(24*root.sdk.scale,contentHeight) : 0;text:root.displayMarkdown(root.details.markdown) || (root.working ? root.t("正在读取说明…","Reading documentation…") : root.t("暂无说明。","No documentation."));textFormat:TextEdit.MarkdownText;readOnly:true;selectByMouse:true;wrapMode:TextEdit.WrapAnywhere;color:root.sdk.colors.ink;font.pixelSize:11*root.sdk.scale;selectionColor:root.sdk.colors.accentBg}
                            Repeater {model:root.filesOpen ? root.details.files || [] : [];delegate:Label {required property var modelData;width:parent.width;text:modelData.path+" · "+root.sizeLabel(modelData.size);font.pixelSize:10*root.sdk.scale;color:root.sdk.colors.muted;wrapMode:Text.WrapAnywhere}}
                            Label {visible:!!root.details.truncated;width:parent.width;text:root.t("仅显示部分正文或文件；字节数只计所列文件。可打开目录查看完整内容。","Some text or files are omitted. Bytes count only the listed files. Open the folder for complete content.");wrapMode:Text.Wrap;color:root.sdk.colors.muted;font.pixelSize:10*root.sdk.scale}
                        }
                    }
                    Label {objectName:"skillManagerPath";Layout.fillWidth:true;text:root.details.path || (root.selected ? root.selected.path : "");font.pixelSize:9*root.sdk.scale;color:root.sdk.colors.muted;elide:Text.ElideMiddle}
                    RowLayout {
                        Layout.fillWidth:true;spacing:5*root.sdk.scale
                        Label {objectName:"skillManagerChatState";text:root.selected && root.selected.attached ? root.t("本聊天可用","Available in this chat") : root.t("本聊天未附带","Excluded from this chat");font.pixelSize:10*root.sdk.scale;Layout.fillWidth:true}
                        SmallButton {objectName:"skillManagerDetailAttach";text:root.selected && root.selected.attached ? root.t("移出聊天","Exclude") : root.t("附带到聊天","Include");enabled:!root.working;onClicked:root.toggle(root.selected)}
                        SmallButton {objectName:"skillManagerReveal";text:root.t("打开目录","Open folder");enabled:!root.working;onClicked:root.request("skills.reveal",{id:root.selectedId})}
                    }
                    RowLayout {
                        Layout.fillWidth:true;spacing:5*root.sdk.scale
                        Label {objectName:"skillManagerDefaultLabel";text:root.defaultLabel();font.pixelSize:10*root.sdk.scale;color:root.sdk.colors.muted;Layout.fillWidth:true}
                        SmallButton {objectName:"skillManagerDefault";text:root.t("更改默认…","Change default…");enabled:!root.working && !!root.selected && root.selected.defaultMutable===true;onClicked:root.request("skills.default",{id:root.selectedId,enabled:!root.selected.enabled})}
                        SmallButton {objectName:"skillManagerRemove";visible:!!root.selected && root.selected.removable===true && !!root.selected.packageSource;text:root.t("卸载包…","Remove package…");enabled:!root.working;onClicked:root.request("skills.remove",{id:root.selectedId})}
                    }
                    Label {objectName:"skillManagerDefaultReason";visible:text!=="";Layout.fillWidth:true;text:root.defaultExplanation();wrapMode:Text.Wrap;font.pixelSize:9*root.sdk.scale;color:root.sdk.colors.muted}
                }
            }
            Label {Layout.fillWidth:true;text:root.t("↑↓ 选择 · Space 附带 · Enter 详情","↑↓ select · Space toggle · Enter details");font.pixelSize:9*root.sdk.scale;color:root.sdk.colors.muted}
            Label {objectName:"skillManagerContextHint";Layout.fillWidth:true;text:root.t("名称和简介可用，正文按需读取。移出不清除已读内容；字节数不是 token 用量。","Names and descriptions are available; bodies load on demand. Exclusion keeps content already read. Bytes are not token usage.");wrapMode:Text.Wrap;font.pixelSize:9*root.sdk.scale;color:root.sdk.colors.muted}
        }
        ColumnLayout {
            visible:root.route==="import";Layout.fillWidth:true;Layout.fillHeight:true;spacing:9*root.sdk.scale
            Label {Layout.fillWidth:true;text:root.t("粘贴本地 Skill 文件夹、ZIP 或 .skill 路径，也可拖到面板中。先预览，再由宿主确认写入。","Paste a local skill folder, ZIP or .skill path, or drop one onto this panel. Preview first; the host confirms before writing.");wrapMode:Text.Wrap;color:root.sdk.colors.muted;font.pixelSize:11*root.sdk.scale}
            Input {id:importSource;objectName:"skillManagerImportSource";Layout.fillWidth:true;placeholderText:root.t("本地文件夹或归档路径","Local folder or archive path");enabled:!root.working;onTextChanged:root.clearImportPreview();onAccepted:root.previewImport()}
            RowLayout {
                Layout.fillWidth:true;spacing:5*root.sdk.scale
                SmallButton {objectName:"skillManagerImportProject";text:root.t("当前项目","Current project");selected:root.importProject;enabled:!root.working;onClicked:{root.importProject=true;root.clearImportPreview()}}
                SmallButton {objectName:"skillManagerImportGlobal";text:root.t("全局","Global");selected:!root.importProject;enabled:!root.working;onClicked:{root.importProject=false;root.clearImportPreview()}}
                Item {Layout.fillWidth:true}
                SmallButton {objectName:"skillManagerImportPreview";text:root.t("预览","Preview");enabled:!root.working && importSource.text.trim()!=="";onClicked:root.previewImport()}
            }
            Label {objectName:"skillManagerImportSourceName";visible:!!root.importPreview.id;Layout.fillWidth:true;text:(root.importPreview.sourceName || "")+" · "+(root.importPreview.skills || []).length+root.t(" 项"," skills");font.pixelSize:11*root.sdk.scale}
            Repeater {model:(root.importPreview.errors || []).slice(0,12);delegate:Label {required property var modelData;Layout.fillWidth:true;text:root.importError(modelData);wrapMode:Text.Wrap;color:root.sdk.colors.danger;font.pixelSize:11*root.sdk.scale;maximumLineCount:4}}
            ListView {
                id:importList;objectName:"skillManagerImportList";Layout.fillWidth:true;Layout.fillHeight:true;Layout.minimumHeight:70*root.sdk.scale;clip:true
                model:root.importPreview.skills || [];spacing:7*root.sdk.scale;boundsBehavior:Flickable.StopAtBounds
                ScrollBar.vertical:ScrollBar {policy:ScrollBar.AsNeeded}
                delegate:Rectangle {
                    id:importEntry;required property var modelData;width:importList.width;height:importBody.implicitHeight+16*root.sdk.scale
                    color:root.sdk.colors.bg;radius:5*root.sdk.scale
                    ColumnLayout {
                        id:importBody;x:8*root.sdk.scale;y:8*root.sdk.scale;width:parent.width-16*root.sdk.scale;spacing:5*root.sdk.scale
                        Label {Layout.fillWidth:true;text:importEntry.modelData.name || root.t("无效 Skill","Invalid skill");font.bold:true}
                        Label {Layout.fillWidth:true;text:importEntry.modelData.description || "";wrapMode:Text.Wrap;maximumLineCount:3;color:root.sdk.colors.muted;font.pixelSize:10*root.sdk.scale}
                        Label {objectName:"skillManagerImportError_"+importEntry.modelData.name;visible:!!importEntry.modelData.error;Layout.fillWidth:true;text:root.importError(importEntry.modelData.error);wrapMode:Text.Wrap;maximumLineCount:4;color:root.sdk.colors.danger;font.pixelSize:10*root.sdk.scale}
                        Label {visible:!!importEntry.modelData.conflict;Layout.fillWidth:true;text:importEntry.modelData.replaceable ? root.t("同名 Skill 已存在：跳过或替换。","A skill with this name exists: skip or replace.") : root.t("同名 Skill 来自不可替换的来源，将跳过。","The existing skill belongs to a source that cannot be replaced; skip it.");wrapMode:Text.Wrap;color:root.sdk.colors.muted;font.pixelSize:10*root.sdk.scale}
                        RowLayout {
                            Layout.fillWidth:true
                            SmallButton {objectName:"skillManagerImportSkip_"+importEntry.modelData.name;text:root.t("跳过","Skip");selected:root.importDecisions[importEntry.modelData.name]==="skip";enabled:!root.working;onClicked:root.decideImport(importEntry.modelData.name,"skip")}
                            SmallButton {objectName:"skillManagerImportReplace_"+importEntry.modelData.name;text:importEntry.modelData.conflict ? root.t("替换","Replace") : root.t("导入","Import");selected:root.importDecisions[importEntry.modelData.name]==="replace";enabled:!root.working && !importEntry.modelData.error && (!importEntry.modelData.conflict || importEntry.modelData.replaceable);onClicked:root.decideImport(importEntry.modelData.name,"replace")}
                        }
                    }
                }
            }
            Repeater {model:(root.importResult.errors || []).slice(0,12);delegate:Label {required property var modelData;Layout.fillWidth:true;text:(modelData.name || "")+": "+root.importError(modelData.error);wrapMode:Text.Wrap;maximumLineCount:4;color:root.sdk.colors.danger;font.pixelSize:11*root.sdk.scale}}
            ProgressBar {objectName:"skillManagerImportProgress";visible:root.working;Layout.fillWidth:true;indeterminate:true}
            Label {Layout.fillWidth:true;visible:!!root.importPreview.id;text:root.t("确认前不会写入。跳过的条目保持原样；导入不执行 Skill 脚本。","Nothing is written before confirmation. Skipped entries stay unchanged; import does not run skill scripts.");wrapMode:Text.Wrap;font.pixelSize:10*root.sdk.scale;color:root.sdk.colors.muted}
            SmallButton {objectName:"skillManagerImportSubmit";text:root.t("请求导入…","Request import…");enabled:!root.working && root.importReady;onClicked:root.submitImport()}
        }
        ColumnLayout {
            visible:root.route==="install";Layout.fillWidth:true;Layout.fillHeight:true;spacing:12*root.sdk.scale
            Label {Layout.fillWidth:true;text:root.t("输入 npm、Git 或本地包来源。Pi 会安装整个包，可能同时包含扩展、模板和其他 Skill。","Enter an npm, Git or local package source. Pi installs the whole package, which may include extensions, templates and other skills.");wrapMode:Text.Wrap;color:root.sdk.colors.muted}
            Input {id:installSource;objectName:"skillManagerInstallSource";Layout.fillWidth:true;placeholderText:"npm:package-name";enabled:!root.working;onAccepted:root.startInstall()}
            Label {text:root.t("安装范围","Install scope");font.pixelSize:11*root.sdk.scale}
            RowLayout {
                SmallButton {objectName:"skillManagerInstallProject";text:root.t("当前项目","Current project");selected:root.installProject;enabled:!root.working;onClicked:root.installProject=true}
                SmallButton {objectName:"skillManagerInstallGlobal";text:root.t("全局","Global");selected:!root.installProject;enabled:!root.working;onClicked:root.installProject=false}
            }
            Label {Layout.fillWidth:true;text:root.t("提交后由宿主在本面板内确认。安装进度和错误会显示在这里。","The host asks for confirmation inside this panel. Progress and errors appear here.");wrapMode:Text.Wrap;color:root.sdk.colors.muted;font.pixelSize:11*root.sdk.scale}
            ProgressBar {objectName:"skillManagerInstallProgress";visible:root.working;Layout.fillWidth:true;indeterminate:true}
            RowLayout {
                Layout.fillWidth:true
                SmallButton {objectName:"skillManagerInstallSubmit";text:root.t("请求安装…","Request install…");enabled:!root.working && installSource.text.trim()!=="";onClicked:root.startInstall()}
                SmallButton {objectName:"skillManagerInstallCancel";visible:root.jobOperation==="pi.install" && !!root.job;text:root.t("取消安装","Cancel install");enabled:root.canCancel;onClicked:{root.canCancel=false;root.request("pi.cancel",{id:root.job})}}
            }
            Item {Layout.fillHeight:true}
        }
    }
    DropArea {
        id:skillDrop;objectName:"skillManagerDropArea";anchors.fill:parent;enabled:!root.working
        onEntered:drag=>{drag.accepted=drag.hasUrls && root.acceptsImportUrls(drag.urls)}
        onDropped:drop=>{if(!drop.hasUrls || !root.dropLocalUrls(drop.urls)){drop.accepted=false;return}drop.acceptProposedAction()}
    }
    Rectangle {
        objectName:"skillManagerDropPreview";anchors.fill:parent;z:20;visible:skillDrop.containsDrag || root.dropPreview
        color:root.sdk.colors.accentBg;border.color:root.sdk.colors.accent;border.width:2
        Label {anchors.centerIn:parent;width:parent.width-40*root.sdk.scale;horizontalAlignment:Text.AlignHCenter;wrapMode:Text.Wrap;text:root.t("松开以预览本地 Skill\n文件夹、ZIP 或 .skill 文件","Drop to preview local skills\nFolder, ZIP or .skill file");font.pixelSize:16*root.sdk.scale}
    }
    function startInstall() {
        if (!installSource.text.trim() || working) return
        notice=""; noticeError=false
        request("pi.install",{source:installSource.text.trim(),project:installProject})
    }
    // These menus are ordinary clipped children, never application overlays.
    Rectangle {
        objectName:"skillManagerFilterMenu";visible:root.openMenu!=="" && root.route==="main";z:10
        x:12*root.sdk.scale;y:169*root.sdk.scale;width:Math.min(210*root.sdk.scale,root.width-24*root.sdk.scale);height:Math.min(menuBody.implicitHeight+12*root.sdk.scale,root.height-y)
        color:root.sdk.colors.surface;border.color:root.sdk.colors.line;radius:6*root.sdk.scale;clip:true
        Column {
            id:menuBody;x:6*root.sdk.scale;y:6*root.sdk.scale;width:parent.width-12*root.sdk.scale;spacing:2*root.sdk.scale
            Repeater {model:root.openMenu==="source" ? ["all"].concat(root.sourceKeys) : ["all","on","off"]
                delegate:SmallButton {required property var modelData;objectName:"skillManagerFilter_"+modelData;width:parent.width;text:root.openMenu==="source" ? (modelData==="all" ? root.t("全部来源","All sources") : root.sourceLabel(modelData)) : modelData==="all" ? root.t("全部默认状态","All defaults") : modelData==="on" ? root.t("默认启用","Default on") : root.t("默认停用","Default off");onClicked:{if(root.openMenu==="source")root.sourceFilter=modelData;else root.defaultFilter=modelData;root.openMenu=""}}
            }
        }
    }
    Timer {
        interval:350;repeat:true;running:root.sdk.active && !!root.job
        onTriggered:if(!root.polling){root.polling=true;if(!root.request(root.jobOperation.indexOf("pi.")===0 ? "pi.job" : "skills.job",{id:root.job}))root.polling=false}
    }
    Connections {
        target:root.sdk;ignoreUnknownSignals:true
        function onActiveChanged() {root.initialize()}
        function onHostResponse(id,value) {
            const entry=root.pending[id];if(!entry)return
            let next=Object.assign({},root.pending);delete next[id];root.pending=next
            const op=entry.operation
            if(op==="pi.job" || op==="skills.job")root.polling=false
            if(value.ok===false){root.notice=value.error || value.status || root.t("请求失败，请重试。","Request failed; retry.");if(root.route==="import")root.notice=root.importError(root.notice);root.noticeError=true;if(op!=="pi.cancel")root.job="";return}
            if(value.jobId){root.job=value.jobId;root.jobOperation=op;root.canCancel=op==="pi.install";root.noticeError=false;root.notice=root.t("处理中…","Working…");return}
            if(op==="pi.job" || op==="skills.job") {
                if(value.progress){root.notice=value.progress.message || root.notice;root.canCancel=!!value.progress.cancellable}
                const item=(value.jobs || [])[0]
                if(!item)return
                if(["completed","done","failed","cancelled","canceled"].indexOf(item.status)>=0) {
                    const original=root.jobOperation;root.job="";root.jobOperation="";root.canCancel=false
                    root.complete(original,item.result || {},item.status==="completed" || item.status==="done")
                }
            } else if(op!=="pi.cancel")root.complete(op,value.result || value,true)
        }
    }
}
