.pragma library

// Qt 6.10's Markdown importer loses following table text after an unclosed
// HTML br fragment. Close real breaks, preserving escaped text and code spans.
function forQt(text) {
    if (!/<br\s*>/i.test(text)) return text
    const tokens = /\\[\\`<]|`+|<br\s*>/gi
    const ticks = /`+/g, runs = {}, cursors = {}
    let run
    while ((run = ticks.exec(text)) !== null) {
        const size = run[0].length
        if (!runs[size]) runs[size] = []
        runs[size].push([run.index, ticks.lastIndex])
    }
    let result = "", copied = 0, match
    while ((match = tokens.exec(text)) !== null) {
        if (match[0][0] === "`") {
            const size = match[0].length, closing = runs[size]
            let index = cursors[size] || 0
            while (index < closing.length && closing[index][0] < tokens.lastIndex) index++
            cursors[size] = index
            if (index < closing.length) tokens.lastIndex = closing[index][1]
        } else if (match[0][0] === "<") {
            result += text.slice(copied, match.index) + "<br/>"
            copied = tokens.lastIndex
        }
    }
    return result + text.slice(copied)
}

function blocks(text, markdown, compact) {
    if (compact) {
        text = text.replace(/^[\r\n]+|[\r\n]+$/g, "")
        if (!text.length) return []
    }
    if (!markdown) return [{code:false, text:text}]
    const lines = text.split("\n"), result = []
    let prose = [], code = [], fence = "", language = ""
    function flush() { if (prose.length) { result.push({code:false,text:prose.join("\n")}); prose=[] } }
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
