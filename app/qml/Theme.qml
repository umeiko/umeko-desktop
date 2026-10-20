pragma Singleton
import QtQuick
QtObject {
    readonly property bool dark: backend.config.dark
    readonly property bool yanami: backend.config.theme === "yanami"
    readonly property color bg: yanami ? "#f4f7ff" : dark ? "#191c1b" : "#fcfcfa"
    readonly property color sidebar: yanami ? "#e9effd" : dark ? "#141716" : "#f2f3ef"
    readonly property color surface: dark ? "#212523" : "#ffffff"
    readonly property color userBubble: yanami ? "#e5ecfc" : dark ? "#2b302e" : "#f0f1ee"
    readonly property color hover: yanami ? "#dce6fc" : dark ? "#2a302c" : "#e9ede7"
    readonly property color line: yanami ? "#d6e1f7" : dark ? "#343a36" : "#e5e8e1"
    readonly property color ink: yanami ? "#283957" : dark ? "#e7eae5" : "#252d28"
    readonly property color muted: yanami ? "#7b8dac" : dark ? "#929e95" : "#828b83"
    readonly property color accent: yanami ? "#456fbe" : dark ? "#9dc5ac" : "#365e47"
    readonly property color accentBg: yanami ? "#e6edff" : dark ? "#2b3c31" : "#eaf0e8"
    readonly property color selectionBg: yanami ? "#2f5597" : dark ? "#a5cdb3" : "#315e47"
    readonly property color selectionText: dark ? "#13271a" : "#ffffff"
    readonly property color button: yanami ? "#4d75c1" : dark ? "#8dbd9e" : "#365e47"
    readonly property color buttonText: dark ? "#19271e" : "#ffffff"
    readonly property color danger: dark ? "#e7a791" : "#a25a44"
}
