.pragma library

var defaults = ["low", "high", "max"]
function label(value) {
    return ({none:"None", minimal:"Minimal", low:"Low", medium:"Medium", high:"High", xhigh:"XHigh", max:"Max", ultra:"Ultra"})[value] || value
}

function isSwitchOnly(format) {
    return ["qwen-switch", "reasoning-switch", "deepseek-switch", "template-thinking"].includes(format)
}

function detectedStatus(detection, format) {
    if (detection.verified !== true) return "档位效果未能确认"
    if (detection.levels && detection.levels.length === 1)
        return format.offVerified === true ? "仅可开关思考" : "只有一个思考选项"
    return "已观察到档位变化"
}
