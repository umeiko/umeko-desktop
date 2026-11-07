import QtQuick

Rectangle {
    property alias text: label.text
    implicitWidth: label.implicitWidth + 12
    implicitHeight: label.implicitHeight + 6
    radius: 4
    color: Theme.dark ? "#49380c" : "#fff1bd"
    border.color: Theme.dark ? "#8c6b1c" : "#e2c258"
    Text {
        id: label
        anchors.centerIn: parent
        text: I18n.t("实验版")
        textFormat: Text.PlainText
        font.family: Theme.fontFamily
        font.pixelSize: Theme.font(10, visible)
        font.weight: Font.Medium
        color: Theme.dark ? "#ffdc7a" : "#805900"
    }
}
