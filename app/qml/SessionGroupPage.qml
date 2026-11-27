import QtQuick
import "../../umeko-plugins/global-agents/qml" as Shared

Shared.GroupChat {
    id: root
    objectName: "workspaceGroupChat"
    signal previewDocument(var item)
    agents: backend.sessionGroup.memberRows
    sessionCandidates: backend.sessionGroup.candidates
    collaborationEnabled: true
    sdk: bridge

    QtObject {
        id: bridge
        readonly property real scale: Theme.fontScale
        readonly property string language: I18n.language
        readonly property var colors: ({
            bg: Theme.bg, surface: Theme.surface, ink: Theme.ink, muted: Theme.muted,
            line: Theme.line, hover: Theme.hover, accent: Theme.accent, accentBg: Theme.accentBg,
            danger: Theme.danger, dark: Theme.dark
        })
        signal response(string request, var value)
        function call(method, args) { return backend.sessionGroup.call(method, JSON.stringify(args || {})) }
        function copyText(text) { backend.copy(text) }
        function groupChatAttachments(urls) { return backend.sessionGroup.attachments(urls ? JSON.stringify(urls) : "") }
    }
    Connections {
        target: backend.sessionGroup
        function onResponse(request, value) {
            if (root.active && value.ok && value.result?.preview) root.previewDocument(value.result.preview)
            bridge.response(request, value)
        }
    }
}
