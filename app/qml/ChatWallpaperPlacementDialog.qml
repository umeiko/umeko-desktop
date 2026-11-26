import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

PidPopup {
    id: root
    objectName: "wallpaperPlacementDialog"
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(800, parent.width - 32)
    height: Math.min(Theme.control(544), parent.height - 32)
    closePolicy: Popup.NoAutoClose
    required property string source
    required property string mode
    required property real chatAspect
    property int zoom: 100
    property real offsetX: 0
    property real offsetY: 0
    property real angle: 0
    signal placementAccepted(var adjustment)

    Shortcut { sequence: "Escape"; enabled: root.desiredOpen; onActivated: root.close() }

    function setPlacement(options) {
        zoom = options.zoom
        offsetX = options.offsetX
        offsetY = options.offsetY
        angle = options.angle
    }
    function begin(options) {
        setPlacement(options)
        open()
    }
    function bounded(value, low, high) { return Math.max(low, Math.min(high, value)) }
    function setOffset(x, y) {
        offsetX = bounded(x, -1, 1)
        offsetY = bounded(y, -1, 1)
    }
    function zoomAt(value, point) {
        const next = bounded(Math.round(value), 50, 200)
        const ratio = next / zoom
        const dx = (scene.imageCenter.x - point.x) * (ratio - 1)
        const dy = (scene.imageCenter.y - point.y) * (ratio - 1)
        setOffset(offsetX + dx / aperture.width, offsetY + dy / aperture.height)
        zoom = next
    }
    function angleAt(point) {
        return Math.atan2(point.y - scene.imageCenter.y, point.x - scene.imageCenter.x) * 180 / Math.PI
    }
    function distanceToCenter(point) {
        return Math.hypot(point.x - scene.imageCenter.x, point.y - scene.imageCenter.y)
    }
    function handlePoint(x, y) {
        const radians = angle * Math.PI / 180
        const cosine = Math.cos(radians)
        const sine = Math.sin(radians)
        return Qt.point(bounded(scene.imageCenter.x + x * cosine - y * sine, 16, scene.width - 16),
                        bounded(scene.imageCenter.y + x * sine + y * cosine, 16, scene.height - 16))
    }

    contentItem: Item {
        ColumnLayout {
            anchors.fill: parent
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    text: I18n.t("大小与位置"); color: Theme.ink
                    font.family: Theme.fontFamily; font.pixelSize: Theme.font(19); font.weight: Font.DemiBold
                }
                ActionButton { glyph: "x"; quiet: true; hint: I18n.t("关闭"); Accessible.name: hint; onClicked: root.close() }
            }
            Text {
                Layout.fillWidth: true
                text: I18n.t("拖动图片移动，滚轮或角点缩放，拖动圆形手柄旋转。")
                color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12); wrapMode: Text.Wrap
            }
            Rectangle {
                id: scene
                objectName: "wallpaperPlacementCanvas"
                Layout.fillWidth: true; Layout.fillHeight: true
                color: Theme.bg; border.color: Theme.line; radius: 10; clip: true
                readonly property point imageCenter: Qt.point(aperture.x + aperture.width * (0.5 + root.offsetX),
                                                              aperture.y + aperture.height * (0.5 + root.offsetY))
                Item {
                    id: aperture
                    objectName: "wallpaperPlacementFrame"
                    anchors.centerIn: parent
                    width: Math.max(1, Math.min(scene.width - 80, (scene.height - 80) * root.chatAspect))
                    height: width / root.chatAspect
                    ChatWallpaperLayer {
                        objectName: "wallpaperPlacementImage"
                        anchors.fill: parent
                        clip: false
                        source: root.visible ? root.source : ""
                        useCharacter: root.visible && root.source === ""
                        mode: root.mode; strength: 100; zoom: root.zoom
                        offsetX: root.offsetX; offsetY: root.offsetY; angle: root.angle
                    }
                }
                Repeater {
                    model: [
                        Qt.rect(0, 0, scene.width, aperture.y),
                        Qt.rect(0, aperture.y + aperture.height, scene.width, aperture.y),
                        Qt.rect(0, aperture.y, aperture.x, aperture.height),
                        Qt.rect(aperture.x + aperture.width, aperture.y, aperture.x, aperture.height)
                    ]
                    Rectangle {
                        required property rect modelData
                        x: modelData.x; y: modelData.y; width: modelData.width; height: modelData.height
                        color: Qt.alpha(Theme.bg, 0.79)
                    }
                }
                Rectangle {
                    anchors.fill: aperture
                    color: "transparent"; border.color: Theme.accent
                }
                MouseArea {
                    id: pan
                    objectName: "wallpaperPlacementPan"
                    anchors.fill: parent
                    cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                    property point lastPoint
                    onPressed: event => lastPoint = Qt.point(event.x, event.y)
                    onPositionChanged: event => {
                        if (!pressed) return
                        root.setOffset(root.offsetX + (event.x - lastPoint.x) / aperture.width,
                                       root.offsetY + (event.y - lastPoint.y) / aperture.height)
                        lastPoint = Qt.point(event.x, event.y)
                    }
                    onWheel: event => {
                        const steps = event.angleDelta.y ? event.angleDelta.y / 120 : event.pixelDelta.y / 80
                        root.zoomAt(root.zoom * Math.pow(1.12, steps), Qt.point(event.x, event.y))
                        event.accepted = true
                    }
                }
                Rectangle {
                    id: scaleHandle
                    readonly property point position: root.handlePoint(aperture.width * root.zoom / 200,
                                                                       aperture.height * root.zoom / 200)
                    x: position.x - width / 2; y: position.y - height / 2
                    width: 18; height: width; radius: 4
                    color: Theme.surface; border.color: Theme.accent; border.width: 2
                    MouseArea {
                        objectName: "wallpaperPlacementScaleHandle"
                        anchors.fill: parent; anchors.margins: -4
                        cursorShape: Qt.SizeFDiagCursor
                        property real initialDistance: 1
                        property real initialZoom: 100
                        onPressed: event => {
                            initialZoom = root.zoom
                            initialDistance = Math.max(1, root.distanceToCenter(mapToItem(scene, event.x, event.y)))
                        }
                        onPositionChanged: event => {
                            if (!pressed) return
                            const distance = root.distanceToCenter(mapToItem(scene, event.x, event.y))
                            root.zoomAt(initialZoom * distance / initialDistance, scene.imageCenter)
                        }
                    }
                }
                Rectangle {
                    id: rotateHandle
                    readonly property point position: root.handlePoint(0, -aperture.height * root.zoom / 200 - 24)
                    x: position.x - width / 2; y: position.y - height / 2
                    width: 28; height: width; radius: width / 2
                    color: Theme.surface; border.color: Theme.accent
                    Glyph { name: "refresh-cw"; anchors.centerIn: parent; width: 15; height: width; color: Theme.accent }
                    MouseArea {
                        objectName: "wallpaperPlacementRotateHandle"
                        anchors.fill: parent; anchors.margins: -3
                        cursorShape: pressed ? Qt.ClosedHandCursor : Qt.PointingHandCursor
                        property real previousAngle: 0
                        onPressed: event => previousAngle = root.angleAt(mapToItem(scene, event.x, event.y))
                        onPositionChanged: event => {
                            if (!pressed) return
                            const point = mapToItem(scene, event.x, event.y)
                            if (root.distanceToCenter(point) < 12) return
                            const next = root.angleAt(point)
                            root.angle = ((root.angle + next - previousAngle + 540) % 360) - 180
                            previousAngle = next
                        }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                ActionButton {
                    objectName: "resetWallpaperPlacement"
                    text: I18n.t("恢复默认"); quiet: true
                    enabled: root.zoom !== 100 || root.offsetX !== 0 || root.offsetY !== 0 || root.angle !== 0
                    onClicked: root.setPlacement({zoom: 100, offsetX: 0, offsetY: 0, angle: 0})
                }
                Text {
                    Layout.fillWidth: true
                    text: root.zoom + "%  ·  " + Math.round(root.angle) + "°"
                    color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                }
                ActionButton { objectName: "cancelWallpaperPlacement"; text: I18n.t("取消"); quiet: true; onClicked: root.close() }
                ActionButton {
                    objectName: "acceptWallpaperPlacement"
                    text: I18n.t("完成"); primary: true
                    onClicked: {
                        root.placementAccepted({
                            zoom: root.zoom, angle: Math.round(root.angle * 10) / 10,
                            offsetX: Math.round(root.offsetX * 10000) / 10000,
                            offsetY: Math.round(root.offsetY * 10000) / 10000
                        })
                        root.close()
                    }
                }
            }
        }
    }
}
