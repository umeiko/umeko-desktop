"""Exercise the real collapsed QML tool header as native tool state changes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def render_status():
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlPropertyMap
    from app.syntax_highlight import register_text_types

    app = QGuiApplication([])
    register_text_types()
    engine = QQmlApplicationEngine()
    backend = QQmlPropertyMap()
    for key, value in {"language": "zh", "fontScale": 1.0,
                       "themeStyle": {"base": "light", "colors": {}},
                       "config": {"theme": "light"}}.items():
        backend.insert(key, value)
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(ROOT / "app/qml/ToolHistory.qml")))
    if not engine.rootObjects():
        raise RuntimeError("ToolHistory did not load")
    item = engine.rootObjects()[0]
    summaries = []
    for tools in ([{"id": "a", "name": "bash", "state": "running"}],
                  [{"id": "a", "name": "bash", "state": "done"},
                   {"id": "b", "name": "grep", "state": "running"}],
                  [{"id": "a", "name": "bash", "state": "done"},
                   {"id": "b", "name": "grep", "state": "done"}]):
        item.setProperty("tools", tools)
        app.processEvents()
        assert not item.property("expanded")
        summaries.append(item.property("summary"))
    print(json.dumps(summaries, ensure_ascii=False))
    import shiboken6
    shiboken6.delete(engine)


class RunningToolStatusTests(unittest.TestCase):
    def test_collapsed_header_names_only_currently_running_tools(self):
        # The suite also contains QCoreApplication-only tests; isolate this GUI
        # component in its own process instead of replacing their application.
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                       UMEKO_DATA_DIR=str(Path(temp) / "profile"),
                       PI_CODING_AGENT_DIR=str(Path(temp) / "agent"), PYTHONUTF8="1", PYTHONFAULTHANDLER="1")
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--render"],
                                    cwd=ROOT, env=env, capture_output=True, text=True,
                                    encoding="utf-8", timeout=30,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        running, next_tool, finished = json.loads(result.stdout)
        self.assertIn("bash", running)
        self.assertIn("grep", next_tool)
        self.assertNotIn("bash", next_tool)
        self.assertNotIn("bash", finished)
        self.assertNotIn("grep", finished)


if __name__ == "__main__":
    if "--render" in sys.argv:
        sys.path.insert(0, str(ROOT))
        render_status()
    else:
        unittest.main()
