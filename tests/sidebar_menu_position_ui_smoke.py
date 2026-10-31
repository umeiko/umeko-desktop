"""Cold context menus must keep the click anchor as their layout settles."""
import os
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['UMEKO_DATA_DIR']=tempfile.mkdtemp(prefix='umeko-sidebar-menu-')
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
os.environ.setdefault('UMEKO_LANGUAGE','zh')
from PySide6.QtCore import QObject,Qt,QPoint
from PySide6.QtTest import QTest
from PySide6.QtQml import QQmlExpression,QQmlEngine
from shiboken6 import delete
from main import create_application

app,engine,backend=create_application();window=engine.rootObjects()[0]
warnings=[];engine.warnings.connect(lambda errors:warnings.extend(e.toString() for e in errors))
def find(name):
    pending=[window.contentItem()]
    while pending:
        item=pending.pop()
        if item.objectName()==name:return item
        pending.extend(item.childItems())
    return None
def wait(predicate,label):
    for _ in range(400):
        QTest.qWait(10)
        if predicate():return
    raise AssertionError(label)
def close(menu):
    menu.close();wait(lambda:not menu.property('visible'),'menu closed')
    QTest.qWait(25)
def verify(menu,point,exact=True):
    wait(lambda:menu.property('visible'),'menu opened')
    QTest.qWait(140)
    x,y,w,h=[float(menu.property(key)) for key in ('x','y','width','height')]
    assert x>=9 and y>=9,(x,y,w,h)
    assert x+w<=window.width()-9 and y+h<=window.height()-9,(x,y,w,h)
    if exact:
        assert abs(x-point.x())<2 and abs(y-point.y())<2, f'menu at {(x,y)}, clicked {(point.x(),point.y())}, size {(w,h)}'
    else:
        assert x<=point.x()+1 and point.x()-x<=w+12,(x,point.x(),w)
        assert y<=point.y()+1 and point.y()-y<=h+12,(y,point.y(),h)
    return x,y
def right_click(name):
    item=find(name);assert item,name
    point=item.mapToScene(item.boundingRect().center()).toPoint()
    QTest.mouseClick(window,Qt.RightButton,Qt.NoModifier,point)
    return point
def evaluate(code):
    expression=QQmlExpression(QQmlEngine.contextForObject(window),window,code)
    result=expression.evaluate()
    assert not expression.hasError(),expression.error().toString()
    return result[0]
try:
    QTest.qWait(650)
    workspace=str(Path(os.environ['UMEKO_DATA_DIR'])/'workspace');Path(workspace).mkdir()
    project=backend._ensure_project(workspace)
    backend._sessions=[{'id':f'menu-session-{i}','title':f'Context menu fixture {i:02d}','file':'','workspace':workspace} for i in range(30)]
    backend._activate(backend._new_view(workspace))
    wait(lambda:find('sidebarRow_menu-session-0') is not None,'session row')
    session=window.findChild(QObject,'sessionContextMenu');project_menu=window.findChild(QObject,'projectContextMenu')
    assert session and project_menu
    initial=session.property('implicitHeight')
    point=right_click('sidebarRow_menu-session-0');first=verify(session,point);close(session)
    point=right_click('sidebarRow_menu-session-0');assert verify(session,point)==first;close(session)
    point=right_click('sidebarRow_'+project['id']);verify(project_menu,point);close(project_menu)
    # Repositioning must also survive larger text and translated action labels.
    backend.setFontScale(2);backend.setLanguage('en');QTest.qWait(100)
    point=right_click('sidebarRow_menu-session-0');verify(session,point,False);close(session)
    backend.setFontScale(1);backend.setLanguage('zh');QTest.qWait(100)
    find('projectList').positionViewAtEnd();QTest.qWait(100)
    point=right_click('sidebarRow_menu-session-29');verify(session,point,False);close(session)
    window.setWidth(1100);window.setHeight(720);QTest.qWait(100)
    evaluate('sidebarMenus.openFor({kind:"session",id:"edge",title:"Edge"},Qt.point(1085,705))')
    verify(session,QPoint(1085,705),False);close(session)
    assert not warnings,warnings
    print(f'sidebar_menu_position_ui_smoke: PASS (cold implicit height {initial}; cold/reopen/project/scroll/font/language/window edges)')
finally:
    backend.close();delete(window);delete(engine);app.processEvents()
