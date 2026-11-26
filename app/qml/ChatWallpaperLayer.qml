import QtQuick

Item {
    id: root
    required property url source
    property bool useCharacter: false
    property bool seaSaltDecorations: false
    required property string mode
    required property real strength
    required property real zoom
    property real offsetX: 0
    property real offsetY: 0
    property real angle: 0
    readonly property bool ready: useCharacter ? !!themedArt.item && themedArt.item.status === Image.Ready : image.status === Image.Ready
    readonly property int fillMode: mode === "fit" ? Image.PreserveAspectFit : Image.PreserveAspectCrop
    readonly property real imageWidth: width * zoom / 100
    readonly property real imageHeight: height * zoom / 100
    clip: true

    Item {
        anchors.fill: parent
        visible: root.seaSaltDecorations
        Rectangle {
            width: parent.width * 0.9; height: width; radius: width / 2
            x: parent.width * 0.45; y: -height * 0.55; opacity: 0.38
            gradient: Gradient { GradientStop { position: 0; color: "#ccdfff" } GradientStop { position: 1; color: "#f4f7ff" } }
        }
        Rectangle {
            width: parent.width * 0.55; height: width; radius: width / 2
            x: -width * 0.45; y: parent.height * 0.6; color: "#e2eaff"; opacity: 0.5
        }
        Repeater {
            model: root.seaSaltDecorations ? [{x:0.17,y:0.16,size:12},{x:0.82,y:0.30,size:17},
                                     {x:0.27,y:0.65,size:9},{x:0.73,y:0.73,size:11}] : []
            Glyph {
                required property var modelData
                x: parent.width * modelData.x; y: parent.height * modelData.y
                width: modelData.size; height: width; name: "spark"; opacity: 0.28
            }
        }
    }

    Item {
        width: root.imageWidth; height: root.imageHeight
        x: (root.width - width) / 2 + root.offsetX * root.width
        y: (root.height - height) / 2 + root.offsetY * root.height
        rotation: root.angle

        Loader {
            id: themedArt
            anchors.fill: parent
            active: root.useCharacter
            sourceComponent: CharacterArt {
                objectName: "yanamiWatermark"
                artwork: Character.wallpaper; fallbackSource: Character.wallpaperFallback
                fillMode: root.fillMode
                opacity: root.strength / 100
                asynchronous: true; mipmap: true
            }
        }
        Image {
            id: image
            objectName: "wallpaperImage"
            anchors.fill: parent
            source: root.source
            fillMode: root.fillMode
            opacity: root.strength / 100
            asynchronous: true
            retainWhileLoading: true
            mipmap: true
        }
    }
}
