import QtQuick
import QtQuick.Controls
import "markdown.js" as Markdown

Item {
    id: root
    objectName: "chatSelection"
    property var view
    property var dataSource: backend
    property var editors: []
    property var interactions: []
    readonly property var hoveredTarget: {
        const scroll = view ? view.contentY : 0
        return hovering ? interactionAt(pointer.x, pointer.y) : null
    }
    function attachInteraction(item) { interactions = interactions.concat([item]) }
    function detachInteraction(item) { interactions = interactions.filter(value => value !== item) }
    function interactionAt(x, y) {
        let found = null, priority = -Infinity
        for (const item of interactions) {
            if (!item.visible || !item.enabled || item.width <= 0 || item.height <= 0) continue
            const p = mapToItem(item, x, y)
            if (p.x >= 0 && p.y >= 0 && p.x <= item.width && p.y <= item.height && item.interactionPriority >= priority) {
                found = item; priority = item.interactionPriority
            }
        }
        return found
    }
    property var anchor: null
    property var cursor: null
    property bool dragging: false
    property double lastScrollTime: 0
    property point pointer: Qt.point(0, 0)
    readonly property bool hovering: hoverTracker.hovered
    // Passive tracking keeps hover current when the selection overlay passes
    // a click through to a card or button underneath it.
    HoverHandler {
        id: hoverTracker; objectName: "chatHoverTracker"
        blocking: false
        onPointChanged: if (hovered) root.pointer = point.position
        onHoveredChanged: if (hovered) root.pointer = point.position
    }
    property point pressPoint: Qt.point(0, 0)
    property bool pointerMoved: false
    property int clickCount: 0
    property double lastClickTime: 0
    property point lastClickPoint: Qt.point(0, 0)
    property string lastClickEditor: ""
    property int selectionUnit: 1
    property var unitAnchor: null
    readonly property bool hasSelection: anchor !== null && cursor !== null && compare(anchor, cursor) !== 0
    property var expandedDetails: ({})
    function compare(a, b) { return a.row - b.row || a.block - b.block || a.offset - b.offset }
    function attach(editor) { editors.push(editor); refreshSoon() }
    function detach(editor) { editors = editors.filter(item => item !== editor) }
    function refreshSoon() { refreshTimer.restart() }
    function hideDetails(row, first, count) {
        for (let i = 0; i < count; i++) expandedDetails[row + ":" + (first + i)] = false
        refreshSoon()
    }
    function clear() {
        dragging = false; anchor = null; cursor = null; expandedDetails = ({})
        clickCount = 0; unitAnchor = null; selectionUnit = 1; pointerMoved = false
        for (const editor of editors) editor.deselect()
    }
    function refresh() {
        const start = hasSelection && compare(anchor, cursor) < 0 ? anchor : cursor
        const end = hasSelection && compare(anchor, cursor) < 0 ? cursor : anchor
        for (const editor of editors) {
            const key = editor.messageIndex + ":" + editor.blockIndex
            if (editor.conditionalSelection) expandedDetails[key] = editor.visible
            if (!hasSelection) { if (editor.selectionStart !== editor.selectionEnd) editor.deselect(); continue }
            const first = {row:editor.messageIndex, block:editor.blockIndex, offset:0}
            const last = {row:first.row, block:first.block, offset:editor.length}
            if (compare(last, start) <= 0 || compare(first, end) >= 0) { if (editor.selectionStart !== editor.selectionEnd) editor.deselect() }
            else {
                const from = Math.max(0, compare(first, start) < 0 ? start.offset : 0), to = Math.min(editor.length, compare(last, end) > 0 ? end.offset : editor.length)
                if (editor.selectionStart !== from || editor.selectionEnd !== to) editor.select(from, to)
            }
        }
    }
    function pick(x, y, nearest) {
        let best = null, distance = Infinity
        for (const editor of editors) {
            if (!editor.visible || editor.messageIndex < 0 || editor.height <= 0) continue
            const point = editor.mapToItem(root, 0, 0)
            if (point.y + editor.height < 0 || point.y > height) continue
            const inside = x >= point.x && x <= point.x + editor.width && y >= point.y && y <= point.y + editor.height
            if (!nearest && !inside) continue
            const gap = Math.max(point.y - y, 0, y - point.y - editor.height)
            if (gap < distance) { best = editor; distance = gap }
        }
        return best
    }
    function position(editor, x, y) {
        const p = root.mapToItem(editor, x, y)
        return {row:editor.messageIndex, block:editor.blockIndex, offset:editor.positionAt(Math.max(0, Math.min(editor.width, p.x)), Math.max(0, Math.min(editor.height - 1, p.y)))}
    }
    function extend() {
        const editor = pick(pointer.x, Math.max(0, Math.min(height - 1, pointer.y)), true)
        if (editor) {
            const target = position(editor, pointer.x, Math.max(0, Math.min(height - 1, pointer.y)))
            if (unitAnchor && selectionUnit > 1) {
                const bounds = unitBounds(editor, target.offset, selectionUnit)
                if (compare(bounds.start, unitAnchor.start) < 0) { anchor = unitAnchor.end; cursor = bounds.start }
                else { anchor = unitAnchor.start; cursor = bounds.end }
            } else cursor = target
            refresh()
        }
    }
    function unitBounds(editor, offset, unit) {
        let start = offset, end = offset
        if (unit === 2) {
            editor.cursorPosition = offset; editor.selectWord()
            start = editor.selectionStart; end = editor.selectionEnd
        } else {
            const text = editor.getText(0, editor.length)
            while (start > 0 && !/[\n\r\u2029]/.test(text[start - 1])) start--
            while (end < text.length && !/[\n\r\u2029]/.test(text[end])) end++
        }
        return {start:{row:editor.messageIndex,block:editor.blockIndex,offset:start}, end:{row:editor.messageIndex,block:editor.blockIndex,offset:end}}
    }
    function selectUnit(editor, offset, unit) {
        selectionUnit = unit
        unitAnchor = unitBounds(editor, offset, unit)
        anchor = unitAnchor.start; cursor = unitAnchor.end; refresh()
    }
    function plain(text, markdown, row, block) {
        for (const editor of editors) {
            if (editor.visible && editor.messageIndex === row && editor.blockIndex === block)
                return editor.getText(0, editor.length)
        }
        renderer.textFormat = markdown ? TextEdit.MarkdownText : TextEdit.PlainText
        renderer.text = markdown ? Markdown.forQt(text) : text
        return renderer.getText(0, renderer.length)
    }
    function selectedText() {
        if (!hasSelection) return ""
        const start = compare(anchor, cursor) < 0 ? anchor : cursor
        const end = compare(anchor, cursor) < 0 ? cursor : anchor
        const count = dataSource.messageCount, pieces = []
        for (let row = start.row; row <= end.row && row < count; row++) {
            const message = dataSource.displayMessage(row), segments = Markdown.selectionSegments(message, row, expandedDetails)
            for (const segment of segments) {
                const text = plain(segment.text, segment.markdown, row, segment.block)
                const first = {row:row,block:segment.block,offset:0}, last = {row:row,block:segment.block,offset:text.length}
                if (compare(last, start) <= 0 || compare(first, end) >= 0) continue
                let selected = text.slice(compare(first, start) < 0 ? start.offset : 0, compare(last, end) > 0 ? end.offset : text.length)
                if (segment.copyPrefix && (start.row < row || start.block < segment.block)) {
                    const prefix = plain(segment.copyPrefix, true, -2147483647, -2147483647)
                    if (selected.startsWith(prefix)) selected = selected.slice(prefix.length)
                }
                if (segment.copyJoin && pieces.length) pieces[pieces.length - 1] += (segment.copyJoin === "direct" || pieces[pieces.length - 1].endsWith("\n") ? "" : "\n") + selected
                else pieces.push(selected)
            }
        }
        return pieces.join("\n\n").replace(/\u2029|\u2028/g, "\n")
    }
    function copy() {
        if (!hasSelection) return
        if (dataSource.messageModel.paged || Math.abs(anchor.row - cursor.row) > 100)
            dataSource.copyChatSelection(JSON.stringify({anchor:anchor, cursor:cursor, expanded:expandedDetails}))
        else backend.copy(selectedText())
    }
    function selectAll() {
        const count = dataSource.messageCount
        if (!count) return
        anchor = {row:0,block:-100000,offset:0}
        cursor = {row:count - 1,block:2147483647,offset:0}
        refresh(); forceActiveFocus()
    }
    Keys.onPressed: event => {
        if (event.key === Qt.Key_Escape) { clear(); event.accepted = true }
    }
    onVisibleChanged: if (!visible) clear()
    onDraggingChanged: lastScrollTime = Date.now()
    function autoScroll() {
        if (!dragging || !pointerMoved) return
        const now = Date.now(), elapsed = Math.min(100, Math.max(16, now - lastScrollTime))
        lastScrollTime = now
        const edge = 42
        const speed = pointer.y < edge ? -Math.min(28, (edge - pointer.y) * 0.55) : pointer.y > height - edge ? Math.min(28, (pointer.y - height + edge) * 0.55) : 0
        if (speed) { view.scrollBy(speed * elapsed / 16); Qt.callLater(root.extend) }
    }
    Connections {
        target: backend
        function onViewChanged() { root.clear() }
    }
    Timer { interval: 16; repeat: true; running: root.dragging; onTriggered: Qt.callLater(root.autoScroll) }
    Timer { id: refreshTimer; interval: 0; onTriggered: root.refresh() }
    TextEdit { font.family: Theme.fontFamily; id: renderer; visible: false; readOnly: true }
    FloatingMenu {
        id: selectionMenu; objectName: "selectionContextMenu"
        ContextAction { objectName: "copySelectedText"; text: I18n.t("复制"); glyph: "copy"; enabled: root.hasSelection; onTriggered: root.copy() }
        ContextAction { objectName: "selectAllChatText"; text: I18n.t("全选"); onTriggered: root.selectAll() }
        onClosed: if (root.visible) root.forceActiveFocus()
    }
    MouseArea {
        id: selectionArea
        anchors.fill: parent; anchors.rightMargin: 14
        objectName: "chatPointerArea"
        acceptedButtons: Qt.LeftButton | Qt.RightButton; preventStealing: true; hoverEnabled: true
        cursorShape: root.hoveredTarget ? Qt.PointingHandCursor : root.pick(root.pointer.x, root.pointer.y, false) ? Qt.IBeamCursor : Qt.ArrowCursor
        onPressed: event => {
            root.pointer = Qt.point(event.x, event.y)
            if (root.interactionAt(event.x, event.y)) { if (event.button === Qt.LeftButton) root.clear(); event.accepted = false; return }
            const editor = root.pick(event.x, event.y, false)
            if (!editor) { if (event.button === Qt.LeftButton) root.clear(); event.accepted = false; return }
            if (event.button === Qt.RightButton) {
                if (!root.hasSelection) root.selectUnit(editor, root.position(editor, event.x, event.y).offset, 2)
                root.forceActiveFocus(); return
            }
            const now = Date.now(), key = editor.messageIndex + ":" + editor.blockIndex
            const close = Math.abs(event.x - root.lastClickPoint.x) <= 5 && Math.abs(event.y - root.lastClickPoint.y) <= 5
            root.clickCount = !(event.modifiers & Qt.ShiftModifier) && key === root.lastClickEditor && close && now - root.lastClickTime <= Qt.styleHints.mouseDoubleClickInterval ? Math.min(3, root.clickCount + 1) : 1
            root.lastClickTime = now; root.lastClickPoint = Qt.point(event.x, event.y); root.lastClickEditor = key
            root.pressPoint = Qt.point(event.x, event.y); root.pointerMoved = false; root.unitAnchor = null; root.selectionUnit = 1
            const position = root.position(editor, event.x, event.y)
            if (root.clickCount > 1) root.selectUnit(editor, position.offset, root.clickCount)
            else {
                if (!(event.modifiers & Qt.ShiftModifier) || !root.anchor) root.anchor = position
                root.cursor = position
            }
            root.pointer = Qt.point(event.x, event.y); root.dragging = true
            root.view.beginBrowsing(); root.forceActiveFocus(); root.refresh()
        }
        onClicked: event => { if (event.button === Qt.RightButton) selectionMenu.popup(event.x, event.y) }
        onPositionChanged: event => {
            root.pointer = Qt.point(event.x, event.y)
            if (pressed && root.dragging) {
                if (Math.abs(event.x - root.pressPoint.x) > 2 || Math.abs(event.y - root.pressPoint.y) > 2) root.pointerMoved = true
                if (root.pointerMoved) Qt.callLater(root.extend)
            }
        }
        onReleased: { if (root.dragging && root.pointerMoved) root.extend(); root.dragging = false }
        onCanceled: root.dragging = false
        onDoubleClicked: event => {
            const editor = root.pick(event.x, event.y, false)
            if (!editor) return
            root.clickCount = Math.max(2, root.clickCount)
            root.lastClickTime = Date.now(); root.lastClickPoint = Qt.point(event.x, event.y); root.lastClickEditor = editor.messageIndex + ":" + editor.blockIndex
            root.selectUnit(editor, root.position(editor, event.x, event.y).offset, root.clickCount)
        }
        onWheel: event => {
            const delta = event.pixelDelta.y || event.angleDelta.y / 120 * 60
            if (delta) { root.view.scrollBy(-delta); if (root.dragging) root.extend() }
            event.accepted = true
        }
    }
}
