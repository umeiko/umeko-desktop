import QtQuick

Image {
    property int slot: 0
    source: "../icons/subagents/" + ["lemon-yakishio", "chika-komari", "kaju-nukumizu", "yumeko-shikiya"][Math.max(0,Math.min(3,slot))] + ".png"
    sourceSize: Qt.size(128,128)
    fillMode: Image.PreserveAspectFit
    asynchronous: true
    smooth: false
    cache: true
}
