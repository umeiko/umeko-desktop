from __future__ import annotations

import os
import sys
from pathlib import Path
if __name__ == '__main__' and sys.argv[1:2] == ['--umeko-bash-job']:
    from app.bash_job_windows import main as bash_job_main
    os._exit(bash_job_main())

if __name__ == '__main__' and '--update-process-helper' in sys.argv:
    from app.update_windows import main as update_process_main
    sys.exit(update_process_main(sys.argv[sys.argv.index('--update-process-helper') + 1:]))

if __name__ == '__main__' and sys.argv[1:2] == ['--umeko-cli']:
    from app.terminal_client import main as terminal_main
    sys.exit(terminal_main(sys.argv[2:]))

if __name__ == '__main__':
    from app.preview_launch import route_start
    if route_start(Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))):
        sys.exit(0)
if "--umeko-plugin-worker" in sys.argv:
    import runpy
    _plugin_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    runpy.run_path(str(_plugin_root / "plugin-runtime/worker.py"), run_name="__main__")
    sys.exit(0)

from app.platform_support import configure_input_method, configure_qml_gc

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
configure_qml_gc()
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
    configure_qml_gc()
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    from app.webview import configure, configure_engine
    from app.desktop_preferences import startup_settings
    configure(root, enabled=startup_settings()['webDisplay'] == 'embedded')
    from PySide6.QtQuickControls2 import QQuickStyle
    QQuickStyle.setStyle("UmekoStyle")
    QQuickStyle.setFallbackStyle("Basic")
    app = QApplication(sys.argv)
    from app.input_method import InputMethodUpdates
    app._input_method_updates = InputMethodUpdates(app)
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
        engine.addImportPath(str(root / "app/qml"))
        engine.rootContext().setContextProperty("installer", installer)
        engine.load(QUrl.fromLocalFile(str(root / "app/qml/Installer.qml")))
        if not engine.rootObjects(): raise RuntimeError("安装器界面加载失败")
        QTimer.singleShot(0, installer.begin)
        return app, engine, installer
    controller = Controller(root)
    launch_error = os.environ.pop('UMEKO_PREVIEW_LAUNCH_ERROR', '')
    if launch_error:
        QTimer.singleShot(0, lambda: controller.toast.emit(launch_error))
    from app.bundled_skills import install_bundled
    try:
        install_bundled(root / 'bundled-skills', Path(controller.store.data['agent'].get('agentDir') or os.environ.get('PI_CODING_AGENT_DIR') or Path.home() / '.pi/agent'))
    except (OSError, ValueError) as error:
        print('Bundled Skills could not be installed:', error, file=sys.stderr)
    saved_family = controller.store.data.get("fontFamily", "")
    if saved_family:
        font = app.font()
        font.setFamily(saved_family)
        app.setFont(font)
    register_text_types()
    from app.terminal_view import register_terminal_types
    register_terminal_types()
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(root / "app/qml"))
    configure_engine(engine)
    engine.warnings.connect(lambda errors: diagnostic("\n".join(e.toString() for e in errors)))
    engine.rootContext().setContextProperty("backend", controller)
    engine.load(QUrl.fromLocalFile(str(root / "app/qml/Main.qml")))
    if not engine.rootObjects():
        controller.close()
        raise RuntimeError("QML 界面加载失败")
    app.aboutToQuit.connect(controller.close)
    from app.tray import TrayController
    controller._system_tray = TrayController(engine.rootObjects()[0], QIcon(str(root / "app/icons/app.png")), controller)
    controller._system_tray.set_language(controller.language)
    controller.appearanceChanged.connect(lambda: controller._system_tray.set_language(controller.language))
    controller._system_tray.quitRequested.connect(app.quit)
    controller._system_tray.notificationRequested.connect(controller.toast)
    if controller.loginStartup.background or '--cli-host' in sys.argv:
        controller._system_tray.minimize_to_tray(notify=False)
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
    if '--remote-environments-smoke' not in sys.argv and '--remote-workdir-smoke' not in sys.argv:
        from app.login_session import start_login_proxy
        QTimer.singleShot(0, lambda: start_login_proxy(controller, sys.argv))
        from app.update import start_update_cleanup
        QTimer.singleShot(0, lambda: start_update_cleanup(root, controller.store.directory))
    QTimer.singleShot(150, controller.loadNativeIndex)
    return app, engine, controller


