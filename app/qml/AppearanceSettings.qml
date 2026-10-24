import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Column {
    id: root; spacing: 18
    ThemeSettings { width: parent.width }
    SectionCard {
        width: parent.width
        ColumnLayout {
            width: parent.width; spacing: 18
            Text { text: I18n.t("语言与字号"); color: Theme.ink; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold }
            RowLayout {
                Layout.fillWidth: true
                Text { text: I18n.t("界面语言"); color: Theme.ink; font.pixelSize: Theme.font(12) }
                Item { Layout.fillWidth: true }
                Picker { objectName: "interfaceLanguage"; Layout.preferredWidth: 210; model: ["简体中文", "English"]; currentIndex: backend.language === "zh" ? 0 : 1; onActivated: backend.setLanguage(currentIndex === 0 ? "zh" : "en") }
            }
            RowLayout {
                Layout.fillWidth: true
                Text { text: I18n.t("字体大小"); color: Theme.ink; font.pixelSize: Theme.font(12) }
                Item { Layout.fillWidth: true }
                Text { objectName: "fontScaleLabel"; text: Math.round(backend.fontScale * 100) + "%"; color: Theme.accent; font.pixelSize: Theme.font(13) }
                ActionButton { text: I18n.t("恢复默认"); quiet: true; onClicked: backend.setFontScale(1) }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 14
                Text { text: I18n.t("界面字体"); color: Theme.ink; font.pixelSize: Theme.font(12) }
                Picker { objectName: "interfaceFontFamily"; Layout.fillWidth: true; model: backend.availableFonts; currentIndex: Math.max(0, model.indexOf(backend.config.fontFamily || "系统默认")); onActivated: index => backend.setFontFamily(model[index]) }
            }
            Slider { objectName: "fontScaleSlider"; Layout.fillWidth: true; from: .3; to: 2; stepSize: .01; value: backend.fontScale; onMoved: backend.setFontScale(value); Accessible.name: I18n.t("字体大小") }
            Text { text: I18n.t("30%–200%，即时预览并自动保存。"); color: Theme.muted; font.pixelSize: Theme.font(11) }
            Text { text: I18n.t("这是字体大小预览 Aa 0123456789"); color: Theme.ink; font.pixelSize: Theme.font(16); wrapMode: Text.Wrap; Layout.fillWidth: true }
        }
    }
    SectionCard {
        width: parent.width
        ColumnLayout {
            width: parent.width; spacing: 12
            RowLayout {
                Layout.fillWidth: true
                Text { text: I18n.t("用户数据目录"); color: Theme.ink; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold }
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "openUserDataDirectory"; text: I18n.t("打开目录"); glyph: "folder"; onClicked: backend.openChatboxPath(backend.userDataDirectory, false) }
            }
            TextEdit { text: backend.userDataDirectory; color: Theme.muted; font.pixelSize: Theme.font(12); readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; Layout.fillWidth: true }
            Text { text: I18n.t("供应商、插件、主题和聊天记录保存在此目录，升级应用会保留。"); color: Theme.muted; font.pixelSize: Theme.font(11); Layout.fillWidth: true; wrapMode: Text.Wrap }
        }
    }
}
