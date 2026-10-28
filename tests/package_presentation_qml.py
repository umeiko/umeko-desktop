"""Exercise real panel/approval QML using metadata only; never start a runtime.

Optional --record/--screenshots replays a saved install result for local visual
review. The normal CI fixture is generic and requires no service or packages.
"""
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", QT_QUICK_CONTROLS_STYLE="Basic")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QObject, Signal, Property, Slot, QUrl, QMetaObject
from PySide6.QtGui import QGuiApplication, QFont, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from app.pi_management import PiManagement

parser = argparse.ArgumentParser()
parser.add_argument("--record")
parser.add_argument("--screenshots")
parser.add_argument("--prefix", default="package")
args = parser.parse_args()
row = {"id": "fixture", "name": "example-package", "source": "npm:example-package@1.0.0", "version": "1.0.0", "scope": "global", "path": "index.ts", "enabled": True,
    "installedBy": "agent", "reason": "Installed for the current task", "useCount": 3, "lastUsed": "2026-10-28T08:00:00Z",
    "audit": "3 finding(s) found (0 critical, 0 high, 3 medium, 0 low, 0 info).\n" + repr([
        {"severity": "medium", "pattern": "HTTP client usage", "file": file, "line": line}
        for file, line in (("index.ts", 5), ("index.ts", 102), ("request.ts", 264))])}
if args.record:
    row = next(item for item in json.loads(Path(args.record).read_text(encoding="utf-8"))["packages"] if item.get("removable"))


class Backend(QObject):
    changed = Signal()
    jobDone = Signal(str, object)
    toast = Signal(str)

    def __init__(self, directory):
        super().__init__()
        self.store = SimpleNamespace(directory=Path(directory), data={"agent": {"installPermission": "automatic"}, "workspace": ""}, save=Mock())
        self._view = SimpleNamespace(workspace="")
        self._manager = PiManagement(self)
        self._manager._extensions = [row]
        installation = (row.get("installations") or [dict(row, package=row["name"], time="2026-10-28T08:00:00Z")])[-1]
        # Replay the saved data verbatim; no installation, scan or record rewrite.
        self._manager._package_records.data = {"version": 1, "installations": [installation], "usage": {row["name"]: {"useCount": row["useCount"], "lastUsed": row["lastUsed"]}}}
        self._manager._marketplace_progress = {"operation": "marketplace_install", "state": "done", "message": "Install Pi Package completed"}
        self._manager._scan = lambda apply=False: None
        self._language, self._approval = "zh", {}

    @Property(QObject, constant=True)
    def piManagement(self): return self._manager
    @Property(str, notify=changed)
    def language(self): return self._language
    @Property(float, constant=True)
    def fontScale(self): return 1.0
    @Property("QVariantMap", constant=True)
    def themeStyle(self): return {"base": "light", "colors": {}}
    @Property("QVariantMap", constant=True)
    def config(self): return {"theme": "light", "agent": {"safeMode": False}}
    @Property(bool, constant=True)
    def kernelBusy(self): return False
    @Property("QVariantMap", notify=changed)
    def pendingApproval(self): return self._approval
    @Slot(bool)
    def respondApproval(self, accepted): pass
    @Slot(str)
    def respondPiDialog(self, text): pass


app = QGuiApplication([])
if os.name == "nt":
    QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts/msyh.ttc"))
    app.setFont(QFont("Microsoft YaHei UI", 10))


def settle():
    until = time.monotonic() + 0.45
    while time.monotonic() < until:
        app.processEvents()
        time.sleep(0.01)


with tempfile.TemporaryDirectory(prefix="umeko-package-display-") as temp:
    backend = Backend(temp)
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    engine.rootContext().setContextProperty("backend", backend)
    qml = '''import QtQuick
import QtQuick.Controls
import "."
ApplicationWindow {
    width: 900; height: 720; visible: true; color: Theme.bg
    Item { x: parent.width - 24; y: parent.height - 24; PackagePopup { id: panel } }
    ApprovalDialog { id: approval }
    function showPanel() { panel.open() }
    function hidePanel() { panel.close() }
}'''
    engine.loadData(qml.encode(), QUrl.fromLocalFile(str(ROOT / "app/qml/PackagePresentationFixture.qml")))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    snapshots = []
    def shot(name):
        if args.screenshots:
            output = Path(args.screenshots) / name
            assert window.grabWindow().save(str(output))
            snapshots.append(str(output))
    panel = window.findChild(QObject, "packagePopup")
    def objects():
        pending, seen, result = [window], set(), []
        while pending:
            item = pending.pop()
            if id(item) in seen:
                continue
            seen.add(id(item)); result.append(item)
            pending.extend(item.children())
            if hasattr(item, "childItems"):
                pending.extend(item.childItems())
            content = item.property("contentItem")
            if isinstance(content, QObject):
                pending.append(content)
        return result
    def find(name):
        return next((item for item in objects() if item.objectName() == name), None)
    for language in ("zh", "en"):
        backend._language = language
        backend._approval = {}
        backend.changed.emit()
        QMetaObject.invokeMethod(window, "showPanel")
        settle()
        audit = find("packagePopupAudit_" + row["id"])
        assert audit is not None
        expected = "3 条中风险：HTTP 请求（index.ts、request.ts）" if language == "zh" else "3 medium-risk findings: HTTP requests (index.ts, request.ts)"
        assert audit.property("summary") == expected, audit.property("summary")
        assert not audit.property("opened")
        progress = find("packagePopupProgress")
        assert progress.property("text") == ("安装扩展包已完成" if language == "zh" else "Install package completed")
        suffix = "" if language == "zh" else "-en"
        shot(args.prefix + "-panel-result" + suffix + "-polish.png")
        audit.setProperty("expanded", True)
        settle()
        assert audit.property("opened")
        assert "index.ts:102" in "\n".join(str(child.property("text") or "") for child in objects())
        shot(args.prefix + "-panel-expanded" + suffix + "-polish.png")
        audit.setProperty("expanded", False)
        QMetaObject.invokeMethod(window, "hidePanel")
        confirmation_audit = {"summary": row["audit"].split("\n", 1)[0], "findings": backend.piManagement.auditPresentation(row["audit"])["findings"]}
        backend._approval = {"id": "replay", "method": "confirm", "title": "安装 Pi 扩展包？", "detail": json.dumps({"umekoPackageInstall": {"source": row["source"], "reason": row["reason"], "audit": confirmation_audit}}, ensure_ascii=False)}
        backend.changed.emit()
        settle()
        title = find("approvalTitle")
        assert title.property("text") == ("安装 Pi 扩展包？" if language == "zh" else "Install Pi package?")
        confirmation = find("approvalPackageAudit")
        assert confirmation.property("summary") == expected
        assert not confirmation.property("opened")
        shot(args.prefix + "-confirmation" + suffix + "-polish.png")
    assert not warnings, warnings
    window.close()
    del engine
    print("PACKAGE_PRESENTATION_QML_OK " + json.dumps({"screenshots": snapshots, "warnings": warnings}, ensure_ascii=False))
