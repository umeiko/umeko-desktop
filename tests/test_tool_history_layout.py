"""Measure real ToolHistory item geometry in an offscreen narrow chat column."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LONG_NAME = "mcp__github_enterprise_workspace__get_pull_request_revi_08d4ef2b"
PARALLEL_NAMES = ["mcp__github__get_pull_request", "mcp__github__list_pull_request_reviews"]


def render_cases(output=None):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtQml import QQmlApplicationEngine, QQmlPropertyMap
    from PySide6.QtQuick import QQuickWindow  # Register the window wrapper before loading QML.
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from app.syntax_highlight import register_text_types
    import shiboken6

    app = QApplication([])
    if os.name == "nt":
        for name in ("msyh.ttc", "segoeui.ttf"):
            QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / name))
    app.setFont(QFont("Microsoft YaHei UI", 10) if os.name == "nt" else QFont("sans-serif", 10))
    register_text_types()
    backend = QQmlPropertyMap()
    for key, value in {"language": "zh", "fontScale": 1.0,
                       "themeStyle": {"base": "light", "colors": {}},
                       "config": {"theme": "light"}, "tools": []}.items():
        backend.insert(key, value)
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    engine.rootContext().setContextProperty("backend", backend)
    source = '''import QtQuick
import QtQuick.Controls
import "QML_DIRECTORY" as Umeko
ApplicationWindow {
    width: 800; height: 150; visible: true; color: "#fafafa"
    Text { x: 20; y: 16; text: backend.language + " / 410 px"; color: "#666666" }
    Rectangle { x: 20; y: 50; width: 410; height: 52; color: "transparent"; border.color: "#bd6464" }
    Column {
        x: 20; y: 64; width: 410
        Umeko.ToolHistory { objectName: "layoutHistory"; width: parent.width; tools: backend.tools }
    }
}'''.replace("QML_DIRECTORY", QUrl.fromLocalFile(str(ROOT / "app/qml")).toString())
    engine.loadData(source.encode("utf-8"))
    if not engine.rootObjects():
        raise RuntimeError("\n".join(warnings))
    window = engine.rootObjects()[0]

    def descendants(item):
        yield item
        for child in item.childItems():
            yield from descendants(child)

    history = next(item for item in descendants(window.contentItem()) if item.objectName() == "layoutHistory")
    records = []
    try:
        for language in ("zh", "en"):
            for case, names in (("long-name", [LONG_NAME]), ("parallel", PARALLEL_NAMES)):
                backend.insert("language", language)
                backend.insert("tools", [{"id": str(i), "name": name, "state": "running", "arguments": {}} for i, name in enumerate(names)])
                QTest.qWait(100)
                # The original header is the first visual child too; this keeps
                # the reproduction usable before production objectNames exist.
                header = next((item for item in history.childItems() if item.objectName() == "toolHistoryHeader"), history.childItems()[0])
                children = list(descendants(header))
                label = next(item for item in children if item.property("text") == history.property("summary"))
                arrow = next(item for item in children if item.property("name") == "chevron-right")
                hp, lp, ap = (item.mapToItem(history, 0, 0) for item in (header, label, arrow))
                row = {"language": language, "case": case, "names": names,
                       "column_width": history.width(), "header_x": hp.x(), "header_width": header.width(),
                       "label_x": lp.x(), "label_width": label.width(), "label_implicit_width": label.implicitWidth(),
                       "label_right": lp.x() + label.width(), "label_truncated": bool(label.property("truncated")),
                       "arrow_x": ap.x(), "arrow_width": arrow.width(), "arrow_right": ap.x() + arrow.width(),
                       "arrow_visible": arrow.isVisible(), "summary": history.property("summary")}
                if output:
                    path = Path(output) / f"{language}-{case}.png"
                    image = window.grabWindow()
                    if image.isNull() or not image.save(str(path)):
                        raise RuntimeError("Screenshot failed: " + str(path))
                records.append(row)
        if warnings:
            raise RuntimeError("\n".join(warnings))
        return records
    finally:
        window.hide()
        shiboken6.delete(engine)


class ToolHistoryLayoutTests(unittest.TestCase):
    def test_long_and_parallel_tools_keep_header_and_arrow_inside_410px(self):
        temporary_root = os.environ.get("UMEKO_LAYOUT_TEMP_ROOT")
        with tempfile.TemporaryDirectory(prefix="tool-history-layout-", dir=temporary_root) as temp:
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                       UMEKO_DATA_DIR=str(Path(temp) / "profile"), PI_CODING_AGENT_DIR=str(Path(temp) / "agent"),
                       PYTHONUTF8="1")
            command = [sys.executable, str(Path(__file__).resolve()), "--render"]
            if os.environ.get("UMEKO_LAYOUT_SCREENSHOTS"):
                command.extend(["--output", os.environ["UMEKO_LAYOUT_SCREENSHOTS"]])
            child = subprocess.run(command,
                                   cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
                                   timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
        rows = json.loads(child.stdout)
        self.assertEqual(len(rows), 4)
        for row in rows:
            with self.subTest(language=row["language"], case=row["case"]):
                self.assertGreater(row["header_width"], 0)
                self.assertGreaterEqual(row["header_x"], 0)
                self.assertLessEqual(row["header_x"] + row["header_width"], row["column_width"] + .5, row)
                self.assertTrue(row["arrow_visible"], row)
                self.assertGreater(row["arrow_width"], 0)
                self.assertGreaterEqual(row["arrow_x"], row["header_x"], row)
                self.assertLessEqual(row["arrow_right"], row["column_width"] + .5, row)
                self.assertLessEqual(row["label_right"], row["arrow_x"] - 6.5, row)
                self.assertTrue(row["label_truncated"], row)


if __name__ == "__main__":
    if "--render" in sys.argv:
        sys.path.insert(0, str(ROOT))
        output = sys.argv[sys.argv.index("--output") + 1] if "--output" in sys.argv else None
        rows = render_cases(output)
        if output:
            (Path(output) / "measurements.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(rows, ensure_ascii=False), flush=True)
    else:
        unittest.main()
