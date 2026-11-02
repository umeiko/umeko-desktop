import QtQuick
import QtQuick.Window

Window {
    id: window
    width: 480; height: 600; visible: true
    property bool failInventory: false
    property bool registryReady: false
    property bool registryFailed: false
    property int statusRequests: 0
    property int inventoryRequests: 0
    readonly property var page: content.item
    readonly property bool tagsReady: !!page && page.rows.length === 1 && page.rows[0].tools.length === 2
    QtObject {
        id: bridge
        property bool active: true
        property var session: ({token:"cold-start",workspace:"/fixture",busy:false})
        property var colors: ({bg:"#fcfcfa",surface:"#ffffff",ink:"#27312c",muted:"#858e88",line:"#e3e7df",hover:"#f2f4ef",accent:"#345d47",accentBg:"#e9f0e8",danger:"#ba3c42",dark:false})
        property real scale: 1
        property string language: "zh"
        property var hostCapabilities: ({operations:{"pi.status":{},"pi.inventory":{}}})
        property int sequence: 0
        signal hostResponse(string request, var value)
        function requestHost(operation, args) {
            const id = "request-" + (++sequence)
            Qt.callLater(function() {
                if (operation === "pi.inventory") {
                    window.inventoryRequests++
                    registryDelay.restart()
                    bridge.hostResponse(id,{ok:true})
                } else if (operation === "pi.status") {
                    window.statusRequests++
                    // An idle status can precede the asynchronous resource catalog.
                    // No detail click or session-change event refreshes this fixture.
                    const tools = window.registryReady ? [{name:"enabled_tool",visible:true},{name:"disabled_tool",visible:false}] : []
                    bridge.hostResponse(id,{ok:true,result:{contextCurrent:true,busy:false,agentBusy:false,
                        inventoryReady:window.registryReady,inventoryFailed:window.registryFailed,
                        extensions:[{id:"fixture",name:"Fixture",path:"/fixture",enabled:true,info:{},tools:tools,toolCount:tools.length}],
                        total:1,hasMore:false}})
                }
            })
            return id
        }
    }
    Timer {
        id: registryDelay; interval: 1100
        onTriggered: {window.registryReady=!window.failInventory;window.registryFailed=window.failInventory}
    }
    Loader {
        id: content; anchors.fill: parent
        Component.onCompleted: setSource(Qt.resolvedUrl("../../umeko-plugins/pi-manager/qml/Main.qml"),{sdk:bridge})
    }
}
