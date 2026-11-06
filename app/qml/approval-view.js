.pragma library

// Turns a confirm request into readable sections. Display only: the request,
// its id and the reply sent back are never changed. Labels are Chinese source
// strings that the dialog passes through I18n.t.

var SHELL_TOOLS = ["pwsh", "bash", "shell", "powershell"]
var CONTENT_LIMIT = 1200

var PERMISSIONS = {
    "danger-full-access": "需要完全访问权限（超出当前工作目录）",
    "workspace-write": "需要写入当前工作目录的权限",
    "read-only": "只需要读取权限"
}

function text(value) {
    if (value === undefined || value === null) return ""
    if (Array.isArray(value)) return value.map(String).join(" ")
    return typeof value === "string" ? value : JSON.stringify(value)
}

function clip(value) {
    return value.length > CONTENT_LIMIT ? value.slice(0, CONTENT_LIMIT) + "\n…" : value
}

// ACP tool kinds cover agents whose titles are sentences, not tool names.
function action(tool, kind) {
    var name = String(tool || "").toLowerCase()
    if (SHELL_TOOLS.indexOf(name) >= 0 || kind === "execute") return "运行命令"
    if (name === "write") return "写入文件"
    if (name === "edit" || name === "apply_patch" || kind === "edit") return "修改文件"
    if (kind === "delete") return "删除文件"
    return tool || "工具调用"
}

// Older bridges sent only "title\n{json}\nexplanation" in detail.
function dshInput(request) {
    if (request.rawInput && typeof request.rawInput === "object")
        return {tool: request.toolTitle || "", kind: request.toolKind || "", input: request.rawInput, note: request.toolContent || ""}
    var lines = String(request.detail || "").split("\n")
    try {
        var input = JSON.parse(lines[1] || "")
        if (input && typeof input === "object" && !Array.isArray(input))
            return {tool: lines[0], input: input, note: lines.slice(2).join("\n")}
    } catch (error) {}
    return null
}

function dsh(request) {
    var parsed = dshInput(request)
    if (!parsed) return null
    var input = parsed.input, sections = []
    var command = text(input.command !== undefined ? input.command : input.script)
    var path = text(input.file_path !== undefined ? input.file_path : input.path)
    if (command) sections.push({label: "执行的命令", text: command, mono: true})
    if (path) sections.push({label: "目标文件", text: path, mono: true})
    if (path && typeof input.content === "string")
        sections.push({label: "写入内容", text: clip(input.content), mono: true})
    var justification = text(input.justification)
    if (justification) sections.push({label: "模型说明", text: justification, mono: false})
    else if (parsed.note) sections.push({label: "说明", text: parsed.note, mono: false})
    var level = text(input.sandbox_permissions)
    return {
        structured: true, raw: String(request.detail || ""),
        action: action(parsed.tool, parsed.kind), description: text(input.description),
        sections: sections, permissionLevel: level,
        // A known level is a translatable sentence; an unknown one is shown verbatim.
        permission: PERMISSIONS[level] || "", permissionValue: PERMISSIONS[level] ? "" : level
    }
}

// Pi tool approvals: "原因：…\n\n原始命令：\n…" (or the English form).
function pi(request) {
    var match = String(request.detail || "").match(/^(?:原因：|Reason: )([\s\S]*?)\n\n(原始[^\n：]*|Original [^\n:]*)[：:]\n([\s\S]*)$/)
    if (!match) return null
    return {
        structured: true, raw: "", action: "", description: "",
        sections: [{label: "原因", text: match[1], mono: false}, {label: match[2], text: match[3], mono: true}],
        permissionLevel: "", permission: "", permissionValue: ""
    }
}

function present(request) {
    request = request || {}
    if (request.method !== "confirm") return {structured: false}
    return (request.backend === "dsh" ? dsh(request) : pi(request)) || {structured: false}
}
