import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

SectionCard {
    id: root
    property string kind: "image"
    property string title: ""
    property string providerId: ""
    property string modelId: ""
    property string formatValue: kind === "speech" ? "mp3" : ""
    signal imageProvidersRequested()
    property var accounts: backend.config.providers.filter(p => p.api === "openai" || (p.generationCapabilities || []).includes(root.kind))
    readonly property var account: accounts.find(p => p.id === providerId) || null
    readonly property var imagePreset: account && account.api === "image" && account.imageProtocol !== "openai" ? backend.imageProviderPresets.find(p => p.id === account.presetId) || null : null
    readonly property var models: imagePreset ? imagePreset.modelDetails.map(m => ({upstream:m.id, name:m.name})) : account ? account.api === "image" ? (account.imageModels || []).map(id => ({upstream:id})) : account.models : []
    readonly property var imageLimits: imagePreset ? imagePreset.modelDetails.find(m => m.id === modelId) || imagePreset.modelDetails[0] : null
    readonly property int mappedIndex: models.findIndex(m => m.upstream === modelId)
    onProviderIdChanged: Qt.callLater(syncPickers)
    onModelIdChanged: Qt.callLater(syncPickers)
    onFormatValueChanged: Qt.callLater(syncPickers)
    onImageLimitsChanged: Qt.callLater(syncPickers)
    function syncPickers() {
        if (imageLimits) {
            if (Number(count.text) > imageLimits.maxCount) count.text = "1"
            if (!formats.includes(formatValue)) formatValue = ""
        }
        providerPicker.currentIndex = Math.max(0, accounts.findIndex(p => p.id === providerId) + 1)
        modelPicker.currentIndex = mappedIndex + 1
        format.currentIndex = Math.max(0, formats.indexOf(formatValue))
    }

    function load() {
        const value = backend.config.multimodal[kind]
        providerId = value.providerId
        modelId = value.model
        size.text = kind === "image" ? value.size : ""
        videoSize.text = kind === "video" ? value.size : ""
        seconds.text = kind === "video" ? value.seconds : ""
        quality.text = kind === "image" ? value.quality : ""
        count.text = kind === "image" ? String(value.count) : "1"
        voice.text = kind === "speech" ? value.voice : ""
        speed.text = kind === "speech" ? String(value.speed) : "1"
        formatValue = value.format || ""
        Qt.callLater(syncPickers)
    }
    function values() {
        const common = {providerId: providerId, model: modelId}
        if (kind === "video")
            return Object.assign(common, {seconds: seconds.text, size: videoSize.text})
        return kind === "image" ? Object.assign(common, {size: size.text, quality: imagePreset ? "" : quality.text, count: Number(count.text), format: formatValue})
                                : Object.assign(common, {voice: voice.text, format: formatValue, speed: Number(speed.text)})
    }
    readonly property var formats: kind === "image" ? imageLimits ? [""].concat(imageLimits.formats) : ["", "png", "jpeg", "webp"] : ["mp3", "opus", "aac", "flac", "wav", "pcm"]
    Component.onCompleted: load()

    ColumnLayout {
        width: parent.width; spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Glyph { name: root.kind === "image" ? "image" : "file"; width: Theme.icon(20); height: Theme.icon(20); color: Theme.accent }
            Text { text: root.title; font.family: Theme.fontFamily; font.pixelSize: Theme.font(14, visible); font.weight: Font.DemiBold; color: Theme.ink }
            Item { Layout.fillWidth: true }
            Text { text: root.kind === "image" ? "image_gen" : root.kind === "video" ? "video_gen" : "voice_gen"; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible); color: Theme.muted }
            ActionButton { objectName: root.kind === "image" ? "manageImageProviders" : ""; visible: root.kind === "image"; text: I18n.t("供应商"); glyph: "settings"; quiet: true; onClicked: root.imageProvidersRequested() }
        }
        GridLayout {
            Layout.fillWidth: true; columns: 2; columnSpacing: 14; rowSpacing: 7
            Text { text: I18n.t("供应商"); font.family: Theme.fontFamily; color: Theme.muted; font.pixelSize: Theme.font(11, visible) }
            Text { text: I18n.t("模型"); font.family: Theme.fontFamily; color: Theme.muted; font.pixelSize: Theme.font(11, visible) }
            Picker {
                id: providerPicker
                objectName: root.kind + "GenerationProvider"; Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.minimumWidth: 0
                model: [I18n.t("未配置")].concat(root.accounts.map(p => p.api === "image" && p.imageProtocol !== "openai" ? I18n.t(p.name) : p.name))
                onModelChanged: Qt.callLater(root.syncPickers)
                onActivated: index => {
                    const selected = index > 0 ? root.accounts[index - 1] : null
                    root.providerId = selected ? selected.id : ""
                    root.modelId = selected && selected.api === "image" ? selected.imageModels[0] : ""
                }
                Accessible.name: root.title + " " + I18n.t("供应商")
            }
            Picker {
                id: modelPicker
                objectName: root.kind + "GenerationModel"; Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.minimumWidth: 0; enabled: !!root.account
                model: [I18n.t(root.imagePreset ? "请选择模型" : "手动输入模型 ID")].concat(root.models.map(m => m.name || m.upstream))
                onModelChanged: Qt.callLater(root.syncPickers)
                onActivated: index => { root.modelId = index > 0 ? root.models[index - 1].upstream : "" }
                Accessible.name: root.title + " " + I18n.t("模型")
            }
        }
        InputField {
            objectName: root.kind + "GenerationModelId"; Layout.fillWidth: true
            visible: !!root.account && !root.imagePreset && root.mappedIndex < 0
            text: root.modelId; placeholderText: I18n.t("供应商未列出生成模型时，输入模型 ID")
            onTextEdited: root.modelId = text
            Accessible.name: root.title + " " + I18n.t("模型 ID")
        }
        RowLayout {
            visible: root.kind === "image"; Layout.fillWidth: true; spacing: 12
            ColumnLayout {
                Layout.fillWidth: true; Layout.preferredWidth: 240; Layout.minimumWidth: 80; spacing: 6
                Text { text: I18n.t("尺寸"); font.family: Theme.fontFamily; color: Theme.muted; font.pixelSize: Theme.font(11, visible) }
                InputField { id: size; objectName: root.kind === "image" ? "imageGenerationSize" : ""; Layout.fillWidth: true; placeholderText: root.imageLimits && root.imageLimits.sizeTiers.length ? root.imageLimits.sizeTiers.join(" / ") : I18n.t("供应商默认"); Accessible.name: I18n.t("尺寸") }
            }
            ColumnLayout {
                visible: !root.imagePreset
                Layout.fillWidth: true; Layout.preferredWidth: 240; Layout.minimumWidth: 80; spacing: 6
                Text { text: I18n.t("质量"); font.family: Theme.fontFamily; color: Theme.muted; font.pixelSize: Theme.font(11, visible) }
                InputField { id: quality; objectName: root.kind === "image" ? "imageGenerationQuality" : ""; Layout.fillWidth: true; placeholderText: I18n.t("供应商默认"); Accessible.name: I18n.t("质量") }
            }
            ColumnLayout {
                Layout.fillWidth: false; Layout.preferredWidth: 90; Layout.maximumWidth: 90; spacing: 6
                Text { text: I18n.t("数量"); font.family: Theme.fontFamily; color: Theme.muted; font.pixelSize: Theme.font(11, visible) }
                InputField { id: count; objectName: root.kind === "image" ? "imageGenerationCount" : ""; Layout.fillWidth: true; readOnly: !!root.imageLimits && root.imageLimits.maxCount === 1; validator: IntValidator { bottom: 1; top: root.imageLimits ? root.imageLimits.maxCount : 10 } Accessible.name: I18n.t("数量") }
            }
        }
        RowLayout {
            visible: root.kind === "speech"; Layout.fillWidth: true; spacing: 14
            ColumnLayout {
                Layout.fillWidth: true; spacing: 6
                Text { text: I18n.t("音色 ID"); font.family: Theme.fontFamily; color: Theme.muted; font.pixelSize: Theme.font(11, visible) }
                InputField { id: voice; objectName: root.kind === "speech" ? "speechGenerationVoice" : ""; Layout.fillWidth: true; placeholderText: I18n.t("输入供应商支持的音色 ID"); Accessible.name: I18n.t("音色 ID") }
            }
            ColumnLayout {
                Layout.fillWidth: false; Layout.preferredWidth: 100; Layout.maximumWidth: 100; spacing: 6
                Text { text: I18n.t("语速"); font.family: Theme.fontFamily; color: Theme.muted; font.pixelSize: Theme.font(11, visible) }
                InputField { id: speed; objectName: root.kind === "speech" ? "speechGenerationSpeed" : ""; Layout.fillWidth: true; validator: DoubleValidator { bottom: 0.25; top: 4; locale: "C" } Accessible.name: I18n.t("语速") }
            }
        }
        RowLayout {
            visible: root.kind === "video"; Layout.fillWidth: true; spacing: 14
            ColumnLayout {
                Layout.fillWidth: true; spacing: 6
                Text { text: I18n.t("时长（秒）"); font.family: Theme.fontFamily; color: Theme.muted; font.pixelSize: Theme.font(11, visible) }
                InputField { id: seconds; objectName: root.kind === "video" ? "videoGenerationSeconds" : ""; Layout.fillWidth: true; placeholderText: I18n.t("供应商默认"); validator: RegularExpressionValidator { regularExpression: /[0-9]+/ } Accessible.name: I18n.t("时长（秒）") }
            }
            ColumnLayout {
                Layout.fillWidth: true; spacing: 6
                Text { text: I18n.t("分辨率（宽x高）"); font.family: Theme.fontFamily; color: Theme.muted; font.pixelSize: Theme.font(11, visible) }
                InputField { id: videoSize; objectName: root.kind === "video" ? "videoGenerationSize" : ""; Layout.fillWidth: true; placeholderText: I18n.t("供应商默认，例如 1280x720"); validator: RegularExpressionValidator { regularExpression: /[0-9]+x[0-9]+/ } Accessible.name: I18n.t("分辨率（宽x高）") }
            }
        }
        RowLayout {
            visible: root.kind !== "video"
            Layout.fillWidth: true; spacing: 14
            Text { text: I18n.t("输出格式"); font.family: Theme.fontFamily; color: Theme.muted; font.pixelSize: Theme.font(11, visible) }
            Picker {
                id: format; objectName: root.kind + "GenerationFormat"; Layout.preferredWidth: 150
                model: root.formats.map(f => f || I18n.t("供应商默认"))
                onModelChanged: Qt.callLater(root.syncPickers)
                onActivated: index => root.formatValue = root.formats[index]
                Accessible.name: root.title + " " + I18n.t("输出格式")
            }
            Text { text: I18n.t("参数支持因模型而异，留空使用供应商默认值。"); font.family: Theme.fontFamily; color: Theme.muted; font.pixelSize: Theme.font(10, visible); Layout.fillWidth: true; wrapMode: Text.Wrap }
        }
        Text {
            visible: root.kind === "video"
            text: I18n.t("参数支持因模型而异，留空使用供应商默认值。")
            font.family: Theme.fontFamily; font.pixelSize: Theme.font(10, visible); color: Theme.muted; Layout.fillWidth: true; wrapMode: Text.Wrap
        }
        Text {
            text: root.kind === "image" ? I18n.t("图片提示词会发送给所选供应商，生成前逐次确认。") : root.kind === "video" ? I18n.t("视频提示词会发送给所选供应商，生成前逐次确认。") : I18n.t("朗读文本会发送给所选供应商，生成前逐次确认。")
            font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible); color: Theme.muted; Layout.fillWidth: true; wrapMode: Text.Wrap
        }
    }
}
