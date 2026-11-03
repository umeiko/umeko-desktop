import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Column {
    id: root
    objectName: "multimodalSettings"
    spacing: 18
    property string savedSignature: ""
    function reload() {
        const signature = JSON.stringify(backend.config.multimodal)
        if (signature === savedSignature) return
        savedSignature = signature
        image.load(); speech.load(); video.load()
    }
    Component.onCompleted: reload()
    Connections { target: backend; function onChanged() { root.reload() } }
    RowLayout {
        width: parent.width; spacing: 12
        Text { text: I18n.t("图片、语音与视频生成"); font.family: Theme.fontFamily; color: Theme.ink; font.pixelSize: Theme.font(14, visible); font.weight: Font.DemiBold; Layout.fillWidth: true; wrapMode: Text.Wrap }
        HelpButton { help: I18n.t("复用已有供应商的账号、密钥和网络设置，不另存凭据。") }
        ActionButton {
            objectName: "saveMultimodalSettings"; text: I18n.t("保存"); primary: true
            onClicked: backend.saveMultimodalSettings(JSON.stringify({image: image.values(), speech: speech.values(), video: video.values()}))
        }
    }
    GenerationSettingsCard { id: image; objectName: "imageGenerationSettings"; width: parent.width; kind: "image"; title: I18n.t("图片生成") }
    GenerationSettingsCard { id: speech; objectName: "speechGenerationSettings"; width: parent.width; kind: "speech"; title: I18n.t("语音生成") }
    GenerationSettingsCard { id: video; objectName: "videoGenerationSettings"; width: parent.width; kind: "video"; title: I18n.t("视频生成") }
}
