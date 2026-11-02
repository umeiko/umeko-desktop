import QtQuick
import QtQuick.Controls
import QtQuick.Window

Popup {
    id: root
    objectName: "imagePreview"
    parent: Overlay.overlay
    x: 0; y: 0; width: parent ? parent.width : 1; height: parent ? parent.height : 1
    padding: 0; margins: 0; modal: true; focus: true; dim: false
    closePolicy: Popup.CloseOnEscape
    property var images: []
    property int currentIndex: 0
    readonly property var current: images[currentIndex] || ({})
    property real zoom: 1
    property real panX: 0
    property real panY: 0
    function resetView() { zoom = 1; panX = 0; panY = 0 }
    function show(item, siblings) {
        images = (siblings || [item]).filter(value => value.kind === "image" && value.preview && value.url)
        currentIndex = Math.max(0, images.findIndex(value => value.path === item.path))
        resetView(); open()
    }
    function step(delta) { currentIndex = (currentIndex + delta + images.length) % images.length; resetView() }
    onClosed: { images = []; resetView() }
    background: Rectangle { color: "#bd171b22" }
    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 120 } }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 90 } }
    contentItem: Item {
        Item {
            id: stage; objectName: "imagePreviewStage"; anchors.fill: parent; clip: true
            Image {
                id: picture; objectName: "imagePreviewPicture"
                readonly property real ratio: Math.min((stage.width - 96) / Math.max(1, root.current.pixelWidth || 1), (stage.height - 142) / Math.max(1, root.current.pixelHeight || 1), 1)
                width: Math.max(1, root.current.pixelWidth || 1) * ratio * root.zoom
                height: Math.max(1, root.current.pixelHeight || 1) * ratio * root.zoom
                x: (stage.width - width) / 2 + root.panX; y: (stage.height - height) / 2 + root.panY
                source: root.visible ? root.current.url || "" : ""
                sourceSize: Qt.size(Math.min(4096, root.current.pixelWidth || 4096), Math.min(4096, root.current.pixelHeight || 4096))
                asynchronous: true; cache: false; autoTransform: true; fillMode: Image.PreserveAspectFit
            }
            MouseArea {
                id: pan; objectName: "imagePreviewPan"; anchors.fill: parent
                acceptedButtons: Qt.LeftButton | Qt.RightButton; hoverEnabled: true; preventStealing: true
                cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                property point pressedAt: Qt.point(0, 0)
                property point originalPan: Qt.point(0, 0)
                property bool moved: false
                onPressed: mouse => { pressedAt = Qt.point(mouse.x, mouse.y); originalPan = Qt.point(root.panX, root.panY); moved = false }
                onPositionChanged: mouse => {
                    if (!pressed || !(pressedButtons & Qt.LeftButton)) return
                    const dx = mouse.x - pressedAt.x, dy = mouse.y - pressedAt.y
                    if (Math.abs(dx) + Math.abs(dy) >= 6) moved = true
                    if (moved) { root.panX = originalPan.x + dx; root.panY = originalPan.y + dy }
                }
                onClicked: mouse => { if (mouse.button === Qt.RightButton) previewMenu.popup(mouse.x, mouse.y); else if (!moved) root.close() }
                onWheel: wheel => {
                    const delta = wheel.angleDelta.y || wheel.pixelDelta.y
                    if (!delta) return
                    const next = Math.max(0.25, Math.min(8, root.zoom * Math.pow(1.18, delta / 120)))
                    const ratio = next / root.zoom, x = wheel.x - width / 2, y = wheel.y - height / 2
                    root.panX = x - (x - root.panX) * ratio; root.panY = y - (y - root.panY) * ratio
                    root.zoom = next; wheel.accepted = true
                }
            }
            BusyIndicator { anchors.centerIn: parent; visible: picture.status === Image.Loading; running: visible }
            Text { font.family: Theme.fontFamily; anchors.centerIn: parent; visible: picture.status === Image.Error; text: I18n.t("图片暂不可预览，点击打开"); color: "white"; font.pixelSize: Theme.font(13, visible) }
        }
        Text { font.family: Theme.fontFamily; x: 24; y: 22; text: (root.currentIndex + 1) + " / " + root.images.length; visible: root.images.length > 1; color: "white"; font.pixelSize: Theme.font(12, visible) }
        ActionButton { objectName: "closeImagePreview"; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 20; width: Theme.control(36); height: Theme.control(36); glyph: "x"; hint: I18n.t("关闭预览"); background: Rectangle { radius: width / 2; color: "#fafbfc" } onClicked: root.close() }
        ActionButton { objectName: "previousPreviewImage"; x: 12; anchors.verticalCenter: parent.verticalCenter; visible: root.images.length > 1; width: Theme.control(38); height: Theme.control(48); primary: true; background: Rectangle { radius: 8; color: parent.hovered ? "#22ffffff" : "transparent" } glyph: "chevron-right"; rotation: 180; onClicked: root.step(-1) }
        ActionButton { objectName: "nextPreviewImage"; anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; visible: root.images.length > 1; width: Theme.control(38); height: Theme.control(48); primary: true; background: Rectangle { radius: 8; color: parent.hovered ? "#22ffffff" : "transparent" } glyph: "chevron-right"; onClicked: root.step(1) }
        Text { font.family: Theme.fontFamily; anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 22; width: parent.width - 100; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideMiddle; text: (root.current.path || root.current.name || "") + "  ·  " + Math.round(root.zoom * 100) + "%"; color: "#f0f2f6"; font.pixelSize: Theme.font(11, visible); textFormat: Text.PlainText }
        MediaContextMenu { id: previewMenu; item: root.current; itemKey: "imagePreview"; chatWindow: root.parent ? root.parent.Window.window : null }
    }
}
