import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    required property var player
    required property string key
    required property string path
    required property string itemId
    required property string title
    property string formatLabel: ""
    property var selectionController
    property bool playbackAllowed: true
    signal openRequested()
    signal menuRequested(point at)
    readonly property bool current: player && player.activeKey === key
    readonly property bool playing: current && player.playing
    readonly property real duration: current ? player.duration : 0
    readonly property real position: current ? player.position : 0
    readonly property string volumeLabel: backend.language === "en" ? "Volume" : "音量"
    property string previousKey: ""
    spacing: 0
    onPlaybackAllowedChanged: {
        if (playbackAllowed) return
        if (volumePanel) volumePanel.close()
        if (player) player.deactivate(key)
    }
    onKeyChanged: {
        if (player && previousKey) player.deactivate(previousKey)
        previousKey = key
    }
    Component.onCompleted: previousKey = key
    Component.onDestruction: if (player) player.deactivate(previousKey)

    function timeLabel(ms) {
        const s = Math.max(0, Math.floor(ms / 1000))
        return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0")
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.margins: Theme.control(12)
        spacing: Theme.control(11)
        AudioIconButton {
            id: playbackButton
            objectName: "chatboxAudioPlay_" + root.itemId
            label: root.playing ? (backend.language === "en" ? "Pause" : "暂停") : (backend.language === "en" ? "Play" : "播放")
            iconName: root.playing ? "audio-pause" : "audio-play"
            emphasized: true
            filled: root.playing
            enabled: root.playbackAllowed
            interactionOwner: root.selectionController
            onClicked: root.player.toggle(root.key, root.path)
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: headline.implicitHeight + 6
                    Text {
                        id: headline
                        objectName: "chatboxAudioTitle_" + root.itemId
                        width: parent.width
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.title
                        textFormat: Text.PlainText
                        elide: Text.ElideMiddle
                        color: titleArea.interactionHovered ? Theme.accent : Theme.ink
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.font(13, visible, root.selectionController)
                        font.weight: Font.DemiBold
                    }
                    ChatHitArea {
                        id: titleArea
                        objectName: "openChatboxAudio_" + root.itemId
                        anchors.fill: parent
                        selectionController: root.selectionController
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        onClicked: mouse => {
                            if (mouse.button === Qt.RightButton) root.menuRequested(mapToItem(root, mouse.x, mouse.y))
                            else root.openRequested()
                        }
                    }
                    HoverTip { active: titleArea.interactionHovered && !titleArea.pressed; text: root.title }
                    Accessible.role: Accessible.Button
                    Accessible.name: root.title
                    Accessible.onPressAction: root.openRequested()
                }
                Rectangle {
                    visible: root.formatLabel.length > 0 && root.width > Theme.control(250)
                    implicitWidth: formatText.implicitWidth + 10
                    implicitHeight: formatText.implicitHeight + 4
                    radius: 4
                    color: Theme.hover
                    Text {
                        id: formatText
                        anchors.centerIn: parent
                        text: root.formatLabel
                        color: Theme.muted
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.font(9, visible, root.selectionController)
                        font.weight: Font.Medium
                    }
                }
                AudioIconButton {
                    id: volumeButton
                    objectName: "chatboxAudioVolumeButton_" + root.itemId
                    label: root.volumeLabel
                    iconName: root.player && root.player.volume === 0 ? "audio-muted" : "audio-volume"
                    interactionOwner: root.selectionController
                    highlighted: volumePanel.visible
                    onClicked: { if (volumePanel.visible) volumePanel.close(); else volumePanel.open() }
                    Popup {
                        id: volumePanel
                        objectName: "chatboxAudioVolumePanel_" + root.itemId
                        parent: volumeButton
                        x: volumeButton.width - width
                        y: volumeButton.height + seek.height + Theme.control(15)
                        width: Theme.control(166)
                        padding: 10
                        focus: true
                        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
                        onOpened: volume.forceActiveFocus(Qt.PopupFocusReason)
                        background: Rectangle {
                            color: Theme.surface
                            border.color: Theme.line
                            radius: 9
                        }
                        contentItem: ColumnLayout {
                            spacing: 3
                            RowLayout {
                                Layout.fillWidth: true
                                Text {
                                    Layout.fillWidth: true
                                    text: root.volumeLabel
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.font(11, visible, root.selectionController)
                                    color: Theme.ink
                                }
                                Text {
                                    text: Math.round(volume.value * 100) + "%"
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.font(10, visible, root.selectionController)
                                    color: Theme.muted
                                }
                            }
                            AudioSlider {
                                id: volume
                                objectName: "chatboxAudioVolume_" + root.itemId
                                Accessible.name: root.volumeLabel
                                Layout.fillWidth: true
                                from: 0; to: 1; stepSize: 0.01
                                Binding on value { when: !volume.pressed; value: root.player ? root.player.volume : 0.7; restoreMode: Binding.RestoreNone }
                                onMoved: root.player.setVolume(value)
                            }
                        }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                AudioSlider {
                    id: seek
                    owner: root.selectionController
                    objectName: "chatboxAudioSeek_" + root.itemId
                    Accessible.name: backend.language === "en" ? "Playback position" : "播放进度"
                    Layout.fillWidth: true
                    from: 0; to: Math.max(1, root.duration)
                    property real pendingSeek: -1
                    enabled: root.current && root.player.seekable && root.duration > 0
                    Binding on value { when: !seek.pressed; value: root.position; restoreMode: Binding.RestoreNone }
                    onMoved: {
                        if (pressed) pendingSeek = value
                        else root.player.seek(root.key, value)
                    }
                    onPressedChanged: {
                        if (!pressed && pendingSeek >= 0) root.player.seek(root.key, pendingSeek)
                        pendingSeek = -1
                    }
                }
                Text {
                    text: root.timeLabel(seek.pressed ? seek.position * root.duration : root.position)
                          + (root.duration > 0 ? " / " + root.timeLabel(root.duration) : "")
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.font(10, visible, root.selectionController)
                    color: Theme.muted
                }
            }
        }
    }
    Text {
        visible: root.current && root.player.failed
        Layout.fillWidth: true
        Layout.leftMargin: 12; Layout.rightMargin: 12; Layout.bottomMargin: 10
        wrapMode: Text.Wrap
        text: backend.language === "en" ? "Cannot play this audio. Click the filename to open the original." : "无法播放此音频。可点击文件名打开原文件。"
        font.family: Theme.fontFamily
        font.pixelSize: Theme.font(11, visible, root.selectionController)
        color: Theme.danger
    }

    component AudioIconButton: AbstractButton {
        id: control
        required property string label
        required property string iconName
        property var interactionOwner: null
        property int interactionPriority: 10
        property bool emphasized: false
        property bool filled: false
        property bool highlighted: false
        implicitWidth: Theme.control(emphasized ? 42 : 27)
        implicitHeight: implicitWidth
        hoverEnabled: true
        activeFocusOnTab: true
        Accessible.name: label
        Component.onCompleted: if (interactionOwner) interactionOwner.attachInteraction(control)
        Component.onDestruction: if (interactionOwner) interactionOwner.detachInteraction(control)
        background: Rectangle {
            radius: width / 2
            color: control.filled ? Theme.button
                   : control.emphasized ? control.hovered ? Qt.alpha(Theme.accent, .20) : Theme.accentBg
                   : control.hovered || control.highlighted ? Theme.hover : "transparent"
            border.color: control.visualFocus ? Theme.accent : "transparent"
            Behavior on color { ColorAnimation { duration: 120 } }
        }
        contentItem: Item {
            Glyph {
                anchors.centerIn: parent
                name: control.iconName
                width: Theme.icon(control.emphasized ? 19 : 16)
                height: width
                color: control.filled ? Theme.buttonText : control.emphasized || control.highlighted ? Theme.accent : Theme.muted
            }
        }
        HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
        HoverTip { active: control.hovered && !control.pressed && !control.highlighted; text: control.label }
    }
    component AudioSlider: Slider {
        id: control
        property var owner: null
        property int interactionPriority: 10
        implicitWidth: 68
        implicitHeight: Theme.control(20)
        leftPadding: 4; rightPadding: 4; topPadding: 0; bottomPadding: 0
        hoverEnabled: true
        activeFocusOnTab: true
        Component.onCompleted: if (owner) owner.attachInteraction(control)
        Component.onDestruction: if (owner) owner.detachInteraction(control)
        background: Rectangle {
            x: control.leftPadding
            y: (control.height - height) / 2
            width: Math.max(0, control.availableWidth)
            height: 4
            radius: 2
            color: Theme.line
            Rectangle {
                x: control.mirrored ? parent.width - width : 0
                width: Math.max(0, parent.width * control.position)
                height: parent.height
                radius: 2
                color: Theme.accent
            }
        }
        handle: Rectangle {
            width: 8; height: width; radius: width / 2
            x: control.leftPadding + control.availableWidth * control.visualPosition - width / 2
            y: (control.height - height) / 2
            color: Theme.accent
            opacity: control.enabled && (control.hovered || control.pressed || control.visualFocus || control.position > 0) ? 1 : 0
            border.width: control.visualFocus ? 1 : 0
            border.color: Theme.ink
            Behavior on opacity { NumberAnimation { duration: 100 } }
        }
    }
}
