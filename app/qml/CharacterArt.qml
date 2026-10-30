import QtQuick
import QtQuick.Window

// Static artwork keeps Qt's Image path; only real animation uses a movie decoder.
Item {
    id: root
    property url artwork: fallbackSource
    property url fallbackSource: ""
    property bool failed: false
    readonly property url source: failed ? fallbackSource : artwork
    readonly property bool animated: Character.isAnimated(source)
    readonly property int status: animated && movie.item ? movie.item.status : picture.status
    readonly property int frameCount: movie.item ? movie.item.frameCount : 1
    readonly property bool playing: visible && !!root.Window.window && root.Window.window.visibility !== Window.Hidden && root.Window.window.visibility !== Window.Minimized
    property size sourceSize: Qt.size(-1, -1)
    property int fillMode: Image.PreserveAspectFit
    property int horizontalAlignment: Image.AlignHCenter
    property int verticalAlignment: Image.AlignVCenter
    property bool asynchronous: false
    property bool cache: true
    property bool mipmap: false
    property bool mirror: false
    implicitWidth: animated && movie.item ? movie.item.implicitWidth : picture.implicitWidth
    implicitHeight: animated && movie.item ? movie.item.implicitHeight : picture.implicitHeight
    onArtworkChanged: failed = false
    onStatusChanged: if (status === Image.Error && !failed && source !== fallbackSource) failed = true
    Image {
        id: picture; anchors.fill: parent
        source: root.animated ? "" : root.source
        sourceSize: root.sourceSize; fillMode: root.fillMode
        horizontalAlignment: root.horizontalAlignment; verticalAlignment: root.verticalAlignment
        asynchronous: root.asynchronous; cache: root.cache; mipmap: root.mipmap
        smooth: root.smooth; mirror: root.mirror
    }
    Loader {
        id: movie; anchors.fill: parent; active: root.animated
        sourceComponent: AnimatedImage {
            source: root.source; sourceSize: root.sourceSize; fillMode: root.fillMode
            horizontalAlignment: root.horizontalAlignment; verticalAlignment: root.verticalAlignment
            playing: root.playing; cache: false; mipmap: root.mipmap; smooth: root.smooth; mirror: root.mirror
        }
    }
}
