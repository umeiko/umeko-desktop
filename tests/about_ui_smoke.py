"""Actual About QML, explicit asynchronous checks, and public build details."""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('UMEKO_LANGUAGE','zh')
os.environ["UMEKO_DATA_DIR"] = tempfile.mkdtemp(prefix="umeko-about-ui-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from app.project_info import VERSION, PROJECT_URL, AUTHOR_URL, RELEASES_URL
from app.storage import Store
from main import create_application

store = Store()
store.data["agent"]["agentDir"] = str(store.directory / "agent")
store.data["employeeId"] = "private-fixture-do-not-copy"
store.save()
app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))


def find(name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name: return item
        stack.extend(item.childItems())
    raise AssertionError(name)


def click(name):
    QTest.qWait(60)
    item = find(name)
    assert item.isVisible() and item.isEnabled(), name
    flick = find("settingsScroll").property("contentItem")
    ancestor = item.parentItem()
    while ancestor is not None and ancestor != flick: ancestor = ancestor.parentItem()
    if ancestor is not None:
        y = item.mapToItem(flick, QPointF(0, 0)).y()
        if y < 0 or y + item.height() > flick.height():
            flick.setProperty("contentY", max(0, min(flick.property("contentY") + y - flick.height()/2, flick.property("contentHeight") - flick.height())))
    QTest.qWait(30)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())
    QTest.qWait(30)


def wait_for(predicate):
    for _ in range(300):
        QTest.qWait(10); time.sleep(0.01)
        if predicate(): return
    raise AssertionError("About UI timed out")


def capture(name):
    out = ROOT / "artifacts/screenshots"
    out.mkdir(parents=True, exist_ok=True)
    QTest.qWait(100)
    assert window.grabWindow().save(str(out / (name + ".png")))


try:
    with patch("app.app_about.fetch_latest_release") as fetch:
        window.setProperty("page", "settings")
        click("settingsTab_6")
        assert find("aboutPage").isVisible()
        assert find("aboutVersion").property("text") == "v" + VERSION
        assert find("aboutRepository").property("text") == PROJECT_URL
        if sys.platform == "win32": assert "Windows" in find("aboutPlatform").property("text")
        QTest.qWait(100)
        fetch.assert_not_called()
    click("copyAboutInfoButton")
    assert PROJECT_URL in app.clipboard().text() and VERSION in app.clipboard().text()
    assert "private-fixture-do-not-copy" not in app.clipboard().text()
    with patch("app.app_about.QDesktopServices.openUrl", return_value=True) as opened:
        click("aboutProjectButton"); assert opened.call_args.args[0].toString() == PROJECT_URL
        click("aboutAuthorButton"); assert opened.call_args.args[0].toString() == AUTHOR_URL
        click("openAppReleasesButton"); assert opened.call_args.args[0].toString() == RELEASES_URL
    release_url = PROJECT_URL + "/releases/tag/v0.3.0"
    gate, started = threading.Event(), threading.Event()
    def new_release():
        started.set()
        assert gate.wait(5)
        return {"state":"available", "message":"发现新版本 v0.3.0", "version":"v0.3.0", "url":release_url, "notes":"Fixture release notes\n<b>Plain text only</b>"}
    # A release check has its own busy state, even during an active chat task.
    backend._view.busy, backend._view.phase = True, "running"
    backend.chatChanged.emit()
    with patch("app.app_about.fetch_latest_release", side_effect=new_release) as fetch:
        click("checkAppUpdatesButton")
        wait_for(started.is_set)
        assert backend.appAbout.busy and not find("checkAppUpdatesButton").isEnabled()
        backend.appAbout.checkUpdates()
        assert fetch.call_count == 1
        assert backend.busy and backend.running
        capture("66-about-checking")
        gate.set()
        wait_for(lambda: not backend.appAbout.busy)
        assert backend.busy and backend.running
    backend._view.busy, backend._view.phase = False, "idle"
    backend.chatChanged.emit()
    assert "v0.3.0" in find("appUpdateStatus").property("text")
    assert find("openAppReleasesButton").property("text") == "前往下载"
    assert "<b>" in find("appReleaseNotes").property("text")
    with patch("app.app_about.QDesktopServices.openUrl", return_value=True) as opened:
        click("openAppReleasesButton")
        assert opened.call_args.args[0].toString() == release_url
    capture("67-about-update-available")
    for result in ({"state":"unpublished", "message":"项目暂未发布正式版本。"}, {"state":"error", "message":"检查失败，请稍后重试。"}):
        with patch("app.app_about.fetch_latest_release", return_value=result):
            click("checkAppUpdatesButton")
            wait_for(lambda: not backend.appAbout.busy)
        assert backend.appAbout.release["state"] == result["state"]
        assert find("appUpdateStatus").property("text") == result["message"]
        assert find("checkAppUpdatesButton").isEnabled()
        assert not find("appReleaseNotes").isVisible()
    for theme in ("yanami", "dark", "light"):
        backend.setTheme(theme); window.resize(1060,700); QTest.qWait(80)
        assert find("aboutRepository").width() > 250
        last_tab = find("settingsTab_6")
        assert last_tab.mapToScene(last_tab.boundingRect().bottomRight()).x() < window.width()
    find("settingsScroll").property("contentItem").setProperty("contentY", 0)
    capture("68-about-compact")
    assert not warnings, "\n".join(warnings)
    print("ABOUT_UI_OK: project/build/version, public-only copy/links, explicit background update checks during chat, busy guard/retry, release notes, themes/narrow layout")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
