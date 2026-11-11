import QtQuick
import QtQuick.Controls

Item {
    id: pane
    property var controller: backend
    property string viewName: "conversation"
    property string messagePrefix: ""
    property string assistantName: "umeko"
    property url portrait: ""
    property url replyPortrait: ""
    property int highlightRow: window ? window.searchHighlightRow : -1
    required property var window
    required property var messageModel
    required property string viewKey
    required property var requestInspector
    property bool current: false
    property bool blocked: false
    property bool initialized: false
    property bool layoutDirty: false
    property bool released: false
    property bool busy: false
    property bool running: false
    property string toolStatus: ""
    property var turnStatus: ({})
    property alias view: conversation
    property alias selection: chatSelection
    visible: current
    enabled: current
    function refreshState() {
        if (!current)
            return;
        busy = pane.controller.busy;
        running = pane.controller.running;
        toolStatus = pane.controller.toolStatus;
        turnStatus = pane.controller.turnStatus;
    }
    function activate() {
        current = true;
        refreshState();
        if (!initialized || layoutDirty || conversation.restoring) {
            initialized = true;
            layoutDirty = false;
            conversation.restoreViewport();
        } else {
            conversation.requestVisibleRange();
        }
    }
    function deactivate() {
        conversation.saveViewport();
        current = false;
        tailTimer.stop();
        restoreTimer.stop();
        pagePrefetch.stop();
        chatSelection.clear();
    }
    function release() {
        deactivate();
        released = true;
        conversation.model = null;
    }
    ListView {
        id: conversation
        objectName: pane.current ? pane.viewName : "cachedConversation_" + pane.viewKey
        property bool followTail: true
        property bool restoring: false
        property real restoreOffset: -1
        property int restoreIndex: -1
        property int restoreAttempts: 0
        // Grouped loading. ChatModel splits rows into groups of about
        // groupScreens viewport heights. Rows of the on-screen groups and of
        // keepGroups groups on each side get bodies; farther groups release
        // theirs together. A group is shown only after all of its loaded rows
        // are laid out, its height change is absorbed by keepAnchor() in one
        // step, and scrolling never moves into rows that are not shown yet.
        property real groupScreens: 2.5
        property int keepGroups: 1
        property int activeFirst: 0
        property int activeLast: -1
        property int activeEnd: 0
        property real reach: height * 0.25
        property bool anchoring: false
        property int blockedScrolls: 0
        property int urgentFirst: -1
        property int urgentLast: -2
        property bool forcing: false
        readonly property real groupPixels: Math.max(320, height * groupScreens)
        onGroupPixelsChanged: if (pane.messageModel) pane.messageModel.setGroupHeight(groupPixels)
        Component.onCompleted: if (pane.messageModel) pane.messageModel.setGroupHeight(groupPixels)
        readonly property string layoutKey: width + "/" + Theme.fontScale + "/" + Theme.proseLineHeight + "/" + window.font.family
        onLayoutKeyChanged: {
            pane.messageModel.setLayout(layoutKey);
            if (!pane.current)
                pane.layoutDirty = true;
            else if (!followTail && count)
                restoreViewport();
        }
        function beginBrowsing() {
            tailTimer.stop();
            restoreTimer.stop();
            restoring = false;
            cancelFlick();
            followTail = false;
        }
        function polishBody(item) {
            for (const child of item.children)
                polishBody(child);
            item.ensurePolished();
        }
        function releaseGroups() {
            // Navigation positions by row; every row it instantiates may load.
            reach = height * 0.25;
            activeFirst = 0;
            activeLast = -1;
        }
        function slotMap() {
            const slots = {};
            let first = -1, last = -1;
            for (const item of contentItem.children) {
                if (item.messageSlot !== true)
                    continue;
                slots[item.index] = item;
                if (first < 0 || item.index < first)
                    first = item.index;
                if (item.index > last)
                    last = item.index;
            }
            return {slots: slots, first: first, last: last};
        }
        function visibleRows(slots) {
            const top = contentY, bottom = top + height;
            let first = -1, last = -1;
            for (const key in slots) {
                const item = slots[key];
                if (item.y + item.height <= top || item.y >= bottom)
                    continue;
                if (first < 0 || item.index < first)
                    first = item.index;
                if (item.index > last)
                    last = item.index;
            }
            return {first: first, last: last};
        }
        function keepAnchor(change) {
            // Keep the first shown on-screen row where it is while rows above
            // it change height. Following the tail and restoration position
            // the view themselves.
            if (anchoring || followTail || restoring || !pane.current) {
                change();
                return;
            }
            const top = contentY;
            let anchor = null;
            for (const item of contentItem.children) {
                if (item.messageSlot === true && item.shown && item.y + item.height > top && item.y < top + height
                        && (!anchor || item.index < anchor.index))
                    anchor = item;
            }
            if (!anchor) {
                change();
                return;
            }
            const row = anchor.index, before = anchor.y - top;
            anchoring = true;
            change();
            forceLayout();
            const item = itemAtIndex(row);
            if (item) {
                const shift = item.y - contentY - before;
                if (Math.abs(shift) > 0.5)
                    contentY += shift;
            } else {
                positionViewAtIndex(row, ListView.Beginning);
                contentY -= before;
            }
            anchoring = false;
        }
        function settleGroups(above) {
            // Show a group when every instantiated row in it has loaded. Rows
            // beyond the instantiated range are off screen and join later.
            // A group wholly above the screen changes the rows' heights above
            // the reader, so it waits, laid out, until scrolling reaches it
            // (above = true) and is then inserted with one position correction.
            // A cached view that was shown and is now hidden keeps its groups
            // as they are: keepAnchor() does not correct a hidden view, so a
            // group above the reader that finished loading in the background
            // would move the reading position. Activation settles them with
            // the anchor. A view still being created has no position yet.
            if (!pane.messageModel || !count || (!pane.current && pane.initialized))
                return;
            const model = pane.messageModel, map = slotMap(), slots = map.slots;
            const top = above || followTail || restoring ? -1 : visibleRows(slots).first;
            // While the view follows the latest message, the last group keeps
            // receiving rows as the reply streams, so on a slow machine it is
            // rarely complete: waiting for it would hide the streaming row and
            // keep the restore after a reset from finishing. Its rows are shown
            // one by one as they load; the view is positioned at the end, so
            // nothing the reader is looking at moves.
            const tail = followTail ? model.groupOf(count - 1) : -1;
            const checked = {}, ready = [];
            for (let row = map.first; map.first >= 0 && row <= map.last; row++) {
                const item = slots[row];
                if (!item || item.shown || !item.bodyLoaded)
                    continue;
                const group = model.groupOf(row);
                if (group === tail) {
                    ready.push(item);
                    continue;
                }
                if (checked[group])
                    continue;
                checked[group] = true;
                const first = Math.max(map.first, model.groupFirst(group));
                const last = Math.min(map.last, model.groupLast(group));
                if (last < top)
                    continue;
                const rows = [];
                let complete = true;
                for (let other = first; other <= last && complete; other++) {
                    const slot = slots[other];
                    complete = !!slot && slot.bodyLoaded;
                    if (complete && !slot.shown)
                        rows.push(slot);
                }
                if (complete)
                    ready.push(...rows);
            }
            if (!ready.length)
                return;
            // Loader.Ready precedes deferred TextEdit/Column polish; show the
            // final sizes, not intermediate ones.
            for (const item of ready)
                polishBody(item);
            keepAnchor(() => {
                for (const item of ready)
                    item.shown = true;
            });
            scheduleRange();
        }
        function updateGroups() {
            if (!pane.current || !count || !pane.messageModel)
                return;
            const model = pane.messageModel, map = slotMap(), rows = visibleRows(map.slots);
            if (rows.first < 0)
                return;
            // Neighbouring groups load only after the screen itself is shown,
            // so prefetching never delays the first screen after open or a jump.
            let screenShown = true;
            for (let row = rows.first; row <= rows.last && screenShown; row++)
                screenShown = !!map.slots[row] && map.slots[row].shown;
            const keep = screenShown ? keepGroups : 0;
            const groups = model.groupCount();
            const g0 = model.groupOf(rows.first), g1 = model.groupOf(rows.last);
            const first = model.groupFirst(Math.max(0, g0 - keep));
            const last = model.groupLast(Math.min(groups - 1, g1 + keep));
            if (first !== activeFirst || last !== activeLast)
                keepAnchor(() => {
                    activeEnd = count - 1;
                    activeFirst = first;
                    activeLast = last;
                });
            if (!restoring && screenShown) {
                // Instantiate every row of the kept groups, by estimated extent.
                const top = map.slots[rows.first], bottom = map.slots[rows.last];
                const above = model.spanHeight(first, rows.first - 1) + Math.max(0, contentY - top.y);
                const below = model.spanHeight(rows.last + 1, last) + Math.max(0, bottom.y + bottom.height - contentY - height);
                reach = Math.ceil(Math.min(40000, Math.max(above, below) + height * 0.25) / 256) * 256;
            }
            if (model.paged)
                model.requestGroups(rows.first, rows.last, keep);
            settleGroups();
        }
        function shownLimits() {
            // contentY may move within [upper, lower - height] without
            // showing a row that is not laid out yet.
            // above/below: the first row that is not shown on each side.
            const map = slotMap(), slots = map.slots, rows = visibleRows(slots);
            if (rows.first < 0)
                return {upper: -Infinity, lower: Infinity, above: -1, below: -1};
            let upper = contentY, lower = contentY + height, above = rows.first, below = rows.last;
            if (slots[rows.first].shown) {
                let row = rows.first;
                while (row > 0 && slots[row - 1] && slots[row - 1].shown)
                    row--;
                upper = row === 0 ? -Infinity : slots[row].y;
                above = row - 1;
            }
            if (slots[rows.last].shown) {
                let row = rows.last;
                while (row < count - 1 && slots[row + 1] && slots[row + 1].shown)
                    row++;
                lower = row === count - 1 ? Infinity : slots[row].y + slots[row].height;
                below = row === count - 1 ? -1 : row + 1;
            }
            return {upper: upper, lower: lower, above: above, below: below};
        }
        function finishGroup(row) {
            // The reader reached a group that is still loading in the
            // background: complete its remaining bodies now (Loader finishes
            // an asynchronous load synchronously when asynchronous turns off).
            if (row < 0 || !pane.messageModel)
                return;
            const group = pane.messageModel.groupOf(row);
            forcing = true;
            urgentFirst = pane.messageModel.groupFirst(group);
            urgentLast = pane.messageModel.groupLast(group);
            urgentLast = -2;
            urgentFirst = -1;
            forcing = false;
            settleGroups(true);
        }
        function jumpToMessage(row) {
            if (row < 0 || row >= count)
                return;
            beginBrowsing();
            chatSelection.clear();
            releaseGroups();
            restoring = true;
            restoreIndex = row;
            restoreOffset = 0;
            restoreAttempts = 0;
            restoreTimer.restart();
        }
        function jumpToLatest() {
            beginBrowsing();
            chatSelection.clear();
            releaseGroups();
            followTail = true;
            restoring = true;
            restoreIndex = -1;
            restoreOffset = 0;
            restoreAttempts = 0;
            pane.messageModel.requestRange(Math.max(0, count - 4), count - 1);
            restoreTimer.restart();
        }
        function scrollBy(delta) {
            beginBrowsing();
            const top = originY;
            const bottom = Math.max(top, originY + contentHeight - height);
            let target = Math.max(top, Math.min(bottom, contentY + delta));
            // Never scroll into rows that are not shown yet. A group still
            // loading is finished first; one whose data has not arrived makes
            // the view wait at its edge. The counter only lets a row that
            // never becomes ready stop blocking input.
            let limits = shownLimits();
            const clamp = () => Math.max(Math.min(contentY, limits.upper), Math.min(target, Math.max(contentY, limits.lower - height)));
            let allowed = clamp();
            if (Math.abs(allowed - target) > 0.5) {
                finishGroup(delta < 0 ? limits.above : limits.below);
                // Showing the group may have kept the anchor by moving contentY.
                target = Math.max(originY, Math.min(Math.max(originY, originY + contentHeight - height), contentY + delta));
                limits = shownLimits();
                allowed = clamp();
            }
            if (Math.abs(allowed - target) > 0.5 && blockedScrolls < 30) {
                target = allowed;
                blockedScrolls++;
                scheduleRange();
            } else {
                blockedScrolls = 0;
            }
            contentY = target;
            if (atYEnd && !chatSelection.dragging)
                followTail = true;
        }
        function saveViewport() {
            if (restoring || !pane.current)
                return;
            let index = indexAt(1, contentY + 1);
            if (index < 0)
                index = indexAt(1, contentY + spacing + 2);
            const item = index >= 0 ? itemAtIndex(index) : null;
            pane.controller.saveViewport(index, item ? contentY - item.y : 0, followTail);
        }
        function restoreViewport() {
            releaseGroups();
            restoring = true;
            tailTimer.stop();
            followTail = pane.controller.followTail;
            restoreOffset = pane.controller.scrollPosition;
            restoreIndex = pane.controller.scrollAnchor;
            restoreAttempts = 0;
            if (!count && !pane.controller.loading && !pane.controller.messageCount) {
                restoreTimer.stop(); restoring = false; return;
            }
            restoreTimer.restart();
        }
        acceptedButtons: Qt.NoButton
        visible: count > 0
        anchors.fill: parent
        clip: true
        spacing: 27
        model: pane.messageModel
        cacheBuffer: Math.max(0, reach)
        currentIndex: -1
        // A hidden attached ScrollBar still writes contentY when its
        // size changes. Variable-height rows must have one scroll owner.
        onFollowTailChanged: saveViewport()
        onContentYChanged: {
            saveViewport();
            scheduleRange();
        }
        function scheduleRange() {
            if (pane.current && !pagePrefetch.running)
                pagePrefetch.start();
        }
        function requestVisibleRange() {
            if (!pane.current || !count)
                return;
            forceLayout();
            // indexAt() returns -1 in spacing and outside instantiated delegates;
            // updateGroups() inspects the intersecting slots so a gap cannot
            // starve rows.
            if (visibleRows(slotMap().slots).first < 0)
                scheduleRange();
            else
                updateGroups();
        }
        Timer {
            id: pagePrefetch
            interval: 16
            onTriggered: {
                if (!conversation.restoring)
                    conversation.requestVisibleRange();
            }
        }
        onContentHeightChanged: {
            scheduleRange();
            if (pane.current && followTail && !restoring)
                tailTimer.restart();
        }
        onCountChanged: {
            scheduleRange();
            if (pane.current && followTail && !restoring)
                tailTimer.restart();
        }
        onMovementEnded: scheduleRange()
        Timer {
            id: tailTimer
            interval: 0
            onTriggered: {
                if (pane.current && conversation.followTail && !conversation.restoring)
                    conversation.positionViewAtEnd();
            }
        }
        Timer {
            id: restoreTimer
            interval: 16
            repeat: true
            onTriggered: {
                if (!pane.current) {
                    stop();
                    return;
                }
                conversation.forceLayout();
                conversation.restoreAttempts++;
                if (conversation.followTail || conversation.restoreIndex < 0) {
                    conversation.positionViewAtEnd();
                    pane.messageModel.requestRange(Math.max(0, conversation.count - 4), conversation.count - 1);
                    const tail = conversation.itemAtIndex(conversation.count - 1);
                    if (conversation.count && (!tail || !tail.bodyReady) && conversation.restoreAttempts < 200)
                        return;
                    // Finish with a complete first screen: every row on it shown.
                    const top = conversation.contentY, bottom = top + conversation.height;
                    for (const row of conversation.contentItem.children) {
                        if (row.messageSlot === true && row.y + row.height > top && row.y < bottom
                                && !row.shown && conversation.restoreAttempts < 200)
                            return;
                    }
                } else {
                    const index = Math.min(conversation.restoreIndex, conversation.count - 1);
                    pane.messageModel.requestRange(index, index + 3);
                    if (conversation.restoreAttempts === 1) {
                        conversation.positionViewAtIndex(index, ListView.Beginning);
                        conversation.forceLayout();
                        return;
                    }
                    if (!pane.messageModel.isReady(index) && conversation.restoreAttempts < 200)
                        return;
                    const item = conversation.itemAtIndex(index);
                    if ((!item || !item.bodyReady) && conversation.restoreAttempts < 200)
                        return;
                    // Nearby rows are loaded asynchronously too. In particular,
                    // a short target near the tail can be clamped against a
                    // following placeholder before its real height is known.
                    for (let row = index + 1; row < Math.min(conversation.count, index + 4); row++) {
                        const nearby = conversation.itemAtIndex(row);
                        if ((!pane.messageModel.isReady(row) || (nearby && !nearby.bodyReady))
                                && conversation.restoreAttempts < 200)
                            return;
                    }
                    const bottom = conversation.contentY + conversation.height;
                    const last = Math.min(index + 3, conversation.count - 1);
                    for (const row of conversation.contentItem.children) {
                        if (row.messageSlot !== true || row.index < index || row.index > last ||
                                row.y + row.height <= conversation.contentY || row.y >= bottom)
                            continue;
                        if (!row.bodyReady) {
                            if (conversation.restoreAttempts < 200)
                                return;
                        } else {
                            // Loader.Ready precedes deferred TextEdit/Column
                            // polish; consume their actual sizes before clamping.
                            conversation.polishBody(row);
                        }
                    }
                    conversation.forceLayout();
                    if (item) {
                        conversation.positionViewAtIndex(index, ListView.Beginning);
                        if (!conversation.atYEnd)
                            conversation.contentY += Math.min(conversation.restoreOffset, item.height - 1);
                    }
                    conversation.forceLayout();
                    if (conversation.restoreAttempts < 200) {
                        const bottom = conversation.contentY + conversation.height;
                        const last = Math.min(index + 3, conversation.count - 1);
                        // A pending visible neighbour can still change the end
                        // clamp after the target body itself has become ready.
                        for (const row of conversation.contentItem.children) {
                            if (row.messageSlot === true && row.index >= index && row.index <= last &&
                                    row.y + row.height > conversation.contentY && row.y < bottom && !row.bodyReady)
                                return;
                        }
                    }
                }
                if (conversation.restoreAttempts >= 2) {
                    stop();
                    conversation.restoring = false;
                    conversation.saveViewport();
                    conversation.requestVisibleRange();
                }
            }
        }
        Connections {
            target: pane.controller
            function onTranscriptChanged() {
                if (pane.current && conversation.followTail && !conversation.restoring)
                    tailTimer.restart();
            }
            enabled: pane.current
            function onChatChanged() {
                pane.refreshState();
            }
        }
        Connections {
            target: pane.messageModel
            function onModelAboutToBeReset() {
                if (!pane.current) return;
                conversation.restoring = true;
                tailTimer.stop();
                restoreTimer.stop();
            }
            function onModelReset() {
                // Replacing a live transcript with its indexed snapshot is a
                // structural reset. Preserve its reading anchor; ordinary page
                // arrivals below only refresh viewport demand.
                if (pane.current) conversation.restoreViewport();
                else pane.layoutDirty = true;
            }
            function onViewportChanged() {
                // A page arrival is not a navigation request. ListView keeps
                // its anchor while asynchronous delegate heights settle.
                conversation.scheduleRange();
            }
        }
        footer: Item {
            width: conversation.width
            height: turnStatus.visible ? turnStatus.implicitHeight + 20 : 0
            TaskStatus {
                id: turnStatus
                objectName: "turnStatus"
                x: 33
                y: 8
                status: pane.turnStatus
            }
        }
        delegate: Item {
            id: rowShell
            Component.onDestruction: bodyLoader.active = false
            required property var modelData
            required property int index
            readonly property bool messageSlot: true
            Component.onCompleted: conversation.scheduleRange()
            onYChanged: conversation.scheduleRange()
            onHeightChanged: conversation.scheduleRange()
            // shown: the row's group has finished loading (see settleGroups).
            // Until then the body lays out invisibly at the estimated height.
            property bool shown: false
            readonly property bool bodyLoaded: (bodyLoader.item !== null && bodyLoader.status === Loader.Ready) || !!modelData._loadError
            readonly property bool bodyReady: shown && bodyLoader.item !== null && bodyLoader.status === Loader.Ready
            // Rows appended after a range that reached the last row (streaming)
            // belong to the open tail group and load at once.
            readonly property bool wanted: conversation.activeLast < 0 || index >= conversation.activeFirst
                && (index <= conversation.activeLast || conversation.activeLast >= conversation.activeEnd)
            readonly property var replyMascot: bodyLoader.item ? bodyLoader.item.replyMascot : null
            onBodyLoadedChanged: if (!bodyLoaded)
                shown = false
            width: conversation.width - 16
            height: bodyReady ? bodyLoader.item.implicitHeight : Math.max(64, modelData._estimatedHeight || pane.messageModel.estimatedHeight(index))
            Loader {
                id: bodyLoader
                width: parent.width
                // The latest row loads at once while the view follows it: its
                // placeholder is as tall as the expected reply, so loading it
                // in the background on a slow machine leaves the screen blank.
                asynchronous: (rowShell.index < conversation.urgentFirst || rowShell.index > conversation.urgentLast)
                    && !(conversation.followTail && rowShell.index === conversation.count - 1)
                active: !pane.released && !rowShell.modelData._loading && rowShell.wanted
                opacity: rowShell.shown ? 1 : 0
                enabled: rowShell.shown
                onLoaded: {
                    pane.messageModel.recordHeight(rowShell.index, item.implicitHeight);
                    if (!conversation.forcing)
                        conversation.settleGroups();
                    conversation.scheduleRange();
                }
                sourceComponent: Column {
                    id: messageRow
                    objectName: pane.messagePrefix === "widget" ? "widgetChatMessage_" + index : "chatMessage_" + index
                    readonly property var replyMascot: closingMascot
                    property var modelData: rowShell.modelData
                    property int index: rowShell.index
                    readonly property bool compactionNotice: modelData.customType === "umeko-compaction"
                    readonly property bool dshInterruptionNotice: modelData.customType === "umeko-dsh-interruption"
                    readonly property bool statusNotice: compactionNotice || dshInterruptionNotice
                    readonly property point hoverPoint: chatSelection.mapToItem(messageRow, chatSelection.pointer.x, chatSelection.pointer.y)
                    readonly property bool hovered: chatSelection.hovering && hoverPoint.x >= 0 && hoverPoint.x <= width && hoverPoint.y >= 0 && hoverPoint.y <= height
                    width: conversation.width - 16
                    spacing: 10
                    onImplicitHeightChanged: if (bodyLoader.status === Loader.Ready)
                        pane.messageModel.recordHeight(index, implicitHeight)
                    Row {
                        visible: !modelData._loading && !messageRow.statusNotice && !modelData.continuation && modelData.role !== "user"
                        spacing: 9
                        AssistantAvatar {
                            objectName: pane.messagePrefix ? pane.messagePrefix + "AssistantAvatar_" + messageRow.index : "assistantAvatar_" + messageRow.index
                            messageKey: pane.viewKey + "/" + messageRow.index
                            artwork: String(pane.portrait).length ? pane.portrait : Character.asset(["avatarSmile", "avatarWink", "avatarHappy"][variant], fallbackSource)
                        }
                        SelectableText {
                            selectionController: chatSelection
                            messageIndex: messageRow.index
                            blockIndex: -100000
                            text: pane.assistantName
                            anchors.verticalCenter: parent.verticalCenter
                            color: Theme.ink
                            font.pixelSize: Theme.font(11, visible, chatSelection)
                            font.weight: Font.DemiBold
                        }
                    }
                    Rectangle {
                        objectName: "messageBubble_" + messageRow.index
                        border.width: 1
                        border.color: pane.highlightRow === messageRow.index ? Theme.accent : "transparent"
                        Behavior on border.color {
                            ColorAnimation {
                                duration: 180
                            }
                        }
                        visible: !modelData._loading && !messageRow.statusNotice
                        readonly property bool userMessage: modelData.role === "user"
                        width: userMessage ? (modelData.text.length > 512 ? messageRow.width * 0.82 : Math.min(messageRow.width * 0.82, Math.max(64, userBody.implicitWidth + 28))) : parent.width - 33
                        x: userMessage ? parent.width - width : 33
                        height: replyColumn.implicitHeight + (userMessage ? 22 : modelData.error ? 28 : 4)
                        radius: userMessage ? 13 : 8
                        color: userMessage ? Theme.userBubble : modelData.error ? Theme.accentBg : "transparent"
                        Column {
                            id: replyColumn
                            x: parent.userMessage || modelData.error ? 14 : 0
                            y: parent.userMessage ? 11 : modelData.error ? 14 : 0
                            width: parent.width - x * 2
                            spacing: 10
                            ActivityHistory {
                                width: parent.width
                                activity: modelData.activity || []
                                selectionController: chatSelection
                                messageIndex: messageRow.index
                            }
                            UserMessageBody {
                                id: userBody
                                width: parent.width
                                visible: modelData.role === "user"
                                text: modelData.role === "user" ? modelData.text : ""
                                attachments: modelData.attachments || []
                                selectionController: chatSelection
                                messageIndex: messageRow.index
                            }
                            MessageBody {
                                id: reply
                                width: parent.width
                                preparedBlocks: modelData._rendered || null
                                selectionController: chatSelection
                                messageIndex: messageRow.index
                                visible: modelData.role !== "user" && text.length > 0 && !(modelData.activity || []).length
                                text: modelData.role === "user" || (modelData.activity || []).length ? "" : modelData.text || (messageRow.index === conversation.count - 1 && pane.busy ? I18n.t(pane.toolStatus) + "…" : "")
                                markdown: modelData.role === "assistant" && !modelData.error
                                textColor: modelData.error ? Theme.danger : Theme.ink
                            }
                        }
                    }
                    ActionButton {
                        objectName: pane.messagePrefix === "widget" ? "widgetRequestDetails_" + messageRow.index : "requestDetails_" + messageRow.index
                        selectionController: chatSelection
                        visible: !modelData._loading && !messageRow.statusNotice && !!modelData.error && (modelData.diagnosticId || "").length > 0
                        x: 33
                        text: I18n.t("查看请求与返回")
                        glyph: "code"
                        quiet: true
                        onClicked: backend.showRequestDetails(modelData.diagnosticId)
                    }
                    Text {
                        objectName: "dshInterruptionNotice_" + messageRow.index
                        x: 33
                        width: parent.width - 33
                        height: Math.max(Theme.control(24), implicitHeight)
                        visible: !modelData._loading && messageRow.dshInterruptionNotice
                        // Saved items may still hold the full model instruction; users see the short status.
                        text: messageRow.dshInterruptionNotice ? I18n.t("已停止上一条请求") : ""
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        verticalAlignment: Text.AlignVCenter
                        color: Theme.muted
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.font(12, visible, chatSelection)
                    }
                    Column {
                        id: compactionEvent
                        objectName: "compactionEvent_" + messageRow.index
                        x: 33
                        width: parent.width - 33
                        visible: !modelData._loading && messageRow.compactionNotice
                        readonly property var record: modelData.compaction || ({})
                        readonly property string eventState: record.state || "success"
                        readonly property string heading: eventState === "running" ? I18n.t("正在压缩上下文") : eventState === "failure" ? I18n.t("上下文压缩失败") : I18n.t("上下文已压缩")
                        property bool expanded: false
                        spacing: 6
                        onExpandedChanged: if (!expanded)
                            chatSelection.hideDetails(messageRow.index, 0, 1)
                        Item {
                            width: Math.min(parent.width, compactionHeading.implicitWidth)
                            height: Theme.control(24)
                            Row {
                                id: compactionHeading
                                height: parent.height
                                spacing: 7
                                ActivitySpinner {
                                    visible: compactionEvent.eventState === "running"
                                    width: Theme.icon(12)
                                    height: Theme.icon(12)
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    font.family: Theme.fontFamily
                                    text: compactionEvent.heading
                                    color: compactionHover.interactionHovered ? Theme.ink : Theme.muted
                                    font.pixelSize: Theme.font(12, visible, chatSelection)
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Glyph {
                                    name: compactionEvent.expanded ? "chevron-down" : "chevron-right"
                                    width: Theme.icon(12)
                                    height: Theme.icon(12)
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }
                            ChatHitArea {
                                id: compactionHover
                                objectName: "compactionEventToggle_" + messageRow.index
                                anchors.fill: parent
                                selectionController: chatSelection
                                onClicked: compactionEvent.expanded = !compactionEvent.expanded
                            }
                            Accessible.role: Accessible.Button
                            Accessible.name: compactionEvent.heading
                            Accessible.description: compactionEvent.expanded ? I18n.t("已展开") : I18n.t("已折叠")
                        }
                        Item {
                            visible: compactionEvent.expanded
                            width: parent.width
                            height: compactionDetails.implicitHeight
                            Rectangle {
                                width: 1
                                height: parent.height
                                color: Theme.line
                                x: 6
                            }
                            SelectableText {
                                id: compactionDetails
                                objectName: "compactionEventDetails_" + messageRow.index
                                x: 23
                                width: parent.width - x
                                text: {
                                    const detail = compactionEvent.record, lines = [];
                                    if (typeof detail.before === "number")
                                        lines.push(I18n.t("压缩前：") + detail.before + " tokens");
                                    if (typeof detail.after === "number")
                                        lines.push(I18n.t("压缩后：") + detail.after + " tokens");
                                    if (detail.summary)
                                        lines.push("\n" + I18n.t("压缩摘要") + "\n" + detail.summary);
                                    if (detail.error)
                                        lines.push("\n" + I18n.t(detail.error));
                                    return lines.join("\n");
                                }
                                color: Theme.muted
                                font.pixelSize: Theme.font(13, visible, chatSelection)
                                wrapMode: TextEdit.Wrap
                                textFormat: TextEdit.PlainText
                                selectionController: chatSelection
                                messageIndex: messageRow.index
                                blockIndex: 0
                                conditionalSelection: true
                            }
                        }
                    }
                    OutputLimitNotice {
                        objectName: "outputLimitNotice_" + messageRow.index
                        x: 33
                        width: parent.width - 33
                        visible: !modelData._loading && !messageRow.statusNotice && modelData.segmentLast !== false && modelData.role === "assistant" && modelData.stopReason === "length"
                        continuable: messageRow.index === conversation.count - 1 && !pane.busy
                        onContinued: pane.controller.send(I18n.t("继续刚才未完成的回答，从中断处接着输出，不要重复已有内容。"))
                    }
                    Item {
                        objectName: "messageActions_" + messageRow.index
                        visible: !modelData._loading && !messageRow.statusNotice && modelData.segmentLast !== false
                        width: parent.width
                        height: 18
                        opacity: messageRow.hovered || actionHover.hovered ? 1 : 0
                        HoverHandler {
                            id: actionHover
                        }
                        Row {
                            x: modelData.role === "user" ? parent.width - width : 33
                            height: parent.height
                            spacing: 7
                            Text {
                                font.family: Theme.fontFamily
                                objectName: "messageTime_" + messageRow.index
                                anchors.verticalCenter: parent.verticalCenter
                                color: Theme.muted
                                font.pixelSize: Theme.font(11, visible, chatSelection)
                                text: {
                                    if (!modelData.timestamp)
                                        return "";
                                    const date = new Date(modelData.timestamp);
                                    if (isNaN(date.getTime()))
                                        return "";
                                    return Qt.formatDateTime(date, date.toDateString() === new Date().toDateString() ? "hh:mm" : "MM-dd hh:mm");
                                }
                            }
                            ActionButton {
                                objectName: pane.messagePrefix ? pane.messagePrefix + "CopyMessage_" + messageRow.index : "copyMessage_" + messageRow.index
                                selectionController: chatSelection
                                glyph: "copy"
                                width: Theme.control(22)
                                height: Theme.control(18)
                                quiet: true
                                enabled: parent.parent.opacity > 0
                                hint: I18n.t("复制消息")
                                onClicked: pane.controller.copyDisplayMessage(messageRow.index)
                            }
                        }
                    }
                    ReplyMascot {
                        id: closingMascot
                        portraitSource: String(pane.replyPortrait).length ? pane.replyPortrait : String(pane.portrait).length ? pane.portrait : Character.asset("reply", "../icons/yanami-pixel.webp")
                        interactionLabel: pane.messagePrefix ? pane.assistantName : Character.id === "yanami" ? I18n.t("八奈见：点击互动，连续点击或长按有彩蛋") : Character.style.name
                        objectName: pane.messagePrefix === "subagent" ? "subagentReplyMascot_" + messageRow.index : "replyEndMascot_" + messageRow.index
                        selectionController: chatSelection
                        width: Character.id === "doubao" ? Theme.icon(72) : 56
                        visible: pane.controller.sessionBackend !== "dsh" && !modelData._loading && !messageRow.statusNotice && messageRow.index === conversation.count - 1 && modelData.role === "assistant" && !modelData.error && (modelData.text || "").trim().length > 0 && !pane.running && (pane.turnStatus.state === "finished" || modelData.stopReason === "stop")
                        x: 33
                    }
                }
            }
            Item {
                anchors.fill: parent
                visible: !rowShell.bodyReady && rowShell.wanted
                ActivitySpinner {
                    objectName: "historyLoading_" + rowShell.index
                    x: 33
                    y: 16
                    running: pane.current && parent.visible && !rowShell.modelData._loadError
                }
                ActionButton {
                    x: 33
                    y: 16
                    visible: !!rowShell.modelData._loadError
                    text: I18n.t("重新加载消息")
                    glyph: "refresh-cw"
                    onClicked: pane.messageModel.retryPage(rowShell.index)
                }
            }
        }
    }

    ChatSelection {
        id: chatSelection
        anchors.fill: conversation
        view: conversation
        dataSource: pane.controller
        enabled: pane.current && !pane.blocked
        retainedView: true
        sessionActive: pane.current
    }
}
