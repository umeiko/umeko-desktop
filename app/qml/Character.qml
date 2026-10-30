pragma Singleton
import QtQuick

QtObject {
    readonly property var style: backend.characterStyle
    readonly property string id: style.id || "yanami"
    readonly property var assets: style.assets || ({})
    readonly property var lines: style.lines || ({})
    function has(slot) { return !!assets[slot] }
    function asset(slot, fallback) { return assets[slot] || fallback }
    function isAnimated(source) { return /\.gif(?:\?|$)/i.test(String(source)) || Array.prototype.indexOf.call(style.animatedSources || [], String(source)) >= 0 }
    function line(slot, fallback) { return lines[slot] || fallback }
    function textArray(value) {
        let result = []
        for (let i = 0; i < value.length; i++) result.push(I18n.t(String(value[i])))
        return result
    }
    function scene(path, fallback) {
        let value = style.dialogue || ({})
        for (const part of path.split(".")) {
            if (value === null || value === undefined || value[part] === undefined) return fallback
            value = value[part]
        }
        if (typeof value === "string") return I18n.t(value)
        if (value && typeof value.length === "number") return textArray(value)
        return value
    }
    function role(index) { return (style.subagents || [])[Math.max(0,Math.min(3,index))] || ({}) }
    function roleAsset(index, kind, fallback) {
        const value = role(index)[kind]
        return value || asset((kind === "catch" ? "subagentCatch" : "subagent") + index, fallback)
    }
    function roleLine(index, name, fallback) {
        const value = role(index)[name]
        if (value && typeof value !== "string" && typeof value.length === "number") return textArray(value)
        return value === undefined ? fallback : I18n.t(value)
    }
    function greeting(fallback, index) {
        if (!style.customGreetings) return fallback
        const values = scene("welcome.greetings", [])
        return values.length ? values[Math.max(0,index) % values.length] : fallback
    }
}
