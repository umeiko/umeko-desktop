"""Render icons with empty, valid and broken custom image URLs."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def check_rendering():
    from PySide6.QtCore import QObject, Property, QUrl
    from PySide6.QtGui import QImage, QColor
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    import shiboken6

    class Display(QObject):
        @Property(float,constant=True)
        def fontScale(self):return 1.0
        @Property('QVariantMap',constant=True)
        def themeStyle(self):return {'base':'light','colors':{}}
        @Property('QVariantMap',constant=True)
        def config(self):return {'theme':'light'}

    app=QApplication.instance() or QApplication([])
    display=Display();engine=QQmlApplicationEngine();engine.rootContext().setContextProperty('backend',display)
    with tempfile.TemporaryDirectory() as directory:
        fixture=Path(directory)/'custom.png';image=QImage(16,16,QImage.Format_ARGB32);image.fill(QColor('#2764cc'));assert image.save(str(fixture))
        icons=[{'iconGlyph':name,'iconSource':''} for name in ('folder','branch','terminal')]
        icons.extend([{}, {'iconGlyph':'terminal','iconSource':QUrl.fromLocalFile(str(fixture)).toString()},
                      {'iconGlyph':'terminal','iconSource':QUrl.fromLocalFile(str(Path(directory)/'missing.png')).toString()}])
        source='''import QtQuick
import QtQuick.Controls
import "QML_DIRECTORY" as Umeko
ApplicationWindow {
    width:240;height:64;visible:true;color:"white"
    Row {
        Repeater {
            model:ICON_FIXTURES
            Item {
                required property int index
                required property var modelData
                width:40;height:48
                Umeko.WidgetIcon {objectName:"fixtureIcon_"+parent.index;x:8;y:8;width:24;height:24;plugin:parent.modelData;color:"#202020"}
            }
        }
    }
}'''.replace('QML_DIRECTORY',QUrl.fromLocalFile(str(ROOT/'app/qml')).toString()).replace('ICON_FIXTURES',json.dumps(icons))
        engine.loadData(source.encode('utf-8'));assert engine.rootObjects(),'Icon QML failed to load'
        window=engine.rootObjects()[0]
        try:
            # No mouse/keyboard input: check the actual painted output rather
            # than relying on a successful QML compile or a truthy URL object.
            QTest.qWait(180)
            screenshot=window.grabWindow();assert not screenshot.isNull()
            ratio=screenshot.width()/240
            for index in range(len(icons)):
                painted=0
                for x in range(round((index*40+8)*ratio),round((index*40+32)*ratio)):
                    for y in range(round(8*ratio),round(32*ratio)):
                        pixel=screenshot.pixelColor(x,y)
                        painted+=min(pixel.red(),pixel.green(),pixel.blue())<220
                assert painted>12,f'Widget icon {index} was blank (painted={painted})'
            print('WIDGET_ICONS_RENDERED',flush=True)
        finally:
            window.hide();shiboken6.delete(engine)


class WidgetIconRenderingTests(unittest.TestCase):
    def test_builtin_and_custom_icon_fallbacks_are_visible(self):
        result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--render-check'],
            env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software'),
            capture_output=True,text=True,encoding='utf-8',timeout=30,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('WIDGET_ICONS_RENDERED',result.stdout)


if __name__=='__main__':
    if sys.argv[1:]==['--render-check']:check_rendering()
    else:unittest.main()
