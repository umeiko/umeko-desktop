import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

AnchoredPidPopup {
    id: root
    objectName: "subagentMatrix"
    property var agents: []
    fullWidth: 740
    fullHeight: Math.min(560, Theme.control(52)+Math.ceil(agents.length/grid.columns)*grid.cellHeight+padding*2)
    openBelow: Overlay.overlay ? anchorPosition.y < Overlay.overlay.height/2 : false
    padding: 12
    contentItem: Item {
        clip: true
        ColumnLayout {
            width: root.expandedWidth-root.padding*2; height: root.expandedHeight-root.padding*2
            opacity: root.contentOpacity; spacing: 10
            RowLayout {
                Layout.fillWidth: true
                Text { Layout.fillWidth: true; text: I18n.t("%1 个子智能体").replace("%1",root.agents.length); color: Theme.ink; font.pixelSize: Theme.font(13); elide: Text.ElideRight }
                ActionButton { objectName: "closeSubagentMatrix"; glyph: "x"; quiet: true; width: Theme.control(28); height: width; onClicked: root.close() }
            }
            GridView {
                id: grid; objectName: "subagentMatrixGrid"
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true; cacheBuffer: 150
                readonly property int columns: Math.max(1,Math.floor(width/Theme.control(260)))
                cellWidth: width/columns; cellHeight: Theme.control(82)
                model: root.agents
                ScrollBar.vertical: ScrollBar {}
                delegate: SubagentTile {
                    required property var modelData
                    objectName: "matrixSubagent_" + modelData.id
                    width: grid.cellWidth-8; height: grid.cellHeight-8
                    agent: backend.subagents.agents.find(row => row.id === modelData.id) || modelData
                    onActivated: { root.close(); backend.subagents.open(modelData.id) }
                }
            }
        }
    }
}
