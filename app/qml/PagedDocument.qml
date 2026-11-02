import QtQuick
import QtQuick.Controls
import Umeko.Text 1.0

Item {
    id: root
    objectName: "pagedDocumentPreview"
    QtObject {
        id: selectionSource
        readonly property var messageModel: ({paged:true})
        readonly property int messageCount: documentList.count
        function copyChatSelection(value) { backend.documentPreview.copySelection(value) }
    }
    ListView {
        id: documentList; objectName:"documentBlockList"
        anchors.fill:parent;anchors.leftMargin:18;anchors.rightMargin:18
        clip:true;reuseItems:true;cacheBuffer:height;spacing:8
        boundsBehavior:Flickable.StopAtBounds
        model:backend.documentPreview.blocks
        function beginBrowsing() { cancelFlick() }
        function scrollBy(delta) { contentY=Math.max(originY,Math.min(originY+Math.max(0,contentHeight-height),contentY+delta)) }
        ScrollBar.vertical:ScrollBar {policy:ScrollBar.AsNeeded}
        header:Item {width:1;height:8}
        footer:Item {width:1;height:24}
        delegate:Item {
            id: part
            required property var block
            required property int index
            readonly property bool code:block.kind==="code"
            width:documentList.width;height:Math.max(22,body.contentHeight)+(code ? 42 : 0)
            Rectangle {anchors.fill:parent;visible:part.code;color:Theme.dark ? "#171c19" : "#f3f5f0";border.color:Theme.line;radius:7}
            Text {x:12;y:6;visible:part.code;text:part.block.language || I18n.t("代码");color:Theme.muted;font.pixelSize:Theme.font(10);font.family:Theme.fontFamily}
            SelectableText {
                id:body;objectName:"documentBlockText_"+part.index
                x:part.code ? 12 : 0;y:part.code ? 27 : 0
                width:part.width-2*x;height:contentHeight
                selectionController:selection;messageIndex:part.index;blockIndex:0
                text:part.block.html || part.block.text || ""
                textFormat:part.block.html ? TextEdit.RichText : TextEdit.PlainText
                wrapMode:part.code || part.block.kind==="source" ? TextEdit.WrapAnywhere : TextEdit.Wrap
                color:Theme.ink
                font.family:part.code || part.block.kind==="source" ? "Consolas" : Theme.fontFamily
                font.pixelSize:Theme.font(part.code || part.block.kind==="source" ? 12 : 13)
                onLinkActivated:link=>{
                    if(link[0]==="#") {const row=backend.documentPreview.anchorIndex(link);if(row>=0)documentList.positionViewAtIndex(row,ListView.Beginning)}
                    else if(/^https?:\/\//i.test(link))Qt.openUrlExternally(link)
                }
                SyntaxHighlighter {
                    document:body.textDocument;language:part.block.language || "";dark:Theme.dark
                    enabled:part.code && (part.block.text || "").length<8192
                }
                Item {
                    id:links;anchors.fill:parent
                    property int interactionPriority:2
                    function selectionContains(x,y) { return !!body.linkAt(x,y) }
                    Component.onCompleted:selection.attachInteraction(links)
                    Component.onDestruction:selection.detachInteraction(links)
                }
            }
            ListView.onReused:selection.refreshSoon()
        }
    }
    ChatSelection {id:selection;objectName:"documentSelection";anchors.fill:documentList;view:documentList;dataSource:selectionSource}
    Shortcut {sequences:[StandardKey.Copy];enabled:root.visible && selection.activeFocus && selection.hasSelection;onActivated:Qt.callLater(selection.copy)}
    Shortcut {sequences:[StandardKey.SelectAll];enabled:root.visible && selection.activeFocus;onActivated:selection.selectAll()}
    Shortcut {sequence:"Ctrl+End";enabled:root.visible && selection.activeFocus;onActivated:documentList.positionViewAtEnd()}
    Shortcut {sequence:"Ctrl+Home";enabled:root.visible && selection.activeFocus;onActivated:documentList.positionViewAtBeginning()}
    Connections {target:backend.documentPreview;function onChanged(){selection.clear()}}
}
