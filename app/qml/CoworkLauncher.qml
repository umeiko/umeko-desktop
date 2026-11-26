import QtQuick
import QtQuick.Controls

Popup {
    id: root
    objectName: "coworkLauncher"
    required property var service
    signal abilityChosen(string id)
    signal sessionChosen(var row)
    width: Math.max(0, Math.min(580, parent.width - 48))
    x: Math.round((parent.width - width) / 2)
    y: Math.max(32, Math.round((parent.height - height) * 0.35))
    height: Theme.control(66) + list.height + Theme.control(37)
    modal: true
    focus: true
    padding: 0
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    readonly property bool chinese: backend.language !== "en"
    function label(zh, en) { return chinese ? zh : en }
    function matches(query, value) {
        return !query || query.split(/\s+/).every(term => value.toLowerCase().includes(term))
    }
    function makeRows() {
        const query = field.text.trim().toLowerCase()
        const out = []
        const alias = row => row.id === "data" ? "表格 spreadsheet excel" : ""
        const score = row => matches(query, row.name + " " + alias(row)) ? 0 : 1
        const abilities = service.catalog.filter(row => matches(query, row.name + " " + row.description + " " + alias(row)))
            .sort((left, right) => score(left) - score(right)).slice(0, query ? 8 : 4)
        const sessions = service.recent.filter(row => matches(query, row.title)).slice(0, query ? 6 : 3)
        for (let i = 0; i < abilities.length; i++)
            out.push({key: abilities[i].id, text: abilities[i].name, icon: abilities[i].icon, ability: true,
                      group: i === 0 ? label("能力", "Capabilities") : ""})
        for (let i = 0; i < sessions.length; i++)
            out.push({key: sessions[i].id, text: sessions[i].title, icon: "chat", ability: false,
                      row: sessions[i], group: i === 0 ? label("最近工作", "Recent work") : ""})
        return out
    }
    readonly property var results: makeRows()
    function choose(index) {
        if (!results.length) return
        if (index < 0) index = 0
        if (index >= results.length) return
        const row = results[index]
        close()
        if (row.ability) abilityChosen(row.key)
        else sessionChosen(row.row)
    }
    function move(step) {
        if (!results.length) return
        list.currentIndex = Math.min(results.length - 1, Math.max(0, list.currentIndex + step))
        list.positionViewAtIndex(list.currentIndex, ListView.Contain)
    }
    onResultsChanged: list.currentIndex = results.length ? 0 : -1
    onOpened: { field.clear(); list.currentIndex = results.length ? 0 : -1; field.forceActiveFocus() }
    background: Rectangle { radius: 12; color: Theme.surface; border.color: Theme.line }
    Overlay.modal: Rectangle { color: Qt.alpha(Theme.bg, Theme.dark ? 0.66 : 0.55) }
    contentItem: Item {
        Glyph { name: "search"; x: 17; y: Theme.control(19); width: Theme.icon(16); height: width }
        TextField {
            id: field; objectName: "coworkLauncherInput"
            x: 40; width: parent.width - 90; height: Theme.control(55)
            font.family: Theme.fontFamily; font.pixelSize: Theme.font(14, visible)
            selectByMouse: true; color: Theme.ink; placeholderTextColor: Theme.muted
            placeholderText: root.label("搜索能力或最近工作", "Find a capability or recent work")
            background: null
            Keys.onPressed: event => {
                if (inputMethodComposing) return
                if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                    root.choose(list.currentIndex); event.accepted = true
                } else if (event.key === Qt.Key_Down || event.key === Qt.Key_Up) {
                    root.move(event.key === Qt.Key_Down ? 1 : -1); event.accepted = true
                }
            }
            onAccepted: if (!inputMethodComposing) root.choose(list.currentIndex)
        }
        ActionButton {
            x: parent.width - 44; y: Theme.control(12); width: 33; height: Theme.control(30)
            quiet: true; glyph: "x"; hint: root.label("关闭", "Close"); onClicked: root.close()
        }
        Rectangle { x: 1; y: Theme.control(55); width: parent.width - 2; height: 1; color: Theme.line }
        Text {
            visible: !root.results.length; x: 18; y: Theme.control(75)
            text: root.label("没有找到匹配项", "No matches"); color: Theme.muted
            font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible)
        }
        ListView {
            id: list
            x: 9; y: Theme.control(61); width: parent.width - 18
            height: Math.min(Theme.control(282), Math.max(Theme.control(54), contentHeight))
            clip: true; model: root.results; boundsBehavior: Flickable.StopAtBounds; interactive: contentHeight > height
            delegate: Item {
                id: cell
                required property var modelData
                required property int index
                width: list.width; height: Theme.control(modelData.group ? 58 : 34)
                Text {
                    x: 10; y: 1; visible: !!cell.modelData.group; text: cell.modelData.group
                    color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(10, visible)
                }
                ActionButton {
                    objectName: "coworkLaunch_" + cell.modelData.key
                    x: 0; width: parent.width; height: Theme.control(33); anchors.bottom: parent.bottom
                    quiet: true; text: cell.modelData.text; glyph: cell.modelData.icon; hint: text
                    background: Rectangle { radius: 6; color: Math.max(0, list.currentIndex) === cell.index ? Theme.accentBg : parent.interactionHovered ? Theme.hover : "transparent" }
                    contentItem: Item {
                        Glyph { x: 11; anchors.verticalCenter: parent.verticalCenter; name: cell.modelData.icon
                            width: Theme.icon(15); height: width }
                        Text {
                            x: 34; width: parent.width - x - 11; anchors.verticalCenter: parent.verticalCenter
                            text: cell.modelData.text; elide: Text.ElideRight; textFormat: Text.PlainText
                            color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible)
                        }
                    }
                    onClicked: root.choose(cell.index)
                }
            }
        }
        Rectangle { x: 1; y: parent.height - Theme.control(33); width: parent.width - 2; height: 1; color: Theme.line }
        Text {
            x: 17; anchors.bottom: parent.bottom; anchors.bottomMargin: Theme.control(10)
            text: root.label("草稿和附件保留", "Draft and attachments stay intact")
            font.family: Theme.fontFamily; font.pixelSize: Theme.font(10, visible); color: Theme.muted
        }
    }
}
