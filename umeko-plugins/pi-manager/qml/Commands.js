.pragma library

// Parse a single Pi install invocation, never a shell program. Backslashes in
// Windows paths are literal; quotes group a path containing spaces.
function parse(text, project) {
    const input = String(text).trim()
    if (!input || /[\r\n\x00;&|`<>]/.test(input) || input.indexOf("$(") >= 0)
        throw new Error("请输入一个 Pi 安装命令或来源")
    let tokens=[], word="", quote="", started=false
    for (let i=0; i<input.length; ++i) {
        const c=input[i]
        if (quote) { if(c===quote) quote=""; else word+=c; started=true }
        else if (c==='"' || c==="'") { quote=c; started=true }
        else if (/\s/.test(c)) { if(started) { tokens.push(word); word=""; started=false } }
        else { word+=c; started=true }
    }
    if(quote) throw new Error("请补全路径两侧的引号")
    if(started) tokens.push(word)
    if(tokens[0]==="pi") {
        if(tokens[1]!=="install") throw new Error("这里只支持 pi install")
        tokens=tokens.slice(2)
    }
    let sources=[], local=false
    for(let token of tokens) {
        if(token==="--local" || token==="-l") local=true
        else if(token[0]==="-") throw new Error("不支持这个安装参数")
        else sources.push(token)
    }
    if(sources.length!==1 || !sources[0]) throw new Error("每次只能安装一个来源；带空格的路径请加引号")
    return {source:sources[0], project:local || !!project, forcedProject:local}
}
