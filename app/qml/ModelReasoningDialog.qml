import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "ReasoningLevels.js" as Reasoning

Popup {
    id: root
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(Theme.control(440), parent.width - 40)
    height: Math.min(content.implicitHeight + padding * 2, parent.height - 40)
    padding: 24; modal: true; focus: true
    closePolicy: Popup.CloseOnEscape
    property string modelName: ""
    property int rowIndex: -1
    property string error: ""
    // Draft state; saving the provider or mappings applies it.
    property bool levelsAuto: false
    property bool formatAuto: true
    property string formatValue: "openai"
    // Saved model used to read detection results; empty for unsaved rows.
    property string providerId: ""
    property string lookupAlias: ""
    property string api: ""
    property var settings: ({})
    onOpened: {
        if (providerId && lookupAlias && typeof backend.ensureModelReasoningDetection === "function")
            backend.ensureModelReasoningDetection(providerId, lookupAlias)
        refreshDetection()
    }
    readonly property bool saved: !!settings && settings.states !== undefined
    readonly property var levelsDetection: saved && settings.reasoningDetection ? settings.reasoningDetection : ({})
    readonly property var formatDetection: saved && settings.reasoningFormatDetection ? settings.reasoningFormatDetection : ({})
    readonly property string levelsState: saved ? (levelsDetection.state || "unknown") : "unknown"
    readonly property string formatState: saved ? (formatDetection.state || "unknown") : "unknown"
    readonly property var detectedLevels: levelsDetection.levels && levelsDetection.levels.length !== undefined ? Array.from(levelsDetection.levels, String) : []
    readonly property bool alwaysThinks: formatAuto && formatState === "known" && formatDetection.offSupported === false
    readonly property var formatIds: {
        let values = []
        const options = backend.reasoningFormatOptions
        if (options && options.length) { for (const option of options) values.push(option.value) }
        else values = ["openai", "openai-none", "chat-template", "qwen", "deepseek", "anthropic-adaptive"]
        if (api === "openai") values = values.filter(value => value !== "anthropic-adaptive")
        if (values.indexOf(formatValue) < 0) values.push(formatValue)
        return values
    }
    signal confirmed(int rowIndex, string levelsJson, bool levelsAuto, string format, bool formatAuto)

    function formatLabel(value) {
        switch (value) {
        case "openai": return I18n.t("通过 reasoning_effort 设置，关闭时不发送")
        case "openai-none": return I18n.t("通过 reasoning_effort 设置，关闭时发送 none")
        case "chat-template": return I18n.t("通过 chat_template_kwargs 里的 enable_thinking 开关")
        case "qwen": return I18n.t("通过 enable_thinking 开关")
        case "deepseek": return I18n.t("通过 thinking.type 开关")
        case "anthropic-adaptive": return I18n.t("通过 Anthropic 自适应思考开关")
        case "anthropic": return I18n.t("使用 Anthropic 原生思考参数")
        case "responses": return I18n.t("使用 Responses 原生思考参数")
        default: return I18n.t("其他方式")
        }
    }
    function stateText(state) {
        switch (state) {
        case "probing": return I18n.t("检测中…")
        case "known": return I18n.t("已检测")
        case "failed": return I18n.t("检测失败")
        default: return I18n.t("尚未检测，保存后会在后台自动检测")
        }
    }
    function failureText(detection) {
        const reason = String(detection.error || "").trim()
        return reason ? I18n.t("原因：") + reason : I18n.t("原因未知，可以稍后重新检测")
    }
    function switchText() {
        if (formatState !== "known") return ""
        switch (formatDetection.status) {
        case "on-off-verified": return I18n.t("已确认可以开启和关闭思考")
        case "on-not-observable": return I18n.t("检测时没有看到思考内容，无法确认开启是否生效")
        default: return ""
        }
    }
    function refreshDetection() {
        settings = providerId && lookupAlias && typeof backend.modelReasoningSettings === "function"
            ? backend.modelReasoningSettings(providerId, lookupAlias) || ({}) : ({})
    }
    function loadNames(values) {
        names.clear()
        for (let i = 0; i < values.length; ++i) names.append({value: values[i]})
        count.value = values.length
    }
    function edit(index, name, raw, row, provider, protocol) {
        rowIndex = index; modelName = name; error = ""
        row = row || {}
        providerId = provider || ""; api = protocol || ""
        lookupAlias = row.savedAlias || ""
        levelsAuto = row.reasoningLevelsAuto === true
        formatAuto = row.reasoningFormatAuto !== false
        formatValue = row.reasoningFormat || "openai"
        refreshDetection()
        loadNames(JSON.parse(raw))
        open()
    }
    function setLevelsAuto(automatic) {
        if (!automatic && levelsAuto && levelsState === "known" && detectedLevels.length) loadNames(detectedLevels)
        levelsAuto = automatic; error = ""
    }
    function setFormat(index) {
        if (index <= 0) { formatAuto = true; return }
        formatAuto = false; formatValue = formatIds[index - 1]
    }
    function redetect() {
        if (saved && typeof backend.redetectModelReasoning === "function") backend.redetectModelReasoning(providerId, lookupAlias)
        refreshDetection()
    }
    function resize(count) {
        while (names.count < count) names.append({value: ""})
        if (names.count > count) names.remove(count, names.count - count)
        error = ""
    }
    function confirm() {
        let values = [], seen = []
        if (levelsAuto) {
            for (let i = 0; i < names.count; ++i) values.push(names.get(i).value)
            confirmed(rowIndex, JSON.stringify(levelsState === "known" ? detectedLevels : values.filter(Boolean)), true, formatValue, formatAuto); close()
            return
        }
        for (let i = 0; i < names.count; ++i) {
            const value = names.get(i).value.trim() || Reasoning.defaults[i] || ""
            if (!value || value.length > 64 || /[\s\x00-\x1f\x7f]/.test(value)) {
                error = I18n.t("档位名称需为 1–64 个字符，不能包含空白"); return
            }
            if (value.toLowerCase() === "off" || seen.indexOf(value.toLowerCase()) >= 0) {
                error = I18n.t("档位名称不能重复，也不能使用保留名称 off"); return
            }
            values.push(value); seen.push(value.toLowerCase())
        }
        confirmed(rowIndex, JSON.stringify(values), false, formatValue, formatAuto); close()
    }
    Connections {
        target: backend; ignoreUnknownSignals: true; enabled: root.visible
        function onReasoningDetectionChanged() { root.refreshDetection() }
    }
    ListModel { id: names }
    background: Rectangle { color: Theme.surface; radius: 14; border.color: Theme.line }
    ColumnLayout {
        id: content
        anchors.fill: parent; spacing: 16
        ColumnLayout {
            Layout.fillWidth: true; spacing: 6
            Text { text: I18n.t("思考档位"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(17, visible); font.weight: Font.DemiBold }
            Text { text: root.modelName; textFormat: Text.PlainText; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible); Layout.fillWidth: true; elide: Text.ElideRight }
        }
        ScrollView {
            id: bodyScroll
            Layout.fillWidth: true; Layout.fillHeight: true
            Layout.preferredHeight: body.implicitHeight; Layout.minimumHeight: Math.min(body.implicitHeight, Theme.control(90))
            clip: true; contentWidth: availableWidth
            ColumnLayout {
                id: body; width: bodyScroll.availableWidth; spacing: 14
                RowLayout {
                    Layout.fillWidth: true; spacing: 6
                    Text { text: I18n.t("档位来源"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible) }
                    HelpButton { help: I18n.t("自动检测会向供应商发送很短的请求，读出模型支持的档位。手动设置后以手动填写的为准，重新检测不会改动。") }
                    Item { Layout.fillWidth: true }
                    Picker {
                        id: levelsMode; objectName: root.objectName + "_levelsMode"
                        Layout.preferredWidth: Theme.control(140)
                        model: [I18n.t("自动检测"), I18n.t("手动设置")]
                        currentIndex: root.levelsAuto ? 0 : 1
                        Accessible.name: I18n.t("档位来源")
                        onActivated: index => root.setLevelsAuto(index === 0)
                    }
                }
                // Automatic levels: read-only detection result.
                ColumnLayout {
                    objectName: root.objectName + "_autoLevels"
                    visible: root.levelsAuto
                    Layout.fillWidth: true; spacing: 8
                    RowLayout {
                        Layout.fillWidth: true; spacing: 6
                        Rectangle { width: 7; height: 7; radius: 3.5; color: root.levelsState === "failed" ? Theme.danger : root.levelsState === "known" ? Theme.accent : Theme.muted }
                        Text {
                            objectName: root.objectName + "_levelsState"
                            Layout.fillWidth: true; wrapMode: Text.Wrap
                            text: root.stateText(root.levelsState) + (root.levelsState === "known" && root.levelsDetection.verified === false ? I18n.t(" · 档位未经验证") : "")
                            color: root.levelsState === "failed" ? Theme.danger : Theme.ink
                            font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible)
                        }
                    }
                    Text {
                        objectName: root.objectName + "_levelsNote"
                        visible: text !== ""
                        Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 4; elide: Text.ElideRight; textFormat: Text.PlainText
                        text: root.levelsState === "failed" ? root.failureText(root.levelsDetection)
                            : root.levelsState === "known" && root.levelsDetection.verified === false
                                ? (root.levelsDetection.invalidAccepted ? I18n.t("服务端接受任何档位值，无法确认哪些档位真的有效。下面是常用档位，不保证每一档效果不同。") : I18n.t("这些档位没有经过服务端确认，不保证每一档效果不同。"))
                            : root.levelsState === "known" && root.detectedLevels.length === 0 ? I18n.t("没有检测到可用档位，只能选「关闭」。") : ""
                        color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible)
                    }
                    Text {
                        visible: root.detectedLevels.length > 0
                        text: I18n.t("共 %1 档，从低到高，不含关闭").arg(root.detectedLevels.length)
                        color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(10, visible)
                    }
                    Flow {
                        objectName: root.objectName + "_detectedLevels"
                        visible: root.detectedLevels.length > 0
                        Layout.fillWidth: true; spacing: 6
                        Repeater {
                            model: root.detectedLevels
                            Rectangle {
                                required property int index
                                required property string modelData
                                height: Theme.control(26); radius: 6
                                width: Math.min(levelText.implicitWidth + 16, body.width)
                                color: Theme.accentBg; border.color: Theme.line
                                Text {
                                    id: levelText
                                    anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 8
                                    text: (index + 1) + "  " + Reasoning.label(modelData); textFormat: Text.PlainText
                                    verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
                                    color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11)
                                }
                            }
                        }
                    }
                }
                // Manual levels: the #88 editor, unchanged.
                ColumnLayout {
                    objectName: root.objectName + "_manualLevels"
                    visible: !root.levelsAuto
                    Layout.fillWidth: true; spacing: 16
                    RowLayout {
                        Layout.fillWidth: true; spacing: 6
                        Text { text: I18n.t("档位数量"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible) }
                        HelpButton { help: I18n.t("不含关闭。按从低到高填写，名称须与供应商支持的档位一致。") }
                        Item { Layout.fillWidth: true }
                        SpinBox {
                            id: count; objectName: root.objectName + "_count"
                            from: 0; to: 32; value: 3; editable: true
                            implicitWidth: Theme.control(126); implicitHeight: Math.max(38, Theme.font(13) + 20)
                            leftPadding: Theme.control(36); rightPadding: Theme.control(36)
                            Accessible.name: I18n.t("档位数量（不含关闭）")
                            onValueModified: root.resize(value)
                            background: Rectangle { color: Theme.surface; radius: 8; border.color: count.activeFocus ? Theme.accent : Theme.line }
                            contentItem: TextInput {
                                text: count.textFromValue(count.value, count.locale)
                                color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13, visible)
                                horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                                selectByMouse: true; validator: count.validator; inputMethodHints: Qt.ImhDigitsOnly
                                selectionColor: Theme.accent; selectedTextColor: Theme.buttonText
                            }
                            down.indicator: ActionButton {
                                objectName: root.objectName + "_decrease"
                                x: 1; y: 1; width: Theme.control(34); height: count.height - 2
                                glyph: "minus"; quiet: true; enabled: count.value > count.from
                                Accessible.name: I18n.t("减少档位")
                                onClicked: { count.decrease(); root.resize(count.value) }
                            }
                            up.indicator: ActionButton {
                                objectName: root.objectName + "_increase"
                                x: count.width - width - 1; y: 1; width: Theme.control(34); height: count.height - 2
                                glyph: "plus"; quiet: true; enabled: count.value < count.to
                                Accessible.name: I18n.t("增加档位")
                                onClicked: { count.increase(); root.resize(count.value) }
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: I18n.t("档位名称"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible) }
                        Item { Layout.fillWidth: true }
                        Text { text: I18n.t("从低到高"); color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(10, visible) }
                    }
                    ColumnLayout {
                        id: fields; Layout.fillWidth: true; spacing: 8
                        Repeater {
                            model: names
                            RowLayout {
                                required property int index
                                required property string value
                                Layout.fillWidth: true
                                Text { text: String(index + 1); color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12); Layout.preferredWidth: 16 }
                                InputField {
                                    objectName: root.objectName + "_name_" + index
                                    Layout.fillWidth: true; text: value
                                    placeholderText: Reasoning.defaults[index] || I18n.t("例如：xhigh")
                                    maximumLength: 64
                                    Accessible.name: I18n.t("档位名称") + " " + (index + 1)
                                    onTextEdited: { names.setProperty(index, "value", text); root.error = "" }
                                }
                            }
                        }
                        Text { visible: names.count === 0; text: I18n.t("此模型仅提供关闭档位"); color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12) }
                    }
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
                // Thinking switch: how off and each level are sent.
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 8
                    RowLayout {
                        Layout.fillWidth: true; spacing: 6
                        Text { text: I18n.t("思考开关方式"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible) }
                        HelpButton { help: I18n.t("不同服务开关思考的参数不同。自动检测会看回复里有没有思考内容来判断；手动选择后按所选方式发送，重新检测不会改动。") }
                        Item { Layout.fillWidth: true }
                    }
                    Picker {
                        id: formatPicker; objectName: root.objectName + "_format"
                        Layout.fillWidth: true
                        model: [I18n.t("自动检测")].concat(root.formatIds.map(value => root.formatLabel(value)))
                        currentIndex: root.formatAuto ? 0 : root.formatIds.indexOf(root.formatValue) + 1
                        Accessible.name: I18n.t("思考开关方式")
                        onActivated: index => root.setFormat(index)
                    }
                    RowLayout {
                        visible: root.formatAuto
                        Layout.fillWidth: true; spacing: 6
                        Rectangle { width: 7; height: 7; radius: 3.5; color: root.formatState === "failed" ? Theme.danger : root.formatState === "known" ? Theme.accent : Theme.muted }
                        Text {
                            objectName: root.objectName + "_formatState"
                            Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText
                            text: root.formatState === "known" ? I18n.t("已检测：") + root.formatLabel(root.formatDetection.format || root.formatValue) : root.stateText(root.formatState)
                            color: root.formatState === "failed" ? Theme.danger : Theme.ink
                            font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible)
                        }
                    }
                    Text {
                        objectName: root.objectName + "_formatNote"
                        visible: text !== ""
                        Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 4; elide: Text.ElideRight; textFormat: Text.PlainText
                        text: !root.formatAuto ? I18n.t("按所选方式发送，自动检测结果不会覆盖。")
                            : root.formatState === "failed" ? root.failureText(root.formatDetection) : root.switchText()
                        color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible)
                    }
                    Rectangle {
                        objectName: root.objectName + "_alwaysThinks"
                        visible: root.alwaysThinks
                        Layout.fillWidth: true; implicitHeight: alwaysText.implicitHeight + 16; radius: 8
                        color: Theme.accentBg; border.color: Theme.line
                        Text {
                            id: alwaysText
                            anchors.fill: parent; anchors.margins: 8; wrapMode: Text.Wrap
                            text: I18n.t("这个模型总会思考，选「关闭」也会思考")
                            color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible)
                        }
                    }
                }
            }
        }
        Text { visible: !!root.error; text: root.error; color: Theme.danger; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12); Layout.fillWidth: true; wrapMode: Text.Wrap }
        RowLayout {
            Layout.fillWidth: true
            ActionButton {
                objectName: root.objectName + "_redetect"; text: I18n.t("重新检测"); glyph: "refresh"; quiet: true
                enabled: root.saved && (root.levelsAuto || root.formatAuto)
                onClicked: root.redetect()
            }
            ActionButton { objectName: root.objectName + "_reset"; visible: !root.levelsAuto; text: I18n.t("恢复默认"); quiet: true; onClicked: { names.clear(); Reasoning.defaults.forEach(value => names.append({value:value})); count.value = 3; root.error = "" } }
            Item { Layout.fillWidth: true }
            ActionButton { objectName: root.objectName + "_cancel"; text: I18n.t("取消"); quiet: true; onClicked: root.close() }
            ActionButton { objectName: root.objectName + "_save"; text: I18n.t("确定"); primary: true; onClicked: root.confirm() }
        }
    }
}
