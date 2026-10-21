"""Hover controls stay hidden at rest, copy the displayed message and show its time."""
import os
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['UMEKO_DATA_DIR']=tempfile.mkdtemp(prefix='umeko-message-actions-')
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
from PySide6.QtCore import Qt,QPointF,QMetaObject
from PySide6.QtTest import QTest
from main import create_application

app,engine,backend=create_application();window=engine.rootObjects()[0]
warnings=[];engine.warnings.connect(lambda errors:warnings.extend(e.toString() for e in errors))
def find(name):
    stack=[window.contentItem()]
    while stack:
        item=stack.pop()
        if item.objectName()==name:return item
        stack.extend(item.childItems())
    raise AssertionError(name)
try:
    backend._view.messages=[{'role':'user','text':'Hover and copy this message','timestamp':1792559520000,'error':False},{'role':'assistant','text':'A historical reply','timestamp':1792559580000,'error':False}]
    backend.chatChanged.emit();backend.transcriptChanged.emit();QTest.qWait(350)
    QTest.mouseMove(window,QPointF(50,40).toPoint());QTest.qWait(100)
    assert find('messageActions_0').property('opacity')==0
    bubble=find('messageBubble_0');QTest.mouseMove(window,bubble.mapToScene(bubble.boundingRect().center()).toPoint());QTest.qWait(100)
    assert find('messageActions_0').property('opacity')==1,'Hover did not expose actions'
    assert ':' in find('messageTime_0').property('text')
    button=find('copyMessage_0');QTest.mouseMove(window,button.mapToScene(button.boundingRect().center()).toPoint());QTest.qWait(50)
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,button.mapToScene(button.boundingRect().center()).toPoint());QTest.qWait(50)
    assert app.clipboard().text()=='Hover and copy this message'
    output=ROOT/'artifacts/screenshots/61-message-hover.png';output.parent.mkdir(parents=True,exist_ok=True);assert window.grabWindow().save(str(output))
    QTest.mouseMove(window,QPointF(50,40).toPoint());QTest.qWait(100)
    assert find('messageActions_0').property('opacity')==0
    assert not warnings,'\n'.join(warnings)
    print('MESSAGE_ACTIONS_UI_OK: hover time, click copy and hide on exit')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
