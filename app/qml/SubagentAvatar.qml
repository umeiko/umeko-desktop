import QtQuick

CharacterArt {
    property int slot: 0
    fallbackSource: "../icons/subagents/" + ["lemon-yakishio", "chika-komari", "kaju-nukumizu", "yumeko-shikiya"][Math.max(0,Math.min(3,slot))] + ".png"
    artwork: Character.roleAsset(Math.max(0,Math.min(3,slot)), "avatar", fallbackSource)
    sourceSize: Qt.size(128,128)
    fillMode: Image.PreserveAspectFit
    asynchronous: true
    smooth: false
}
