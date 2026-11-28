import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

SectionCard {
    id: root
    objectName: root.kind + "GenerationSettings"
    required property string kind
    required property string title
    property string providerId: ""
    property string modelId: ""
    property string voiceValue: ""
    readonly property var offeredVoices: kind === "speech" && account && account.speechVoices
        ? account.speechVoices[modelId] || [] : []
    readonly property var voiceChoices: {
        if (!offeredVoices.length) return []
        const rows = [{id: "", label: I18n.t("供应商默认")}]
        for (const row of offeredVoices)
            rows.push({id: row.id, label: row.id})
        // Keep a saved custom voice selectable after an upgrade adds a catalog.
        if (voiceValue && !rows.some(row => row.id === voiceValue))
            rows.push({id: voiceValue, label: voiceValue})
        return rows
    }
    property string formatValue: kind === "speech" ? "mp3" : ""
    readonly property var saved: backend.multimodalPreferences[kind]
    readonly property string savedSignature: JSON.stringify(saved)
    property bool loaded: false
    property var accounts: backend.multimodalProviders.filter(p => p.kinds.includes(root.kind))
    readonly property var imagePresets: backend.imageProviderPresets
    readonly property var account: accounts.find(p => p.id === providerId) || null
    readonly property var imagePreset: account && account.api === "image" ? imagePresets.find(p => p.id === account.presetId && !p.custom) || null : null
    readonly property var imageLimits: imagePreset ? imagePreset.modelDetails.find(m => m.id === modelId) || null : null
    readonly property var choices: defaultChoices(accounts, kind, imagePresets)
    function defaultChoices(providers, type, presets) {
        const rows = [{providerId: "", model: "", label: I18n.t("未配置")}]
        for (const provider of providers) {
            const preset = presets.find(p => p.id === provider.presetId && !p.custom)
            const name = (preset ? I18n.t(provider.name) : provider.name) +
                (provider.accountLabel ? " (" + provider.accountLabel + ")" : "")
            for (const model of provider.models[type] || []) {
                const detail = preset ? preset.modelDetails.find(row => row.id === model) : null
                rows.push({providerId: provider.id, model: model, label: (detail ? detail.name : model) + " · " + name})
            }
        }
        return rows
    }
    onSavedSignatureChanged: if (loaded && saved) load()
    onProviderIdChanged: Qt.callLater(syncPickers)
    onModelIdChanged: Qt.callLater(syncPickers)
    onFormatValueChanged: Qt.callLater(syncPickers)
    onImageLimitsChanged: Qt.callLater(syncPickers)
    function syncPickers() {
        if (!choices || !modelPicker || !format) return
        if (imageLimits) {
            if (Number(count.text) > imageLimits.maxCount) count.text = "1"
            if (!formats.includes(formatValue)) formatValue = ""
        }
        modelPicker.currentIndex = Math.max(0, choices.findIndex(row => row.providerId === providerId && row.model === modelId))
        format.currentIndex = Math.max(0, formats.indexOf(formatValue))
    }

    function load() {
        const value = saved
        if (!value) return
        providerId = value.providerId
        modelId = value.model
        size.text = kind === "image" ? value.size : ""
        videoSize.text = kind === "video" ? value.size : ""
        seconds.text = kind === "video" ? value.seconds : ""
        quality.text = kind === "image" ? value.quality : ""
        count.text = kind === "image" ? String(value.count) : "1"
        voiceValue = kind === "speech" ? value.voice : ""
        voice.text = voiceValue
        speed.text = kind === "speech" ? String(value.speed) : "1"
        formatValue = value.format || ""
        Qt.callLater(syncPickers)
    }
    function values() {
        const common = {providerId: providerId, model: modelId}
        if (kind === "video")
            return Object.assign(common, {seconds: seconds.text, size: videoSize.text})
        return kind === "image" ? Object.assign(common, {size: size.text, quality: imagePreset ? "" : quality.text, count: Number(count.text), format: formatValue})
                                : Object.assign(common, {voice: voiceChoices.length ? voiceValue : voice.text, format: formatValue, speed: Number(speed.text)})
    }
    readonly property var formats: kind === "image" ? imageLimits ? [""].concat(imageLimits.formats) : ["", "png", "jpeg", "webp"] : ["mp3", "opus", "aac", "flac", "wav", "pcm"]
    Component.onCompleted: { load(); loaded = true }

    ColumnLayout {
        width: parent.width; spacing: 12
        RowLayout {
            Layout.fillWidth: true; spacing: 12
            Text {
                Layout.fillWidth: true
                text: I18n.t("默认模型"); color: Theme.ink
                font.family: Theme.fontFamily; font.pixelSize: Theme.font(14, visible); font.weight: Font.DemiBold
            }
            ActionButton {
                objectName: "saveMultimodalSettings"; text: I18n.t("保存"); primary: true
                onClicked: backend.saveMultimodalSettings(JSON.stringify({[root.kind]: root.values()}))
            }
        }
        Picker {
            id: modelPicker
            objectName: root.kind + "GenerationModel"; Layout.fillWidth: true
            model: root.choices.map(row => row.label)
            onModelChanged: Qt.callLater(root.syncPickers)
            onActivated: index => {
                if (index < 0 || index >= root.choices.length) return
                const next = root.choices[index]
                if (root.kind === "speech" && (root.providerId !== next.providerId || root.modelId !== next.model)) {
                    const saved = root.saved
                    // Do not carry a voice across models, but restore it when returning to the saved selection.
                    const originalVoice = saved && saved.providerId === next.providerId && saved.model === next.model
                        ? saved.voice : ""
                    root.voiceValue = originalVoice
                    voice.text = originalVoice
                }
                root.providerId = next.providerId
                root.modelId = next.model
            }
            Accessible.name: I18n.t("默认模型")
        }
        RowLayout {
            visible: root.kind === "image" && !!root.account; Layout.fillWidth: true; spacing: 12
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
            visible: root.kind === "speech" && !!root.account; Layout.fillWidth: true; spacing: 14
            ColumnLayout {
                Layout.fillWidth: true; spacing: 6
                Text { text: I18n.t("音色"); font.family: Theme.fontFamily; color: Theme.muted; font.pixelSize: Theme.font(11, visible) }
                Picker {
                    id: voicePicker
                    objectName: root.kind === "speech" ? "speechGenerationVoicePicker" : ""
                    visible: root.voiceChoices.length > 0
                    Layout.fillWidth: true
                    plainText: true
                    model: root.voiceChoices.map(row => row.label)
                    currentIndex: root.voiceChoices.findIndex(row => row.id === root.voiceValue)
                    onActivated: index => {
                        if (index >= 0 && index < root.voiceChoices.length)
                            root.voiceValue = root.voiceChoices[index].id
                    }
                    Accessible.name: I18n.t("音色")
                }
                InputField {
                    id: voice
                    objectName: root.kind === "speech" ? "speechGenerationVoice" : ""
                    visible: !root.voiceChoices.length
                    Layout.fillWidth: true
                    placeholderText: root.account && root.account.api === "plugin" ? I18n.t("供应商默认") : I18n.t("输入供应商支持的音色 ID")
                    Accessible.name: I18n.t("音色 ID")
                }
            }
            ColumnLayout {
                Layout.fillWidth: false; Layout.preferredWidth: 100; Layout.maximumWidth: 100; spacing: 6
                Text { text: I18n.t("语速"); font.family: Theme.fontFamily; color: Theme.muted; font.pixelSize: Theme.font(11, visible) }
                InputField { id: speed; objectName: root.kind === "speech" ? "speechGenerationSpeed" : ""; Layout.fillWidth: true; validator: DoubleValidator { bottom: 0.25; top: 4; locale: "C" } Accessible.name: I18n.t("语速") }
            }
        }
        RowLayout {
            visible: root.kind === "video" && !!root.account; Layout.fillWidth: true; spacing: 14
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
            visible: root.kind !== "video" && !!root.account
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
            visible: root.kind === "video" && !!root.account
            text: I18n.t("参数支持因模型而异，留空使用供应商默认值。")
            font.family: Theme.fontFamily; font.pixelSize: Theme.font(10, visible); color: Theme.muted; Layout.fillWidth: true; wrapMode: Text.Wrap
        }
        Text {
            visible: !!root.account
            text: root.kind === "image" ? I18n.t("图片提示词会发送给所选供应商。「询问」模式下，生成前会确认。")
                : root.kind === "video" ? I18n.t("视频提示词会发送给所选供应商，生成前逐次确认。")
                : I18n.t("朗读文本会发送给所选供应商。「询问」模式下，生成前会确认。")
            font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible); color: Theme.muted; Layout.fillWidth: true; wrapMode: Text.Wrap
        }
    }
}
