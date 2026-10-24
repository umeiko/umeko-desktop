"""Show the actual installer QML in working/completed states for local acceptance."""
import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QUICK_CONTROLS_STYLE','Basic')
from PySide6.QtCore import QObject,Property,Signal,Slot,QTimer,QUrl,QEvent
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow

app=QGuiApplication(sys.argv)
models=[];engines=[];windows=[]
class Preview(QObject):
    changed=Signal()
    def __init__(self,state):
        super().__init__();self.value=dict(state=state,message='安装完成' if state=='complete' else '安装中…',progress=1 if state=='complete' else .46)
    @Property('QVariantMap',notify=changed)
    def status(self):return self.value
    @Property(str,constant=True)
    def language(self):return 'zh'
    @Slot()
    def finish(self):
        for model in models:
            model.value['state']='complete';model.changed.emit()
        app.quit()
    def eventFilter(self,watched,event):
        # This is a visual preview, with no installation job to protect.
        if event.type()==QEvent.Close:
            self.value['state']='complete';self.changed.emit()
        return False

area=app.primaryScreen().availableGeometry()
for index,state in enumerate(('installing','complete')):
    model=Preview(state);models.append(model)
    engine=QQmlApplicationEngine();engines.append(engine)
    engine.rootContext().setContextProperty('installer',model)
    engine.load(QUrl.fromLocalFile(str(ROOT/'app/qml/Installer.qml')))
    assert engine.rootObjects(),'Installer preview did not load'
    window=engine.rootObjects()[0];windows.append(window)
    window.installEventFilter(model)
    window.setTitle('Umeko · '+('安装中预览' if index==0 else '安装完成预览'))
    window.setPosition(area.x()+max(0,(area.width()-750)//2)+index*390,area.y()+max(0,(area.height()-430)//2))

def capture():
    out=ROOT/'artifacts/screenshots';out.mkdir(parents=True,exist_ok=True)
    for window,name in zip(windows,('installer-installing','installer-complete-preview')):
        assert window.grabWindow().save(str(out/(name+'.png')))
    if '--smoke' in sys.argv: models[1].finish()
QTimer.singleShot(400,capture)
app.exec()
