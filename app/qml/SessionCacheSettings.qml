import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

SectionCard {
    id: root
    objectName: "sessionCacheSettings"
    readonly property int storedValue: backend.config.ui && backend.config.ui.sessionCacheSize !== undefined
        ? backend.config.ui.sessionCacheSize : 3
    ColumnLayout {
        width: parent.width; spacing: 14
        Text {
            objectName: "sessionCacheTitle"
            font.family: Theme.fontFamily; text: I18n.t("会话缓存"); color: Theme.ink
            font.pixelSize: Theme.font(14, visible); font.weight: Font.DemiBold
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 18
            Text {
                objectName: "sessionCacheSizeLabel"
                font.family: Theme.fontFamily; text: I18n.t("空闲会话缓存数"); color: Theme.ink
                font.pixelSize: Theme.font(12, visible); wrapMode: Text.Wrap; Layout.fillWidth: true
            }
            SpinBox {
                objectName: "sessionCacheSizeValue"
                from: 0; to: 2147483647; editable: true
                value: root.storedValue
                font.pixelSize: Theme.font(12, visible)
                Accessible.name: I18n.t("空闲会话缓存数")
                onValueModified: {
                    backend.setSessionCacheSize(value)
                    value = Qt.binding(function() { return root.storedValue })
                }
            }
        }
        Text {
            objectName: "sessionCacheDescription"
            font.family: Theme.fontFamily
            text: I18n.t("保留最近使用的空闲会话，加快再次切换；默认 3 个（包括当前会话）。设为 0 时，仅保留当前空闲会话。")
            color: Theme.muted; font.pixelSize: Theme.font(11, visible)
            Layout.fillWidth: true; wrapMode: Text.Wrap
        }
        Text {
            objectName: "sessionCacheRunningDescription"
            font.family: Theme.fontFamily
            text: I18n.t("正在运行、执行工具或等待确认的会话始终保留，不占用此数量。修改立即保存并生效，不会删除聊天记录。")
            color: Theme.muted; font.pixelSize: Theme.font(11, visible)
            Layout.fillWidth: true; wrapMode: Text.Wrap
        }
    }
}
