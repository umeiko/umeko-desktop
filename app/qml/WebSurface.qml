import QtQuick
import QtWebView

WebView {
    id: view
    objectName: "embeddedWebView"
    property string errorMessage: ""
    settings.javaScriptEnabled: true
    settings.localStorageEnabled: true
    settings.allowFileAccess: false
    settings.localContentCanAccessFileUrls: false
    onLoadingChanged: request => {
        if (request.status === WebView.LoadFailedStatus) errorMessage = request.errorString
        else if (request.status === WebView.LoadStartedStatus) errorMessage = ""
    }
}
