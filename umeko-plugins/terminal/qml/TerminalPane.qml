import QtQuick
import QtQuick.Controls
import Umeko.Terminal 1.0
Rectangle {
    id: pane
    required property var sdk
    required property string terminalId
    required property var sendRequest
    property bool ready: false
    property var pendingFrames: []
    property string inputBuffer: ""
    property int columns: 80
    property int rows: 24
    readonly property alias hasSelection: screen.hasSelection
    signal reloadRequested()
    signal menuRequested(real x, real y)
    signal failed(string message)
    signal activated()
    color: sdk.colors.dark ? "#1e1e1e" : "#ffffff"
    function snapshot(frame) {
        screen.applyFrame(frame)
        ready = true
        const queued = pendingFrames; pendingFrames = []
        for (const value of queued) if (value.revision > frame.revision) receive(value)
    }
    function receive(frame) {
        if (!ready) { pendingFrames = pendingFrames.concat([frame]).slice(-32); return }
        if (frame.resync) { ready = false; reloadRequested(); return }
        screen.applyFrame(frame)
    }
    function copy() { screen.copy() }
    function paste() { screen.paste() }
    function selectAll() { screen.selectAll() }
    function focusTerminal() { screen.forceActiveFocus() }
    Connections {
        target: pane.sdk
        function onEvent(topic, data) {
            if (topic === "terminal.frame" && data.terminalId === pane.terminalId) pane.receive(data)
        }
    }
    TerminalView {
        id: screen
        objectName: "terminalScreen_" + pane.terminalId
        anchors.fill: parent
        fontSize: (pane.sdk.config.fontSize || 12) * pane.sdk.scale
        fontFamily: pane.sdk.config.fontFamily || ""
        backgroundColor: pane.color
        foregroundColor: pane.sdk.colors.dark ? "#d4d4d4" : "#202020"
        cursorColor: "#2684ff"
        onActiveFocusChanged: if(activeFocus)pane.activated()
        onInput: text => { pane.inputBuffer += text; inputTimer.restart() }
        onInputRejected: message => pane.failed(message)
        onResized: (columns, rows) => { pane.columns = columns; pane.rows = rows; resizeTimer.restart() }
        onContextMenuRequested: (x,y) => pane.menuRequested(x,y)
    }
    Timer { id: inputTimer; interval: 8; onTriggered: {
        let count=Math.min(16000,pane.inputBuffer.length)
        if(count<pane.inputBuffer.length && count>0 && pane.inputBuffer.charCodeAt(count-1)>=0xd800 && pane.inputBuffer.charCodeAt(count-1)<=0xdbff)count--
        const text=pane.inputBuffer.slice(0,count)
        if(text && pane.sendRequest("input",{terminalId:pane.terminalId,text:text}))pane.inputBuffer=pane.inputBuffer.slice(count)
        if(pane.inputBuffer)restart()
    } }
    Timer { id: resizeTimer; interval: 100; onTriggered: pane.sendRequest("resize", {terminalId:pane.terminalId,columns:pane.columns,rows:pane.rows}) }
    Text { anchors.centerIn: parent; visible: !pane.ready; text: pane.sdk.language === "en" ? "Connecting terminal…" : "正在连接终端…"; color: pane.sdk.colors.muted; font.pixelSize: 12 * pane.sdk.scale }
}
