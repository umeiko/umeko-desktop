pragma Singleton
import QtQuick
import "theme.js" as Colors
QtObject {
    readonly property real fontScale: backend.fontScale
    readonly property string fontFamily: backend.config.fontFamily || Qt.application.font.family
    readonly property real proseLineHeight: ({compact: 1.0, standard: 1.2, relaxed: 1.5})[backend.lineSpacing || "standard"]
    function font(size) { return Math.max(1, Math.round(size * fontScale)) }
    function icon(size) { return Math.max(1, Math.round(size * fontScale)) }
    function control(size) { return Math.round(size * Math.max(1, fontScale)) }
    readonly property var style: backend.themeStyle
    readonly property string base: style.base || backend.config.theme
    readonly property bool dark: base === "dark"
    readonly property bool yanami: base === "yanami"
    readonly property var palette: Colors.palette(base, style.colors)
    readonly property color bg: palette.bg
    readonly property color sidebar: palette.sidebar
    readonly property color surface: palette.surface
    readonly property color userBubble: palette.userBubble
    readonly property color hover: palette.hover
    readonly property color line: palette.line
    readonly property color ink: palette.ink
    readonly property color muted: palette.muted
    readonly property color accent: palette.accent
    readonly property color accentBg: palette.accentBg
    readonly property color selectionBg: palette.selectionBg
    readonly property color selectionText: palette.selectionText
    readonly property color button: palette.button
    readonly property color buttonText: palette.buttonText
    readonly property color danger: palette.danger
}
