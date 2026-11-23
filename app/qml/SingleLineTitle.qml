import QtQuick

// Presentation only: keep session/project metadata and rename fields untouched.
Text {
    property string rawTitle: ""
    // Unicode White_Space, including NEL (which JavaScript's \\s omits).
    text: rawTitle.replace(/[\u0009-\u000d\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/g, " ").replace(/^ | $/g, "")
    textFormat: Text.PlainText
    wrapMode: Text.NoWrap
    maximumLineCount: 1
    elide: Text.ElideRight
}
