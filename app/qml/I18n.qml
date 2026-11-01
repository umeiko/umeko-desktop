pragma Singleton
import QtQuick
import "english.js" as English

QtObject {
    id: root
    readonly property string language: backend.language
    function widgetText(plugin, value) {
        return plugin && plugin.id === "skill-manager" && plugin.builtin !== false ? t(value) : value
    }
    function t(value) {
        const text = String(value || "")
        const certificate = text.match(/^TLS certificate validation failed \(([^)]+)\); check the provider's Network settings and CA file, then open request details(.*)$/)
        if (certificate) return root.language === "en" ? text : "证书校验失败（" + certificate[1] + "），请检查供应商的网络设置与 CA 证书，并查看请求详情" + certificate[2]
        if (root.language !== "en") return text
        if (Object.prototype.hasOwnProperty.call(English.strings, text)) return English.strings[text]
        const patterns = [
            [/^已压缩：(\d+) → (\d+) tokens$/, English.strings["已压缩：{before} → {after} tokens"].replace("{before}", "$1").replace("{after}", "$2")],
            [/^下载服务器返回 HTTP (\d+)$/, "Download server returned HTTP $1"],
            [/^系统代理返回 HTTP (\d+)$/, "System proxy returned HTTP $1"],
            [/^新版本 (.+) 可下载$/, "New version available: $1"],
            [/^已发现 (\d+) 个扩展$/, "Found $1 extensions"],
            [/^已启用 (\d+) \/ (\d+) 个扩展$/, "Enabled $1 / $2 extensions"],
            [/^发现新版本 (.+)$/, "New version available: $1"],
            [/^当前构建版本高于最新正式版（(.+)）。$/, "This build is newer than the latest stable release ($1)."],
            [/^发现发布版本 (.+)，请前往发布页确认。$/, "Found release $1. Check the release page for details."]
        ]
        for (const pair of patterns) if (pair[0].test(text)) return text.replace(pair[0], pair[1])
        return text
    }
}
