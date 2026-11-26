import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Column {
    id: root
    objectName: "multimodalSettings"
    spacing: 18
    property var savedSignatures: ({})
    function reload() {
        const settings = backend.config.multimodal
        for (const card of [image, speech, video]) {
            const signature = JSON.stringify(settings[card.kind])
            if (signature === savedSignatures[card.kind]) continue
            savedSignatures[card.kind] = signature
            card.load()
        }
    }
    Component.onCompleted: reload()
    Connections { target: backend; function onChanged() { root.reload() } }
    RowLayout {
        width: parent.width; spacing: 12
        Text { text: I18n.t("图片、语音与视频生成"); font.family: Theme.fontFamily; color: Theme.ink; font.pixelSize: Theme.font(14, visible); font.weight: Font.DemiBold; Layout.fillWidth: true; wrapMode: Text.Wrap }
        HelpButton { help: I18n.t("为图片、语音和视频分别配置专用多模态供应商，与聊天模型供应商相互独立，密钥使用系统凭据保护保存。") }
        ActionButton {
            objectName: "saveMultimodalSettings"; text: I18n.t("保存"); primary: true
            onClicked: backend.saveMultimodalSettings(JSON.stringify({image: image.values(), speech: speech.values(), video: video.values()}))
        }
    }
    ImageProviderDialog { id: imageProviders }
    GenerationSettingsCard { id: image; objectName: "imageGenerationSettings"; width: parent.width; kind: "image"; title: I18n.t("图片生成"); onProvidersRequested: imageProviders.openFor("image") }
    GenerationSettingsCard { id: speech; objectName: "speechGenerationSettings"; width: parent.width; kind: "speech"; title: I18n.t("语音生成"); onProvidersRequested: imageProviders.openFor("speech") }
    GenerationSettingsCard { id: video; objectName: "videoGenerationSettings"; width: parent.width; kind: "video"; title: I18n.t("视频生成"); onProvidersRequested: imageProviders.openFor("video") }
}
