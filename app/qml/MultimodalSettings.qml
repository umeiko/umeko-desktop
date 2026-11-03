import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Column {
    id: root
    objectName: "multimodalSettings"
    spacing: 16
    function reload() { image.load(); speech.load() }
    Connections { target: backend; function onChanged() { root.reload() } }
    RowLayout {
        width: parent.width; spacing: 16
        ColumnLayout {
            Layout.fillWidth: true; spacing: 5
            Text { text: I18n.t("多模态模型"); font.family: Theme.fontFamily; color: Theme.ink; font.pixelSize: Theme.font(19, visible); font.weight: Font.Medium }
            Text { text: I18n.t("复用已有供应商的账号、密钥和网络设置，不另存凭据。"); font.family: Theme.fontFamily; color: Theme.muted; font.pixelSize: Theme.font(11, visible); Layout.fillWidth: true; wrapMode: Text.Wrap }
        }
        ActionButton {
            objectName: "saveMultimodalSettings"; text: I18n.t("保存"); primary: true
            onClicked: backend.saveMultimodalSettings(JSON.stringify({image: image.values(), speech: speech.values()}))
        }
    }
    GenerationSettingsCard { id: image; objectName: "imageGenerationSettings"; width: parent.width; kind: "image"; title: I18n.t("图片生成") }
    GenerationSettingsCard { id: speech; objectName: "speechGenerationSettings"; width: parent.width; kind: "speech"; title: I18n.t("语音生成") }
    SectionCard {
        objectName: "videoGenerationNotice"; width: parent.width; enabled: false
        RowLayout {
            width: parent.width; spacing: 16
            Text { text: I18n.t("视频生成"); font.family: Theme.fontFamily; font.pixelSize: Theme.font(13, visible); color: Theme.muted; font.weight: Font.DemiBold }
            Text { text: I18n.t("将在后续版本加入异步任务、进度和取消支持。"); font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible); color: Theme.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
        }
    }
    SectionCard {
        objectName: "imageUnderstandingNotice"; width: parent.width
        RowLayout {
            width: parent.width; spacing: 16
            Text { text: I18n.t("图片理解"); font.family: Theme.fontFamily; font.pixelSize: Theme.font(13, visible); color: Theme.muted; font.weight: Font.DemiBold }
            Text { text: I18n.t("独立的识图模型设置预留于此，方案仍在 #49 讨论。"); font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible); color: Theme.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
        }
    }
}
