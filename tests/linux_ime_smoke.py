"""Run on a real xcb desktop with fcitx5+pinyin; never substitutes a fake commit."""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument('--plugins', type=Path, default=ROOT/'build/input-method/plugins')
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'xcb'
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
os.environ['QT_QUICK_CONTROLS_STYLE'] = 'Basic'
from PySide6.QtCore import QCoreApplication, QMetaObject, Qt, Q_ARG, Q_RETURN_ARG, QObject, QUrl
QCoreApplication.addLibraryPath(str(args.plugins.resolve()))
from app.platform_support import configure_input_method
configure_input_method(plugin_directory=args.plugins/'platforminputcontexts')
from PySide6.QtDBus import QDBusConnection, QDBusInterface
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

app = QApplication([])
def contexts():
    tree = subprocess.check_output(['busctl', '--user', 'tree', 'org.fcitx.Fcitx5'], text=True)
    return set(re.findall(r'/org/freedesktop/portal/inputcontext/\d+', tree))
before = contexts()
engine = QQmlApplicationEngine()
engine.loadData(b'''import QtQuick
import QtQuick.Controls
Window { width: 420; height: 180; visible: true; title: "Umeko IME verification"
  TextArea { anchors.fill: parent; anchors.margins: 20; objectName: "input"; focus: true; font.pixelSize: 24 }
}''', QUrl('file:///umeko-ime-test.qml'))
assert engine.rootObjects()
window = engine.rootObjects()[0]
input_item = window.findChild(QObject, 'input')
window.requestActivate(); input_item.forceActiveFocus(); QTest.qWait(800)
created = contexts() - before
assert len(created) == 1, f'Expected one native fcitx input context, found {created}'
# The real plugin uses its own named D-Bus connection. Fcitx checks its owner.
bus = QDBusConnection('fcitx')
assert bus.isConnected(), 'Qt did not load the fcitx input plugin'
proxy = QDBusInterface('org.fcitx.Fcitx5', next(iter(created)), 'org.fcitx.Fcitx.InputContext1', bus)
controller = QDBusInterface('org.fcitx.Fcitx5', '/controller', 'org.fcitx.Fcitx.Controller1', bus)
previous = controller.call('CurrentInputMethod').arguments()[0]
try:
    controller.call('SetCurrentIM', 'pinyin'); proxy.call('FocusIn'); QTest.qWait(100)
    def key(value):
        handled = QMetaObject.invokeMethod(proxy, 'ProcessKeyEvent', Qt.DirectConnection, Q_RETURN_ARG(bool),
            Q_ARG('uint', value), Q_ARG('uint', 0), Q_ARG('uint', 0), Q_ARG(bool, False), Q_ARG('uint', 0))
        assert handled, 'fcitx did not process the input key'
        QTest.qWait(120)
    key(ord('n')); key(ord('i'))
    assert input_item.property('preeditText'), 'No real fcitx composition reached the Qt Quick editor'
    key(ord(' '))
    assert input_item.property('text') == '你', repr(input_item.property('text'))
    print('LINUX_IME_OK: native context, pinyin preedit and Chinese commit in Qt Quick; '+str(args.plugins))
finally:
    controller.call('SetCurrentIM', previous)
    window.close(); app.processEvents()
