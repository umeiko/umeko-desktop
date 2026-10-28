"""Real close events keep work alive; the tray menu and explicit quit still exit."""
import os, sys
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon, QWindow
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QSystemTrayIcon
from app.tray import TrayController
app=QApplication([])
window=QQuickWindow();window.resize(320,240);window.show()
ticks=[];agent=QTimer();agent.timeout.connect(lambda:ticks.append(1));agent.start(5)
with patch.object(QSystemTrayIcon,'isSystemTrayAvailable',return_value=True), patch.object(QSystemTrayIcon,'show'), patch.object(QSystemTrayIcon,'showMessage') as notify:
    tray=TrayController(window,QIcon(str(ROOT/'app/icons/yanami-pixel.png')))
    exits=[];tray.quitRequested.connect(lambda:exits.append(1))
    assert not window.close()
    assert not window.isVisible() and not exits
    QTest.qWait(50);assert ticks,'Agents stopped when window was hidden'
    notify.assert_called_once();assert notify.call_args.args[1]=='我在这里继续执行任务！需要完全退出你可以右键点击任务栏中的图标~'
    assert not tray.tray.icon().isNull()
    tray.open_action.trigger();QTest.qWait(20);assert window.isVisible()
    window.showMaximized();QTest.qWait(20)
    assert not window.close();tray.tray.messageClicked.emit();QTest.qWait(20)
    assert window.visibility()==QWindow.Maximized
    tray.quit_action.trigger();tray.quit_action.trigger();assert exits==[1]
    assert window.close()
tray.window_destroyed();tray.deleteLater();QTest.qWait(10)
with patch.object(QSystemTrayIcon,'isSystemTrayAvailable',return_value=False):
    window=QQuickWindow();window.show()
    tray=TrayController(window,QIcon(str(ROOT/'app/icons/yanami-pixel.png')))
    assert not window.close() and window.visibility()==QWindow.Minimized
    tray.restore();assert window.isVisible() and window.visibility()!=QWindow.Minimized
    quit_events=[];app.aboutToQuit.connect(lambda:quit_events.append(1))
    QTimer.singleShot(0,app.quit);app.exec()
    assert quit_events==[1] and tray.quitting
    assert window.close()
print('TRAY_UI_OK: close-to-tray notification, live background work, restore/maximize, menu exit, missing tray fallback, updater quit')
