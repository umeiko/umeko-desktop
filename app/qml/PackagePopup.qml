import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

PidPopup {
    id: root
    objectName: "packagePopup"
    property real heightLimit: 560
    signal configure()
    function toggle() { if (visible) close(); else open() }
    width: Math.min(560, Overlay.overlay ? Overlay.overlay.width - 24 : 560)
    height: Math.max(180, Math.min(heightLimit, 560))
    x: parent ? parent.width - width : 0
    y: -height - 8
    padding: 18
    transformOrigin: Popup.BottomRight
    onAboutToShow: backend.piManagement.scan()
    contentItem: ColumnLayout {
        spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Glyph { name: "wrench"; width: Theme.icon(17); height: Theme.icon(17) }
            Text { text: I18n.t("扩展包"); color: Theme.ink; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold }
            Item { Layout.fillWidth: true }
            ActionButton { glyph: "refresh"; quiet: true; hint: I18n.t("刷新"); enabled: !backend.piManagement.busy; onClicked: backend.piManagement.scan() }
            ActionButton { glyph: "x"; quiet: true; hint: I18n.t("关闭"); onClicked: root.close() }
        }
        PackagePermission { Layout.fillWidth: true; namePrefix: "packagePopup" }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            contentWidth: availableWidth
            PackageList { width: parent.width; namePrefix: "packagePopup" }
        }
        ActionButton { Layout.fillWidth: true; text: I18n.t("在设置中管理扩展"); glyph: "sliders"; quiet: true; onClicked: { root.close(); root.configure() } }
    }
}
