import QtQuick

ReplyMascot {
    id: root
    property int avatarSlot: 0
    property string characterName: ""
    readonly property int role: Math.max(0,Math.min(3,avatarSlot))
    portraitSource: "../icons/subagents/" + ["lemon-yakishio","chika-komari","kaju-nukumizu","yumeko-shikiya"][role] + ".png"
    interactionLabel: characterName + I18n.t("：点击互动，连续点击或长按有彩蛋")
    tapLines: [
        [I18n.t("嘿，下一棒交给我！"), I18n.t("补充点水分，再出发！"), I18n.t("这次也跑到终点啦！")],
        [I18n.t("那、那个……已经写好了。"), I18n.t("别一直盯着看啦……"), I18n.t("这次……有帮上忙吗？")],
        [I18n.t("嗯哼，都替你整理好了。"), I18n.t("这个小细节，我有注意到哦。"), I18n.t("接下来想让我帮你看哪里？")],
        [I18n.t("……啊，已经结束了呢。"), I18n.t("嗯……我有在听哦。"), I18n.t("再点一下……也不会睡着的。")]
    ][role]
    celebrationLine: [I18n.t("加时赛？那就再陪你跑一圈！"), I18n.t("这、这可是文学部的特别篇！"), I18n.t("被发现了？是佳树的特别照顾哦。"), I18n.t("……醒着呢。这次，真的醒着。")][role]
}