if __name__ == "__main__":
    remote_smoke = '--remote-environments-smoke' in sys.argv
    workdir_smoke = '--remote-workdir-smoke' in sys.argv
    if remote_smoke or workdir_smoke:
        from app.storage import data_directory, legacy_data_directory
        profile = os.environ.get('UMEKO_DATA_DIR')
        if (os.environ.get('QT_QPA_PLATFORM') != 'offscreen' or not profile
                or any(Path(profile).resolve().is_relative_to(path.resolve())
                       for path in (data_directory(), legacy_data_directory(), Path.home() / '.umeko'))):
            raise SystemExit('The remote smoke test needs an isolated profile and offscreen Qt.')
    # Opt-in diagnostics for a frozen smoke process that hangs during teardown.
    # Keep the watchdog alive through Python/Qt finalization, after EXIT:0.
    if "--smoke" in sys.argv and os.environ.get('UMEKO_SMOKE_STACKS'):
        import faulthandler
        _smoke_stacks = open(os.environ['UMEKO_SMOKE_STACKS'], 'w', encoding='utf-8')
        faulthandler.dump_traceback_later(30, file=_smoke_stacks)
    from app.login_session import instance_for_launch
    from app.preview_launch import profile_directory
    instance_lock, continue_launch = instance_for_launch(profile_directory(), sys.argv)
    if not continue_launch or ('--cli-host' in sys.argv and instance_lock is None):
        sys.exit(0)
    if instance_lock is None and not any(arg in sys.argv for arg in (
            "--install-update", "--smoke", "--remote-environments-smoke", "--remote-workdir-smoke")):
        # If a terminal start already owns this profile, reveal that desktop.
        from app.terminal_client import TerminalClient
        from PySide6.QtCore import QCoreApplication
        try:
            peer = TerminalClient(start=False)
            peer.call("show")
        except (OSError, ValueError):
            core = QCoreApplication.instance()
            if core is not None:
                core.shutdown()
        else:
            peer.close()
            sys.exit(0)
    try:
        app, engine, controller = create_application()
    except Exception as exc:
        diagnostic(str(exc))
        if not remote_smoke and not workdir_smoke and "--smoke" not in sys.argv and os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, "应用启动失败。请检查本机设置或从源码启动查看诊断。", "Umeko", 0x10)
        sys.exit(1)
    if instance_lock is not None and not any(arg in sys.argv for arg in (
            "--install-update", "--smoke", "--remote-environments-smoke", "--remote-workdir-smoke")):
        from app.terminal_host import TerminalHost
        try:
            terminal_host = TerminalHost(controller)
            app.aboutToQuit.connect(terminal_host.close)
        except OSError as error:
            diagnostic(f"Terminal host unavailable: {error}")
    diagnostic("QML_READY")
    preview_url=os.environ.get('UMEKO_WEB_PREVIEW_URL') if '--demo' in sys.argv else ''
    if preview_url: QTimer.singleShot(800, lambda: controller.webRequested.emit(preview_url,'Preview'))
    if remote_smoke:
        from app.remote_environments_smoke import start
        start(app, engine, controller, Path(sys.argv[sys.argv.index('--remote-environments-smoke') + 1]))
    elif workdir_smoke:
        from app.remote_workdir_smoke import start
        start(app, engine, controller, Path(sys.argv[sys.argv.index('--remote-workdir-smoke') + 1]))
    elif "--smoke" not in sys.argv and "--install-update" not in sys.argv:
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
    smoke_finish = os.environ.get('UMEKO_SMOKE_FINISH_FILE', '') if preview_url and '--smoke' in sys.argv else ''
    if "--snapshot" in sys.argv and not smoke_finish:
        output = sys.argv[sys.argv.index("--snapshot") + 1]
        QTimer.singleShot(4000 if preview_url else 650, lambda: engine.rootObjects()[0].grabWindow().save(output))
    if "--smoke" in sys.argv:
        if smoke_finish:
            from app.smoke_lifecycle import watch_smoke_finish
            # Match the native preview test: let WebView2 render in an active
            # window rather than leave requestAnimationFrame occluded by CI.
            engine.rootObjects()[0].raise_()
            engine.rootObjects()[0].requestActivate()
            snapshot = sys.argv[sys.argv.index('--snapshot') + 1] if '--snapshot' in sys.argv else ''
            _smoke_finish_timer = watch_smoke_finish(app, engine.rootObjects()[0], smoke_finish, snapshot)
        elif os.environ.get("UMEKO_SHELL_SMOKE_DIRECTORY"):
            from app.shell_smoke import attach
            attach(app, controller, Path(os.environ["UMEKO_SHELL_SMOKE_DIRECTORY"]), engine.rootObjects()[0])
        else:
            QTimer.singleShot(5500 if preview_url else 1500, app.quit)
    result = app.exec()
    diagnostic("EXIT:" + str(result))
    import shiboken6
    shiboken6.delete(engine)
    sys.exit(result)
