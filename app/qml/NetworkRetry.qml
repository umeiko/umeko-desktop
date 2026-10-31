import QtQuick

Text { font.family: Theme.fontFamily;
    id: root
    objectName: "networkRetryStatus"
    property var retryState: backend.networkRetry
    property double clock: Date.now()
    readonly property int seconds: Math.ceil((retryState.delayMs || 0) / 1000)
    readonly property int elapsed: Math.min(seconds, Math.max(0, Math.floor((clock - (retryState.startedAt || clock)) / 1000)))
    visible: retryState.active === true && backend.running
    color: Theme.muted
    font.pixelSize: Theme.font(12)
    elide: Text.ElideRight
    text: {
        const attempt = retryState.attempt || 1
        const ordinal = ["一", "二", "三", "四", "五"][attempt - 1] || attempt
        if (I18n.language === "en")
            return retryState.waiting ? "Network stream interrupted, retrying (" + attempt + "/5) " + elapsed + "s/" + seconds + "s" : "Reconnecting (" + attempt + "/5)…"
        return retryState.waiting ? "网络流已中断，等待重试中（第" + ordinal + "次）" + elapsed + "s/" + seconds + "s" : "正在重新连接（第" + ordinal + "次）…"
    }
    onRetryStateChanged: clock = Date.now()
    Timer { interval: 250; repeat: true; running: root.visible && root.retryState.waiting === true; onTriggered: root.clock = Date.now() }
}
