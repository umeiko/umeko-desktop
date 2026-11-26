import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtQuick.Window
import "theme.js" as Colors

PidPopup {
    id: root
    objectName: "chatWallpaperDialog"
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(788, parent.width - 32)
    height: Math.min(parent.height - 32,
                     heading.implicitHeight + editor.implicitHeight + footer.implicitHeight + body.spacing * 2 + padding * 2)
    readonly property var service: backend.chatWallpaper
    readonly property var hostWindow: parent ? parent.Window.window : null
    readonly property var saved: service.settings
    readonly property var draft: service.draft
    property bool clearSavedImage: false
    property bool alternateTheme: false
    property var options: service.defaults
    readonly property string previewSource: draft.source || (clearSavedImage ? "" : saved.source)
    readonly property string previewName: draft.name || (clearSavedImage ? "" : saved.name)
    readonly property bool hasCharacterImage: String(Character.wallpaper) !== ""
    readonly property bool hasImage: hasCharacterImage || previewSource !== ""
    readonly property real strength: Theme.wallpaperOpacity(options.opacity, previewSource !== "")
    readonly property bool canApply: !draft.busy && (draft.source !== "" ||
        (clearSavedImage && saved.source !== "") || optionsDiffer(options, saved))
    readonly property var previewColors: alternateTheme ? Colors.palette(Theme.dark ? "white" : "dark") : Theme.palette

    function begin() {
        service.discard()
        clearSavedImage = false
        alternateTheme = false
        options = Object.assign({}, saved)
        open()
    }
    function optionsDiffer(left, right) {
        return Object.keys(service.defaults).some(key => left[key] !== right[key])
    }
    function setOption(key, value) {
        const edited = Object.assign({}, options)
        edited[key] = value
        options = edited
    }
    function restoreDefaults() {
        clearSavedImage = true
        service.discard()
        options = service.defaults
    }
    onClosed: service.discard()
    onVisibleChanged: if (hostWindow) hostWindow.wallpaperDialogVisible = visible

    Loader {
        id: placementDialog
        active: false
        sourceComponent: ChatWallpaperPlacementDialog {
            z: root.z + 1
            source: root.previewSource; mode: root.options.mode
            chatAspect: root.hostWindow ? root.hostWindow.chatWallpaperAspect : 1
            onPlacementAccepted: adjustment => root.options = Object.assign({}, root.options, adjustment)
        }
    }

    FileDialog {
        id: picker
        objectName: "chatWallpaperFileDialog"
        title: I18n.t("选择背景图")
        nameFilters: [I18n.t("图片 (*.png *.jpg *.jpeg *.webp)")]
        onAccepted: root.service.chooseImage(selectedFile)
    }

    component Adjustment: ColumnLayout {
        id: adjustment
        required property string label
        required property int minimum
        required property int maximum
        required property real value
        property real step: 1
        signal edited(real next)
        spacing: 3
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                font.family: Theme.fontFamily; font.pixelSize: Theme.font(12); color: Theme.ink
                text: adjustment.label
            }
            Text {
                font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                color: adjustment.enabled ? Theme.accent : Theme.muted
                text: adjustment.value + "%"
            }
        }
        Slider {
            id: slider
            objectName: adjustment.objectName + "Slider"
            Layout.fillWidth: true; implicitHeight: Theme.control(27)
            padding: 0
            from: adjustment.minimum; to: adjustment.maximum; stepSize: adjustment.step
            snapMode: Slider.SnapAlways
            value: adjustment.value
            onMoved: adjustment.edited(Math.round(value / stepSize) * stepSize)
            Accessible.name: adjustment.label
            background: Rectangle {
                x: 0; y: (slider.height - height) / 2
                width: slider.width; height: 4; radius: 2; color: Theme.line
                Rectangle {
                    width: parent.width * slider.visualPosition; height: parent.height; radius: parent.radius
                    color: slider.enabled ? Theme.accent : Theme.line
                }
            }
            handle: Rectangle {
                x: slider.visualPosition * Math.max(0, slider.width - width)
                y: (slider.height - height) / 2
                width: Theme.control(15); height: width; radius: width / 2
                color: slider.pressed ? Theme.accent : Theme.surface
                border.color: slider.enabled ? Theme.accent : Theme.line
                border.width: slider.activeFocus ? 2 : 1
            }
        }
    }

    contentItem: Item {
        ColumnLayout {
            id: body
            anchors.fill: parent
            spacing: 16

            RowLayout {
                id: heading
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    text: I18n.t("聊天背景"); color: Theme.ink
                    font.family: Theme.fontFamily; font.pixelSize: Theme.font(19); font.weight: Font.DemiBold
                }
                ActionButton { glyph: "x"; quiet: true; hint: I18n.t("关闭"); Accessible.name: hint; onClicked: root.close() }
            }

            ScrollView {
                id: scroll
                Layout.fillWidth: true; Layout.fillHeight: true
                contentWidth: availableWidth; contentHeight: editor.implicitHeight
                clip: true
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                GridLayout {
                    id: editor
                    width: scroll.availableWidth
                    columns: width >= 644 && Theme.fontScale <= 1.4 ? 2 : 1
                    columnSpacing: 20; rowSpacing: 20

                    ColumnLayout {
                        Layout.fillWidth: true; Layout.preferredWidth: 428; Layout.minimumWidth: 0; Layout.alignment: Qt.AlignTop
                        spacing: 8
                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                Layout.fillWidth: true
                                text: I18n.t("预览"); color: Theme.ink
                                font.family: Theme.fontFamily; font.pixelSize: Theme.font(12); font.weight: Font.DemiBold
                            }
                            ActionButton {
                                objectName: "wallpaperPreviewTheme"
                                quiet: true; glyph: "eye"; height: Theme.control(30)
                                text: I18n.t(root.alternateTheme ? "当前主题" : Theme.dark ? "浅色预览" : "深色预览")
                                onClicked: root.alternateTheme = !root.alternateTheme
                            }
                        }
                        Rectangle {
                            id: previewFrame
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.max(248, mockChat.implicitHeight + 46)
                            color: root.previewColors.bg; border.color: root.previewColors.line; radius: 11

                            Item {
                                anchors.fill: parent; anchors.margins: 7
                                ChatWallpaperLayer {
                                    objectName: "wallpaperPreviewLayer"
                                    anchors.fill: parent
                                    source: root.visible ? root.previewSource : ""
                                    useCharacter: root.visible && root.previewSource === "" && root.strength > 0
                                    seaSaltDecorations: Theme.yanami && !root.alternateTheme && root.previewSource === ""
                                    mode: root.options.mode; strength: root.strength; zoom: root.options.zoom
                                    offsetX: root.options.offsetX; offsetY: root.options.offsetY; angle: root.options.angle
                                }
                            }
                            ColumnLayout {
                                id: mockChat
                                anchors.fill: parent; anchors.margins: 19
                                spacing: 9
                                Rectangle {
                                    Layout.alignment: Qt.AlignRight
                                    Layout.maximumWidth: mockChat.width
                                    implicitWidth: userSample.implicitWidth + 22
                                    implicitHeight: userSample.implicitHeight + 14
                                    radius: 9; color: root.previewColors.userBubble
                                    Text {
                                        id: userSample
                                        anchors.fill: parent; anchors.margins: 7
                                        text: I18n.t("看看项目有哪些改动"); color: root.previewColors.ink
                                        font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                                        horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
                                    }
                                }
                                Text {
                                    Layout.fillWidth: true; Layout.topMargin: 5
                                    text: I18n.t("可以先用这条命令查看改动。"); color: root.previewColors.ink
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); wrapMode: Text.Wrap
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: codeSample.implicitHeight + 20
                                    radius: 7; color: root.previewColors.surface; border.color: root.previewColors.line
                                    Text {
                                        id: codeSample; x: 11; anchors.verticalCenter: parent.verticalCenter
                                        text: "git status --short"; color: root.previewColors.ink
                                        font.family: "monospace"; font.pixelSize: Theme.font(11)
                                    }
                                }
                                Item { Layout.fillHeight: true; Layout.minimumHeight: 4 }
                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: Theme.control(37)
                                    radius: 10; color: root.previewColors.surface; border.color: root.previewColors.line
                                    Text {
                                        x: 11; anchors.verticalCenter: parent.verticalCenter
                                        text: I18n.t("输入消息…"); color: root.previewColors.muted
                                        font.family: Theme.fontFamily; font.pixelSize: Theme.font(11)
                                    }
                                    Rectangle {
                                        anchors.right: parent.right; anchors.rightMargin: 6; anchors.verticalCenter: parent.verticalCenter
                                        width: Theme.control(24); height: width; radius: 7
                                        color: root.previewColors.button
                                        Glyph { name: "arrow-up"; width: Theme.icon(14); height: width; anchors.centerIn: parent; color: root.previewColors.buttonText }
                                    }
                                }
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true; Layout.preferredWidth: 265; Layout.minimumWidth: 0; Layout.alignment: Qt.AlignTop
                        spacing: 12
                        RowLayout {
                            Layout.fillWidth: true
                            Glyph { name: "image"; width: Theme.icon(18); height: width }
                            Text {
                                Layout.fillWidth: true
                                text: root.previewSource !== "" ? root.previewName || I18n.t("自定义背景")
                                    : root.hasCharacterImage ? I18n.t("默认图片 · %1").arg(I18n.t(Character.style.name))
                                    : I18n.t("默认背景")
                                textFormat: Text.PlainText; elide: Text.ElideMiddle; color: Theme.ink
                                font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                            }
                        }
                        ActionButton {
                            objectName: "chooseWallpaperImage"
                            Layout.fillWidth: true
                            enabled: !root.draft.busy
                            glyph: "folder"; text: I18n.t(root.draft.busy ? "正在读取图片…" : "选择背景图")
                            onClicked: picker.open()
                        }
                        Text {
                            objectName: "wallpaperError"
                            Layout.fillWidth: true
                            visible: root.draft.error !== ""
                            text: I18n.t(root.draft.error); color: Theme.danger
                            font.family: Theme.fontFamily; font.pixelSize: Theme.font(11); wrapMode: Text.Wrap
                        }
                        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
                        RowLayout {
                            Layout.fillWidth: true
                            enabled: root.hasImage
                            Text {
                                Layout.fillWidth: true
                                text: I18n.t("显示方式"); color: enabled ? Theme.ink : Theme.muted
                                font.family: Theme.fontFamily; font.pixelSize: Theme.font(12)
                            }
                            Picker {
                                objectName: "wallpaperFit"
                                Layout.preferredWidth: Theme.control(116)
                                model: [I18n.t("填充"), I18n.t("适应")]
                                currentIndex: root.options.mode === "fit" ? 1 : 0
                                Accessible.name: I18n.t("显示方式")
                                onActivated: index => root.setOption("mode", index === 1 ? "fit" : "fill")
                            }
                        }
                        Adjustment {
                            objectName: "wallpaperOpacity"
                            Layout.fillWidth: true; enabled: root.hasImage
                            label: I18n.t("图片不透明度"); minimum: 0; maximum: root.service.maximumOpacity
                            value: root.strength; step: 0.5
                            onEdited: next => root.setOption("opacity", next)
                        }
                        ActionButton {
                            objectName: "openWallpaperPlacement"
                            Layout.fillWidth: true; enabled: root.hasImage
                            glyph: "sliders"; text: I18n.t("大小与位置")
                            onClicked: {
                                placementDialog.active = true
                                placementDialog.item.begin(root.options)
                            }
                        }
                    }
                }
            }

            RowLayout {
                id: footer
                Layout.fillWidth: true; spacing: 8
                ActionButton {
                    objectName: "resetChatWallpaper"
                    text: I18n.t("恢复默认"); quiet: true
                    enabled: !root.draft.busy && (root.previewSource !== "" || root.optionsDiffer(root.options, root.service.defaults))
                    onClicked: root.restoreDefaults()
                }
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "cancelChatWallpaper"; text: I18n.t("取消"); quiet: true; onClicked: root.close() }
                ActionButton {
                    objectName: "applyChatWallpaper"
                    text: I18n.t("应用"); primary: true; enabled: root.canApply
                    onClicked: {
                        if (root.service.apply(root.clearSavedImage, root.options))
                            root.close()
                    }
                }
            }
        }
    }
}
