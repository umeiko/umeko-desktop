.pragma library

var items = [
    "你知道吗？我可以改变这软件的外观！试试跟我说：生成一个纯白色的主题并且应用！",
    "可以试试让我给自己安装 Pi 扩展，来丰富、强化我的能力！",
    "想要批量处理任务？可以让我委派多个子代理！",
    // Keep this historical: current OpenClaw owns its agent runtime.
    // https://docs.openclaw.ai/agent-runtime-architecture
    "我的内核是 Pi，和 OpenClaw 那只龙虾早期的内核是同一家族哦！",
    "你有更多的模型供应商和 API？直接让我帮你添加，无需自己动手！",
    "我和我的插件运行出了问题？可以让我自己排查自己！我很厉害的！",
    "喂给我更多 Token，我才能好好干活呢。",
    "文件太多，懒得打路径？把它们拖进输入框，让我自己看看！",
    "写好的网页、代码和文档，都可以让我放到右边预览。来验收我的成果吧！",
    "子代理都在忙什么？点点右上角的小头像，就能找到正在工作的伙伴！",
    "想给某个子代理单独提要求？点开它的对话，直接告诉它就好！",
    "忙到一半想换个方向？把新要求告诉我，按 Ctrl+S 就能优先处理！",
    "模型名字太长，记不住？给常用模型起个别名，选起来就轻松多啦！",
    "聊天越来越长了？可以让我压缩一下上下文，轻装上阵继续干活！",
    "把你想要的效果和验收标准告诉我，我就更容易一次做好。默契也是练出来的嘛！",
    "任务有点复杂？先让我列个计划，再一项项搞定，别急！",
    "同一家供应商也能放好几个账号！给它们取个别名，就不会认错啦。",
    "想试试另一个思路，又舍不得这段上下文？点一下“分支”，我们换条路继续！"
]

function choose(previous, randomValue) {
    var valid = previous >= 0 && previous < items.length
    var random = randomValue === undefined ? Math.random() : Math.max(0,Math.min(0.999999999,randomValue))
    var next = Math.floor(random * (items.length - (valid ? 1 : 0)))
    return valid && next >= previous ? next + 1 : next
}
