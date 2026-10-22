.pragma library

function blocks(text, markdown, compact) {
    if (compact) {
        text = text.replace(/^[\r\n]+|[\r\n]+$/g, "")
        if (!text.length) return []
    }
    if (!markdown) return [{code:false, text:text}]
    const lines = text.split("\n"), result = []
    let prose = [], code = [], fence = "", language = ""
    function flush() {
        if (prose.length) {
            const value = prose.join("\n")
            const table = /(^|\n)[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(\|[ \t]*:?-{3,}:?[ \t]*)+\|?[ \t]*(\n|$)/.test(value)
            result.push({code:false,text:value,table:table}); prose=[]
        }
    }
    for (let line of lines) {
        if (!fence) {
            const match = /^ {0,3}(`{3,}|~{3,})([^\r]*)\r?$/.exec(line)
            if (match && !(match[1][0] === "`" && match[2].indexOf("`") >= 0)) {
                flush(); fence=match[1]; language=match[2].trim().split(/\s+/)[0]; code=[]
            } else prose.push(line)
        } else {
            const close = /^ {0,3}(`{3,}|~{3,})\s*$/.exec(line)
            if (close && close[1][0] === fence[0] && close[1].length >= fence.length) {
                result.push({code:true,text:code.join("\n"),language:language}); fence=""; code=[]
            } else code.push(line.replace(/\r$/, ""))
        }
    }
    if (fence) result.push({code:true,text:code.join("\n"),language:language})
    flush()
    return result
}
