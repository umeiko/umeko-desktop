import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

SectionCard {
    ColumnLayout { width: parent.width; spacing: 18
        RowLayout { Layout.fillWidth: true; spacing: 12
            Image { source: "../icons/pi.svg"; Layout.preferredWidth: 38; Layout.preferredHeight: 38; sourceSize: Qt.size(76,76)
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: backend.openPiGithub() }
            }
            Text { font.family: Theme.fontFamily; text: "Pi Coding Agent"; color: Theme.ink; font.pixelSize: Theme.font(17); font.weight: Font.Medium }
            HelpButton { help: I18n.t("仅点击检查或更新时访问 npm 软件源。保留完整 Pi Coding Agent，仅替换内置供应商目录。新内核通过原生工具执行、会话持久化和连接策略验证后再切换；失败保留旧版本。") }
            Item { Layout.fillWidth: true }
            Text { text: "v" + backend.kernelVersion; color: Theme.accent; font.pixelSize: Theme.font(20); font.family: "Consolas" }
        }
        RowLayout { Layout.fillWidth: true
            Text { font.family: Theme.fontFamily; Layout.fillWidth: true; text: I18n.t(backend.kernelStatus); wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(12) }
            ActionButton { objectName: "checkKernelButton"; text: backend.kernelBusy ? I18n.t("处理中…") : I18n.t("检查更新"); glyph: "refresh"; enabled: !backend.kernelBusy && !backend.piManagement.busy; onClicked: backend.checkKernel() }
            ActionButton { objectName: "updateKernelButton"; text: I18n.t("更新内核"); primary: true; enabled: !backend.kernelBusy && !backend.piManagement.busy && backend.latestVersion !== "" && backend.latestVersion !== backend.kernelVersion; onClicked: backend.updateKernel() }
        }
        BusyIndicator { visible: backend.kernelBusy; running: visible; Layout.alignment: Qt.AlignHCenter; implicitWidth: 25; implicitHeight: 25 }
    }
}
