import QtQuick

Text { font.family: Theme.fontFamily;
    id: root
    objectName: "networkRetryStatus"
    required property var retryState
    property double clock: Date.now()
    readonly property bool activeRetry: retryState.active === true
    readonly property int seconds: Math.ceil((retryState.delayMs || 0) / 1000)
    readonly property int elapsed: Math.min(seconds, Math.max(0, Math.floor((clock - (retryState.startedAt || clock)) / 1000)))
    visible: activeRetry
    color: Theme.muted
    font.pixelSize: Theme.font(13, visible)
    elide: Text.ElideRight
    text: {
        const attempt = retryState.attempt || 1
        const maxAttempts = retryState.maxAttempts || 5
        if (activeRetry && retryState.continuation)
            return I18n.t("等待自动接续") + " " + attempt + "/" + maxAttempts + " (" + elapsed + "s/" + seconds + "s)"
        const ordinal = ["一", "二", "三", "四", "五"][attempt - 1] || attempt
        if (I18n.language === "en")
            return retryState.waiting ? "Reconnecting... " + attempt + "/" + maxAttempts + " (" + elapsed + "s/" + seconds + "s)" : "Reconnecting... " + attempt + "/" + maxAttempts
        return retryState.waiting ? "网络流已中断，等待重新连接 " + attempt + "/" + maxAttempts + "（第" + ordinal + "次）" + elapsed + "s/" + seconds + "s" : "正在重新连接 " + attempt + "/" + maxAttempts + "…"
    }
    onRetryStateChanged: clock = Date.now()
    Timer { interval: 250; repeat: true; running: root.visible && root.retryState.waiting === true; onTriggered: root.clock = Date.now() }
}
