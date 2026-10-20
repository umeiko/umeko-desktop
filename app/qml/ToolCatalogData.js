.pragma library

// Use native registry provenance: an extension may override a built-in name.
function category(tool) {
    const source = tool.source || ""
    if (source === "builtin:mcp") return "mcp"
    if (["builtin:codemode", "builtin:tool-search"].indexOf(source) >= 0) return "extensions"
    if (source === "builtin:" + tool.name) return "native"
    return "extensions"
}

function entries(resources, section, query) {
    const tools = ["native", "mcp", "extensions"].indexOf(section) >= 0
    const rows = tools ? (resources.allTools || []).filter(t => category(t) === section) : resources[section] || []
    const needle = (query || "").trim().toLowerCase()
    return rows.filter(row => !needle || [row.name, row.description, row.source, row.path].join(" ").toLowerCase().indexOf(needle) >= 0)
}

function status(tool) {
    if (tool.exposure === "hidden") return "已隐藏"
    if (tool.active) return "当前启用"
    if (["codemode", "deferred"].indexOf(tool.exposure) >= 0) return "按需调用"
    return "未启用"
}

function server(tool, resources) {
    const servers = resources.mcp || []
    for (let i = 0; i < servers.length; i++)
        if ((servers[i].tools || []).some(t => t.name === tool.name)) return servers[i].name
    return "MCP 资源"
}
