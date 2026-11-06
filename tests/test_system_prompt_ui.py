"""Offscreen built-in prompt Widget contract smoke; never uses desktop input."""
import copy
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(os.environ.get("UMEKO_SYSTEM_PROMPT_SCREENSHOTS", "C:/UmekoTests/p116/screenshots" if os.name == "nt" else str(Path(tempfile.gettempdir()) / "umeko-p116/screenshots")))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"
os.environ["QSG_RHI_BACKEND"] = "software"

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QFont, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
import shiboken6


def leaf(identifier, name, text, enabled=True):
    return dict(id=identifier, name=name, originalText=text, currentText=text,
                effectiveText=text if enabled else "",
                enabled=enabled, modified=False, stale=False, checkState=2 if enabled else 0)


class FakeSdk(QObject):
    hostResponse = Signal(str, "QVariantMap")
    activeChanged = Signal()
    appearanceChanged = Signal()
    languageChanged = Signal()
    sessionChanged = Signal()

    def __init__(self):
        super().__init__()
        self.requests = []
        self.counter = 0
        self.busy = False
        self.fail = False
        self.lang = "zh"
        self.tree = [dict(id="group", name="项目指令文件", labelKey="group:workspace", children=[
            leaf("intro", "CLAUDE.md", "Be clear and helpful.\nExplain your reasoning briefly."),
            dict(id="nested", name="docs", children=[
                leaf("notes", "notes.md", "Keep answers concise.\nUse examples when useful."),
                leaf("archive", "archived.md", "A disabled instruction example.", False)])]),
            dict(id="widgets", name="Widgets", labelKey="group:widgets", children=[])]
        self.recompute()

    @Property(bool, notify=activeChanged)
    def active(self): return True

    @Property(float, notify=appearanceChanged)
    def scale(self): return 1.0

    @Property(float, notify=appearanceChanged)
    def fontScale(self): return 1.0

    @Property("QVariantMap", constant=True)
    def config(self): return {"fontFamily": "Segoe UI"}

    @Property("QVariantMap", constant=True)
    def themeStyle(self): return {"base": "dark"}

    @Property(str, constant=True)
    def lineSpacing(self): return "standard"

    @Property(str, notify=languageChanged)
    def language(self): return self.lang

    @Property("QVariantMap", notify=sessionChanged)
    def session(self): return {"busy": self.busy}

    @Property("QVariantMap", constant=True)
    def colors(self):
        return dict(surface="#202521", bg="#181d19", ink="#e4e9e3", muted="#929e94",
                    accent="#9cc69f", accentBg="#334636", hover="#29362b", line="#465148", danger="#f0a4a0", dark=True)

    @Property("QVariantMap", constant=True)
    def hostCapabilities(self):
        return {"operations": {"systemPrompt." + name: True for name in ("inspect", "toggle", "save", "restore")}}

    def find(self, identifier):
        def visit(nodes):
            for node in nodes:
                if node["id"] == identifier: return node
                found = visit(node.get("children", []))
                if found: return found
        return visit(self.tree)

    def recompute(self):
        def visit(node):
            if "children" not in node:
                node["checkState"] = 2 if node["enabled"] else 0
                node["effectiveText"] = node["currentText"] if node["enabled"] and not node.get("shadowed") else ""
                return
            for child in node["children"]: visit(child)
            states = {child["checkState"] for child in node["children"]}
            node.update(checkState=next(iter(states)) if len(states) == 1 else 1,
                        enabled=any(child["enabled"] for child in node["children"]),
                        modified=any(child["modified"] for child in node["children"]),
                        stale=any(child["stale"] for child in node["children"]))
        for node in self.tree:
            if node["children"]: visit(node)
            else: node.update(checkState=2, enabled=True, modified=False, stale=False)

    def snapshot(self):
        leaves = [self.find(identifier) for identifier in ("intro", "notes", "archive")]
        return dict(ok=True, tree=copy.deepcopy(self.tree),
                    originalCharacters=sum(len(node["originalText"]) for node in leaves),
                    effectiveCharacters=sum(len(node["effectiveText"]) for node in leaves if node["enabled"]))

    @Slot(str, "QVariantMap", result=str)
    def requestHost(self, operation, args):
        self.counter += 1
        identifier = str(self.counter)
        self.requests.append((operation, copy.deepcopy(args)))
        if self.fail:
            self.fail = False
            value = dict(ok=False, error="fixture error")
        else:
            node = self.find(args.get("id"))
            if operation == "systemPrompt.toggle":
                def toggle(item):
                    if "children" in item:
                        for child in item["children"]: toggle(child)
                    else: item["enabled"] = args["enabled"]
                toggle(node)
            elif operation == "systemPrompt.save":
                node.update(currentText=args["text"], modified=args["text"] != node["originalText"])
            elif operation == "systemPrompt.restore":
                node.update(currentText=node["originalText"], modified=False, stale=False)
            self.recompute()
            value = self.snapshot()
        QTimer.singleShot(0, lambda: self.hostResponse.emit(identifier, value))
        return identifier


