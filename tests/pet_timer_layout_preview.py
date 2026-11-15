"""One-surface Qt layout preview; not a native desktop/multi-window screenshot.

Actual components use Popup.Item in this offscreen-only preview so grabWindow
can capture all surfaces. Production popupType remains Window.
"""
import json, os, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
tmp=tempfile.TemporaryDirectory(prefix='umeko-timer-layout-')
os.environ.update(UMEKO_DATA_DIR=tmp.name+'/profile',PI_CODING_AGENT_DIR=tmp.name+'/agent',QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',UMEKO_LANGUAGE='zh')
from PySide6.QtCore import QObject
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
    window.setProperty('width',400);window.setProperty('height',480)
    window.setProperty('x',0);window.setProperty('y',0)
    window.setProperty('color','#f4f6fb')
    js(composer,'popupType = Popup.Item');js(prompt,'popupType = Popup.Item')
    workspace=b.store.directory/'workspace';workspace.mkdir(exist_ok=True)
    file=Path(tmp.name)/'ordinary.jsonl';file.write_text(json.dumps({'type':'session','version':3,'id':'ordinary','timestamp':'2026-11-15T00:00:00Z','cwd':str(workspace)})+'\n')
    record=SessionState(id='ordinary',file=str(file),title='构建检查',workspace='')
    b._pool.touch(record);b._sessions.append({'id':record.id,'file':record.file,'title':record.title,'workspace':''})
    js(window,'openTaskComposer()');QTest.qWait(500)
    field.setProperty('text','/定时任务 每隔 10 分钟检查构建');js(composer,'submit()')
    pet.taskSchedule.answer('ordinary')
    # Fixed positions on a single test canvas: not a native positioning test.
    composer.setProperty('x',20);composer.setProperty('y',250)
    js(prompt,'y = Qt.binding(function() { return -height - 6 })')
    QTest.qWait(500)
    assert window.grabWindow().save(str(out/'08-question-layout-preview.png'))
    pet.taskSchedule.answer('构建检查');pet.taskSchedule.answer('main')
    QTest.qWait(500)
    assert pet.taskSchedule.preview,pet.taskSchedule.error
    assert window.grabWindow().save(str(out/'09-confirm-layout-preview.png'))
    print('Actual Qt single-surface layout previews saved; no task created:',out)
finally:
    b.close()
    import shiboken6
    shiboken6.delete(engine);app.processEvents();tmp.cleanup()
