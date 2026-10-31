import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    objectName: "contextUsageIndicator"
    property var usage: {
        const current = backend.contextUsage
        return current.model === backend.config.selectedModel ? current : ({})
    }
    readonly property bool known: usage.tokens !== undefined && usage.tokens !== null && usage.contextWindow > 0 && typeof usage.percent === "number"
    readonly property real fraction: known ? Math.max(0, Math.min(1, usage.percent / 100)) : 0
    readonly property color ringColor: !known ? Theme.muted : usage.percent >= 90 ? Theme.danger : usage.percent >= 75 ? (Theme.dark ? "#d6b66c" : "#b98a37") : Theme.accent
    readonly property string description: known ? I18n.t("上下文约使用 ") + usage.percent.toFixed(1) + "%\n" + Math.round(usage.tokens).toLocaleString(Qt.locale(), "f", 0) + " / " + usage.contextWindow.toLocaleString(Qt.locale(), "f", 0) + " tokens" : usage.contextWindow > 0 ? I18n.t("上下文用量待更新\n窗口：") + usage.contextWindow.toLocaleString(Qt.locale(), "f", 0) + " tokens" : I18n.t("上下文用量待更新")
    width: Theme.control(25); height: Theme.control(31)
    Canvas {
        id: ring; objectName: "contextUsageRing"
        width: Theme.icon(14); height: Theme.icon(14); anchors.centerIn: parent
        property color track: Theme.line
        property color stroke: root.ringColor
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onTrackChanged: requestPaint()
        onStrokeChanged: requestPaint()
        onPaint: {
            const ctx = getContext("2d"), center = width / 2, radius = center - 1.3
            ctx.reset(); ctx.lineWidth = 1.8 * Theme.fontScale; ctx.lineCap = "round"
            ctx.beginPath(); ctx.strokeStyle = track; ctx.arc(center, center, radius, 0, 2 * Math.PI); ctx.stroke()
            if (root.known && root.fraction > 0) {
                ctx.beginPath(); ctx.strokeStyle = stroke
                ctx.arc(center, center, radius, -Math.PI / 2, -Math.PI / 2 + root.fraction * 2 * Math.PI); ctx.stroke()
            }
        }
    }
    onFractionChanged: ring.requestPaint()
    onKnownChanged: ring.requestPaint()
    Accessible.role: Accessible.Button; Accessible.name: root.description
    MouseArea {
        id: hover; objectName: "contextUsageMouse"
        anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
        onClicked: compactPopup.toggle()
    }
    ToolTip {
        objectName: "contextUsageTooltip"
        parent: root; x: 0; y: -height - 8; margins: 12; padding: 12
        visible: hover.containsMouse && !compactPopup.visible; delay: 250
        background: Rectangle { radius: 8; color: Theme.ink }
        contentItem: Text { font.family: Theme.fontFamily; text: root.description; color: Theme.bg; font.pixelSize: Theme.font(11); lineHeight: 1.5 }
    }
    AnchoredPidPopup {
        id: compactPopup; objectName: "compactContextPopup"
        parent: root
        fullWidth: 320
        fullHeight: popupContents.implicitHeight + padding * 2
        contentItem: Item {
            clip: true
            ColumnLayout {
                id: popupContents
                width: compactPopup.expandedWidth - compactPopup.padding * 2
                spacing: 10; opacity: compactPopup.contentOpacity
                Text { font.family: Theme.fontFamily;
                    Layout.fillWidth: true; text: root.description
                    color: Theme.muted; font.pixelSize: Theme.font(11); lineHeight: 1.5; wrapMode: Text.Wrap
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
                ActionButton {
                    objectName: "compactContextAction"
                    Layout.fillWidth: true; quiet: true
                    text: I18n.t("压缩上下文")
                    enabled: backend.compactionAvailable && !backend.busy && !!backend.activeSession
                    onClicked: { compactPopup.close(); backend.compactSession() }
                }
                Text { font.family: Theme.fontFamily;
                    visible: backend.busy
                    Layout.fillWidth: true
                    text: I18n.t("仅在当前任务结束后可压缩上下文。")
                    color: Theme.muted; font.pixelSize: Theme.font(10); wrapMode: Text.Wrap
                }
            }
        }
    }
}
