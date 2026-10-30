from __future__ import annotations

import os
import sys
from pathlib import Path
if "--umeko-plugin-worker" in sys.argv:
    import runpy
    _plugin_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    runpy.run_path(str(_plugin_root / "plugin-runtime/worker.py"), run_name="__main__")
    sys.exit(0)

from app.platform_support import configure_input_method

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
configure_input_method()

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QIcon, QFont, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtWidgets import QApplication

from app.controller import Controller
from app.project_info import VERSION
from app.syntax_highlight import register_text_types


def diagnostic(message):
    target = os.environ.get("UMEKO_DIAGNOSTICS")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    elif sys.stdout:
        print(message, flush=True)


def create_application():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    from app.webview import configure, configure_engine
    configure(root)
    app = QApplication(sys.argv)
    if not QFontDatabase.families() and os.name == "nt":
        # The Windows offscreen test platform does not discover system fonts.
        for font in ("msyh.ttc", "segoeui.ttf", "consola.ttf"):
            QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / font))
    app.setApplicationName("Umeko")
    app.setApplicationVersion(VERSION)
    app.setOrganizationName("Umeko")
    app.setFont(QFont("Microsoft YaHei UI", 10) if os.name == "nt" else QFontDatabase.systemFont(QFontDatabase.GeneralFont))
    app.setWindowIcon(QIcon(str(root / "app/icons/app.ico")))
    if "--install-update" in sys.argv:
        from app.update import UpdateInstaller
        installer = UpdateInstaller(root, sys.argv[sys.argv.index("--install-update") + 1])
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("installer", installer)
        engine.load(QUrl.fromLocalFile(str(root / "app/qml/Installer.qml")))
        if not engine.rootObjects(): raise RuntimeError("安装器界面加载失败")
        QTimer.singleShot(0, installer.begin)
        return app, engine, installer
    controller = Controller(root)
    saved_family = controller.store.data.get("fontFamily", "")
    if saved_family:
        font = app.font()
        font.setFamily(saved_family)
        app.setFont(font)
    register_text_types()
    engine = QQmlApplicationEngine()
    configure_engine(engine)
    engine.warnings.connect(lambda errors: diagnostic("\n".join(e.toString() for e in errors)))
    engine.rootContext().setContextProperty("backend", controller)
    engine.load(QUrl.fromLocalFile(str(root / "app/qml/Main.qml")))
    if not engine.rootObjects():
        controller.close()
        raise RuntimeError("QML 界面加载失败")
    app.aboutToQuit.connect(controller.close)
    from app.tray import TrayController
    controller._system_tray = TrayController(engine.rootObjects()[0], QIcon(str(root / "app/icons/yanami-pixel.png")), controller)
    controller._system_tray.set_language(controller.language)
    controller.appearanceChanged.connect(lambda: controller._system_tray.set_language(controller.language))
    controller._system_tray.quitRequested.connect(app.quit)
    controller._system_tray.notificationRequested.connect(controller.toast)
    from app.notifications import TaskNotifications
    controller._task_notifications = TaskNotifications(engine.rootObjects()[0], controller._system_tray.tray, root, controller)
    controller._task_notifications.language = controller.language
    controller.appearanceChanged.connect(lambda: setattr(controller._task_notifications, 'language', controller.language))
    controller.taskFinished.connect(controller._task_notifications.task_finished)
    def open_finished_session(session):
        engine.rootObjects()[0].setProperty('page', 'chat')
        controller.openSession(session)
        controller._system_tray.restore()
    controller._task_notifications.activated.connect(open_finished_session)
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
    preview_url=os.environ.get('UMEKO_WEB_PREVIEW_URL') if '--demo' in sys.argv else ''
    if preview_url: QTimer.singleShot(800, lambda: controller.webRequested.emit(preview_url,'Preview'))
    if "--smoke" not in sys.argv and "--install-update" not in sys.argv:
        controller.appAbout.startAutomaticChecks()
    if "--smoke" in sys.argv:
        notifications = controller._task_notifications.native
        diagnostic("NATIVE_NOTIFICATIONS_READY:" + str(int(notifications.library is not None or notifications.desktop is not None)))
        if sys.platform.startswith('linux'):
            from PySide6.QtCore import QLibraryInfo, QPluginLoader
            plugin = Path(QLibraryInfo.path(QLibraryInfo.PluginsPath)) / 'platforminputcontexts/libfcitx5platforminputcontextplugin.so'
            owned = Path(__file__).resolve().parent / 'build/input-method/plugins/platforminputcontexts/libfcitx5platforminputcontextplugin.so'
            if not getattr(sys, 'frozen', False) and owned.is_file(): plugin = owned
            loader = QPluginLoader(str(plugin))
            diagnostic('IME_PLUGIN_READY:' + str(int(loader.load())))
        from app.pi_runtime import node_executable
        diagnostic("NODE_EXECUTABLE:" + node_executable())
        if hasattr(controller, "_system_tray"):
            diagnostic("TRAY_ICON_READY:" + str(int(not controller._system_tray.tray.icon().pixmap(32,32).isNull())))
    if "--snapshot" in sys.argv:
        output = sys.argv[sys.argv.index("--snapshot") + 1]
        QTimer.singleShot(4000 if preview_url else 650, lambda: engine.rootObjects()[0].grabWindow().save(output))
    if "--smoke" in sys.argv:
        QTimer.singleShot(5500 if preview_url else 1500, app.quit)
    result = app.exec()
    diagnostic("EXIT:" + str(result))
    import shiboken6
    shiboken6.delete(engine)
    sys.exit(result)
