"""Real offscreen Umeko plugin lifecycle with disposable resources and fake auth.

Run after scripts/build_provider_resources.py. Never uses a real profile, browser,
CodeArts CLI, model request or legacy credential vault.
"""
from __future__ import annotations

import copy
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                  QT_QUICK_CONTROLS_STYLE="Basic", UMEKO_LANGUAGE="en")

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import shiboken6

from app.controller import Controller
from app.bundled_providers import BundledProviders
from app.syntax_highlight import register_text_types
from app.webview import configure, configure_engine


AK, SK = "FAKE_F6_UI_ACCESS_KEY", "FAKE_F6_UI_SECRET_KEY"
MODEL = "huaweicloud/fixture-plugin-ui-model"


def wait(predicate, message, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QTest.qWait(20)
        if predicate():
            return
    raise AssertionError(message)


class Window:
    def __init__(self, application_root, profile):
        os.environ["UMEKO_DATA_DIR"] = str(profile)
        os.environ["PI_CODING_AGENT_DIR"] = str(profile.parent / (profile.name + "-agent"))
        def private_resources(manager):
            bundled = BundledProviders(manager)
            bundled.index = application_root / "provider-resources/bundled-providers.json"
            return bundled

        # Keep the real application assets/runtime while selecting only private
        # release resources for this test's application-version transitions.
        with patch("app.provider_plugins.BundledProviders", side_effect=private_resources):
            self.backend = Controller(ROOT)
        self.manager = self.backend.providerPlugins
        self.notices, self.warnings = [], []
        self.backend.toast.connect(self.notices.append)
        self.engine = QQmlApplicationEngine()
        configure_engine(self.engine)
        self.engine.warnings.connect(lambda errors: self.warnings.extend(error.toString() for error in errors))
        self.engine.rootContext().setContextProperty("backend", self.backend)
        self.engine.load(QUrl.fromLocalFile(str(ROOT / "app/qml/Main.qml")))
        assert self.engine.rootObjects(), "Actual Main.qml did not load"
        self.window = self.engine.rootObjects()[0]
        self.window.resize(1180, 900)
        QTest.qWait(150)
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
        QTest.qWait(80)

    def account(self):
        ids = {record["id"] for record in self.backend.store.data["providers"]
               if record.get("api") == "plugin" and record.get("pluginId") == "codearts"}
        rows = [row for row in self.manager.rows if row["id"] in ids]
        assert len(rows) == 1, rows
        return rows[0]

    def close(self):
        self.backend.close()
        self.window.close()
        shiboken6.delete(self.engine)
        self.backend.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def resources(destination, source_index, version=None):
    """Rewrite only a private ZIP manifest to represent another app release."""
    folder = destination / "provider-resources"
    folder.mkdir(parents=True, exist_ok=True)
    source_document = json.loads(source_index.read_text(encoding="utf-8-sig"))
    original = next(row for row in source_document["providers"] if row["id"] == "codearts")
    row = copy.deepcopy(original)
    archive = source_index.parent / row["archive"]
    if version is None:
        shutil.copyfile(archive, folder / row["archive"])
    else:
        row.update(version=version, archive=f"codearts-{version}.zip")
        with zipfile.ZipFile(archive) as source, zipfile.ZipFile(folder / row["archive"], "w", zipfile.ZIP_DEFLATED) as output:
            for entry in source.infolist():
                value = source.read(entry.filename)
                if entry.filename == "manifest.json":
                    manifest = json.loads(value)
                    manifest["version"] = version
                    value = json.dumps(manifest).encode("utf-8")
                output.writestr(entry, value)
    (folder / "bundled-providers.json").write_text(json.dumps({"schemaVersion": 1, "providers": [row]}), encoding="utf-8")
    return row


class FakeLegacy:
    def __init__(self, profile):
        self.profile = str(profile.resolve())
        self.raw = json.dumps({"ak": AK, "sk": SK})
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
    index = next((folder / "bundled-providers.json" for folder in (ROOT / "provider-resources", ROOT / "build/provider-resources")
                  if (folder / "bundled-providers.json").is_file()), None)
    assert index, "Build bundled provider resources before running this smoke test"
    base = Path("C:/UmekoTests") if os.name == "nt" else Path(tempfile.gettempdir()) / "UmekoTests"
    base.mkdir(parents=True, exist_ok=True)
    active = None
    report = {}
    with tempfile.TemporaryDirectory(prefix="codearts-f6-ui-", dir=base) as temporary:
        work = Path(temporary)
        os.environ["UMEKO_DATA_DIR"] = str(work / "profile")
        os.environ["PI_CODING_AGENT_DIR"] = str(work / "agent")
        configure(ROOT)
        app = QApplication.instance() or QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        if not QFontDatabase.families() and os.name == "nt":
            for name in ("msyh.ttc", "segoeui.ttf", "consola.ttf"):
                QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / name))
        app.setFont(QFont("Microsoft YaHei UI", 10))
        register_text_types()
        root = work / "application"
        profile = work / "profile"
        shipped = resources(root, index)
        major, minor, patch_version = shipped["version"].split(".")
        newer = f"{major}.{minor}.{int(patch_version) + 1}"
        opened = []
        try:
            # These guards cover every real product operation in all six cases.
            with patch.object(QDesktopServices, "openUrl", side_effect=lambda url: opened.append(url.toString()) or True), \
                 patch("app.project_info.git_output", return_value=""), \
                 patch("subprocess.Popen", side_effect=AssertionError("Smoke attempted a real external process")), \
                 patch("urllib.request.urlopen", side_effect=AssertionError("Smoke attempted a real network request")):
                if "--startup-only" in sys.argv:
                    active = Window(root, profile)
                    assert not active.warnings, active.warnings
                    active.close()
                    active = None
                    print(json.dumps({"ok": True, "startupOnly": True, "qmlWarnings": 0,
                                      "controlsStyle": "Basic", "fakeOnly": True}))
                    return
                if "--resume-e" not in sys.argv and "--resume-f" not in sys.argv:
                    active = Window(root, profile)
                    if "--resume-d" not in sys.argv:
                        row = active.account()
                        assert row["name"] == "CodeArts", row
                        assert active.find("uninstallPlugin_codearts_" + shipped["version"]).isVisible()
                        assert active.find("loginPlugin_" + row["id"]).isVisible()
                        assert not active.manager.clients, "Startup activated a bundled plugin"
                        report["a"] = {"passed": True, "card": row["name"], "version": row["version"], "uninstallButton": True}
                        active.click("uninstallPlugin_codearts_" + shipped["version"])
                        assert active.window.findChild(QObject, "uninstallProviderDialog").property("opened")
                        active.click("confirmUninstallProviderButton")
                        active.close()
                        active = Window(root, profile)
                        assert not active.manager.rows and not active.manager.packages
                        report["b"] = {"passed": True, "absentAfterUninstallAndRestart": True}
                    else:
                        # Set up only the failed stage; keep prior a-c evidence.
                        active.manager.uninstall("codearts", shipped["version"])
                    active.close()
                    active = None
                    resources(root, index, newer)
                    active = Window(root, profile)
                    if "--resume-d" not in sys.argv:
                        assert not active.manager.rows and not active.manager.packages
                        report["c"] = {"passed": True, "newApplicationBundleVersion": newer, "stillUninstalled": True}
                    active.click("importCustomProviderButton")
                    assert active.window.findChild(QObject, "customProviderImportDialog").property("opened")
                    assert active.manager.availableBundles == [{"id": "codearts", "version": newer, "name": shipped["name"]}]
                    active.click("installBundledProvider_codearts")
                    wait(lambda: not active.window.findChild(QObject, "customProviderImportDialog").property("opened"),
                         "The install popup did not finish its closing transition")
                    assert active.account()["version"] == newer
                    report["d"] = {"passed": True, "plusDialogListedBundle": True, "oneClickInstalledVersion": newer}
                    active.close()
                    active = None
                old_profile = work / "older-profile"
                if "--resume-f" not in sys.argv:
                    resources(root, index, "0.0.1")
                    active = Window(root, old_profile)
                    old_id = active.account()["id"]
                    active.close()
                    active = None
                    resources(root, index)
                    active = Window(root, old_profile)
                    upgraded = active.account()
                    assert upgraded["id"] == old_id and upgraded["version"] == shipped["version"]
                    report["e"] = {"passed": True, "from": "0.0.1", "to": upgraded["version"], "sameAccountId": True}
                    active.close()
                    active = None
                migration_profile = work / "migration-profile"
                downloads = work / "Downloads"
                downloads.mkdir()
                active = Window(root, migration_profile)
                legacy = FakeLegacy(migration_profile)
                manager = active.manager
                account_id = active.account()["id"]
                original_import = importlib.import_module
                patched = []
                calls = []

                def import_guard(name, package=None):
                    module = original_import(name, package)
                    account_class = getattr(module, "CodeartsAccount", None)
                    if account_class is not None and not patched:
                        def ensure_cli(account):
                            account._cli = work / "fake-codearts.cmd"
                            return True

                        def fake_run(account, command, *, env, cwd, timeout):
                            assert env["CODEARTS_CLI_AK"] == AK and env["CODEARTS_CLI_SK"] == SK
                            assert command[-1] == "models", command
                            calls.append("models")
                            return subprocess.CompletedProcess(command, 0, (MODEL + "\n").encode(), b"")

                        for attribute, replacement in (("_ensure_cli", ensure_cli), ("_run", fake_run), ("_legacy", lambda account: legacy)):
                            guard = patch.object(account_class, attribute, replacement)
                            guard.start()
                            patched.append(guard)
                    return module

                try:
                    with patch("app.provider_plugins.importlib.import_module", side_effect=import_guard), \
                         patch("app.provider_plugins.QStandardPaths.writableLocation", return_value=str(downloads)):
                        active.click("loginPlugin_" + account_id)
                        wait(lambda: account_id not in manager.busy, "Fake legacy migration did not finish")
                        QTest.qWait(80)
                        connected = active.account()
                        assert patched, "The product factory's account was not intercepted before activation"
                        assert connected["models"] and connected["models"][0]["upstream"] == MODEL, (connected, active.notices)
                        assert manager._secrets(account_id).get("account") == {"ak": AK, "sk": SK}
                        assert legacy.raw is None and len(legacy.reads) == 1 and legacy.reads == legacy.deletes
                        assert active.find("managePluginModels_" + account_id).isVisible()
                        assert connected["status"] and connected["cardStatus"] == "", connected
                        public = json.dumps([connected, active.backend.config], ensure_ascii=False)
                        assert AK not in public and SK not in public
                        report["f"] = {"passed": True, "actualProductFactory": True, "fakeLegacyDeleted": True,
                                       "protectedPluginCredentials": True, "connectedModel": MODEL,
                                       "cardStatus": connected["cardStatus"], "fakeCliCalls": len(calls)}
                        assert not active.warnings, active.warnings
                        active.close()
                        active = None
                finally:
                    for guard in reversed(patched):
                        guard.stop()
                assert not opened, "Lifecycle unexpectedly opened a browser"
        finally:
            if active is not None:
                active.close()
        report.update(ok=True, fakeOnly=True, actualMainQml=True, profilesCleaned=True, externalProcesses=0, browserOpens=0)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
