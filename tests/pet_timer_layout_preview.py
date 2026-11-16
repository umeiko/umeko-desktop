"""Composite of actual offscreen Qt tool-window captures, not a Windows screenshot.

Production window types and geometry remain unchanged. The individual grabs are
placed at their actual global coordinates on a neutral preview canvas.
"""
import json, os, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
tmp=tempfile.TemporaryDirectory(prefix='umeko-timer-layout-')
os.environ.update(UMEKO_DATA_DIR=tmp.name+'/profile',PI_CODING_AGENT_DIR=tmp.name+'/agent',QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',UMEKO_LANGUAGE='zh')
from PySide6.QtCore import QObject, QRect
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtQml import QQmlEngine,QQmlExpression
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QSystemTrayIcon
QSystemTrayIcon.show=lambda *args:None
from main import create_application
from app.pi_sessions import SessionState
app,engine,b=create_application();main=engine.rootObjects()[0];pet=b.desktopPlugins.pet
out=ROOT/'build/pet-timer-ui';out.mkdir(parents=True,exist_ok=True)
def js(obj,code):
    exp=QQmlExpression(QQmlEngine.contextForObject(obj),obj,code);result=exp.evaluate()[0]
    assert not exp.hasError(),exp.error().toString()
    return result
try:
    pet.ui('show',{});QTest.qWait(500)
    window=main.findChild(QObject,'desktopPetWindow')
    composer=window.findChild(QObject,'desktopPetTaskComposer')
    prompt=window.findChild(QObject,'petTimerPrompt')
    field=window.findChild(QObject,'desktopPetTaskInput')
    workspace=b.store.directory/'workspace';workspace.mkdir(exist_ok=True)
    file=Path(tmp.name)/'ordinary.jsonl';file.write_text(json.dumps({'type':'session','version':3,'id':'ordinary','timestamp':'2026-11-15T00:00:00Z','cwd':str(workspace)})+'\n')
    record=SessionState(id='ordinary',file=str(file),title='构建检查',workspace='')
    b._pool.touch(record);b._sessions.append({'id':record.id,'file':record.file,'title':record.title,'workspace':''})
    js(window,'openTaskComposer()');QTest.qWait(500)
    field.setProperty('text','/定时任务 每隔 10 分钟检查构建');js(composer,'submit()')
    pet.taskSchedule.answer('ordinary')
    def capture(name):
        QTest.qWait(500)
        capsule = js(composer,'contentItem.Window.window')
        surfaces = [window, capsule, prompt]
        bounds = QRect()
        for surface in surfaces: bounds = bounds.united(surface.geometry())
        bounds.adjust(-12,-12,12,12)
        image = QImage(bounds.size(), QImage.Format_ARGB32)
        image.fill(QColor('#f4f6fb'))
        painter = QPainter(image)
        for surface in surfaces: painter.drawImage(surface.position()-bounds.topLeft(), surface.grabWindow())
        painter.end()
        assert image.save(str(out/name))
    capture('08-question-layout-preview.png')
    pet.taskSchedule.answer('构建检查');pet.taskSchedule.answer('main')
    QTest.qWait(500)
    assert pet.taskSchedule.preview,pet.taskSchedule.error
    capture('09-confirm-layout-preview.png')
    print('Actual Qt native-window capture composites saved; no task created:',out)
finally:
    b.close()
    import shiboken6
    shiboken6.delete(engine);app.processEvents();tmp.cleanup()
