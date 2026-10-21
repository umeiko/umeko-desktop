from __future__ import annotations

import os
import sys
from pathlib import Path
from app.platform_support import configure_input_method

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
configure_input_method()

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QIcon, QFont, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow

from app.controller import Controller
from app.project_info import VERSION
from app.syntax_highlight import register_text_types


def diagnostic(message):
    target = os.environ.get("CODEAGENT_DIAGNOSTICS")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    elif sys.stdout:
        print(message, flush=True)


def create_application():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    app = QGuiApplication(sys.argv)
    if not QFontDatabase.families() and os.name == "nt":
        # The Windows offscreen test platform does not discover system fonts.
        for font in ("msyh.ttc", "segoeui.ttf", "consola.ttf"):
            QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / font))
    app.setApplicationName("Umeko")
    app.setApplicationVersion(VERSION)
    app.setOrganizationName("Umeko")
    app.setFont(QFont("Microsoft YaHei UI", 10) if os.name == "nt" else QFontDatabase.systemFont(QFontDatabase.GeneralFont))
    app.setWindowIcon(QIcon(str(root / "app/icons/app.ico")))
    controller = Controller(root)
    register_text_types()
    engine = QQmlApplicationEngine()
    engine.warnings.connect(lambda errors: diagnostic("\n".join(e.toString() for e in errors)))
    engine.rootContext().setContextProperty("backend", controller)
    engine.load(QUrl.fromLocalFile(str(root / "app/qml/Main.qml")))
    if not engine.rootObjects():
        controller.close()
        raise RuntimeError("QML 界面加载失败")
    app.aboutToQuit.connect(controller.close)
    QTimer.singleShot(150, controller.loadNativeIndex)
    return app, engine, controller


if __name__ == "__main__":
    try:
        app, engine, controller = create_application()
    except Exception as exc:
        diagnostic(str(exc))
        if "--smoke" not in sys.argv and os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, "应用启动失败。请检查本机设置或从源码启动查看诊断。", "Umeko", 0x10)
        sys.exit(1)
    diagnostic("QML_READY")
    if "--smoke" in sys.argv:
        from app.pi_runtime import node_executable
        diagnostic("NODE_EXECUTABLE:" + node_executable())
    if "--snapshot" in sys.argv:
        output = sys.argv[sys.argv.index("--snapshot") + 1]
        QTimer.singleShot(650, lambda: engine.rootObjects()[0].grabWindow().save(output))
    if "--smoke" in sys.argv:
        QTimer.singleShot(1500, app.quit)
    result = app.exec()
    diagnostic("EXIT:" + str(result))
    import shiboken6
    shiboken6.delete(engine)
    sys.exit(result)
