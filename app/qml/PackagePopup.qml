import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

AnchoredPidPopup {
    id: root
    objectName: "packagePopup"
    property real heightLimit: 560
    property bool refreshPending: false
    property bool listReady: false
    property var packageRows: []
    signal configure()
    signal dismissed()
    fullWidth: 560
    fullHeight: Math.max(180, Math.min(heightLimit, 560))
    alignRight: true
    padding: 18
    function refreshWhenSettled() {
        if (!visible || !desiredOpen || animating) return
        packageRows = backend.piManagement.manageablePackages
        if (!refreshPending) return
        refreshPending = false
        listReady = true
        backend.piManagement.scan()
    }
    onAboutToShow: { focus = true; refreshPending = true; Qt.callLater(root.refreshWhenSettled) }
    onAboutToHide: { refreshPending = false; focus = false; dismissed() }
    onClosed: dismissed()
    onOpened: contentItem.forceActiveFocus()
    onAnimatingChanged: if (!animating) Qt.callLater(root.refreshWhenSettled)
    Connections { target: backend.piManagement; function onChanged() { Qt.callLater(root.refreshWhenSettled) } }
    contentItem: Item {
        clip: true
    ColumnLayout {
        width: root.expandedWidth - root.padding * 2
        height: root.expandedHeight - root.padding * 2
        opacity: root.contentOpacity
        enabled: root.desiredOpen && !root.animating
        spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Glyph { name: "wrench"; width: Theme.icon(17); height: Theme.icon(17) }
            Text { text: I18n.t("扩展包"); color: Theme.ink; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold }
            Item { Layout.fillWidth: true }
            ActionButton { objectName: "packagePopupRefreshButton"; glyph: "refresh"; quiet: true; hint: I18n.t("刷新"); enabled: !backend.piManagement.busy; onClicked: backend.piManagement.scan() }
            ActionButton { glyph: "x"; quiet: true; hint: I18n.t("关闭"); onClicked: root.close() }
        }
        PackagePermission { Layout.fillWidth: true; namePrefix: "packagePopup" }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            contentWidth: availableWidth
            Loader {
                width: parent.width
                active: root.listReady
                sourceComponent: PackageList { namePrefix: "packagePopup"; packageRows: root.packageRows }
            }
        }
        ActionButton { objectName: "packagePopupConfigureButton"; Layout.fillWidth: true; text: I18n.t("在设置中管理扩展"); glyph: "sliders"; quiet: true; onClicked: { root.close(); root.configure() } }
    }
    }
}
