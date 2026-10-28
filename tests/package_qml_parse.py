"""Compile the package-panel components offscreen, without services or models."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine, QQmlComponent

ROOT = Path(__file__).resolve().parents[1]
app = QGuiApplication(sys.argv)
engine = QQmlEngine()
for name in ("PackagePermission.qml", "PackageList.qml", "PackagePopup.qml", "Composer.qml", "ExtensionManager.qml"):
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(ROOT / "app/qml" / name)))
    if component.isError():
        raise AssertionError(component.errorString())
    assert component.status() == QQmlComponent.Ready, name
print("PACKAGE_QML_PARSE_OK")
