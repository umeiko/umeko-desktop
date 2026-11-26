import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

Popup {
    id: root
    objectName: "quickOcrDialog"
    required property var service
    property bool showSetup: false
    property bool copied: false
    function tr(zh, en) { return backend.language === "en" ? en : zh }
    readonly property bool working: service && (service.state === "checking" || service.state === "running")
    readonly property bool needsSetup: service && !service.ready && !working
    function chooseFile(url) {
        copied = false
        return service.selectImage(url)
    }
    function showDialog() {
        showSetup = false
        copied = false
        if (service.begin()) open()
    }
    function errorText() {
        switch (service.error) {
        case "engine": return tr("组件缺失或版本不匹配，请按下方说明安装。", "The component is missing or has the wrong version. See Setup below.")
        case "weights": return tr("模型校验失败，请重新安装本地组件。", "Model integrity check failed. Reinstall the local component.")
        case "offline": return tr("已阻止联网请求。请重新安装完整组件。", "A network request was blocked. Reinstall the complete component.")
        case "format": return tr("只接受本地 PNG、JPEG、BMP、WebP 或单页 TIFF。", "Choose a local PNG, JPEG, BMP, WebP or single-page TIFF.")
        case "image_size": return tr("图像过大（上限 40 MiB、2,000 万像素、单边 10,000 像素）。", "Image exceeds 40 MiB, 20 megapixels or 10,000 pixels on one edge.")
        case "decode": return tr("无法打开这张图片。请确认文件未损坏。", "This image could not be opened. Check that it is not damaged.")
        case "timeout": return tr("本地处理超时。请裁剪图片后重试。", "Local processing timed out. Try cropping the image.")
        default: return tr("本次识别失败，未尝试上传文件。", "Recognition failed. No file upload was attempted.")
        }
    }
    anchors.centerIn: parent
    width: Math.min(610, parent.width - 24)
    height: Math.min(parent.height - 24, 580)
    padding: 21
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape
    background: Rectangle { radius: 15; color: Theme.surface; border.color: Theme.line }
    Overlay.modal: Rectangle { color: Qt.alpha(Theme.ink, 0.30) }

    onClosed: if (service) service.end()
    Connections {
        target: backend
        function onViewChanged() { if (root.opened) root.close() }
    }

    FileDialog {
        id: imageDialog
        title: root.tr("选择用于本地识别的图片", "Choose an image for local recognition")
        fileMode: FileDialog.OpenFile
        nameFilters: ["Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)"]
        onAccepted: root.chooseFile(selectedFile)
    }

    contentItem: ColumnLayout {
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Glyph { name: "eye"; color: Theme.accent; Layout.preferredWidth: Theme.icon(22); Layout.preferredHeight: Theme.icon(22) }
            Text {
                Layout.fillWidth: true; text: root.tr("快速 OCR", "Quick OCR")
                font.family: Theme.fontFamily; font.pixelSize: Theme.font(21); font.weight: Font.DemiBold; color: Theme.ink
            }
            ActionButton { objectName: "quickOcrClose"; glyph: "x"; quiet: true; hint: root.tr("关闭", "Close"); onClicked: root.close() }
        }
        Text {
            Layout.fillWidth: true; wrapMode: Text.Wrap
            text: root.tr("本地 CPU 识别简繁中文、英文和数字。不上传图片，不调用聊天模型。", "Extract Chinese, English and numbers on this device. Nothing is sent to a chat model or remote service.")
            font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); color: Theme.muted
        }
        RowLayout {
            Layout.fillWidth: true
            ActionButton {
                objectName: "quickOcrChoose"; text: root.tr("选择图片", "Choose image"); glyph: "folder"
                enabled: !root.working; onClicked: imageDialog.open()
            }
            Text {
                objectName: "quickOcrFileName"; Layout.fillWidth: true
                text: service.sourceName || root.tr("PNG / JPEG / BMP / WebP / TIFF", "PNG / JPEG / BMP / WebP / TIFF")
                textFormat: Text.PlainText; elide: Text.ElideMiddle
                font.family: Theme.fontFamily; font.pixelSize: Theme.font(12); color: Theme.muted
            }
            ActionButton {
                objectName: "quickOcrRotate"; text: service.rotation ? service.rotation + "°" : root.tr("旋转 90°", "Rotate 90°")
                hint: root.tr("顺时针旋转原图后重新识别（不修改原文件）", "Rotate clockwise for recognition without changing the original")
                enabled: !!service.sourceName && !root.working; onClicked: { root.copied = false; service.rotate() }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text {
                objectName: "quickOcrStatus"; Layout.fillWidth: true; wrapMode: Text.Wrap
                text: service.state === "running" ? root.tr("本地识别中…", "Recognizing locally…")
                    : service.state === "checking" ? root.tr("正在检查本地组件…", "Checking local component…")
                    : root.needsSetup && !service.error ? root.tr("未安装本地 OCR 组件。", "The local OCR component is not installed.")
                    : service.error ? root.errorText()
                    : service.state === "done" && !service.result ? root.tr("未识别到文字。可旋转或换图后重试。", "No text was found. Try rotation or a different image.")
                    : service.truncated ? root.tr("已到 60,000 字符上限，结果已截断。", "Result truncated at 60,000 characters.")
                    : service.state === "done" ? root.tr("识别完成", "Recognition complete")
                    : service.ready ? root.tr("PP-OCRv6 small · 本地组件就绪", "PP-OCRv6 small · Ready") : ""
                font.family: Theme.fontFamily; font.pixelSize: Theme.font(12); color: service.error || root.needsSetup ? Theme.ink : Theme.muted
            }
            ActionButton {
                objectName: "quickOcrSetup"; text: root.tr("安装说明", "Setup")
                quiet: !root.needsSetup; onClicked: root.showSetup = !root.showSetup
            }
        }
        Rectangle {
            visible: root.showSetup || root.needsSetup
            Layout.fillWidth: true; implicitHeight: setup.implicitHeight + 14; radius: 8; color: Theme.bg; border.color: Theme.line
            ColumnLayout {
                id: setup; x: 9; y: 7; width: parent.width - 18; spacing: 5
                Text {
                    Layout.fillWidth: true; wrapMode: Text.Wrap
                    text: root.tr('用 Python 3.12 运行源码附带的 scripts/install_quick_ocr.py，传入 --profile-dir 和下面的目录。安装后点「重新检查」。',
                                  'Use Python 3.12 to run scripts/install_quick_ocr.py from the source package, passing --profile-dir and the folder below. Then Check again.')
                    font.family: Theme.fontFamily; font.pixelSize: Theme.font(12); color: Theme.ink
                }
                Text { Layout.fillWidth: true; text: service.profilePath; textFormat: Text.PlainText; elide: Text.ElideMiddle; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11); color: Theme.muted }
                RowLayout {
                    ActionButton { text: root.tr("复制目录", "Copy folder"); quiet: true; onClicked: service.copyProfilePath() }
                    ActionButton { objectName: "quickOcrRefresh"; text: root.tr("重新检查", "Check again"); enabled: !root.working; quiet: true; onClicked: service.refresh() }
                }
            }
        }
        Rectangle {
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 48
            color: Theme.bg; radius: 9; border.color: Theme.line
            ScrollView {
                anchors.fill: parent; anchors.margins: 2; clip: true
                TextArea {
                    objectName: "quickOcrResult"
                    text: service.result; textFormat: TextEdit.PlainText; readOnly: true; selectByMouse: true
                    wrapMode: TextEdit.Wrap
                    placeholderText: root.tr("识别结果会显示在这里。", "Recognized text appears here.")
                    padding: 12; color: Theme.ink; placeholderTextColor: Theme.muted
                    font.family: Theme.fontFamily; font.pixelSize: Theme.font(14)
                    background: Item {}
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true; wrapMode: Text.Wrap
                text: root.tr("只提取图片中的文字。本版暂不支持 PDF 或还原版式。", "Image text only. This version does not support PDFs or layout reconstruction.")
                font.family: Theme.fontFamily; font.pixelSize: Theme.font(11); color: Theme.muted
            }
            ActionButton {
                objectName: "quickOcrCopy"; text: root.copied ? root.tr("已复制", "Copied") : root.tr("复制文字", "Copy text")
                enabled: !!service.result; onClicked: { service.copyResult(); root.copied = true }
            }
            ActionButton {
                objectName: "quickOcrRun"; text: service.state === "running" ? root.tr("取消", "Cancel") : root.tr("开始识别", "Recognize")
                primary: true
                enabled: service.state === "running" || (service.ready && !!service.sourceName && !root.working)
                onClicked: {
                    root.copied = false
                    if (service.state === "running") service.cancel()
                    else service.recognize()
                }
            }
        }
    }
}
