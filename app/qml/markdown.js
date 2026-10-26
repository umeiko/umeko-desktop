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


function selectionSegments(message, row, expanded) {
    const segments = message.role === "user" || message.continuation ? [] : [{block:-100000,text:"umeko",markdown:false}]
            const activity = message.activity || []
            if (activity.length) {
                for (let stepIndex = 0; stepIndex < activity.length; stepIndex++) {
                    const step = activity[stepIndex]
                    if (step.kind === "text") {
                        blocks(step.text || "", !step.error, stepIndex < activity.length - 1).forEach((block, index) => segments.push({block:step.blockOffset + index,text:block.text,markdown:!step.error && !block.code,copyPrefix:index === 0 ? step._copyPrefix || "" : "",copyJoin:index === 0 ? step._copyJoin || "" : ""}))
                    } else if (step.kind === "thinking" && expanded[row + ":" + step.blockOffset]) {
                        segments.push({block:step.blockOffset,text:step.text,markdown:false})
                    } else if (step.kind === "media") {
                        (step.items || []).forEach((item, index) => {
                            const key = step.blockOffset + index * 3
                            segments.push({block:key,text:item.title || item.name || "",markdown:false})
                            if (item.kind === "image" && item.preview && item.caption) segments.push({block:key + 1,text:item.caption,markdown:false})
                        })
                    } else if (step.kind === "tools") {
                        step.tools.forEach((tool, index) => {
                            const key = step.blockOffset + index + 1
                            if (expanded[row + ":" + key]) segments.push({block:key,text:JSON.stringify(tool.arguments || {}, null, 2) + (tool.result ? "\n\n" + tool.result : ""),markdown:false})
                        })
                    }
                }
            } else {
                const markdown = message.role === "assistant" && !message.error
                blocks(message.text || "", markdown).forEach((block, index) => segments.push({block:index,text:block.text,markdown:markdown && !block.code,copyPrefix:index === 0 ? message._copyPrefix || "" : "",copyJoin:index === 0 ? message._copyJoin || "" : ""}))
                if (message.role === "user") (message.attachments || []).forEach((item, index) => segments.push({block:10000 + index,text:item.name,markdown:false}))
            }
    return segments
}
