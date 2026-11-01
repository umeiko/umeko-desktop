import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Controls.impl

Rectangle {
    id: root
    objectName: "compactCommandMenu"
    property var entries: []
    property string query: ""
    property int selectedIndex: 0
    property real maximumHeight: 360
    readonly property string normalizedQuery: query.trim().replace(/^\//, "").trim().toLowerCase()
    readonly property string queryHead: normalizedQuery.split(/\s+/)[0]
    readonly property bool skillScope: queryHead.length > 0 && "skills".startsWith(queryHead)
    readonly property string needle: skillScope ? normalizedQuery.slice(queryHead.length).trim() : normalizedQuery
    function matchesName(entry) {
        const prefixOnly = /[a-z0-9]/.test(needle)
        return [entry.title, entry.command || ""].some(value => {
            const name = value.replace(/^\//, "").toLowerCase()
            return prefixOnly ? name.startsWith(needle) : name.includes(needle)
        })
    }
    function matchedPinyin(entry) {
        if (!needle || !/^[a-z]+$/.test(needle)) return ""
        // Only the displayed title's pronunciation, never descriptions or aliases.
        const syllables = entry.titlePinyin || []
        const full = syllables.join("").toLowerCase()
        const initials = syllables.map(part => part.charAt(0)).join("").toLowerCase()
        return full.startsWith(needle) || initials.startsWith(needle) ? syllables.join(" ") : ""
    }
    readonly property var matches: entries.filter(entry => {
        if (skillScope && entry.group !== "技能" && !(entry.group === "Widgets" && entry.widgetId === "skill-manager")) return false
        return !needle || matchesName(entry) || matchedPinyin(entry)
    })
    readonly property var rows: {
        let result = [], index = 0
        for (const group of ["命令", "Widgets", "技能"]) {
            const values = matches.filter(entry => entry.group === group)
            if (!values.length) continue
            result.push({heading: group})
            for (const entry of values) result.push({entry: entry, index: index++})
        }
        return result
    }
    readonly property real rowHeight: Theme.control(33)
    readonly property real headingHeight: Theme.control(25)
    readonly property real naturalHeight: rows.reduce((height, row) => height + (row.heading ? headingHeight : rowHeight), 16)
    signal chosen(var entry)
    function moveSelection(delta) {
        if (!matches.length) return
        selectedIndex = (selectedIndex + delta + matches.length) % matches.length
        revealSelection()
    }
    function revealSelection() {
        const index = rows.findIndex(row => row.entry && row.index === selectedIndex)
        if (index >= 0) listing.positionViewAtIndex(index, ListView.Contain)
    }
    function chooseSelection() {
        const row = rows.find(row => row.entry && row.index === selectedIndex)
        if (row) chosen(row.entry)
    }
    onQueryChanged: { selectedIndex = 0; listing.contentY = 0 }
    onEntriesChanged: { selectedIndex = 0; listing.contentY = 0 }
    width: 850
    height: Math.min(maximumHeight, Math.max(Theme.control(66), naturalHeight))
    radius: 16
    color: Theme.surface
    border.color: Theme.line
    clip: true

    ListView {
        id: listing
        objectName: "compactCommandList"
        anchors.fill: parent
        anchors.margins: 8
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: root.rows
        reuseItems: true
        delegate: Item {
            id: row
            required property var modelData
            width: listing.width
            height: modelData.heading ? root.headingHeight : root.rowHeight
            readonly property bool selected: !!modelData.entry && root.selectedIndex === modelData.index
            Text {
                visible: !!row.modelData.heading
                x: 7; anchors.verticalCenter: parent.verticalCenter
                text: I18n.t(row.modelData.heading || "")
                color: Theme.muted
                font.pixelSize: Theme.font(11)
            }
            Rectangle {
                anchors.fill: parent
                anchors.rightMargin: 6
                visible: !!row.modelData.entry && row.selected
                radius: height / 2
                color: Theme.dark ? "#303631" : "#f0f2f0"
            }
            RowLayout {
                visible: !!row.modelData.entry
                anchors.fill: parent
                anchors.leftMargin: 9; anchors.rightMargin: 20
                spacing: 10
                Glyph {
                    visible: !!row.modelData.entry && row.modelData.entry.icon !== "skill" && !row.modelData.entry.iconSource
                    name: row.modelData.entry && row.modelData.entry.icon !== "skill" ? row.modelData.entry.icon : ""
                    color: row.selected ? Theme.ink : Theme.muted
                    Layout.preferredWidth: Theme.icon(17)
                    Layout.preferredHeight: Theme.icon(17)
                }
                IconImage {
                    visible: !!row.modelData.entry && (row.modelData.entry.icon === "skill" || !!row.modelData.entry.iconSource)
                    source: visible ? row.modelData.entry.iconSource || Qt.resolvedUrl("skill.svg") : ""
                    sourceSize: Qt.size(48, 48)
                    color: row.selected ? Theme.ink : Theme.muted
                    Layout.preferredWidth: Theme.icon(17)
                    Layout.preferredHeight: Theme.icon(17)
                }
                Text {
                    text: row.modelData.entry ? row.modelData.entry.title : ""
                    color: Theme.ink
                    font.pixelSize: Theme.font(13)
                    textFormat: Text.PlainText
                    elide: Text.ElideRight
                    Layout.maximumWidth: root.width * 0.34
                }
                Text {
                    readonly property string pronunciation: row.modelData.entry && !root.matchesName(row.modelData.entry)
                        ? root.matchedPinyin(row.modelData.entry) : ""
                    visible: pronunciation.length > 0
                    text: pronunciation
                    color: Theme.muted
                    font.pixelSize: Theme.font(11)
                    textFormat: Text.PlainText
                    elide: Text.ElideRight
                    Layout.maximumWidth: root.width * 0.25
                }
                Text {
                    text: row.modelData.entry ? row.modelData.entry.description : ""
                    color: Theme.muted
                    font.pixelSize: Theme.font(12)
                    textFormat: Text.PlainText
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
                Text {
                    text: row.modelData.entry ? row.modelData.entry.scope || "" : ""
                    color: Theme.muted
                    font.pixelSize: Theme.font(11)
                    textFormat: Text.PlainText
                }
            }
            MouseArea {
                anchors.fill: parent
                enabled: !!row.modelData.entry
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onPositionChanged: root.selectedIndex = row.modelData.index
                onClicked: root.chosen(row.modelData.entry)
            }
            Accessible.role: modelData.heading ? Accessible.Heading : Accessible.ListItem
            Accessible.name: modelData.heading || (modelData.entry.title + "，" + modelData.entry.description)
            Accessible.selected: selected
            Accessible.onPressAction: if (modelData.entry) root.chosen(modelData.entry)
        }
        ScrollBar.vertical: ScrollBar {
            width: 4
            policy: ScrollBar.AsNeeded
            opacity: listing.contentHeight > listing.height ? 1 : 0
            contentItem: Rectangle { implicitWidth: 4; radius: 2; color: Theme.muted; opacity: 0.28 }
            background: null
        }
    }
    Text {
        anchors.centerIn: parent
        visible: root.matches.length === 0
        text: I18n.t(root.skillScope ? (root.needle ? "没有匹配的技能" : "没有可用的技能或 Skills Widget") : "没有匹配项")
        color: Theme.muted
        font.pixelSize: Theme.font(12)
    }
}
