import QtQuick

DropArea {
    id: root
    objectName: "projectDropArea"
    property var listView
    property bool sessionDrop: false
    property string targetProjectId: ""
    property string targetProjectTitle: ""
    function locate(x, y) {
        targetProjectId = ""; targetProjectTitle = ""
        if (!(sessionDrop || backend.cowork.active) || !listView) return
        const point = listView.mapFromItem(root, x, y)
        const index = listView.indexAt(point.x + listView.contentX, point.y + listView.contentY)
        if (index < 0) return
        const row = listView.model[index]
        targetProjectId = row.kind === "project" ? row.id : row.projectId || ""
        const project = listView.model.find(item => item.kind === "project" && item.id === targetProjectId)
        targetProjectTitle = project ? project.title : ""
    }
    onEntered: drag => {
        drag.accepted = drag.urls.length > 0 && !backend.sessionFiles.busy
        sessionDrop = drag.urls.some(url => /\.jsonl$/i.test(url.toString()))
        if (backend.cowork.active) {
            drag.accepted = drag.urls.length === 1 && backend.cowork.folderPath(drag.urls[0].toString()) !== ""
            sessionDrop = false
        }
        locate(drag.x, drag.y)
    }
    onPositionChanged: drag => locate(drag.x, drag.y)
    onExited: { targetProjectId = ""; targetProjectTitle = "" }
    onDropped: drop => {
        locate(drop.x, drop.y)
        if (backend.cowork.active)
            backend.cowork.requestCreate(targetProjectId, drop.urls[0].toString())
        else
            backend.dropProjects(JSON.stringify(drop.urls.map(url => url.toString())), targetProjectId)
        drop.accept(Qt.CopyAction)
        targetProjectId = ""; targetProjectTitle = ""
    }
}