class SystemPromptUiSmoke(unittest.TestCase):
    def test_offscreen_widget(self):
        if os.environ.get("UMEKO_SYSTEM_PROMPT_UI_WORKER") != "1":
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker"],
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                    capture_output=True, text=True, encoding="utf-8")
            print(result.stdout, end="")
            self.assertEqual(result.returncode, 0, result.stderr)
            return
        QQuickStyle.setStyle("Basic")
        app = QGuiApplication.instance() or QGuiApplication([])
        for filename in ("segoeui.ttf", "msyh.ttc"):
            font = Path("C:/Windows/Fonts") / filename
            if font.is_file(): QFontDatabase.addApplicationFont(str(font))
        app.setFont(QFont("Segoe UI", 10))
        sdk = FakeSdk()
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
        engine.rootContext().setContextProperty("backend", sdk)
        engine.rootContext().setContextProperty("fixtureSdk", sdk)
        source = QUrl.fromLocalFile(str(ROOT / "umeko-plugins/system-prompt/qml")).toString()
        engine.loadData(('import QtQuick\nimport QtQuick.Window\nimport "' + source + '" as Prompt\n'
                         'Window { width: 500; height: 780; visible: true; '
                         'Prompt.Main { objectName: "fixtureWidget"; anchors.fill: parent; sdk: fixtureSdk } }').encode())
        self.assertTrue(engine.rootObjects(), "\n".join(warnings))
        window = engine.rootObjects()[0]
        root = window.findChild(QObject, "fixtureWidget")

        def value(item, key):
            result = item.property(key)
            return result.toVariant() if hasattr(result, "toVariant") else result

        def js(code, scope=root):
            expression = QQmlExpression(engine.rootContext(), scope, code)
            result = expression.evaluate()
            self.assertFalse(expression.hasError(), expression.error().toString())
            return result[0] if isinstance(result, tuple) else result

        def idle():
            for _ in range(200):
                QTest.qWait(10)
                if not root.property("working"): return
            self.fail("Widget did not complete its fixture request")

        def find(name):
            # ListView visual delegates are not always QObject children.
            stack = [window.contentItem()]
            while stack:
                item = stack.pop()
                if item.objectName() == name: return item
                stack.extend(item.childItems())
            self.fail("Missing item: " + name)

        def action(name):
            item = find(name)
            self.assertTrue(item.isVisible() and item.isEnabled(), name)
            js("clicked()", item)
            QTest.qWait(20)

        def screenshot(name):
            cases = os.environ.get("UMEKO_SYSTEM_PROMPT_SCREENSHOT_CASES")
            if cases and name not in cases.split(","): return
            QTest.qWait(40)
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            self.assertTrue(window.grabWindow().save(str(ARTIFACTS / (name + ".png"))))

        try:
            idle()
            self.assertEqual(root.property("selectedId"), "intro")
            self.assertEqual(js("Number(checkState)", find("systemPromptCheck_group")), 1)
            self.assertEqual(len(value(root, "entries")), 7)
            hint = value(root, "entries")[-1]
            self.assertTrue(hint["hint"] and "Widget" in hint["label"])
            self.assertFalse(find("systemPromptCheck_widgets").isEnabled())
            self.assertEqual(find("systemPromptName_group").property("text"), "项目指令文件")
            self.assertEqual(find("systemPromptTotals").property("text"), "当前注入 100 字 · 原文 131 字")
            initial_entries = {row["id"]: row for row in value(root, "entries")}
            for identifier in ("archive", "nested", "group"):
                self.assertTrue(initial_entries[identifier]["changed"], identifier + " did not reflect disabled effective text")
                self.assertEqual(find("systemPromptName_" + identifier).property("color").name(), "#d7b65b")
            self.assertFalse(initial_entries["intro"]["changed"])
            screenshot("01-mixed-tree")
            js('fold("nested")')
            self.assertEqual(len(value(root, "entries")), 5)
            js('fold("nested")')
            find("systemPromptEditor").setProperty("text", "Be clear and helpful.\nUse concrete, friendly examples.")
            self.assertTrue(root.property("dirty"))
            js('selectedId="notes"')
            js('selectedId="intro"')
            self.assertIn("friendly", root.property("draftText"))
            action("systemPromptRefresh"); idle()
            self.assertTrue(root.property("dirty"), "Refresh discarded an unsaved draft")
            action("systemPromptSave"); idle()
            self.assertFalse(root.property("dirty"))
            self.assertTrue(sdk.find("intro")["modified"])
            entries = value(root, "entries")
            self.assertTrue(next(row for row in entries if row["id"] == "group")["changed"])
            self.assertEqual(find("systemPromptName_intro").property("color").name(), "#d7b65b")
            screenshot("02-edited-segment")
            before = len(app.topLevelWindows())
            action("systemPromptRestore")
            self.assertTrue(find("systemPromptRestoreConfirmation").isVisible())
            self.assertEqual(len(app.topLevelWindows()), before, "Confirmation opened a native window")
            screenshot("03-restore-confirmation")
            action("systemPromptRestoreCancel")
            self.assertFalse(any(op == "systemPrompt.restore" for op, args in sdk.requests))
            action("systemPromptRestore"); action("systemPromptRestoreConfirm"); idle()
            self.assertFalse(sdk.find("intro")["modified"])
            self.assertEqual(root.property("draftText"), sdk.find("intro")["originalText"])
            js('selectedId="archive"')
            self.assertTrue(find("systemPromptDisabledNotice").isVisible())
            self.assertEqual(find("systemPromptName_archive").property("color").name(), "#d7b65b")
            self.assertEqual(js("Number(checkState)", find("systemPromptCheck_archive")), 0)
            self.assertEqual(sdk.find("archive")["effectiveText"], "")
            self.assertEqual(root.property("draftText"), sdk.find("archive")["currentText"])
            self.assertTrue(find("systemPromptCharacterCount").property("text").startswith("本段未注入"))
            screenshot("04-disabled-segment")
            js('request("systemPrompt.toggle", {id:"nested",enabled:true})'); idle()
            self.assertTrue(sdk.find("archive")["enabled"])
            js('request("systemPrompt.toggle", {id:"nested",enabled:false})'); idle()
            self.assertFalse(sdk.find("notes")["enabled"])
            self.assertEqual(js("Number(checkState)", find("systemPromptCheck_group")), 1)
            js('selectedId="intro";edit("Retain this unsaved draft.")')
            sdk.fail = True
            action("systemPromptSave"); idle()
            self.assertTrue(root.property("dirty"), "Failed save discarded a draft")
            sdk.find("intro")["stale"] = True
            action("systemPromptRefresh"); idle()
            self.assertTrue(find("systemPromptStaleNotice").isVisible())
            sdk.busy = True; sdk.sessionChanged.emit(); idle()
            self.assertFalse(find("systemPromptSave").isEnabled())
            self.assertTrue(find("systemPromptEditor").property("readOnly"))
            count = len(sdk.requests)
            js('save();request("systemPrompt.toggle",{id:"intro",enabled:false})')
            self.assertEqual(len(sdk.requests), count, "Busy session accepted a mutation")
            sdk.busy = False; sdk.sessionChanged.emit(); idle()
            sdk.find("intro")["shadowed"] = True
            action("systemPromptRefresh"); idle()
            self.assertEqual(sdk.find("intro")["effectiveText"], "")
            self.assertEqual(sdk.find("intro")["currentText"], sdk.find("intro")["originalText"])
            self.assertTrue(find("systemPromptShadowedNotice").isVisible())
            self.assertTrue(next(row for row in value(root, "entries") if row["id"] == "intro")["changed"])
            self.assertTrue(find("systemPromptCharacterCount").property("text").startswith("本段未注入"))
            self.assertEqual(root.property("draftText"), "Retain this unsaved draft.")
            self.assertEqual(find("systemPromptEditor").property("text"), "Retain this unsaved draft.")
            self.assertFalse(find("systemPromptEditor").property("readOnly"))
            self.assertEqual(find("systemPromptBreadcrumb").property("text"), "项目指令文件")
            sdk.lang = "en"; sdk.languageChanged.emit(); QTest.qWait(30)
            self.assertEqual(find("systemPromptSave").property("text"), "Save")
            self.assertEqual(find("systemPromptName_group").property("text"), "Project instruction files")
            self.assertTrue(find("systemPromptCharacterCount").property("text").startswith("Not injected"))
            window.setWidth(360); window.setHeight(650); QTest.qWait(30)
            self.assertGreater(find("systemPromptEditor").width(), 200)
            self.assertFalse(warnings, "\n".join(warnings))
            print("SYSTEM_PROMPT_UI_OK: mixed folders, collapse, draft retention, save/failure, restore overlay, disabled/stale, busy guard, i18n, neutral screenshots", flush=True)
        finally:
            window.close()
            shiboken6.delete(engine)
            app.processEvents()


def peak_memory():
    if os.name != "nt": return {}
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [(key, ctypes.c_size_t) for key in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    counters = Counters(); counters.cb = ctypes.sizeof(counters)
    ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    if not ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb): return {}
    return dict(peakRssMiB=round(counters.PeakWorkingSetSize / 1048576, 1),
                peakCommitMiB=round(counters.PeakPagefileUsage / 1048576, 1))


if __name__ == "__main__":
    if "--worker" not in sys.argv:
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker"],
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                capture_output=True, text=True, encoding="utf-8")
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
        raise SystemExit(result.returncode)
    sys.argv.remove("--worker")
    os.environ["UMEKO_SYSTEM_PROMPT_UI_WORKER"] = "1"
    try:
        unittest.main()
    finally:
        print("SYSTEM_PROMPT_UI_MEMORY " + json.dumps(peak_memory()), flush=True)
