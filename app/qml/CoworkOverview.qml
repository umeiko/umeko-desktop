import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    required property var service
    signal createRequested(string typeId)
    signal editTypeRequested(string typeId)
    signal openInstanceRequested(string instanceId)

    color: Theme.bg
    clip: true

    function tr(zh, en) { return backend.language === "en" ? en : zh }

    function tonePalette(tone) {
        const dark = Theme.dark
        const map = {
            sage:   dark ? { bg: "#1f3328", fg: "#7fd1a2", border: "#355d47" } : { bg: "#e8f4ec", fg: "#256945", border: "#b7dec6" },
            blue:   dark ? { bg: "#1d2d47", fg: "#7fb0ff", border: "#335182" } : { bg: "#e8f1ff", fg: "#265fd8", border: "#b9d3ff" },
            violet: dark ? { bg: "#2d2347", fg: "#b49cff", border: "#4d3c7a" } : { bg: "#f1ecff", fg: "#6741d9", border: "#d3c3ff" },
            amber:  dark ? { bg: "#3b2d17", fg: "#f4be66", border: "#664d24" } : { bg: "#fef3dc", fg: "#b46900", border: "#f5d79b" },
            teal:   dark ? { bg: "#1a3534", fg: "#6cd4cc", border: "#2f615f" } : { bg: "#e4f5f4", fg: "#0f766e", border: "#aee2de" },
            rose:   dark ? { bg: "#3d212c", fg: "#f58ead", border: "#6b384c" } : { bg: "#fdebf0", fg: "#c4325e", border: "#f5bfd0" },
            indigo: dark ? { bg: "#222847", fg: "#93a4ff", border: "#3c477d" } : { bg: "#ebefff", fg: "#3b4cc0", border: "#c3cdfc" }
        }
        return map[tone] || map.blue
    }

    function instanceCount(typeId) {
        const list = service.instances || []
        let count = 0
        for (let i = 0; i < list.length; ++i) {
            if (list[i].typeId === typeId) count++
        }
        return count
    }

    // Block clicks from passing through to the underlying chat canvas.
    MouseArea { anchors.fill: parent }

    // Subtle top ambient gradient wash so the empty state feels calm and crafted.
    Rectangle {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 220
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.alpha(Theme.accent, Theme.dark ? 0.08 : 0.045) }
            GradientStop { position: 1.0; color: "transparent" }
        }
    }

    ScrollView {
        id: scroller
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

        Item {
            width: scroller.availableWidth
            implicitHeight: container.implicitHeight + 64

            ColumnLayout {
                id: container
                readonly property real maxContentWidth: Math.min(940, Math.max(360, parent.width - 56))
                width: maxContentWidth
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.topMargin: 24
                spacing: 24

                // Hero banner
                Rectangle {
                    id: heroCard
                    Layout.fillWidth: true
                    implicitHeight: heroLayout.implicitHeight + 44
                    radius: 16
                    color: Theme.surface
                    border.color: Theme.line
                    clip: true

                    Rectangle {
                        width: 220; height: 220; radius: 110
                        anchors.right: parent.right; anchors.rightMargin: -56
                        anchors.top: parent.top; anchors.topMargin: -92
                        color: Qt.alpha(Theme.accent, Theme.dark ? 0.12 : 0.07)
                    }
                    Rectangle {
                        width: 140; height: 140; radius: 70
                        anchors.right: parent.right; anchors.rightMargin: 96
                        anchors.bottom: parent.bottom; anchors.bottomMargin: -76
                        color: Qt.alpha(Theme.accent, Theme.dark ? 0.07 : 0.045)
                    }

                    GridLayout {
                        id: heroLayout
                        anchors.fill: parent
                        anchors.margins: 22
                        columns: heroCard.width >= 640 ? 2 : 1
                        columnSpacing: 20
                        rowSpacing: 16

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 15

                            Rectangle {
                                Layout.preferredWidth: 48
                                Layout.preferredHeight: 48
                                Layout.alignment: Qt.AlignTop
                                radius: 13
                                color: Theme.accentBg
                                border.color: Qt.alpha(Theme.accent, Theme.dark ? 0.35 : 0.18)
                                Glyph {
                                    anchors.centerIn: parent
                                    name: "spark"
                                    width: Theme.icon(22)
                                    height: Theme.icon(22)
                                    color: Theme.accent
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 5

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8
                                    Text {
                                        text: "Cowork"
                                        color: Theme.ink
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.font(21)
                                        font.weight: Font.DemiBold
                                    }
                                    ExperimentalBadge {}
                                    Item { Layout.fillWidth: true }
                                }

                                Text {
                                    Layout.fillWidth: true
                                    text: root.tr(
                                        "为不同任务配置专属 AI 协作者，独立管理工作目录、Tools、Skills 与子智能体。",
                                        "Configure dedicated AI coworkers with scoped working folders, Tools, Skills and subagents."
                                    )
                                    color: Theme.muted
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.font(12)
                                    lineHeight: 1.45
                                    wrapMode: Text.Wrap
                                }
                            }
                        }

                        RowLayout {
                            Layout.alignment: heroCard.width >= 640 ? (Qt.AlignRight | Qt.AlignVCenter) : Qt.AlignLeft
                            spacing: 8

                            ActionButton {
                                objectName: "coworkEmptyNewType"
                                glyph: "sliders"
                                text: root.tr("新建大类", "New type")
                                implicitHeight: Theme.control(38)
                                onClicked: root.editTypeRequested("")
                            }

                            ActionButton {
                                objectName: "coworkEmptyCreate"
                                primary: true
                                glyph: "plus"
                                text: root.tr("新建 Coworker", "New coworker")
                                implicitHeight: Theme.control(38)
                                onClicked: root.createRequested("")
                            }
                        }
                    }
                }

                // Existing Coworker instances (shown when the user already has instances)
                ColumnLayout {
                    visible: (root.service.instances || []).length > 0
                    Layout.fillWidth: true
                    spacing: 12

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        Text {
                            text: root.tr("我的 Coworkers", "My Coworkers")
                            color: Theme.ink
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.font(14)
                            font.weight: Font.DemiBold
                        }

                        Rectangle {
                            radius: 9
                            color: Theme.accentBg
                            implicitWidth: instanceCountText.implicitWidth + 14
                            implicitHeight: 20
                            Text {
                                id: instanceCountText
                                anchors.centerIn: parent
                                text: String((root.service.instances || []).length)
                                color: Theme.accent
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.font(10)
                                font.weight: Font.DemiBold
                            }
                        }

                        Item { Layout.fillWidth: true }

                        Text {
                            text: root.tr("点击卡片继续协作", "Click a card to jump back in")
                            color: Theme.muted
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.font(11)
                        }
                    }

                    Flow {
                        id: instanceFlow
                        Layout.fillWidth: true
                        spacing: 12
                        readonly property int columns: width >= 760 ? 3 : width >= 460 ? 2 : 1
                        readonly property real cardWidth: Math.floor((width - spacing * (columns - 1)) / columns)

                        Repeater {
                            model: root.service.instances || []
                            delegate: Rectangle {
                                id: instanceCard
                                required property var modelData
                                readonly property var tone: root.tonePalette(modelData.tone)
                                objectName: "coworkInstanceCard_" + modelData.id
                                width: instanceFlow.cardWidth
                                height: Math.max(76, Math.round(76 * Math.max(1, Theme.fontScale)))
                                radius: 13
                                color: instanceMouse.containsMouse ? (Theme.dark ? Qt.lighter(Theme.surface, 1.07) : Theme.hover) : Theme.surface
                                border.color: instanceMouse.containsMouse ? tone.border : Theme.line
                                Behavior on color { ColorAnimation { duration: 130 } }
                                Behavior on border.color { ColorAnimation { duration: 130 } }

                                MouseArea {
                                    id: instanceMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.openInstanceRequested(instanceCard.modelData.id)
                                }

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 13
                                    spacing: 12

                                    Rectangle {
                                        Layout.preferredWidth: 38
                                        Layout.preferredHeight: 38
                                        radius: 10
                                        color: instanceCard.tone.bg
                                        Glyph {
                                            anchors.centerIn: parent
                                            name: instanceCard.modelData.icon || "spark"
                                            width: Theme.icon(18)
                                            height: Theme.icon(18)
                                            color: instanceCard.tone.fg
                                        }
                                    }

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 3

                                        Text {
                                            Layout.fillWidth: true
                                            text: instanceCard.modelData.name
                                            textFormat: Text.PlainText
                                            elide: Text.ElideRight
                                            color: Theme.ink
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.font(13)
                                            font.weight: Font.DemiBold
                                        }

                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 5
                                            Glyph {
                                                name: "folder"
                                                width: Theme.icon(11)
                                                height: Theme.icon(11)
                                                color: Theme.muted
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                text: instanceCard.modelData.folder + " · " + instanceCard.modelData.typeName
                                                textFormat: Text.PlainText
                                                elide: Text.ElideRight
                                                color: Theme.muted
                                                font.family: Theme.fontFamily
                                                font.pixelSize: Theme.font(11)
                                            }
                                        }
                                    }

                                    Glyph {
                                        name: "arrow-right"
                                        width: Theme.icon(15)
                                        height: Theme.icon(15)
                                        color: instanceMouse.containsMouse ? instanceCard.tone.fg : Theme.muted
                                        opacity: instanceMouse.containsMouse ? 1 : 0.55
                                    }
                                }

                                HoverTip {
                                    active: instanceMouse.containsMouse && !!instanceCard.modelData.workspace
                                    text: instanceCard.modelData.workspace || ""
                                }
                            }
                        }
                    }
                }

                // Available Coworker catalog section
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 12

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        Text {
                            text: root.tr("可用 Coworker", "Available Coworkers")
                            color: Theme.ink
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.font(14)
                            font.weight: Font.DemiBold
                        }

                        Rectangle {
                            radius: 9
                            color: Theme.surface
                            border.color: Theme.line
                            implicitWidth: catalogCountText.implicitWidth + 14
                            implicitHeight: 20
                            Text {
                                id: catalogCountText
                                anchors.centerIn: parent
                                text: String((root.service.catalog || []).length)
                                color: Theme.muted
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.font(10)
                                font.weight: Font.DemiBold
                            }
                        }

                        Item { Layout.fillWidth: true }

                        Text {
                            text: root.tr("选择角色卡片即可快速创建实例", "Choose a role card to create an instance")
                            color: Theme.muted
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.font(11)
                        }
                    }

                    Flow {
                        id: catalogFlow
                        Layout.fillWidth: true
                        spacing: 14
                        readonly property int columns: width >= 760 ? 3 : width >= 460 ? 2 : 1
                        readonly property real cardWidth: Math.floor((width - spacing * (columns - 1)) / columns)
                        readonly property real cardHeight: Math.max(170, Math.round(170 * Math.max(1, Theme.fontScale)))

                        Repeater {
                            model: root.service.catalog || []
                            delegate: Rectangle {
                                id: typeCard
                                required property var modelData
                                readonly property var tone: root.tonePalette(modelData.tone)
                                readonly property int activeInstances: root.instanceCount(modelData.id)
                                readonly property bool cardHovered: cardMouse.containsMouse || editTypeButton.hovered
                                objectName: "coworkCard_" + modelData.id
                                width: catalogFlow.cardWidth
                                height: catalogFlow.cardHeight
                                radius: 14
                                color: cardHovered ? (Theme.dark ? Qt.lighter(Theme.surface, 1.07) : Theme.surface) : Theme.surface
                                border.color: cardHovered ? tone.border : Theme.line
                                clip: true
                                Behavior on color { ColorAnimation { duration: 140 } }
                                Behavior on border.color { ColorAnimation { duration: 140 } }

                                // Soft top highlight strip revealed on hover.
                                Rectangle {
                                    anchors.top: parent.top
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    height: 3
                                    color: typeCard.tone.fg
                                    opacity: typeCard.cardHovered ? 0.85 : 0
                                    Behavior on opacity { NumberAnimation { duration: 150 } }
                                }

                                MouseArea {
                                    id: cardMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.createRequested(typeCard.modelData.id)
                                }

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 16
                                    spacing: 10

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 11

                                        Rectangle {
                                            Layout.preferredWidth: 38
                                            Layout.preferredHeight: 38
                                            radius: 10
                                            color: typeCard.tone.bg
                                            Glyph {
                                                anchors.centerIn: parent
                                                name: typeCard.modelData.icon || "spark"
                                                width: Theme.icon(19)
                                                height: Theme.icon(19)
                                                color: typeCard.tone.fg
                                            }
                                        }

                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 3

                                            Text {
                                                Layout.fillWidth: true
                                                text: typeCard.modelData.name
                                                textFormat: Text.PlainText
                                                elide: Text.ElideRight
                                                color: Theme.ink
                                                font.family: Theme.fontFamily
                                                font.pixelSize: Theme.font(14)
                                                font.weight: Font.DemiBold
                                            }

                                            RowLayout {
                                                Layout.fillWidth: true
                                                spacing: 5

                                                Rectangle {
                                                    visible: typeCard.modelData.custom === true
                                                    radius: 4
                                                    color: Theme.accentBg
                                                    implicitWidth: customLabel.implicitWidth + 10
                                                    implicitHeight: customLabel.implicitHeight + 4
                                                    Text {
                                                        id: customLabel
                                                        anchors.centerIn: parent
                                                        text: root.tr("自定义", "Custom")
                                                        color: Theme.accent
                                                        font.family: Theme.fontFamily
                                                        font.pixelSize: Theme.font(9)
                                                        font.weight: Font.Medium
                                                    }
                                                }

                                                Rectangle {
                                                    visible: typeCard.activeInstances > 0
                                                    radius: 4
                                                    color: typeCard.tone.bg
                                                    implicitWidth: activeCountLabel.implicitWidth + 10
                                                    implicitHeight: activeCountLabel.implicitHeight + 4
                                                    Text {
                                                        id: activeCountLabel
                                                        anchors.centerIn: parent
                                                        text: root.tr(typeCard.activeInstances + " 个实例", typeCard.activeInstances + " active")
                                                        color: typeCard.tone.fg
                                                        font.family: Theme.fontFamily
                                                        font.pixelSize: Theme.font(9)
                                                        font.weight: Font.Medium
                                                    }
                                                }

                                                Text {
                                                    visible: !typeCard.modelData.custom && typeCard.activeInstances === 0
                                                    Layout.fillWidth: true
                                                    text: typeCard.modelData.context || ""
                                                    textFormat: Text.PlainText
                                                    elide: Text.ElideRight
                                                    color: Theme.muted
                                                    font.family: Theme.fontFamily
                                                    font.pixelSize: Theme.font(10)
                                                }
                                            }
                                        }

                                        ActionButton {
                                            id: editTypeButton
                                            objectName: "coworkCardEdit_" + typeCard.modelData.id
                                            z: 2
                                            glyph: "settings"
                                            quiet: true
                                            implicitWidth: 30
                                            implicitHeight: 30
                                            opacity: typeCard.cardHovered ? 1 : 0.45
                                            hint: root.tr("配置 Coworker 大类", "Configure Coworker type")
                                            Accessible.name: hint
                                            onClicked: root.editTypeRequested(typeCard.modelData.id)
                                            Behavior on opacity { NumberAnimation { duration: 140 } }
                                        }
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: typeCard.modelData.description || root.tr("使用自定义提示词与工具协助完成任务。", "Assists with tasks using custom instructions and tools.")
                                        textFormat: Text.PlainText
                                        color: Theme.muted
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.font(12)
                                        lineHeight: 1.4
                                        wrapMode: Text.Wrap
                                        maximumLineCount: 2
                                        elide: Text.ElideRight
                                    }

                                    Item { Layout.fillHeight: true }

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 6

                                        CapabilityChip {
                                            visible: (typeCard.modelData.toolCount || 0) > 0
                                            label: typeCard.modelData.toolCount + " Tools"
                                        }
                                        CapabilityChip {
                                            visible: (typeCard.modelData.skillCount || 0) > 0
                                            label: typeCard.modelData.skillCount + (typeCard.modelData.skillCount === 1 ? " Skill" : " Skills")
                                        }
                                        CapabilityChip {
                                            visible: (typeCard.modelData.subagentCount || 0) > 0
                                            label: root.tr(typeCard.modelData.subagentCount + " 子智能体", typeCard.modelData.subagentCount + " Agents")
                                        }

                                        Item { Layout.fillWidth: true }

                                        Row {
                                            spacing: 4
                                            Text {
                                                text: root.tr("使用", "Use")
                                                color: typeCard.cardHovered ? typeCard.tone.fg : Theme.muted
                                                font.family: Theme.fontFamily
                                                font.pixelSize: Theme.font(11)
                                                font.weight: Font.Medium
                                                anchors.verticalCenter: parent.verticalCenter
                                                Behavior on color { ColorAnimation { duration: 140 } }
                                            }
                                            Glyph {
                                                name: "arrow-right"
                                                width: Theme.icon(13)
                                                height: Theme.icon(13)
                                                color: typeCard.cardHovered ? typeCard.tone.fg : Theme.muted
                                                anchors.verticalCenter: parent.verticalCenter
                                                transform: Translate {
                                                    x: typeCard.cardHovered ? 2 : 0
                                                    Behavior on x { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        // Create custom Coworker type card
                        Rectangle {
                            id: customCard
                            objectName: "coworkCardNewType"
                            width: catalogFlow.cardWidth
                            height: catalogFlow.cardHeight
                            radius: 14
                            color: customMouse.containsMouse ? Theme.accentBg : Qt.alpha(Theme.surface, Theme.dark ? 0.55 : 0.72)
                            border.color: customMouse.containsMouse ? Theme.accent : Theme.line
                            Behavior on color { ColorAnimation { duration: 140 } }
                            Behavior on border.color { ColorAnimation { duration: 140 } }

                            MouseArea {
                                id: customMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.editTypeRequested("")
                            }

                            ColumnLayout {
                                anchors.centerIn: parent
                                width: parent.width - 36
                                spacing: 10

                                Rectangle {
                                    Layout.alignment: Qt.AlignHCenter
                                    Layout.preferredWidth: 42
                                    Layout.preferredHeight: 42
                                    radius: 21
                                    color: customMouse.containsMouse ? Theme.accent : Theme.accentBg
                                    Behavior on color { ColorAnimation { duration: 140 } }
                                    Glyph {
                                        anchors.centerIn: parent
                                        name: "plus"
                                        width: Theme.icon(19)
                                        height: Theme.icon(19)
                                        color: customMouse.containsMouse ? Theme.buttonText : Theme.accent
                                    }
                                }

                                Text {
                                    Layout.fillWidth: true
                                    horizontalAlignment: Text.AlignHCenter
                                    text: root.tr("自定义 Coworker", "Custom Coworker")
                                    color: Theme.ink
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.font(14)
                                    font.weight: Font.DemiBold
                                }

                                Text {
                                    Layout.fillWidth: true
                                    horizontalAlignment: Text.AlignHCenter
                                    text: root.tr("自由组合系统提示词、Tools、Skills 与子智能体池", "Combine custom prompts, Tools, Skills and subagents")
                                    color: Theme.muted
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.font(11)
                                    lineHeight: 1.4
                                    wrapMode: Text.Wrap
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    component CapabilityChip: Rectangle {
        property string label: ""
        radius: 6
        color: Theme.bg
        border.color: Theme.line
        implicitWidth: chipText.implicitWidth + 12
        implicitHeight: chipText.implicitHeight + 6
        Text {
            id: chipText
            anchors.centerIn: parent
            text: parent.label
            textFormat: Text.PlainText
            color: Theme.muted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.font(10)
        }
    }
}
