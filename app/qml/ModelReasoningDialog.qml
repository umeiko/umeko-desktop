import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "ReasoningLevels.js" as Reasoning

Popup {
    id: root
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(Theme.control(400), parent.width - 40)
    height: Math.min(content.implicitHeight + padding * 2, parent.height - 40)
    padding: 24; modal: true; focus: true
    closePolicy: Popup.CloseOnEscape
    property string modelName: ""
    property int rowIndex: -1
    property string error: ""
    signal confirmed(int rowIndex, string levelsJson)
    function edit(index, name, raw) {
        rowIndex = index; modelName = name; error = ""
        const values = JSON.parse(raw)
        names.clear()
        for (let i = 0; i < values.length; ++i) names.append({value: values[i]})
        count.value = values.length
        open()
    }
    function resize(count) {
        while (names.count < count) names.append({value: ""})
        if (names.count > count) names.remove(count, names.count - count)
        error = ""
    }
    function confirm() {
        let values = [], seen = []
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
        confirmed(rowIndex, JSON.stringify(values)); close()
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
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true
            Layout.preferredHeight: Math.min(Theme.control(240), fields.implicitHeight)
            clip: true; contentWidth: availableWidth
            ColumnLayout {
                id: fields; width: parent.width; spacing: 8
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
        Text { visible: !!root.error; text: root.error; color: Theme.danger; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12); Layout.fillWidth: true; wrapMode: Text.Wrap }
        RowLayout {
            Layout.fillWidth: true
            ActionButton { objectName: root.objectName + "_reset"; text: I18n.t("恢复默认"); quiet: true; onClicked: { names.clear(); Reasoning.defaults.forEach(value => names.append({value:value})); count.value = 3; root.error = "" } }
            Item { Layout.fillWidth: true }
            ActionButton { objectName: root.objectName + "_cancel"; text: I18n.t("取消"); quiet: true; onClicked: root.close() }
            ActionButton { objectName: root.objectName + "_save"; text: I18n.t("确定"); primary: true; onClicked: root.confirm() }
        }
    }
}
