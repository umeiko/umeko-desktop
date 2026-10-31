"""Skill Widget UI against an asynchronous fake SDK, with no real profile or process."""
import os
import json
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QObject, Property, QPointF, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
from PySide6.QtQuick import QQuickItem, QQuickTextDocument, QQuickView
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQml import QQmlExpression
from PySide6.QtTest import QTest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ["global", "project", "package", "extension", "extra"]


class FakeSdk(QObject):
    hostResponse = Signal(str, "QVariantMap")
    activeChanged = Signal()
    languageChanged = Signal()
    capabilitiesChanged = Signal()

    def __init__(self):
        super().__init__()
        self._language = "en"
        self._operations = {name: True for name in [
            "skills.list", "skills.details", "skills.attach", "skills.default",
            "skills.reveal", "skills.remove", "skills.job", "skills.importPreview", "skills.import", "pi.install", "pi.job", "pi.cancel",
        ]}
        self.requests = []
        self.jobs = {}
        self.counter = 0
        self.fail_list = False
        self.install_failure = False
        self.cancelled = False
        self.import_fatal = False
        self.import_errors = False
        self.rows = [{
            "id": f"skill-{i:02d}", "name": f"document-{i:02d}",
            "description": f"Organize notes for topic {i:02d}.",
            "path": f"<fixture-skills>/{i:02d}/SKILL.md", "source": SOURCES[i // 8],
            "scope": "project" if i // 8 == 1 else "global", "enabled": i % 3 != 0,
            "attached": i % 5 < 2, "packageSource": "npm:fixture-skills" if i // 8 == 2 else "",
            "removable": i // 8 == 2, "defaultMutable": i // 8 in (0, 1, 2),
        } for i in range(40)]

    @Property(bool, notify=activeChanged)
    def active(self): return True

    @Property(float, constant=True)
    def scale(self): return 1.0

    @Property(str, notify=languageChanged)
    def language(self): return self._language

    @Property("QVariantMap", constant=True)
    def colors(self):
        return dict(surface="#202521", bg="#181d19", ink="#e4e9e3", muted="#929e94",
                    accent="#9cc69f", accentBg="#334636", hover="#29362b", line="#465148", danger="#f0a4a0")

    @Property("QVariantMap", notify=capabilitiesChanged)
    def hostCapabilities(self): return {"operations": self._operations}

    def reply(self, request, value):
        QTimer.singleShot(0, lambda: self.hostResponse.emit(request, value))

    @Slot(str, "QVariantMap", result=str)
    def requestHost(self, operation, args):
        self.counter += 1
        request = f"request-{self.counter}"
        self.requests.append((operation, args))
        if operation in ("skills.job", "pi.job"):
            item = self.jobs[args["id"]]
            if item["operation"] == "pi.install" and not self.install_failure and not self.cancelled:
                self.reply(request, {"ok": True, "jobs": [{"id": args["id"], "status": "running"}],
                                     "progress": {"message": "Installing fixture package…", "cancellable": True}})
            else:
                failed = item["operation"] == "pi.install" and self.install_failure
                status = "failed" if failed else "cancelled" if item["operation"] == "pi.install" and self.cancelled else "completed"
                result = item["result"]
                if failed: result = {"ok": False, "error": "Fixture installation failed"}
                elif status == "cancelled": result = {"ok": False, "error": "Fixture installation cancelled"}
                self.reply(request, {"ok": True, "jobs": [{"id": args["id"], "status": status, "result": result}]})
        elif operation == "pi.cancel":
            self.cancelled = True
            self.reply(request, {"ok": True, "result": {"ok": True}})
        elif operation == "skills.list" and self.fail_list:
            self.fail_list = False
            self.reply(request, {"ok": False, "error": "Fixture host busy"})
        else:
            result = {"ok": True}
            if operation == "skills.list": result["skills"] = [dict(row) for row in self.rows]
            elif operation == "skills.details":
                row = next(row for row in self.rows if row["id"] == args["id"])
                result["details"] = dict(id=row["id"], markdown="# Fixture guide\n\n**Read carefully** and preserve order.",
                    files=[{"path": "SKILL.md", "size": 1024}, {"path": "references/guide.md", "size": 512}],
                    size=1536, path=row["path"], directory="<fixture-skills>", truncated=False)
            elif operation in ("skills.attach", "skills.default"):
                row = next(row for row in self.rows if row["id"] == args["id"])
                row["attached" if operation == "skills.attach" else "enabled"] = args["enabled"]
            elif operation == "skills.remove":
                self.rows = [row for row in self.rows if row["packageSource"] != "npm:fixture-skills"]
            elif operation == "skills.importPreview":
                result["preview"] = {"id": "import-preview", "sourceName": "local-skills.skill", "project": args["project"],
                    "errors": ["Fixture archive is invalid"] if self.import_fatal else [], "skills": [
                        {"name": "local-guide", "description": "Organize local documents.", "conflict": False, "replaceable": False},
                        {"name": "existing-notes", "description": "Arrange existing notes.", "conflict": True, "replaceable": True},
                        {"name": "blocked-guide", "description": "Read a packaged guide.", "conflict": True, "replaceable": False,
                         "error": "同名技能位于所选目录之外，只能跳过。"},
                        {"name": "invalid-guide", "description": "", "conflict": False, "replaceable": False,
                         "error": "Fixture SKILL.md is invalid"},
                    ]}
            elif operation == "skills.import":
                result.update(imported=[name for name, decision in args["decisions"].items() if decision == "replace"],
                              skipped=[name for name, decision in args["decisions"].items() if decision == "skip"],
                              errors=[{"name": "fixture-item", "error": "Fixture copy failed"}] if self.import_errors else [])
            job = f"job-{self.counter}"
            self.jobs[job] = {"operation": operation, "result": result}
            self.reply(request, {"ok": True, "accepted": True, "jobId": job})
        return request


QQuickStyle.setStyle("Basic")
app = QGuiApplication([])
# Windows' offscreen platform has no native font database.
for font in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/msyh.ttc"):
    if Path(font).is_file(): QFontDatabase.addApplicationFont(font)
app.setFont(QFont("Segoe UI", 10))
sdk = FakeSdk()
view = QQuickView()
warnings = []
view.engine().warnings.connect(lambda values: warnings.extend(value.toString() for value in values))
view.setResizeMode(QQuickView.SizeRootObjectToView)
view.setInitialProperties({"sdk": sdk})
view.setSource(QUrl.fromLocalFile(str(ROOT / "umeko-plugins/skill-manager/qml/Main.qml")))
assert view.status() == QQuickView.Ready, [e.toString() for e in view.errors()]
view.resize(500, 800)
view.show()
root = view.rootObject()


def find(name):
    stack = [root]
    while stack:
        item = stack.pop()
        if item.objectName() == name: return item
        stack.extend(item.childItems())
    return root.findChild(QQuickItem, name)


def wait_for(predicate, label):
    for _ in range(400):
        QTest.qWait(10)
        if predicate(): return
    raise AssertionError(label + ": " + str(root.property("notice")))


def idle(): wait_for(lambda: not root.property("working"), "Widget did not become idle")


def click(name):
    QTest.qWait(30)
    item = find(name)
    assert item and item.isVisible() and item.isEnabled(), name
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())
    QTest.qWait(30)


