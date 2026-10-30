"""Explicit optional ZIP import through actual Main.qml; fake account IO only.

Run scripts/package-codearts-provider.py first, or set CODEARTS_PROVIDER_ZIP.
All profiles, Downloads and CLI state are disposable; no model calls are made.
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                  QT_QUICK_CONTROLS_STYLE="Basic", UMEKO_LANGUAGE="en")

from PySide6.QtCore import QCoreApplication, QEvent, QMimeData, QObject, QPointF, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
import shiboken6

from app.controller import Controller
from app.webview import configure_engine
from main import create_application

AK, SK = "FAKE_F8_UI_ACCESS_KEY", "FAKE_F8_UI_SECRET_KEY"
CSV = f"Access Key Id,Secret Access Key\n{AK},{SK}\n"
MODEL = "huaweicloud/fixture-plugin-ui-model"


def wait(predicate, message, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QTest.qWait(20)
        if predicate():
            return
    raise AssertionError(message)


class Window:
    def __init__(self, profile, *, first=False):
        os.environ["UMEKO_DATA_DIR"] = str(profile)
        os.environ["PI_CODING_AGENT_DIR"] = str(profile.parent / (profile.name + "-agent"))
        self.warnings, self.notices = [], []
        if first:
            self.app, self.engine, self.backend = create_application()
            self.app.setQuitOnLastWindowClosed(False)
        else:
            self.backend = Controller(ROOT)
            self.engine = QQmlApplicationEngine()
            configure_engine(self.engine)
            self.engine.rootContext().setContextProperty("backend", self.backend)
            self.engine.load(QUrl.fromLocalFile(str(ROOT / "app/qml/Main.qml")))
        self.engine.warnings.connect(lambda errors: self.warnings.extend(error.toString() for error in errors))
        self.backend.toast.connect(self.notices.append)
        self.manager = self.backend.providerPlugins
        assert self.engine.rootObjects(), "Actual Main.qml did not load"
        self.window = self.engine.rootObjects()[0]
        self.window.resize(1180, 900)
        QTest.qWait(200)
        self.click("settingsButton")
        assert self.window.property("page") == "settings"

    def find(self, name):
        stack = [self.window.contentItem()]
        while stack:
            current = stack.pop()
            if current.objectName() == name:
                return current
            stack.extend(current.childItems())
        return self.window.findChild(QQuickItem, name)

    def click(self, name):
        target = self.find(name)
        assert target is not None and target.isVisible() and target.isEnabled(), name
        scroll = self.find("settingsScroll")
        flick = scroll.property("contentItem") if scroll else None
        ancestor = target.parentItem()
        while ancestor is not None and ancestor != flick:
            ancestor = ancestor.parentItem()
        if ancestor is not None:
            point = target.mapToItem(flick, target.boundingRect().center())
            flick.setProperty("contentY", max(0, min(flick.property("contentY") + point.y() - flick.height() / 2,
                                                   max(0, flick.property("contentHeight") - flick.height()))))
            QTest.qWait(50)
        point = target.mapToScene(target.boundingRect().center()).toPoint()
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(100)

    def import_zip(self, archive):
        self.click("importCustomProviderButton")
        popup = self.window.findChild(QObject, "customProviderImportDialog")
        assert popup.property("opened")
        assert self.manager.availableBundles == [], "Optional package appeared in default bundle UI"
        area = self.find("providerPackageDropArea")
        assert area and area.isVisible()
        point = area.mapToScene(area.boundingRect().center()).toPoint()
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(archive))])
        app = QCoreApplication.instance()
        app.sendEvent(self.window, QDragEnterEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
        app.sendEvent(self.window, QDragMoveEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
        event = QDropEvent(QPointF(point), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        app.sendEvent(self.window, event)
        assert event.isAccepted(), "ZIP drop was rejected"
        wait(lambda: not popup.property("opened"), "Explicit import did not close popup")
        assert len(self.manager.packages) == 1, self.notices
        assert not self.manager.clients, "Import activated plugin Python before login"
        return self.account()

    def account(self):
        ids = {record["id"] for record in self.backend.store.data["providers"]
               if record.get("api") == "plugin" and record.get("pluginId") == "codearts"}
        rows = [row for row in self.manager.rows if row["id"] in ids]
        assert len(rows) == 1, rows
        return rows[0]

    def capture(self, destination):
        QTest.qWait(150)
        assert self.window.grabWindow().save(str(destination))

    def close(self):
        assert not self.warnings, self.warnings
        self.backend.close()
        self.window.close()
        shiboken6.delete(self.engine)
        self.backend.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


class FakeLegacy:
    def __init__(self, profile, credentials=False):
        self.profile = str(profile.resolve())
        self.raw = json.dumps({"ak": AK, "sk": SK}) if credentials else None
        self.reads, self.deletes = [], []

    def get_password(self, service, username):
        assert username == self.profile, "Migration searched another profile"
        self.reads.append((service, username))
        return self.raw

    def delete_password(self, service, username):
        assert username == self.profile
        self.deletes.append((service, username))
        self.raw = None


def main():
    archive = Path(os.environ.get("CODEARTS_PROVIDER_ZIP", ROOT / "build/optional-providers/umeko-codearts-provider-0.1.0.zip"))
    assert archive.is_file(), "Build the optional CodeArts ZIP first"
    out = ROOT.parent / "experiments/umeko-codearts/screenshots"
    out.mkdir(parents=True, exist_ok=True)
    base = Path("C:/UmekoTests") if os.name == "nt" else Path(tempfile.gettempdir()) / "UmekoTests"
    base.mkdir(parents=True, exist_ok=True)
    active, report, opened, calls, guards = None, {}, [], [], []
    with tempfile.TemporaryDirectory(prefix="codearts-f8-ui-", dir=base) as temporary:
        work = Path(temporary)
        private_temp = work / "temp"
        private_temp.mkdir()
        profile, downloads = work / "profile", work / "Downloads"
        downloads.mkdir()
        legacy = FakeLegacy(profile)
        original_import = importlib.import_module
        patched_classes = set()

        def import_guard(name, package=None):
            module = original_import(name, package)
            account_class = getattr(module, "CodeartsAccount", None)
            if account_class is not None and account_class not in patched_classes:
                patched_classes.add(account_class)

                def ensure_cli(account):
                    account._cli = work / "fake-codearts.exe"
                    return True

                def fake_run(account, command, *, env, cwd, timeout):
                    assert (env["CODEARTS_CLI_AK"], env["CODEARTS_CLI_SK"]) == (AK, SK)
                    assert command[-1] == "models", command
                    assert Path(cwd).resolve().is_relative_to(work.resolve()), cwd
                    calls.append("models")
                    return subprocess.CompletedProcess(command, 0, (MODEL + "\n").encode(), b"")

                for attribute, replacement in (("_ensure_cli", ensure_cli), ("_run", fake_run),
                                               ("_legacy", lambda account: legacy)):
                    guard = patch.object(account_class, attribute, replacement)
                    guard.start()
                    guards.append(guard)
            return module

        try:
            with patch.dict(os.environ, {"TEMP": str(private_temp), "TMP": str(private_temp)}), \
                 patch.object(QDesktopServices, "openUrl", side_effect=lambda url: opened.append(url.toString()) or True), \
                 patch.object(Controller, "loadNativeIndex", new=lambda self: None), \
                 patch("app.project_info.git_output", return_value=""), \
                 patch("subprocess.Popen", side_effect=AssertionError("Smoke attempted a real external process")), \
                 patch("urllib.request.urlopen", side_effect=AssertionError("Smoke attempted a real network request")), \
                 patch("app.provider_plugins.QStandardPaths.writableLocation", return_value=str(downloads)):
                active = Window(profile, first=True)
                assert active.backend.config["providers"] == []
                assert active.manager.packages == [] and active.manager.rows == []
                assert active.manager.availableBundles == [] and not active.manager.clients
                report["defaultStartup"] = {"passed": True, "packages": 0, "accounts": 0, "activeClients": 0}
                row = active.import_zip(archive)
                account_id, version = row["id"], row["version"]
                assert row["name"] == "CodeArts"
                active.capture(out / "codearts-optional-imported.png")
                report["explicitZipImport"] = {"passed": True, "plusPopup": True, "zipDrop": True, "version": version}
                with patch("app.provider_plugins.importlib.import_module", side_effect=import_guard):
                    active.click("loginPlugin_" + account_id)
                    wait(lambda: account_id not in active.manager.busy, "Fake login did not finish")
                assert patched_classes, "Product account factory was not intercepted"
                assert not active.account()["models"]
                assert active.find("pluginCardAction_" + account_id + "_open_console").isVisible()
                active.click("pluginCardAction_" + account_id + "_open_console")
                wait(lambda: account_id not in active.manager.busy, "Fake console action did not finish")
                assert len(opened) == 1 and opened[0].startswith("https://console.huaweicloud.com/")
                csv_file = downloads / "new-fake-credentials.csv"
                csv_file.write_text(CSV, encoding="utf-8")
                wait(lambda: bool(active.account()["models"]), "Card CSV import did not publish fake model catalog")
                connected = active.account()
                assert connected["models"][0]["upstream"] == MODEL
                assert not csv_file.exists(), "Successful card import retained credential CSV"
                assert active.manager._secrets(account_id).get("account") == {"ak": AK, "sk": SK}
                public = json.dumps([connected, active.backend.config], ensure_ascii=False)
                assert AK not in public and SK not in public
                assert active.find("managePluginModels_" + account_id).isVisible()
                active.capture(out / "codearts-optional-connected.png")
                report["cardCsvLogin"] = {"passed": True, "fakeBrowserOpens": 1, "csvDeleted": True,
                                          "protectedCredentials": True, "connectedModel": MODEL}
                active.click("uninstallPlugin_codearts_" + version)
                assert active.window.findChild(QObject, "uninstallProviderDialog").property("opened")
                active.click("confirmUninstallProviderButton")
                assert active.manager.packages == [] and active.manager.rows == []
                active.close()
                active = Window(profile)
                assert active.manager.packages == [] and active.manager.rows == []
                active.import_zip(archive)
                report["uninstallReimport"] = {"passed": True, "absentAfterRestart": True, "explicitReimport": True}
                active.close()
                migration_profile = work / "migration-profile"
                legacy = FakeLegacy(migration_profile, credentials=True)
                active = Window(migration_profile)
                old_row = active.import_zip(archive)
                with patch("app.provider_plugins.importlib.import_module", side_effect=import_guard):
                    active.click("loginPlugin_" + old_row["id"])
                    wait(lambda: old_row["id"] not in active.manager.busy, "Fake legacy migration did not finish")
                assert active.account()["models"][0]["upstream"] == MODEL
                assert legacy.raw is None and legacy.reads == legacy.deletes and len(legacy.reads) == 1
                report["legacyVaultMigration"] = {"passed": True, "actualProductFactory": True, "fakeOldVaultDeleted": True}
                active.close()
                active = None
                report.update(ok=True, fakeOnly=True, actualCreateApplication=True, actualMainQml=True,
                              controlsStyle="Basic", fakeCliCatalogCalls=len(calls), externalProcesses=0,
                              modelCalls=0, qmlWarnings=0,
                              temporaryBytesBeforeCleanup=sum(p.stat().st_size for p in work.rglob("*") if p.is_file()))
        finally:
            if active is not None:
                active.close()
            for guard in reversed(guards):
                guard.stop()
    report.update(profilesCleaned=not work.exists(), temporaryBytesAfterCleanup=0)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
