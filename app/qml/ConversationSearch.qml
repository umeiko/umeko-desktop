import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

FocusScope {
    id: root
    objectName: "conversationSearch"
    property var service: backend.chatSearch
    property bool filtersOpen: false
    property string validationError: ""
    property string searchedContext: ""
    readonly property bool compactHeader: width < Theme.control(235)
    signal backRequested()
    signal dismissRequested()
    signal resultRequested(int row)
    signal newChatRequested()
    function contextKey() { return (backend.config.workspace || "") + (scope.currentIndex === 1 ? "/" + backend.activeSession : "") }
    function focusSearch() {
        if (searchInput.text.trim() && searchedContext !== contextKey()) execute()
        searchInput.forceActiveFocus(); searchInput.selectAll()
    }
    function reset() {
        debounce.stop(); searchInput.clear(); includeInput.clear(); excludeInput.clear()
        sinceInput.clear(); untilInput.clear(); scope.currentIndex = 0; role.currentIndex = 0
        validationError = ""; service.clear(); results.currentIndex = -1
    }
    function execute() {
        debounce.stop(); validationError = ""
        searchedContext = contextKey()
        const since = sinceInput.text.trim() ? Date.parse(sinceInput.text.trim() + "T00:00:00") : 0
        const until = untilInput.text.trim() ? Date.parse(untilInput.text.trim() + "T23:59:59.999") : 0
        if (isNaN(since) || isNaN(until) || since && until && since > until) {
            validationError = I18n.t("请填写有效日期：YYYY-MM-DD"); service.cancel(); return
        }
        results.currentIndex = -1
        service.search(searchInput.text, {caseSensitive: matchCase.checked, wholeWord: wholeWord.checked,
            regex: regex.checked, scope: scope.currentIndex === 1 ? "session" : "project",
            role: role.currentIndex === 1 ? "user" : role.currentIndex === 2 ? "assistant" : "",
            include: includeInput.text, exclude: excludeInput.text, since: since, until: until})
    }
    function activate(row) {
        const item = service.item(row)
        if (!item.kind) return
        if (item.kind === "session") service.toggle(item.sessionId)
        else { debounce.stop(); root.resultRequested(row) }
    }
    function move(delta) {
        if (debounce.running) { execute(); return }
        if (!results.count) return
        results.currentIndex = Math.max(0, Math.min(results.count - 1, results.currentIndex + delta))
        results.positionViewAtIndex(results.currentIndex, ListView.Contain)
    }
    Keys.onEscapePressed: event => { root.dismissRequested(); event.accepted = true }
    Keys.onDownPressed: event => { move(1); event.accepted = true }
    Keys.onUpPressed: event => { move(-1); event.accepted = true }
    Keys.onReturnPressed: event => { activate(results.currentIndex); event.accepted = true }
    Timer { id: debounce; interval: 150; onTriggered: root.execute() }

    component SearchAction: ActionButton {
        implicitWidth: Theme.control(23); implicitHeight: Theme.control(23)
        width: Theme.control(23); height: Theme.control(23); quiet: true
        background: Rectangle { radius: 3; color: parent.down || parent.checked ? Theme.accentBg : parent.hovered ? Theme.hover : "transparent"; border.color: parent.checked ? Theme.accent : "transparent" }
    }
    component SearchField: TextField { font.family: Theme.fontFamily;
        height: Theme.control(25); font.pixelSize: Theme.font(11); color: Theme.ink
        selectByMouse: true; selectionColor: Theme.selectionBg; selectedTextColor: Theme.selectionText
        leftPadding: 6; rightPadding: 6
        background: Rectangle { radius: 2; color: Theme.surface; border.color: parent.activeFocus ? Theme.accent : Theme.line }
        onTextEdited: { results.currentIndex = -1; debounce.restart() }
        onAccepted: root.execute()
    }
    component SearchCombo: ComboBox {
        id: combo; implicitHeight: Theme.control(26); font.pixelSize: Theme.font(10)
        background: Rectangle { radius: 2; color: Theme.surface; border.color: combo.activeFocus ? Theme.accent : Theme.line }
        indicator: Glyph { name: "chevron-down"; width: Theme.icon(12); height: width; x: combo.width-width-6; y: (combo.height-height)/2 }
        contentItem: Text { leftPadding: 7; rightPadding: Theme.icon(18)+5; text: combo.displayText; font: combo.font; color: Theme.ink; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
        delegate: ItemDelegate { required property var modelData; required property int index; width: combo.width; height: Theme.control(28); highlighted: combo.highlightedIndex === index
            contentItem: Text { text: modelData; font: combo.font; color: Theme.ink; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
            background: Rectangle { radius: 2; color: parent.highlighted || parent.hovered ? Theme.accentBg : "transparent" }
        }
        popup: Popup { y: combo.height+2; width: combo.width; padding: 4; implicitHeight: Math.min(contentItem.implicitHeight+8,300)
            background: Rectangle { radius: 4; color: Theme.surface; border.color: Theme.line }
            contentItem: ListView { clip: true; implicitHeight: contentHeight; model: combo.popup.visible ? combo.delegateModel : null; currentIndex: combo.highlightedIndex; ScrollIndicator.vertical: ScrollIndicator {} }
        }
    }
    RowLayout {
        id: header; x: 12; y: 19; width: parent.width - 24; height: Theme.control(30); spacing: 1
        SearchAction { objectName: "searchBackButton"; glyph: "arrow-left"; hint: I18n.t("返回并清空搜索"); onClicked: { root.reset(); root.backRequested() } }
        Text { font.family: Theme.fontFamily; text: I18n.t("搜索"); color: Theme.ink; font.pixelSize: Theme.font(11); Layout.fillWidth: true; elide: Text.ElideRight; leftPadding: 5 }
        SearchAction { objectName: "searchRefreshButton"; glyph: root.service.busy ? "stop" : "refresh-cw"; hint: root.service.busy ? I18n.t("停止搜索") : I18n.t("重新搜索"); onClicked: root.service.busy ? root.service.cancel() : root.execute() }
        SearchAction { objectName: "searchClearButton"; visible: !root.compactHeader; glyph: "x"; hint: I18n.t("清空搜索结果"); onClicked: { root.reset(); root.focusSearch() } }
        SearchAction { objectName: "searchCollapseButton"; visible: !root.compactHeader; glyph: "layers"; hint: I18n.t("展开或折叠全部会话"); onClicked: root.service.collapseAll() }
        SearchAction { objectName: "searchNewChatButton"; visible: !root.compactHeader; glyph: "plus"; hint: I18n.t("新建会话") + " · Ctrl+N"; onClicked: root.newChatRequested() }
        SearchAction { visible: root.compactHeader; glyph: "more"; onClicked: headerMenu.open()
            Menu { id: headerMenu
                MenuItem { text: I18n.t("清空搜索结果"); onTriggered: { root.reset(); root.focusSearch() } }
                MenuItem { text: I18n.t("展开或折叠全部会话"); onTriggered: root.service.collapseAll() }
                MenuItem { text: I18n.t("新建会话") + " · Ctrl+N"; onTriggered: root.newChatRequested() }
            }
        }
    }
    Column {
        id: controls; x: 12; y: header.y + header.height + 6; width: parent.width - 24; spacing: 7
        Item {
            width: parent.width; height: Theme.control(27)
            SearchField {
                id: searchInput; objectName: "conversationSearchInput"; anchors.fill: parent
                placeholderText: I18n.t("搜索"); rightPadding: switches.width + 5
                Keys.onReturnPressed: event => { if (!debounce.running && results.currentIndex >= 0) root.activate(results.currentIndex); else root.execute(); event.accepted = true }
            }
            Row {
                id: switches; anchors.right: parent.right; anchors.rightMargin: 2; anchors.verticalCenter: parent.verticalCenter; spacing: 1
                SearchAction { id: matchCase; objectName: "searchMatchCase"; checkable: true; hint: I18n.t("区分大小写"); onToggled: debounce.restart(); contentItem: Text { font.family: Theme.fontFamily; text: "Aa"; color: Theme.ink; font.pixelSize: Theme.font(11); horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter } }
                SearchAction { id: wholeWord; objectName: "searchWholeWord"; checkable: true; hint: I18n.t("全词匹配"); onToggled: debounce.restart(); contentItem: Text { font.family: Theme.fontFamily; text: "ab"; font.underline: true; color: Theme.ink; font.pixelSize: Theme.font(11); horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter } }
                SearchAction { id: regex; objectName: "searchRegex"; checkable: true; hint: I18n.t("使用正则表达式"); onToggled: debounce.restart(); contentItem: Text { text: ".*"; color: Theme.ink; font.pixelSize: Theme.font(12); font.family: "monospace"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter } }
            }
        }
        RowLayout {
            width: parent.width; spacing: 5
            SearchCombo { id: scope; objectName: "searchScope"; Layout.fillWidth: true; model: [I18n.t("当前项目"),I18n.t("当前会话")]; onActivated: debounce.restart() }
            SearchAction { objectName: "searchFiltersButton"; glyph: root.filtersOpen ? "chevron-up" : "more"; checked: root.filtersOpen; hint: I18n.t("搜索筛选"); onClicked: root.filtersOpen = !root.filtersOpen }
        }
        Column {
            width: parent.width; spacing: 6; visible: root.filtersOpen
            Text { font.family: Theme.fontFamily; text: I18n.t("包含的会话"); color: Theme.muted; font.pixelSize: Theme.font(10) }
            SearchField { id: includeInput; objectName: "searchInclude"; width: parent.width; placeholderText: I18n.t("会话标题，逗号分隔") }
            Text { font.family: Theme.fontFamily; text: I18n.t("排除的会话"); color: Theme.muted; font.pixelSize: Theme.font(10) }
            SearchField { id: excludeInput; objectName: "searchExclude"; width: parent.width; placeholderText: I18n.t("会话标题，逗号分隔") }
            SearchCombo { id: role; objectName: "searchRole"; width: parent.width; model: [I18n.t("所有角色"),I18n.t("用户"),I18n.t("助手")]; onActivated: debounce.restart() }
            Row { width: parent.width; spacing: 5
                SearchField { id: sinceInput; objectName: "searchSince"; width: (parent.width-5)/2; placeholderText: I18n.t("开始日期") }
                SearchField { id: untilInput; objectName: "searchUntil"; width: (parent.width-5)/2; placeholderText: I18n.t("结束日期") }
            }
        }
        Row {
            width: parent.width; spacing: 6; visible: root.service.busy
            ActivitySpinner { width: Theme.icon(13); height: Theme.icon(13); anchors.verticalCenter: parent.verticalCenter }
            Text { font.family: Theme.fontFamily; text: root.service.phase === "preparing" ? I18n.t("正在读取会话…") : I18n.t("正在搜索…"); color: Theme.muted; font.pixelSize: Theme.font(10) }
        }
        Text { font.family: Theme.fontFamily;
            width: parent.width; wrapMode: Text.Wrap; color: root.validationError || root.service.error ? Theme.danger : Theme.muted; font.pixelSize: Theme.font(10)
            text: root.validationError || I18n.t(root.service.error) || (root.service.phase === "stopped" ? I18n.t("搜索已停止") : root.service.count > 0 ? root.service.count + " " + I18n.t("个匹配，来自") + " " + root.service.conversationCount + " " + I18n.t("个会话") : !root.service.busy && root.service.query ? I18n.t("未找到匹配结果") : I18n.t("在当前项目的聊天正文中搜索"))
        }
        Text { font.family: Theme.fontFamily; width: parent.width; wrapMode: Text.Wrap; visible: root.service.limitHit; text: I18n.t("已达到 20,000 条结果上限，请缩小搜索范围"); color: Theme.muted; font.pixelSize: Theme.font(10) }
        Text { font.family: Theme.fontFamily; width: parent.width; wrapMode: Text.Wrap; visible: root.service.skipped > 0; text: I18n.t("部分会话暂时无法读取，请刷新重试"); color: Theme.muted; font.pixelSize: Theme.font(10) }
    }
    ListView {
        id: results; objectName: "conversationSearchResults"; x: 5; width: parent.width - 10
        anchors.top: controls.bottom; anchors.topMargin: 9; anchors.bottom: parent.bottom; anchors.bottomMargin: 7
        model: root.service; clip: true; currentIndex: -1; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        delegate: Item {
            id: resultRow; required property var modelData; required property int index
            objectName: "searchResult_" + index
            readonly property bool group: modelData.kind === "session"
            width: results.width; height: Theme.control(group ? 28 : 39)
            Rectangle { anchors.fill: parent; radius: 2; color: results.currentIndex === resultRow.index ? Theme.accentBg : hover.hovered ? Theme.hover : "transparent" }
            HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: { results.currentIndex = resultRow.index; root.activate(resultRow.index) } }
            Glyph { x: Theme.control(group ? 7 : 20); y: group ? (parent.height-height)/2 : Theme.control(4); width: Theme.icon(13); height: Theme.icon(13); name: group ? (modelData.collapsed ? "chevron-right" : "chevron-down") : modelData.role === "user" ? "user" : "chat" }
            Text { font.family: Theme.fontFamily;
                x: Theme.control(resultRow.group ? 27 : 39); y: resultRow.group ? (parent.height-height)/2 : Theme.control(3)
                width: Math.max(0,parent.width-x-Theme.control(resultRow.group ? 32 : 8)); elide: Text.ElideRight
                font.pixelSize: Theme.font(11); color: Theme.ink; textFormat: resultRow.group ? Text.PlainText : Text.RichText
                clip: true
                function escaped(value) { return String(value || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/\"/g,"&quot;") }
                text: resultRow.group ? modelData.title : escaped(modelData.before) + "<b style='background-color:" + (Theme.dark ? "#714713" : "#ffe0a1") + ";color:" + (Theme.dark ? "#ffffff" : "#342300") + "'>" + escaped(modelData.hit) + "</b>" + escaped(modelData.after)
            }
            Text { visible: resultRow.group; anchors.right: parent.right; anchors.rightMargin: 9; anchors.verticalCenter: parent.verticalCenter; text: modelData.count || ""; color: Theme.muted; font.pixelSize: Theme.font(10) }
            Text { visible: !resultRow.group; x: Theme.control(39); y: Theme.control(21); width: parent.width-x-8; elide: Text.ElideRight; color: Theme.muted; font.pixelSize: Theme.font(9)
                text: (modelData.role === "user" ? I18n.t("用户") : I18n.t("助手")) + " · " + (modelData.timestamp ? Qt.formatDateTime(new Date(modelData.timestamp),"MM-dd hh:mm") : "") + " · " + I18n.t("行") + " " + (modelData.line || 1) }
            HoverTip { active: hover.hovered; text: resultRow.group ? modelData.title : (modelData.before || "") + (modelData.hit || "") + (modelData.after || "") }
        }
    }
}
