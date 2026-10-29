import QtQuick

ReplyMascot {
    id: root
    property int avatarSlot: 0
    property string characterName: ""
    readonly property int role: Math.max(0,Math.min(3,avatarSlot))
    portraitSource: Character.roleAsset(role, "avatar", "../icons/subagents/" + ["lemon-yakishio","chika-komari","kaju-nukumizu","yumeko-shikiya"][role] + ".png")
    interactionLabel: characterName + I18n.t("：点击互动，连续点击或长按有彩蛋")
    tapLines: Character.roleLine(role, "tap", [])
    celebrationLine: Character.roleLine(role, "celebration", "")
}
