"""Background discovery and the sidebar's direct download action during chat."""
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['UMEKO_DATA_DIR']=tempfile.mkdtemp(prefix='umeko-auto-update-')
os.environ['UMEKO_LANGUAGE']='zh'
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from main import create_application

app,engine,backend=create_application()
window=engine.rootObjects()[0]
warnings=[]
engine.warnings.connect(lambda errors:warnings.extend(e.toString() for e in errors))
def find(name):
    pending=[window.contentItem()]
    while pending:
        item=pending.pop()
        if item.objectName()==name:return item
        pending.extend(item.childItems())
    raise AssertionError(name)
def wait(condition):
    for _ in range(100):
        if condition():return
        QTest.qWait(25)
    assert condition()
try:
    about=backend.appAbout
    QTest.qWait(100)
    button=find('sidebarUpdateButton')
    assert not button.isVisible()
    release={'state':'available','version':'v99.0.0','message':'发现新版本 v99.0.0','asset':{'name':'fixture.zip'}}
    backend._view.phase='running'
    backend.chatChanged.emit()
    with patch('app.app_about.fetch_latest_release',return_value=release) as check, patch('app.app_about.QTimer.singleShot',side_effect=lambda delay,context,call:call()) as timer:
        about.startAutomaticChecks(); about.startAutomaticChecks()
        wait(lambda:not about.busy)
        timer.assert_called_once()
        check.assert_called_once()
    assert about._automatic.interval()==6*60*60*1000 and button.isVisible()
    about._automatic.stop()
    gate,started=threading.Event(),threading.Event()
    location=str(Path(os.environ['UMEKO_DATA_DIR'])/'downloaded.zip')
    def transfer(asset,directory,progress,cancelled):
        started.set();progress(50)
        assert gate.wait(5)
        return location
    with patch('app.app_about.download_asset',side_effect=transfer) as download:
        QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,button.mapToScene(button.boundingRect().center()).toPoint())
        wait(started.is_set)
        wait(lambda:about.download.get('progress')==50)
        assert not button.isEnabled() and backend.running and window.property('page')=='chat'
        about.downloadUpdate();download.assert_called_once()
        gate.set();wait(lambda:about.download.get('state')=='ready')
    with patch('app.app_about.QDesktopServices.openUrl',return_value=True) as opened:
        QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,button.mapToScene(button.boundingRect().center()).toPoint())
        assert Path(opened.call_args.args[0].toLocalFile())==Path(location).parent
    backend._view.phase='idle'
    backend.chatChanged.emit()
    assert not warnings,'\n'.join(warnings)
    print('AUTO_UPDATE_UI_OK',flush=True)
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
