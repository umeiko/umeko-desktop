import QtQuick
import QtQuick.Layouts

RowLayout {
    property alias text: noticeText.text
    property bool continuable: false
    signal continued()
    spacing: 10
    Text {
        id: noticeText
        Layout.fillWidth: true
        text: I18n.t("已达到本次输出上限，内容可能尚未完成")
        color: Theme.muted; font.pixelSize: Theme.font(12)
        wrapMode: Text.Wrap
    }
    ActionButton {
        objectName: "continueOutputButton"
        visible: parent.continuable
        text: I18n.t("继续生成"); quiet: true
        onClicked: parent.continued()
    }
}