def entries(): return root.property("entries").toVariant()


def variant(value): return value.toVariant() if hasattr(value, "toVariant") else value


def js(expression):
    code = QQmlExpression(view.engine().rootContext(), root, expression)
    result = code.evaluate()
    assert not code.hasError(), code.error().toString()
    return result[0] if isinstance(result, tuple) else result


def run_import_cases():
    idle()
    click("skillManagerImport")
    assert root.property("route") == "import"
    assert not any(op == "skills.importPreview" for op, _ in sdk.requests)
    find("skillManagerImportSource").setProperty("text", "C:/fixture/local-skills.skill")
    click("skillManagerImportGlobal")
    click("skillManagerImportPreview")
    idle()
    assert sdk.requests[-2][0] == "skills.importPreview" and sdk.requests[-2][1]["project"] is False
    assert root.property("importReady")
    assert not find("skillManagerImportReplace_blocked-guide").isEnabled()
    assert not find("skillManagerImportReplace_invalid-guide").isEnabled()
    assert find("skillManagerImportError_blocked-guide").property("text") == "The existing skill is outside the selected directory and must be skipped."
    assert js('importError("Native validation detail: missing description")') == "Native validation detail: missing description"
    assert js('importError("SKILL.md 必须为 UTF-8 且通过 Pi 原生格式验证。Missing description")').endswith("Missing description")
    click("skillManagerImportReplace_existing-notes")
    click("skillManagerImportSubmit")
    idle()
    imported = next(args for op, args in reversed(sdk.requests) if op == "skills.import")
    assert imported == {"id": "import-preview", "decisions": {"local-guide": "replace", "existing-notes": "replace", "blocked-guide": "skip", "invalid-guide": "skip"}}
    assert root.property("route") == "import" and "Imported 2; skipped 2" in root.property("notice")
    # A drop uses the same preview operation. This invokes the logical handler;
    # it does not inject an OS drag, touch the clipboard, or access a profile.
    assert js('dropLocalUrls(["file:///C:/fixture/drop.skill"])')
    idle()
    last_preview = next(args for op, args in reversed(sdk.requests) if op == "skills.importPreview")
    assert last_preview["source"] == "file:///C:/fixture/drop.skill" and last_preview["project"] is False
    assert not js('dropLocalUrls(["https://example.invalid/local.zip"])')
    assert not js('dropLocalUrls(["file:///C:/fixture/a.zip", "file:///C:/fixture/b.zip"])')
    sdk.import_errors = True
    click("skillManagerImportSubmit")
    idle()
    assert root.property("route") == "import" and root.property("noticeError")
    assert variant(root.property("importResult"))["errors"][0]["error"] == "Fixture copy failed"
    sdk.import_fatal = True
    click("skillManagerImportPreview")
    idle()
    assert not root.property("importReady") and not find("skillManagerImportSubmit").isEnabled()
    assert variant(root.property("importPreview"))["errors"] == ["Fixture archive is invalid"]
    sdk._operations.pop("skills.importPreview")
    sdk.capabilitiesChanged.emit()
    click("skillManagerImportPreview")
    assert "newer Umeko" in root.property("notice")
    assert js('displayMarkdown("Text ![alt](https://example.invalid/a.png) <img src=\\"https://example.invalid/b.png\\"> ![reference][image]")') == "Text alt  reference"
    assert not any("approve" in op.lower() or "confirm" in op.lower() for op, _ in sdk.requests)
    assert not warnings, "\n".join(warnings)
    print("SKILL_MANAGER_IMPORT_UI_OK: path/one-local-URL drop, preview/scope, conflict skip/replace, invalid rows, result/error retention, missing capability, no Widget approval")


