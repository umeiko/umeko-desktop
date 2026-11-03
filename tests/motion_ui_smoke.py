"""Popup PID behavior and independent render-thread sidebar selection."""
import os
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.setdefault('UMEKO_LANGUAGE','zh')
os.environ['UMEKO_DATA_DIR']=tempfile.mkdtemp(prefix='umeko-motion-ui-')
os.environ.setdefault('QT_QPA_PLATFORM','offscreen');os.environ.setdefault('QT_QUICK_BACKEND','software')
from PySide6.QtCore import Qt,QPoint,QObject
from PySide6.QtQml import QQmlEngine, QQmlExpression
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
def click(item):QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(item.boundingRect().center()).toPoint())
def settled(popup):
    for _ in range(200):
        QTest.qWait(20)
        if not popup.property('animating'):return
    raise AssertionError('PID failed to settle')
def selection_settled():
    for _ in range(300):
        QTest.qWait(20)
        if not animator.property('running'): return
    raise AssertionError('Sidebar PID failed to settle')
def evaluate(item, expression):
    query=QQmlExpression(QQmlEngine.contextForObject(item), item, expression)
    value=query.evaluate()[0]
    assert not query.hasError(),query.error().toString()
    return value.toVariant() if hasattr(value,'toVariant') else value
try:
    backend.store.data.update(selectedProvider='fixture',selectedModel='fixture',providers=[{'id':'fixture','name':'Fixture','api':'openai','baseUrl':'http://127.0.0.1:1/v1','models':[{'upstream':'fixture','alias':'fixture'}]}]);backend.changed.emit();QTest.qWait(150)
    button=find('modelSelector');popup=window.findChild(QObject,'modelPopup');click(button);QTest.qWait(30)
    assert popup.property('desiredOpen') and popup.property('animating')
    assert button.width()<popup.property('width')<365,'Popup did not grow from its button'
    click(button);QTest.qWait(30);assert not popup.property('desiredOpen'),'Second click reopened popup'
    before=popup.property('width');click(button);QTest.qWait(20)
    assert popup.property('desiredOpen') and abs(popup.property('width')-before)<80,'Rapid retarget reset the animation'
    settled(popup);assert popup.property('visible') and abs(popup.property('width')-365)<.2
    click(button);QTest.qWait(950);assert not popup.property('visible')
    click(button);QTest.qWait(40);QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,QPoint(400,90));QTest.qWait(950);assert not popup.property('visible')
    backend._sessions=[{'id':str(i),'title':f'Fixture {i}','workspace':''} for i in range(5)]
    backend._view.id='0';backend.chatChanged.emit();QTest.qWait(1500)
    highlight=find('sidebarHighlight')
    motion=find('sidebarPidMotion')
    animator=window.findChild(QObject,'sidebarSelectionAnimator')
    assert [motion.property(key) for key in ('kp','ki','kd')]==[280,60,20]
    backend._view.id='4';backend.chatChanged.emit();QTest.qWait(90)
    state=evaluate(motion,'currentState()')
    path=evaluate(motion,'trajectory')
    assert abs(state[1])>1, 'PID lost its velocity'
    positions=[row[0] for row in path['samples']]
    direction=1 if path['destination']>path['start'] else -1
    assert max(direction*(position-path['destination']) for position in positions)>1, 'PID lost its damped overshoot'
    # Retarget while moving: retain position, velocity and integral, including
    # the brief motion in the old direction before reversing.
    backend._view.id='2';backend.chatChanged.emit();QTest.qWait(5)
    retarget=evaluate(motion,'trajectory.samples[0]')
    assert abs(retarget[0]-state[0])<20, (state,retarget)
    assert state[1]*retarget[1]>0 and abs(retarget[1])>1, (state,retarget)
    assert state[2]*retarget[2]>0, (state,retarget)
    selection_settled()
    assert abs(find('sidebarHighlight').mapToScene(find('sidebarHighlight').boundingRect().topLeft()).y()-find('sidebarRow_2').mapToScene(find('sidebarRow_2').boundingRect().topLeft()).y())<.2
    backend._view.id='4';backend.chatChanged.emit();selection_settled()
    assert abs(find('sidebarHighlight').mapToScene(find('sidebarHighlight').boundingRect().topLeft()).y()-find('sidebarRow_4').mapToScene(find('sidebarRow_4').boundingRect().topLeft()).y())<.2
    backend._view.id='2';backend.chatChanged.emit();selection_settled()
    assert abs(find('sidebarHighlight').mapToScene(find('sidebarHighlight').boundingRect().topLeft()).y()-find('sidebarRow_2').mapToScene(find('sidebarRow_2').boundingRect().topLeft()).y())<.2
    # The PID trajectory runs independently of data attachment.
    from unittest.mock import patch
    calls=[]
    def loaded(session_id):
        calls.append((session_id,animator.property('running')))
        backend._view.id=session_id;backend.chatChanged.emit()
    with patch.object(backend,'openSession',side_effect=loaded):
        click(find('sidebarRow_4'))
        for _ in range(100):
            QTest.qWait(5)
            if calls:break
        assert calls and calls[0][0]=='4' and calls[0][1],calls
        calls.clear()
        click(find('sidebarRow_1'))
        click(find('sidebarRow_0'))
        for _ in range(100):
            QTest.qWait(5)
            if calls:break
        assert [row[0] for row in calls]==['0'],calls
        selection_settled()
        assert abs(find('sidebarHighlight').mapToScene(find('sidebarHighlight').boundingRect().topLeft()).y()-find('sidebarRow_0').mapToScene(find('sidebarRow_0').boundingRect().topLeft()).y())<.2
    assert not warnings,'\n'.join(warnings)
    print('MOTION_UI_OK: original PID gains, damped overshoot, continuous velocity/integral on retarget, stable selection, latest-click wins and independent content attachment')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
