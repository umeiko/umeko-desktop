import QtQuick
import QtQuick.Controls
import QtQuick.Window

Item {
    id: pane
    property var controller: backend
    property string viewName: "conversation"
    property string messagePrefix: ""
    property string assistantName: "umeko"
    property url portrait: ""
    property url replyPortrait: ""
    property int roleSlot: -1
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
    property bool officeMode: false
    property bool busy: false
    property bool running: false
    property string toolStatus: ""
    property var turnStatus: ({})
    property var turnStatusOverride: null
    property alias view: conversation
    property alias selection: chatSelection
    // While a newly activated pane positions its rows it stays transparent
    // and the previous pane remains on screen (holding) until the swap.
    property bool holding: false
    property bool concealed: false
    visible: current || holding
    opacity: concealed ? 0 : 1
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
        if (openAtBottom) {
            initialized = true;
            layoutDirty = false;
            conversation.startBottom();
        } else if (!initialized || layoutDirty || conversation.restoring) {
            initialized = true;
            layoutDirty = false;
            conversation.restoreViewport();
        } else {
            conversation.requestVisibleRange();
        }
    }
    property bool openAtBottom: false
    property bool renderReady: true
    readonly property int renderGeneration: openAtBottom && messageModel ? messageModel.openGeneration : 0
    readonly property int firstFrameRows: openAtBottom && messageModel ? messageModel.firstFrameRows : 0
    function finishOpening(generation) {
        if (current && !released && generation === renderGeneration) {
            messageModel.finishOpen(generation);
            if (conversation.firstScreenPositioned) {
                conversation.finishPosition();
                conversation.requestVisibleRange();
            } else {
                conversation.scheduleRange();
            }
        }
    }
    function deactivate() {
        conversation.saveViewport();
        current = false;
        conversation.resetScrollDemand();
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
        property bool firstScreenPositioned: false
        property real restoreOffset: -1
        property int restoreIndex: -1
        property int restoreAttempts: 0
        property bool explicitJump: false
        property bool jumpingOutsidePartial: false
        // Grouped loading. ChatModel splits rows into groups of about
        // groupScreens viewport heights. Rows of the on-screen groups and of
        // keepGroups groups on each side get bodies; farther groups release
        // theirs together. A group is shown only after all of its loaded rows
        // are laid out, its height change is absorbed by keepAnchor() in one
        // step, so scrolling can advance through already prepared rows.
        property real groupScreens: 2.5
        property int keepGroups: 1
        property int activeFirst: 0
        property int activeLast: -1
        property int activeEnd: 0
        property real reach: height * 0.25
        property bool anchoring: false
        property real pendingWheelPixels: 0
        property double lastWheelTime: 0
        property real aheadPixels: 0
        property int scrollDirection: 0
        property bool layoutPending: false
        property int probedBoundary: -1
        property int urgentFirst: -1
        property int urgentLast: -2
        property bool forcing: false
        property int prependAnchor: -1
        property real prependOffset: 0
        readonly property real bottomY: Math.max(originY, originY + contentHeight - height)
        readonly property bool nearBottom: bottomY - contentY <= 3
        readonly property real groupPixels: Math.max(320, height * groupScreens)
        readonly property int wheelMargin: scrollDirection ? Math.ceil(Math.min(groupPixels * 2, Math.max(height, aheadPixels))) : 0
        onGroupPixelsChanged: if (pane.messageModel) pane.messageModel.setGroupHeight(groupPixels)
        Component.onCompleted: if (pane.messageModel) pane.messageModel.setGroupHeight(groupPixels)
        readonly property string layoutKey: [
            width, Theme.fontFamily, Theme.fontScale, Theme.proseLineHeight,
            Screen.devicePixelRatio, Theme.dark, window.font.family, window.font.pixelSize
        ].join("/")
        onLayoutKeyChanged: {
            if (pane.messageModel)
                pane.messageModel.setLayout(layoutKey);
            if (!pane.current)
                pane.layoutDirty = true;
            else if (!followTail && count && !explicitJump)
                restoreViewport();
        }
        // User scrolling and explicit jumps supersede a navigator selection.
        signal browsingStarted()
        function beginBrowsing() {
            browsingStarted();
            tailTimer.stop();
            restoreTimer.stop();
            restoring = false;
            firstScreenPositioned = false;
            explicitJump = false;
            jumpingOutsidePartial = false;
            urgentFirst = -1;
            urgentLast = -2;
            cancelFlick();
            followTail = false;
        }
        function pinTail() {
            if (!count || anchoring)
                return;
            anchoring = true;
            positionViewAtEnd();
            anchoring = false;
        }
        function polishBody(item) {
            for (const child of item.children)
                if (child.visible)
                    polishBody(child);
            item.ensurePolished();
        }
        function releaseGroups() {
            // Navigation positions by row; every row it instantiates may load.
            urgentFirst = -1;
            urgentLast = -2;
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
                if (item.messageSlot === true && (item.shown || pane.openAtBottom)
                        && item.y + item.height > top && item.y < top + height
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
            // A group wholly above the viewport can lay out without changing
            // the displayed heights. Apply its measured heights together
            // when scrolling reaches it and keep the visible row anchored.
            // A cached view that was shown and is now hidden keeps its groups
            // as they are: keepAnchor() does not correct a hidden view, so a
            // group above the reader that finished loading in the background
            // would move the reading position. Activation settles them with
            // the anchor. A view still being created has no position yet.
            if (!pane.messageModel || !count || (!pane.current && pane.initialized))
                return;
            const model = pane.messageModel, map = slotMap(), slots = map.slots;
            const direction = Math.sign(pendingWheelPixels);
            const ready = [];
            if (direction && !restoring && !followTail) {
                // Advance as soon as the next contiguous bodies are measured.
                // More distant bodies in the group can catch up on later frames.
                const viewport = visibleRows(slots);
                let row = direction < 0 ? viewport.first : viewport.last;
                while (slots[row] && slots[row].bodyLoaded) {
                    if (!slots[row].shown)
                        ready.push(slots[row]);
                    row += direction;
                }
                showMeasuredRows(ready);
                return;
            }
            const top = above || followTail || restoring ? -1 : visibleRows(slots).first;
            // While the view follows the latest message, the last group keeps
            // receiving rows as the reply streams, so on a slow machine it is
            // rarely complete: waiting for it would hide the streaming row and
            // keep the restore after a reset from finishing. Its rows are shown
            // one by one as they load; the view is positioned at the end, so
            // nothing the reader is looking at moves.
            const tail = followTail ? model.groupOf(count - 1) : -1;
            const checked = {};
            for (const key in slots) {
                const item = slots[key], row = item.index;
                if (item.shown || !item.bodyLoaded || checked[row])
                    continue;
                const group = model.groupOf(row);
                // A concealed restore can commit its visible bodies as they
                // finish. Waiting for the rest of their groups spends a render
                // frame on each asynchronous incubation before revealing the pane.
                if (group === tail || (restoring && row >= urgentFirst && row <= urgentLast)) {
                    ready.push(item);
                    continue;
                }
                const groupFirst = model.groupFirst(group), groupLast = model.groupLast(group);
                let first = row, last = row;
                // ListView can retain a detached current item far from the
                // viewport. Gaps between instantiated runs cannot hold up
                // the bodies beside the reader.
                while (first > groupFirst && slots[first - 1])
                    first--;
                while (last < groupLast && slots[last + 1])
                    last++;
                if (last < top)
                    continue;
                const rows = [];
                let complete = true;
                for (let other = first; other <= last; other++) {
                    const slot = slots[other];
                    checked[other] = true;
                    complete = complete && slot.bodyLoaded;
                    if (!slot.shown)
                        rows.push(slot);
                }
                if (complete)
                    ready.push(...rows);
            }
            showMeasuredRows(ready);
        }
        function showMeasuredRows(ready) {
            if (!ready.length)
                return;
            keepAnchor(() => {
                for (const item of ready)
                    item.shown = true;
            });
            scheduleRange();
        }
        function settleExposedRows() {
            // Removing the earlier-history header exposes an extra strip of
            // the old page. Finish its intersecting bodies before presenting it.
            const slots = slotMap().slots, rows = visibleRows(slots), ready = [];
            if (rows.first < 0)
                return;
            forcing = true;
            for (let index = rows.first; index <= rows.last; index++) {
                const row = slots[index];
                if (!row || row.shown)
                    continue;
                if (row.bodyIncubating)
                    row.finishIncubation();
                if (row.layoutWork.length)
                    row.prepareLayout(Infinity);
                if (row.bodyLoaded)
                    ready.push(row);
            }
            forcing = false;
            showMeasuredRows(ready);
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
            // A fast wheel gesture can cross a viewport and an entire
            // neighbouring group in one event. Prepare ahead on that side
            // while retaining the usual range behind the reader.
            const ahead = Math.min(3, Math.ceil((aheadPixels + height) / groupPixels));
            const before = screenShown && scrollDirection < 0 ? Math.max(keep, ahead) : keep;
            const after = screenShown && scrollDirection > 0 ? Math.max(keep, ahead) : keep;
            const first = model.groupFirst(Math.max(0, g0 - before));
            const last = model.groupLast(Math.min(groups - 1, g1 + after));
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
                model.requestScrollGroups(rows.first, rows.last, before, after, scrollDirection);
            settleGroups(scrollDirection < 0 && aheadPixels > 0);
        }
        function shownLimits() {
            // contentY may move within [upper, lower - height] without
            // showing a row that is not laid out yet.
            // above/below: the first row that is not shown on each side.
            const map = slotMap(), slots = map.slots, rows = visibleRows(slots);
            if (rows.first < 0)
                return {upper: contentY, lower: contentY + height, above: -1, below: -1};
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
        function finishGroup(row, step) {
            // Complete the prepared group's remaining bodies when scrolling
            // reaches its edge (a Loader finishes when asynchronous turns off).
            if (row < 0 || !pane.messageModel)
                return;
            ensureBoundaryShell(row, step);
            const group = pane.messageModel.groupOf(row);
            forcing = true;
            urgentFirst = pane.messageModel.groupFirst(group);
            urgentLast = pane.messageModel.groupLast(group);
            urgentLast = -2;
            urgentFirst = -1;
            forcing = false;
            settleGroups(true);
        }
        function ensureBoundaryShell(row, step) {
            if (row >= 0 && !itemAtIndex(row)) {
                // A row whose edge meets the screen edge exactly may not be
                // created yet: ListView fills its cache buffer later. Cross
                // the inter-row spacing and return in the same animation
                // tick, so Qt instantiates the shell before it is visible.
                anchoring = true;
                const previous = contentY;
                contentY += step * (spacing + 1);
                forceLayout();
                contentY = previous;
                forceLayout();
                anchoring = false;
            }
        }
        function layoutNearViewport() {
            const map = slotMap(), rows = visibleRows(map.slots);
            const waiting = Object.values(map.slots).filter(row => row.layoutWork.length > 0
                || (pendingWheelPixels !== 0 && row.bodyIncubating));
            if (rows.first < 0)
                return waiting.length > 0;
            // Complete visible rows and then the rows the next wheel step will
            // reach. Keep a distance order on the other side for reversals.
            function priority(row) {
                if (row.index >= rows.first && row.index <= rows.last)
                    return 0;
                const after = row.index > rows.last;
                const distance = after ? row.index - rows.last : rows.first - row.index;
                return distance + ((after && scrollDirection < 0) || (!after && scrollDirection > 0) ? count : 0);
            }
            waiting.sort((a, b) => priority(a) - priority(b));
            // Leave room in each frame for scene updates and input handling.
            const deadline = Date.now() + (pendingWheelPixels ? 10 : 6);
            let ready = 0;
            for (const row of waiting) {
                // Qt gives offscreen incubation spare time. When the reader
                // is scrolling continuously, lend the first waiting body a
                // frame slot even if the incubator has not finished it yet.
                if (row.bodyIncubating)
                    row.finishIncubation();
                if (row.layoutWork.length && row.prepareLayout(deadline))
                    ready++;
                if (Date.now() >= deadline)
                    break;
            }
            // Preserve the stationary viewport. Entire measured groups above
            // it can remain at their estimates until a wheel step needs them.
            if (ready)
                settleGroups(pendingWheelPixels < 0);
            return waiting.length > ready;
        }
        function jumpToMessage(row) {
            const partial = pane.messageModel.partialHistory && pane.controller.recentHistory;
            if (row < 0 || (row >= count && !partial))
                return;
            // An explicit question or keyboard navigation can precede the
            // deferred fill and must use the complete model's row numbers.
            pane.finishOpening(pane.renderGeneration);
            resetScrollDemand();
            beginBrowsing();
            chatSelection.clear();
            releaseGroups();
            restoring = true;
            restoreIndex = row;
            restoreOffset = 0;
            restoreAttempts = 0;
            explicitJump = true;
            jumpingOutsidePartial = row >= count;
            if (partial)
                pane.controller.recentHistory.loadEarlier();
            restoreTimer.restart();
        }
        function jumpToLatest() {
            resetScrollDemand();
            beginBrowsing();
            chatSelection.clear();
            releaseGroups();
            if (pane.openAtBottom) {
                startBottom();
                return;
            }
            followTail = true;
            restoring = true;
            restoreIndex = -1;
            restoreOffset = 0;
            restoreAttempts = 0;
            pane.messageModel.requestRange(Math.max(0, count - 4), count - 1);
            restoreTimer.restart();
        }
        function scrollBy(delta) {
            applyScroll(delta, false);
        }
        function scrollWheel(delta) {
            applyScroll(delta, true);
        }
        function applyScroll(delta, wheel) {
            if (!delta)
                return;
            if (pane.firstFrameRows)
                pane.finishOpening(pane.renderGeneration);
            if (!pane.openAtBottom || !wheel) {
                resetScrollDemand();
                beginBrowsing();
                advanceScroll(delta, false);
                return;
            }
            const starting = !scrollDirection || restoring || followTail;
            if (starting)
                beginBrowsing();
            const now = Date.now();
            if (now - lastWheelTime > scrollIdle.interval || scrollDirection * delta < 0)
                resetScrollDemand();
            scrollDirection = Math.sign(delta);
            lastWheelTime = now;
            aheadPixels = Math.max(aheadPixels, Math.abs(delta));
            const waiting = pendingWheelPixels !== 0;
            const distance = Math.min(groupPixels * 2, Math.abs(pendingWheelPixels) + Math.abs(delta));
            pendingWheelPixels = scrollDirection * distance;
            // A small step can use the ready rows immediately. Further steps
            // behind a pending boundary wait for the per-frame layout budget.
            if (!waiting && Math.abs(delta) <= height) {
                // Entering browse mode activates the directional display
                // margin. Read its new row positions before moving into it.
                if (starting)
                    forceLayout();
                advanceScroll(delta, true);
            }
            scrollIdle.restart();
            scheduleRange();
        }
        function resetScrollDemand() {
            scrollIdle.stop();
            lastWheelTime = 0;
            aheadPixels = 0;
            scrollDirection = 0;
            pendingWheelPixels = 0;
            probedBoundary = -1;
        }
        function advanceScroll(distance, deferred) {
            let target = Math.max(originY, Math.min(bottomY, contentY + distance));
            let limits = shownLimits();
            const clamp = () => Math.max(Math.min(contentY, limits.upper), Math.min(target, Math.max(contentY, limits.lower - height)));
            let allowed = clamp();
            const refresh = () => {
                target = Math.max(originY, Math.min(bottomY, contentY + distance));
                limits = shownLimits();
                allowed = clamp();
            };
            const direction = Math.sign(distance);
            if (Math.abs(allowed - target) > 0.5) {
                const boundary = direction < 0 ? limits.above : limits.below;
                if (deferred) {
                    // At the exact cache edge Qt can postpone creating the next
                    // shell. Nudge it once, leaving the body to the layout budget.
                    if (Math.abs(allowed - contentY) <= 0.5 && boundary >= 0 && boundary !== probedBoundary
                            && !itemAtIndex(boundary)) {
                        probedBoundary = boundary;
                        ensureBoundaryShell(boundary, direction);
                        refresh();
                    }
                } else {
                    finishGroup(boundary, direction);
                    refresh();
                }
            }
            if (deferred) {
                const moved = allowed - contentY;
                pendingWheelPixels = (direction < 0 ? allowed <= originY : allowed >= bottomY)
                    || Math.abs(pendingWheelPixels - moved) < 0.5 ? 0 : pendingWheelPixels - moved;
            }
            if (Math.abs(allowed - contentY) >= 0.01) {
                anchoring = true;
                contentY = allowed;
                anchoring = false;
                scheduleRange();
            }
            if (direction < 0)
                loadEarlierAtTop();
            if (direction > 0 && nearBottom && !chatSelection.dragging) {
                followTail = true;
                pinTail();
            }
        }
        function saveViewport() {
            if (restoring || !pane.current)
                return;
            let index = indexAt(1, contentY + 1);
            if (index < 0)
                index = indexAt(1, contentY + spacing + 2);
            if (index < 0)
                index = visibleRows(slotMap().slots).first;
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
            if (followTail && count && pane.messageModel) {
                // The first screen at the latest message is not visible
                // until it is complete; its rows load at once instead of
                // across many frames.
                let first = count - 1, extent = 0;
                while (first > 0 && extent < height * 1.5) {
                    extent += pane.messageModel.estimatedHeight(first) + spacing;
                    first--;
                }
                urgentFirst = first;
                urgentLast = count - 1;
            }
            if (!count && !pane.controller.loading && !pane.controller.messageCount) {
                restoreTimer.stop(); restoring = false; return;
            }
            restoreTimer.restart();
        }
        function startBottom() {
            // Keep a retained pane's laid-out rows. Move to its up-to-date
            // tail after the composer and hint bars established the viewport.
            resetScrollDemand();
            restoreTimer.stop();
            firstScreenPositioned = false;
            restoring = true;
            followTail = true;
            restoreIndex = -1;
            restoreOffset = 0;
            restoreAttempts = 0;
            if (!count) {
                restoring = false;
                return;
            }
            const first = Math.max(0, count - Math.max(20, pane.firstFrameRows));
            urgentFirst = first;
            urgentLast = count - 1;
            activeFirst = first;
            activeLast = count - 1;
            activeEnd = count - 1;
            pinTail();
            forceLayout();
            requestFirstScreen();
            if (firstScreenReady())
                finishPosition();
            else
                restoreTimer.start();
        }
        function requestFirstScreen() {
            // The logical first frame contains the latest twenty rows. The
            // viewport decides which of those bodies need preparing first.
            const rows = visibleRows(slotMap().slots);
            const priority = [];
            const stagingFloor = Math.max(0, count - pane.firstFrameRows);
            const first = rows.first >= 0 ? Math.max(pane.firstFrameRows ? stagingFloor : 0, rows.first) : count - 1;
            urgentFirst = Math.min(urgentFirst, first);
            activeFirst = Math.min(activeFirst, first);
            for (let row = count - 1; row >= Math.max(0, first); row--)
                priority.push(row);
            if (!priority.length && count)
                priority.push(count - 1);
            pane.messageModel.requestViewport(priority, []);
        }
        function firstScreenReady() {
            const tail = itemAtIndex(count - 1);
            if (count && (!tail || !tail.bodyReady))
                return false;
            const top = contentY, bottom = contentY + height;
            let first = null;
            for (const row of contentItem.children) {
                if (row.messageSlot !== true || row.y + row.height <= top || row.y >= bottom)
                    continue;
                if (!row.shown)
                    return false;
                if (!first || row.index < first.index)
                    first = row;
            }
            return !first || first.index === 0 || first.y <= top + spacing + 1;
        }
        function checkLoadedTail(generation) {
            // A body completing between timer ticks can already cover the
            // first screen. Keep its opening token until the check runs.
            if (generation !== pane.renderGeneration || !pane.current || !pane.concealed
                    || !restoring || !followTail || firstScreenPositioned || !count)
                return;
            forceLayout();
            pinTail();
            if (firstScreenReady())
                finishPosition();
            else
                requestFirstScreen();
        }
        function finishPosition() {
            restoreTimer.stop();
            if (followTail && pane.firstFrameRows) {
                // Let the host paint the positioned suffix for a frame. The
                // opening still owns navigation until older bodies can load.
                firstScreenPositioned = true;
                pinTail();
                return;
            }
            firstScreenPositioned = false;
            urgentFirst = -1;
            urgentLast = -2;
            restoring = false;
            explicitJump = false;
            jumpingOutsidePartial = false;
            if (followTail)
                pinTail();
            saveViewport();
            scheduleRange();
        }
        function prioritizeAnchor(index) {
            let last = index;
            let extent = pane.messageModel.estimatedHeight(index);
            const needed = height + Math.max(0, restoreOffset);
            while (last + 1 < count && extent < needed) {
                last++;
                extent += pane.messageModel.estimatedHeight(last) + spacing;
            }
            urgentFirst = index;
            urgentLast = last;
        }
        acceptedButtons: Qt.NoButton
        visible: count > 0
        anchors.fill: parent
        clip: true
        spacing: 27
        model: pane.renderReady ? pane.messageModel : null
        // Create the nearby shells before reaching their estimated positions.
        // Rich message bodies still incubate and measure separately.
        displayMarginBeginning: scrollDirection < 0 ? wheelMargin : 0
        displayMarginEnd: scrollDirection > 0 ? wheelMargin : 0
        cacheBuffer: Math.max(0, reach - wheelMargin)
        currentIndex: -1
        activeFocusOnTab: true
        Keys.onPressed: event => {
            if (event.key === Qt.Key_PageUp || event.key === Qt.Key_Home) {
                scrollBy(event.key === Qt.Key_Home ? -contentHeight : -height);
                event.accepted = true;
            } else if (event.key === Qt.Key_PageDown || event.key === Qt.Key_End) {
                if (event.key === Qt.Key_End) jumpToLatest();
                else scrollBy(height);
                event.accepted = true;
            }
        }
        // Keep the control detached so programmatic size changes cannot write
        // back to the ListView while a loaded row replaces its estimate.
        ScrollBar {
            objectName: pane.current ? "conversationScrollBar" : ""
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            orientation: Qt.Vertical
            size: Math.min(1, conversation.height / Math.max(1, conversation.contentHeight))
            position: conversation.visibleArea.yPosition
            active: pressed || hovered || conversation.moving
            visible: size < 1 && pane.current
            onPressedChanged: if (pressed) {
                conversation.forceActiveFocus()
                conversation.beginBrowsing()
            }
            onPositionChanged: {
                if (pressed && !conversation.anchoring) {
                    const target = conversation.originY + position * conversation.contentHeight;
                    if (Math.abs(target - conversation.contentY) > 1)
                        conversation.scrollBy(target - conversation.contentY);
                }
            }
        }
        onFollowTailChanged: saveViewport()
        onContentYChanged: {
            saveViewport();
            scheduleRange();
            loadEarlierAtTop();
        }
        onAtYBeginningChanged: loadEarlierAtTop()
        function loadEarlierAtTop() {
            if (anchoring || followTail || restoring || !pane.current || !pane.messageModel
                    || !pane.messageModel.partialHistory || !pane.controller.recentHistory)
                return;
            // A wheel queue may reach the first message before ListView
            // reaches the beginning of its header. Request earlier history
            // as that first row enters the area being laid out.
            const first = itemAtIndex(0);
            if (atYBeginning || (scrollDirection < 0 && first && first.y <= contentY + height
                    && first.y + first.height >= contentY - height))
                pane.controller.recentHistory.loadEarlier();
        }
        function scheduleRange() {
            if (pane.current && !pagePrefetch.running)
                pagePrefetch.start();
        }
        function requestVisibleRange() {
            if (!pane.current || !count || (pane.firstFrameRows && !explicitJump))
                return;
            if (!wheelFrame.running)
                forceLayout();
            // indexAt() returns -1 in spacing and outside instantiated delegates;
            // updateGroups() inspects the intersecting slots so a gap cannot
            // starve rows.
            if (visibleRows(slotMap().slots).first < 0)
                scheduleRange();
            else
                updateGroups();
        }
        FrameAnimation {
            id: wheelFrame
            running: pane.current && (conversation.layoutPending || conversation.pendingWheelPixels !== 0)
            onTriggered: {
                if (conversation.layoutPending || conversation.pendingWheelPixels)
                    conversation.layoutPending = conversation.layoutNearViewport();
                if (conversation.pendingWheelPixels && !conversation.restoring) {
                    // Keep an overlapping strip of the previous screen in
                    // each frame of a large wheel gesture.
                    const step = Math.max(1, conversation.height * 0.58);
                    const pending = conversation.pendingWheelPixels;
                    conversation.advanceScroll(Math.sign(pending) * Math.min(Math.abs(pending), step), true);
                }
            }
        }
        Timer {
            id: scrollIdle
            interval: 100
            onTriggered: {
                if (conversation.pendingWheelPixels)
                    start();
                else
                    conversation.resetScrollDemand();
                conversation.scheduleRange();
            }
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
            if (pane.current && followTail && !restoring) {
                // Rows above the tail settle their heights in the background.
                // Re-pin the tail in the same frame, so the latest message
                // never draws one frame away from the bottom.
                if (!pane.concealed)
                    pinTail();
                tailTimer.restart();
            }
        }
        onCountChanged: {
            scheduleRange();
            if (pane.current && followTail && !restoring)
                tailTimer.restart();
        }
        onHeightChanged: {
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
                    conversation.pinTail();
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
                    conversation.pinTail();
                    if (pane.openAtBottom && conversation.urgentLast >= 0)
                        conversation.requestFirstScreen();
                    else
                        pane.messageModel.requestRange(Math.max(0, conversation.count - 4), conversation.count - 1);
                    if (!conversation.firstScreenReady() && conversation.restoreAttempts < 200)
                        return;
                } else {
                    if (conversation.jumpingOutsidePartial && pane.messageModel.partialHistory)
                        return;
                    const index = Math.min(conversation.restoreIndex, conversation.count - 1);
                    if (index < 0 && conversation.restoreAttempts < 200)
                        return;
                    if (index >= 0 && conversation.urgentFirst < 0) {
                        conversation.prioritizeAnchor(index);
                        pane.messageModel.requestRange(conversation.urgentFirst, conversation.urgentLast);
                        conversation.positionViewAtIndex(index, ListView.Beginning);
                        conversation.forceLayout();
                    }
                    conversation.settleGroups();
                    const item = conversation.itemAtIndex(index);
                    if ((!item || !item.bodyReady) && conversation.restoreAttempts < 200)
                        return;
                    if (item) {
                        const offset = Math.min(conversation.restoreOffset, item.height - 1);
                        conversation.positionViewAtIndex(index, ListView.Beginning);
                        if (!conversation.atYEnd)
                            conversation.contentY += offset;
                    }
                    conversation.forceLayout();
                    if (conversation.restoreAttempts < 200) {
                        const slots = conversation.slotMap().slots;
                        const rows = conversation.visibleRows(slots);
                        if (rows.first < 0)
                            return;
                        // Estimates can underfill the screen, or the end clamp
                        // can expose rows above the anchor. Only prioritize the
                        // rows that actually intersect the viewport.
                        const first = Math.min(index, rows.first);
                        const last = Math.max(index, rows.last);
                        if (first < conversation.urgentFirst || last > conversation.urgentLast) {
                            conversation.urgentFirst = Math.min(first, conversation.urgentFirst);
                            conversation.urgentLast = Math.max(last, conversation.urgentLast);
                            pane.messageModel.requestRange(conversation.urgentFirst, conversation.urgentLast);
                        }
                        for (let row = rows.first; row <= rows.last; row++) {
                            if (!slots[row] || !slots[row].shown)
                                return;
                        }
                    }
                }
                if (conversation.restoreAttempts >= 2 || (pane.openAtBottom && conversation.followTail)) {
                    conversation.finishPosition();
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
                if (!conversation.followTail)
                    conversation.saveViewport();
                conversation.restoring = true;
                tailTimer.stop();
                restoreTimer.stop();
            }
            function onModelReset() {
                // Replacing a live transcript with its indexed snapshot is a
                // structural reset. Preserve its reading anchor; ordinary page
                // arrivals below only refresh viewport demand.
                if (!pane.current) {
                    pane.layoutDirty = true;
                } else if (conversation.explicitJump) {
                    // A Pi-to-index replacement can arrive just after the
                    // reader selected a question. Keep that request rather
                    // than reopening at the position before the click.
                    conversation.releaseGroups();
                    conversation.restoreAttempts = 0;
                    restoreTimer.start();
                } else {
                    conversation.restoreViewport();
                }
            }
            function onViewportChanged() {
                // A page arrival is not a navigation request. ListView keeps
                // its anchor while asynchronous delegate heights settle.
                conversation.scheduleRange();
            }
            // A partial history gains its earlier rows above the rows on
            // screen. Row numbers move by count; the loaded range covers old
            // and new numbers while ListView inserts, so no body unloads.
            function onHistoryAboutToPrepend(count) {
                chatSelection.clear();
                // Keep the first row on screen in place, accounting for only
                // the visible part of the loading header when it disappears.
                const rows = conversation.visibleRows(conversation.slotMap().slots);
                const item = rows.first >= 0 ? conversation.itemAtIndex(rows.first) : null;
                const header = conversation.headerItem, top = conversation.contentY;
                const loading = header ? Math.max(0, Math.min(header.y + header.height, top + conversation.height)
                    - Math.max(header.y, top)) : 0;
                conversation.prependAnchor = item ? rows.first : -1;
                conversation.prependOffset = item ? item.y - top - loading : 0;
                if (conversation.activeLast >= 0) {
                    conversation.activeLast += count;
                    conversation.activeEnd += count;
                }
            }
            function onHistoryPrepended(count) {
                if (conversation.activeLast >= 0)
                    conversation.activeFirst += count;
                if (conversation.restoreIndex >= 0 && !conversation.jumpingOutsidePartial)
                    conversation.restoreIndex += count;
                if (conversation.explicitJump) {
                    conversation.urgentFirst = -1;
                    conversation.urgentLast = -2;
                    conversation.restoreAttempts = 0;
                }
                const anchor = conversation.prependAnchor;
                conversation.prependAnchor = -1;
                if (anchor >= 0 && !conversation.followTail && !conversation.restoring) {
                    conversation.anchoring = true;
                    conversation.forceLayout();
                    const item = conversation.itemAtIndex(anchor + count);
                    if (item) {
                        conversation.contentY = item.y - conversation.prependOffset;
                    } else {
                        conversation.positionViewAtIndex(anchor + count, ListView.Beginning);
                        conversation.contentY -= conversation.prependOffset;
                    }
                    // Let ListView create the row just above the screen, so
                    // scrolling up has a row to load and move into.
                    conversation.contentY -= 1;
                    conversation.forceLayout();
                    conversation.contentY += 1;
                    if (pane.openAtBottom)
                        conversation.settleExposedRows();
                    conversation.anchoring = false;
                }
                if (conversation.followTail && !conversation.restoring)
                    conversation.pinTail();
                conversation.scheduleRange();
            }
        }
        header: Item {
            objectName: pane.current ? "earlierHistoryLoading" : ""
            width: conversation.width
            visible: !!pane.messageModel && pane.messageModel.partialHistory
            height: visible ? 48 : 0
            Text {
                anchors.centerIn: parent
                text: I18n.t("正在加载更早的消息…")
                color: Theme.muted
                font.family: Theme.fontFamily
                font.pixelSize: Theme.font(11)
            }
        }
        footer: Item {
            width: conversation.width
            height: turnStatus.visible ? turnStatus.implicitHeight + 20 : 0
            TaskStatus {
                id: turnStatus
                // Named only on the pane in use; a held pane shows the previous chat.
                objectName: pane.current ? "turnStatus" : ""
                x: 33
                y: 8
                status: pane.turnStatusOverride === null ? pane.turnStatus : pane.turnStatusOverride
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
            property bool laidOut: false
            property real measuredHeight: 0
            property var layoutWork: []
            property bool finishingIncubation: false
            readonly property bool bodyIncubating: bodyLoader.status === Loader.Loading
            function finishIncubation() {
                finishingIncubation = true;
                finishingIncubation = false;
            }
            function prepareLayout(deadline) {
                // The queue belongs to the delegate and dies with it. Visit
                // children before their parent, like polishBody(), but yield
                // even when a single message has many components.
                while (layoutWork.length && Date.now() < deadline) {
                    const job = layoutWork.pop();
                    const node = job.item;
                    if (!node)
                        continue;
                    if (job.childrenDone) {
                        node.ensurePolished();
                    } else {
                        layoutWork.push({item: node, childrenDone: true});
                        for (let i = node.children.length - 1; i >= 0; i--)
                            if (node.children[i].visible)
                                layoutWork.push({item: node.children[i], childrenDone: false});
                    }
                }
                if (layoutWork.length || !bodyLoader.item)
                    return false;
                applyHeight(bodyLoader.item.implicitHeight, bodyLoader.item.expandedLayout);
                laidOut = true;
                return true;
            }
            function applyHeight(value, expanded) {
                if (!(value > 0) || pane.released)
                    return;
                if (shown && y < conversation.contentY && !conversation.followTail
                        && Math.abs(value - measuredHeight) > 0.5)
                    conversation.keepAnchor(() => { measuredHeight = value; });
                else
                    measuredHeight = value;
                // Expanded blocks are still expanded while their pane is
                // retained. A rebuilt delegate starts collapsed.
                if (expanded)
                    pane.messageModel.invalidateHeight(index);
                else
                    pane.messageModel.recordHeight(index, value);
            }
            readonly property bool bodyLoaded: (laidOut && bodyLoader.item !== null && bodyLoader.status === Loader.Ready) || !!modelData._loadError
            readonly property bool bodyReady: shown && bodyLoader.item !== null && bodyLoader.status === Loader.Ready
            // Rows appended after a range that reached the last row (streaming)
            // belong to the open tail group and load at once.
            readonly property bool wanted: conversation.activeLast < 0 || index >= conversation.activeFirst
                && (index <= conversation.activeLast || conversation.activeLast >= conversation.activeEnd)
            readonly property var replyMascot: bodyLoader.item ? bodyLoader.item.replyMascot : null
            onBodyLoadedChanged: if (!bodyLoaded)
                shown = false
            width: conversation.width - 16
            height: bodyReady && measuredHeight > 0 ? measuredHeight : Math.max(64, modelData._estimatedHeight || pane.messageModel.estimatedHeight(index))
            Loader {
                id: bodyLoader
                width: parent.width
                // The latest row loads at once while the view follows it: its
                // placeholder is as tall as the expected reply, so loading it
                // in the background on a slow machine leaves the screen blank.
                asynchronous: !rowShell.finishingIncubation
                    && (rowShell.index < conversation.urgentFirst || rowShell.index > conversation.urgentLast)
                    && !(conversation.followTail && rowShell.index === conversation.count - 1)
                active: !pane.released && !rowShell.modelData._loading && rowShell.wanted
                    && (!pane.firstFrameRows || rowShell.index >= conversation.count - pane.firstFrameRows)
                opacity: rowShell.shown ? 1 : 0
                enabled: rowShell.shown
                onStatusChanged: if (status !== Loader.Ready) {
                    rowShell.laidOut = false;
                    rowShell.layoutWork = [];
                }
                onLoaded: {
                    if (pane.openAtBottom && !conversation.followTail && !conversation.restoring && !conversation.forcing) {
                        rowShell.layoutWork = [{item: item, childrenDone: false}];
                        conversation.layoutPending = true;
                    } else {
                        conversation.polishBody(item);
                        rowShell.applyHeight(item.implicitHeight, item.expandedLayout);
                        rowShell.laidOut = true;
                        if (!conversation.forcing)
                            conversation.settleGroups();
                    }
                    if (pane.openAtBottom && pane.concealed && conversation.followTail && conversation.restoring)
                        Qt.callLater(conversation.checkLoadedTail, pane.renderGeneration);
                    conversation.scheduleRange();
                }
                sourceComponent: Column {
                    id: messageRow
                    objectName: pane.messagePrefix === "widget" ? "widgetChatMessage_" + index : "chatMessage_" + index
                    readonly property var replyMascot: closingMascot.item
                    property var modelData: rowShell.modelData
                    property int index: rowShell.index
                    readonly property bool compactionNotice: modelData.customType === "umeko-compaction"
                    readonly property bool dshInterruptionNotice: modelData.customType === "umeko-dsh-interruption"
                    readonly property bool gatewayContinuationNotice: modelData.customType === "umeko-gateway-continuation"
                    readonly property bool networkRetryNotice: modelData.customType === "umeko-network-retry"
                    readonly property bool statusNotice: compactionNotice || dshInterruptionNotice || gatewayContinuationNotice || networkRetryNotice
                    readonly property point hoverPoint: chatSelection.mapToItem(messageRow, chatSelection.pointer.x, chatSelection.pointer.y)
                    readonly property bool hovered: chatSelection.hovering && hoverPoint.x >= 0 && hoverPoint.x <= width && hoverPoint.y >= 0 && hoverPoint.y <= height
                    width: conversation.width - 16
                    spacing: 10
                    readonly property bool expandedLayout: activityHistory.layoutExpanded || !!(compactionLoader.item && compactionLoader.item.expanded)
                    onExpandedLayoutChanged: if (rowShell.laidOut)
                        rowShell.applyHeight(implicitHeight, expandedLayout)
                    onImplicitHeightChanged: if (rowShell.laidOut)
                        rowShell.applyHeight(implicitHeight, expandedLayout)
                    Row {
                        visible: !modelData._loading && !messageRow.statusNotice && !modelData.continuation && modelData.role !== "user"
                        spacing: 9
                        AssistantAvatar {
                            objectName: pane.messagePrefix ? pane.messagePrefix + "AssistantAvatar_" + messageRow.index : "assistantAvatar_" + messageRow.index
                            // The row's own entry keeps its avatar when rows
                            // are inserted above it.
                            messageKey: pane.viewKey + "/" + ((modelData._entries || [])[0] || messageRow.index)
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
                        readonly property real userBodyWidth: userBody.item ? userBody.item.implicitWidth : 0
                        width: userMessage ? (modelData.text.length > 512 ? messageRow.width * 0.82 : Math.min(messageRow.width * 0.82, Math.max(64, userBodyWidth + 28))) : parent.width - 33
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
                                id: activityHistory
                                width: parent.width
                                activity: modelData.activity || []
                                selectionController: chatSelection
                                messageIndex: messageRow.index
                            }
                            Text {
                                objectName: "partialIncompleteNotice_" + messageRow.index
                                visible: !!modelData.partialIncomplete
                                width: parent.width
                                text: I18n.t("已保留中断前的部分回复（未完成）")
                                textFormat: Text.PlainText
                                wrapMode: Text.Wrap
                                color: Theme.muted
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.font(11, visible, chatSelection)
                            }
                            Loader {
                                id: userBody
                                width: parent.width
                                active: modelData.role === "user"
                                visible: active
                                sourceComponent: UserMessageBody {
                                    text: modelData.text
                                    attachments: modelData.attachments || []
                                    selectionController: chatSelection
                                    messageIndex: messageRow.index
                                }
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
                    Loader {
                        readonly property bool showDetails: (modelData.diagnosticId || "").length > 0
                        readonly property bool showStagedContinue: !pane.messagePrefix && !!modelData.stagedContinueAvailable && messageRow.index === conversation.count - 1 && !pane.busy && backend.sessionBackend !== "dsh"
                        active: !modelData._loading && !messageRow.statusNotice && !!modelData.error && (showDetails || showStagedContinue)
                        visible: active
                        x: 33
                        sourceComponent: Row {
                            spacing: 8
                            ActionButton {
                                objectName: (pane.messagePrefix ? pane.messagePrefix + "RequestDetails_" : "requestDetails_") + messageRow.index
                                visible: (modelData.diagnosticId || "").length > 0
                                selectionController: chatSelection
                                text: I18n.t("查看请求与返回")
                                glyph: "code"
                                quiet: true
                                onClicked: backend.showRequestDetails(modelData.diagnosticId)
                            }
                            ActionButton {
                                objectName: "stagedContinue_" + messageRow.index
                                visible: !pane.messagePrefix && !!modelData.stagedContinueAvailable && messageRow.index === conversation.count - 1 && !pane.busy && backend.sessionBackend !== "dsh"
                                selectionController: chatSelection
                                text: I18n.t("分阶段继续")
                                glyph: "layers"
                                primary: true
                                onClicked: backend.continueInStages()
                            }
                        }
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
                    Loader {
                        id: compactionLoader
                        active: !modelData._loading && messageRow.compactionNotice
                        visible: active
                        x: 33
                        width: parent.width - 33
                        sourceComponent: Column {
                            id: compactionEvent
                            objectName: "compactionEvent_" + messageRow.index
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
                    }
                    Loader {
                        objectName: "outputLimitNotice_" + messageRow.index
                        active: !modelData._loading && !messageRow.statusNotice && modelData.segmentLast !== false && modelData.role === "assistant" && modelData.stopReason === "length"
                        visible: active
                        x: 33
                        width: parent.width - 33
                        sourceComponent: OutputLimitNotice {
                            continuable: messageRow.index === conversation.count - 1 && !pane.busy
                            onContinued: pane.controller.send(I18n.t("继续刚才未完成的回答，从中断处接着输出，不要重复已有内容。"))
                        }
                    }
                    Loader {
                        active: !modelData._loading && (messageRow.gatewayContinuationNotice || messageRow.networkRetryNotice)
                        visible: active
                        x: 33
                        sourceComponent: Row {
                            objectName: messageRow.gatewayContinuationNotice ? "gatewayContinuationTag" : "networkRetryActivity"
                            spacing: 8
                            Glyph {
                                name: "refresh-cw"
                                color: Theme.muted
                                width: Theme.icon(14)
                                height: width
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Loader {
                                sourceComponent: messageRow.networkRetryNotice ? retryLabel : resumedLabel
                                Component {
                                    id: retryLabel
                                    NetworkRetry { retryState: modelData.networkRetry || ({}) }
                                }
                                Component {
                                    id: resumedLabel
                                    Text {
                                        objectName: "gatewayContinuationText"
                                        text: I18n.t("网关超时，已自动接续")
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.font(13)
                                        color: Theme.muted
                                    }
                                }
                            }
                        }
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
                    Loader {
                        id: closingMascot
                        readonly property string mascotName: pane.messagePrefix === "subagent" ? "subagentReplyMascot_" + messageRow.index : "replyEndMascot_" + messageRow.index
                        readonly property bool eligible: !pane.officeMode && pane.controller.sessionBackend !== "dsh" && !modelData._loading && !messageRow.statusNotice && messageRow.index === conversation.count - 1 && modelData.role === "assistant" && !modelData.error && (modelData.text || "").trim().length > 0 && !pane.running && (pane.turnStatus.state === "finished" || modelData.stopReason === "stop")
                        property bool created: false
                        objectName: active ? "" : mascotName
                        width: Character.id === "doubao" ? Theme.icon(72) : 56
                        active: eligible || created
                        visible: eligible
                        x: 33
                        onLoaded: created = true
                        sourceComponent: ReplyMascot {
                            objectName: closingMascot.mascotName
                            portraitSource: String(pane.replyPortrait).length ? pane.replyPortrait : String(pane.portrait).length ? pane.portrait : Character.asset("reply", "../icons/yanami-pixel.png")
                            interactionLabel: pane.roleSlot >= 0 ? pane.assistantName + (Character.personalityEnabled ? I18n.t("：点击互动，连续点击或长按有彩蛋") : "") : pane.messagePrefix ? pane.assistantName : Character.id === "yanami" ? I18n.t("八奈见：点击互动，连续点击或长按有彩蛋") : Character.style.name
                            tapLines: pane.roleSlot >= 0 ? Character.roleLine(pane.roleSlot, "tap", []) : pane.messagePrefix === "widget" ? [] : Character.scene("reply.tap", [])
                            celebrationLine: pane.roleSlot >= 0 ? Character.roleLine(pane.roleSlot, "celebration", "") : pane.messagePrefix === "widget" ? "" : Character.scene("reply.celebration", "")
                            selectionController: chatSelection
                            captionMaxWidth: Math.max(1, messageRow.width - closingMascot.x - width - 8)
                        }
                    }
                }
            }
            Item {
                anchors.fill: parent
                visible: !rowShell.bodyReady && rowShell.wanted
                Loader {
                    id: loadingIndicator
                    readonly property string spinnerName: "historyLoading_" + rowShell.index
                    objectName: active ? "" : spinnerName
                    active: parent.visible && !rowShell.modelData._loadError
                        && rowShell.y + rowShell.height > conversation.contentY
                        && rowShell.y < conversation.contentY + conversation.height
                    visible: active
                    x: 33
                    y: 16
                    sourceComponent: ActivitySpinner {
                        objectName: loadingIndicator.spinnerName
                        running: pane.current
                    }
                }
                Loader {
                    active: parent.visible && !!rowShell.modelData._loadError
                    visible: active
                    x: 33
                    y: 16
                    sourceComponent: ActionButton {
                        text: I18n.t("重新加载消息")
                        glyph: "refresh-cw"
                        onClicked: pane.messageModel.retryPage(rowShell.index)
                    }
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
        renderGeneration: pane.renderGeneration
        onDecodedImageBytesChanged: if (pane.openAtBottom && !pane.released) imageBudget.restart()
    }
    Timer {
        id: imageBudget
        interval: 0
        onTriggered: if (!pane.released) pane.controller.recordConversationImages(pane.viewKey, chatSelection.decodedImageBytes)
    }
}
