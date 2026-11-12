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
        if (!sessionDrop || !listView) return
        const point = listView.mapFromItem(root, x, y)
        const index = listView.indexAt(point.x + listView.contentX, point.y + listView.contentY)
        if (index < 0) return
        const row = backend.projectRows[index]
        targetProjectId = row.kind === "project" ? row.id : row.projectId || ""
        const project = backend.projectRows.find(item => item.kind === "project" && item.id === targetProjectId)
        targetProjectTitle = project ? project.title : ""
    }
    onEntered: drag => {
        drag.accepted = drag.urls.length > 0 && !backend.sessionFiles.busy
        sessionDrop = drag.urls.some(url => /\.jsonl$/i.test(url.toString()))
        locate(drag.x, drag.y)
    }
    onPositionChanged: drag => locate(drag.x, drag.y)
    onExited: { targetProjectId = ""; targetProjectTitle = "" }
    onDropped: drop => {
        locate(drop.x, drop.y)
        backend.dropProjects(JSON.stringify(drop.urls.map(url => url.toString())), targetProjectId)
        drop.accept(Qt.CopyAction)
        targetProjectId = ""; targetProjectTitle = ""
    }
}
