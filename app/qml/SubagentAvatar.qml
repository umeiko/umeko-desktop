import QtQuick

CharacterArt {
    property int slot: 0
    property string character: ""
    fallbackSource: "../icons/subagents/" + ["lemon-yakishio", "chika-komari", "kaju-nukumizu", "yumeko-shikiya"][Math.max(0,Math.min(3,slot))] + ".png"
    artwork: (Character.personalityEnabled && Character.subagentPack(character)?.portrait) || Character.roleAsset(Math.max(0,Math.min(3,slot)), "avatar", fallbackSource)
    sourceSize: Qt.size(128,128)
    fillMode: Image.PreserveAspectFit
    asynchronous: true
    smooth: false
}
