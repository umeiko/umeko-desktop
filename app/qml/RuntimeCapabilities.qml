import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

SectionCard {
    id: root
    objectName: "runtimeCapabilitiesCard"
    readonly property var report: backend.runtimeCapabilities.snapshot
    function status(value) {
        return I18n.t(({available:"可用", partial:"部分可用", missing:"缺失", error:"检测失败", checking:"正在检测", unchecked:"尚未检测", ready:"检测完成"})[value] || "尚未检测")
    }
    onVisibleChanged: if (visible) backend.runtimeCapabilities.check()
    Component.onCompleted: if (visible) backend.runtimeCapabilities.check()
    Timer { interval: 5000; repeat: true; running: root.visible; onTriggered: backend.runtimeCapabilities.check() }
    ColumnLayout {
        width: parent.width; spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Text { Layout.fillWidth: true; text: I18n.t("能力与运行依赖"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(14, visible); font.weight: Font.DemiBold }
            ActionButton { objectName: "refreshRuntimeCapabilities"; text: I18n.t("重新检测"); glyph: "refresh"; enabled: !root.report.busy; onClicked: backend.runtimeCapabilities.refresh() }
        }
        Text { Layout.fillWidth: true; text: I18n.t("仅检测本机基础依赖，不安装软件、不下载模型。远程服务与生成质量未检测。"); wrapMode: Text.Wrap; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible) }
        Text { objectName: "runtimeCapabilitiesState"; Layout.fillWidth: true; text: root.status(root.report.state) + (root.report.stale ? " · " + I18n.t("结果已过期或尚未检测") : ""); color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible) }
        Text { Layout.fillWidth: true; text: I18n.t("执行目录") + ": " + (root.report.workspace || ""); wrapMode: Text.WrapAnywhere; textFormat: Text.PlainText; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible) }
        Text { Layout.fillWidth: true; visible: !!root.report.checkedAt; text: I18n.t("检测时间") + ": " + new Date((root.report.checkedAt || 0) * 1000).toLocaleString(); wrapMode: Text.Wrap; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible) }
        Text { Layout.fillWidth: true; visible: !!root.report.error; text: I18n.t(root.report.error || ""); wrapMode: Text.Wrap; color: Theme.danger; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible) }
        Repeater {
            model: root.report.capabilities || []
            SettingsFold {
                required property var modelData
                objectName: "runtimeCapability_" + modelData.id
                Layout.fillWidth: true; nested: true
                title: I18n.t(modelData.name) + " · " + root.status(modelData.state)
                ColumnLayout {
                width: parent.width; spacing: 6
                Repeater {
                    model: modelData.dependencies
                    Text {
                        required property var modelData
                        Layout.fillWidth: true; wrapMode: Text.WrapAnywhere; textFormat: Text.PlainText
                        text: modelData.id + (modelData.minimum ? " >= " + modelData.minimum : "") + " · " + root.status(modelData.state)
                            + (modelData.version ? " · " + modelData.version : "")
                            + (modelData.path ? "\n" + modelData.path : "")
                            + (modelData.reason ? "\n" + I18n.t(modelData.reason) : "")
                        color: modelData.state === "available" ? Theme.muted : Theme.danger
                        font.family: Theme.fontFamily; font.pixelSize: Theme.font(10, visible)
                    }
                }
                Text { Layout.fillWidth: true; text: I18n.t(modelData.guide); wrapMode: Text.Wrap; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible) }
                }
            }
        }
        Text { Layout.fillWidth: true; visible: !!root.report.guides; text: root.report.guides ? [I18n.t(root.report.guides.python), I18n.t(root.report.guides.soffice), I18n.t(root.report.guides.pdftoppm)].join("\n") : ""; wrapMode: Text.Wrap; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible) }
    }
}
