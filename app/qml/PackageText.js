.pragma library

function format(template, values) {
    return template.replace(/%([1-9])/g, function(_, n) { return String(values[Number(n) - 1]) })
}

function pattern(value, t) {
    const keys = {
        "Recursive file deletion": "递归删除文件", "rimraf (recursive delete)": "递归删除文件（rimraf）",
        "File unlink/delete": "删除文件", "Directory removal": "删除目录", "fs.rm recursive delete": "递归删除文件（fs.rm）",
        "eval() dynamic code execution": "动态执行代码（eval）", "Function() constructor": "动态构造函数",
        "Synchronous command execution": "同步执行命令", "Template literal in exec()": "命令中的模板字符串",
        "Child process spawn": "启动子进程", "Environment variable access": "读取环境变量", "Child process module": "子进程模块",
        "External HTTP request": "外部 HTTP 请求", "HTTP client usage": "HTTP 请求",
        "File permission change": "修改文件权限", "File ownership change": "修改文件所有者", "Source scan unavailable": "源码检查不可用"
    }
    return t(keys[value] || value)
}

function severity(value, t) {
    return t(({critical:"严重风险", high:"高风险", medium:"中风险", low:"低风险", info:"提示"})[value] || "未知风险")
}

function auditSummary(audit, t) {
    const labels = {critical:"%1 条严重风险", high:"%1 条高风险", medium:"%1 条中风险", low:"%1 条低风险", info:"%1 条提示"}
    const counts = audit.counts || {}, rows = audit.findings || []
    const groups = Object.keys(labels).filter(key => counts[key]).map(key => format(t(labels[key]), [counts[key]]))
    if (!groups.length) return t(audit.status === "not-audited" ? "尚未检查" : audit.status === "incomplete" ? "源码检查未完成" : audit.status === "clear" ? "未命中检查模式" : "已保存检查备注")
    const patterns = [], files = []
    rows.forEach(row => {
        const label = pattern(row.pattern, t), file = row.file.replace(/\\/g, "/").split("/").pop()
        if (label && !patterns.includes(label)) patterns.push(label)
        if (file && !files.includes(file)) files.push(file)
    })
    const joiner = t("、"), suffix = patterns.slice(0, 2).join(joiner)
    return groups.join(joiner) + (suffix ? t("：") + suffix : "") + (files.length ? format(t("（%1）"), [files.slice(0, 3).join(joiner) + (files.length > 3 ? t("等") : "")]) : "") + (audit.status === "incomplete" ? t("；源码检查未完成") : "")
}

function finding(row, t) {
    return severity(row.severity, t) + " · " + pattern(row.pattern, t) + (row.file ? " · " + row.file + (row.line ? ":" + row.line : "") : "")
}

function progress(event, t) {
    const operations = {marketplace_search:"搜索扩展包", search:"搜索扩展包", marketplace_detail:"读取扩展包详情", marketplace_audit:"检查扩展包", marketplace_install:"安装扩展包", install:"安装扩展包", remove:"卸载扩展包", uninstall:"卸载扩展包"}
    if (!event || !operations[event.operation]) return ""
    const templates = {running:"正在%1…", done:"%1已完成", error:"%1失败"}
    return format(t(templates[event.state] || "%1"), [t(operations[event.operation])]) + (event.package ? t("：") + event.package : "")
}

function installRequest(detail) {
    try {
        const request = JSON.parse(detail).umekoPackageInstall
        return request && typeof request.source === "string" && typeof request.reason === "string" ? request : null
    } catch (_) { return null }
}