if "--import-only" in sys.argv:
    try:
        run_import_cases()
    finally:
        view.close()
        view.setSource(QUrl())
        app.processEvents()
    raise SystemExit(0)


try:
    idle()
    assert len(entries()) == 16
    click("skillManagerAll")
    assert len(entries()) == 40
    assert entries()[0]["skill"]["name"] == "document-00"
    click("skillManagerSort")
    assert entries()[0]["skill"]["name"] == "document-39"
    click("skillManagerSort")
    click("skillManagerSourceFilter")
    click("skillManagerFilter_project")
    assert len(entries()) == 8 and all(e["skill"]["source"] == "project" for e in entries())
    click("skillManagerDefaultFilter")
    click("skillManagerFilter_off")
    assert all(not e["skill"]["enabled"] for e in entries())
    root.setProperty("sourceFilter", "all")
    root.setProperty("defaultFilter", "all")
    click("skillManagerGroup")
    assert len(entries()) == 45 and entries()[0]["kind"] == "group"
    listing = find("skillManagerList")
    listing.forceActiveFocus()
    listing.setProperty("currentIndex", 0)
    QTest.keyClick(view, Qt.Key_Right)
    assert len(entries()) == 37
    QTest.keyClick(view, Qt.Key_Left)
    assert len(entries()) == 45
    click("skillManagerGroup")
    listing.forceActiveFocus()
    listing.setProperty("currentIndex", 0)
    QTest.keyClick(view, Qt.Key_Down)
    assert listing.property("currentIndex") == 1
    QTest.keyClick(view, Qt.Key_Up)
    assert listing.property("currentIndex") == 0
    old_attached = sdk.rows[0]["attached"]
    QTest.keyClick(view, Qt.Key_Space)
    idle()
    assert sdk.rows[0]["attached"] != old_attached
    QTest.keyClick(view, Qt.Key_Return)
    idle()
    assert find("skillManagerDetails").isVisible()
    quick_document = find("skillManagerMarkdown").property("textDocument")
    rendered_document = quick_document.textDocument()
    rendered = rendered_document.toPlainText()
    assert "Fixture guide" in rendered and "**" not in rendered and "# " not in rendered
    assert "1,536 bytes" in find("skillManagerSize").property("text")
    assert find("skillManagerEntry_skill-00").height() == 26
    check = find("skillManagerAttach_skill-00")
    assert check.mapToItem(listing, QPointF()).x() > listing.width() - 40
    assert find("skillManagerRemove").isVisible() is False
    click("skillManagerFilesTab")
    assert root.property("filesOpen")
    click("skillManagerDefault")
    idle()
    assert sdk.rows[0]["enabled"]
    click("skillManagerReveal")
    idle()
    assert any(op == "skills.reveal" for op, _ in sdk.requests)
    listing.forceActiveFocus()
    QTest.keyClick(view, Qt.Key_F, Qt.ControlModifier)
    assert find("skillManagerSearch").hasActiveFocus()
    find("skillManagerSearch").setProperty("text", "topic 23")
    assert len(entries()) == 1 and entries()[0]["skill"]["id"] == "skill-23"
    find("skillManagerSearch").setProperty("text", "")
    root.setProperty("detailOpen", False)
    idle()
    sdk._language = "zh"
    sdk.languageChanged.emit()
    assert "移出不清除已读内容" in find("skillManagerContextHint").property("text")
    sdk._language = "en"
    sdk.languageChanged.emit()
    sdk.fail_list = True
    click("skillManagerRefresh")
    idle()
    assert "Fixture host busy" in root.property("notice")
    click("skillManagerRetry")
    idle()
    assert len(entries()) == 40
    click("skillManagerInstall")
    find("skillManagerInstallSource").setProperty("text", "npm:fixture-skills")
    click("skillManagerInstallGlobal")
    click("skillManagerInstallSubmit")
    wait_for(lambda: bool(root.property("job")), "Install job not accepted")
    assert sdk.requests[-1][0] == "pi.install" and sdk.requests[-1][1]["project"] is False
    click("skillManagerInstallCancel")
    idle()
    assert sdk.cancelled and "cancelled" in root.property("notice")
    sdk.cancelled = False
    sdk.install_failure = True
    click("skillManagerInstallSubmit")
    idle()
    assert "Fixture installation failed" in root.property("notice")
    assert root.property("route") == "install" and find("skillManagerRetry").isVisible()
    assert not any("approve" in op.lower() or "confirm" in op.lower() for op, _ in sdk.requests)
    # The widget retains its own menus and fixed detail content inside its bounds.
    assert root.property("clip") and find("skillManagerFilterMenu").property("clip")
    assert not warnings, "\n".join(warnings)
    print("SKILL_MANAGER_UI_OK: 40-row async fixture, dense rows, keyboard, filters, grouping, Markdown/files, chat/default requests, install cancellation/failure, i18n")
    root.setProperty("route", "main")
    run_import_cases()
finally:
    view.close()
    view.setSource(QUrl())
    app.processEvents()
