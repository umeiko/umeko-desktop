pragma Singleton
import QtQuick
import "../theme.js" as Colors
QtObject {
    readonly property bool appContext:typeof backend!=="undefined"
    readonly property real uiScale:appContext?Math.max(1,backend.fontScale):1
    readonly property string base:appContext?(backend.themeStyle.base || backend.config.theme):"white"
    readonly property bool dark:base==="dark"
    readonly property var colors:Colors.palette(base,appContext?backend.themeStyle.colors:({}))
}
