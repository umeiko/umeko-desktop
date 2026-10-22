"""Pointer regression for native word/paragraph boundaries and release behavior."""
import os
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('UMEKO_LANGUAGE','zh')
os.environ['UMEKO_DATA_DIR']=tempfile.mkdtemp(prefix='umeko-selection-click-')
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
from PySide6.QtCore import Qt,QPointF,QRectF,QMetaObject,Q_ARG,Q_RETURN_ARG
from PySide6.QtTest import QTest
from main import create_application

app,engine,backend=create_application();window=engine.rootObjects()[0]
warnings=[];engine.warnings.connect(lambda errors:warnings.extend(e.toString() for e in errors))

def find(name):
    stack=[window.contentItem()]
    while stack:
        item=stack.pop()
        if item.objectName()==name and item.isVisible() and (not name.startswith('selectText_') or item.property('text')):return item
        stack.extend(item.childItems())
    raise AssertionError(name)

def at(editor,offset):
    rect=QMetaObject.invokeMethod(editor,'positionToRectangle',Qt.DirectConnection,Q_RETURN_ARG(QRectF),Q_ARG(int,offset))
    return editor.mapToScene(QPointF(rect.x()+2,rect.y()+rect.height()/2)).toPoint()

def copied(selection):
    QMetaObject.invokeMethod(selection,'copy')
    return app.clipboard().text()

try:
    paragraph='alpha beta gamma '+('a wrapped sentence ' * 14)+'end'
    chinese='第二段包含中文𠮷字符，三击应选中整个段落。'
    backend._view.messages=[{'role':'assistant','text':paragraph+'\n\n'+chinese,'error':False}]
    backend.chatChanged.emit();backend.transcriptChanged.emit();QTest.qWait(350)
    view=find('conversation');QMetaObject.invokeMethod(view,'beginBrowsing');QMetaObject.invokeMethod(view,'positionViewAtBeginning');QTest.qWait(100)
    selection=find('chatSelection');editor=find('selectText_0_0');point=at(editor,8)
    QTest.mouseDClick(window,Qt.LeftButton,Qt.NoModifier,point)
    QTest.mouseRelease(window,Qt.LeftButton,Qt.NoModifier,point)
    QTest.qWait(30)
    assert copied(selection)=='beta',('double click collapsed or chose wrong word',copied(selection))
    QTest.mouseClick(window,Qt.RightButton,Qt.NoModifier,point);QTest.qWait(150)
    assert copied(selection)=='beta','Right-click changed the existing selection'
    copy_action=find('copySelectedText');assert copy_action.parent().property('visible')
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,copy_action.mapToScene(copy_action.boundingRect().center()).toPoint());QTest.qWait(50)
    assert app.clipboard().text()=='beta'
    assert selection.property('hasSelection'),'Copy should preserve the text selection'
    # Reset synthetic click timing after the menu interaction, then select again.
    QMetaObject.invokeMethod(selection,'clear')
    QTest.mouseDClick(window,Qt.LeftButton,Qt.NoModifier,point);QTest.mouseRelease(window,Qt.LeftButton,Qt.NoModifier,point)
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,point);QTest.qWait(30)
    assert copied(selection)==paragraph,('triple click must include wrapped paragraph',copied(selection))
    QMetaObject.invokeMethod(selection,'clear')
    stack=[window.contentItem()];editor=None
    while stack:
        item=stack.pop()
        if item.objectName().startswith('selectText_') and item.isVisible() and chinese in str(item.property('text')):
            editor=item;break
        stack.extend(item.childItems())
    assert editor is not None,'Visible Chinese paragraph'
    plain=QMetaObject.invokeMethod(editor,'getText',Qt.DirectConnection,Q_RETURN_ARG(str),Q_ARG(int,0),Q_ARG(int,editor.property('length')))
    point=at(editor,plain.index(chinese)+8)
    QTest.mouseDClick(window,Qt.LeftButton,Qt.NoModifier,point);QTest.mouseRelease(window,Qt.LeftButton,Qt.NoModifier,point)
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,point);QTest.qWait(30)
    assert copied(selection)==chinese,('Unicode paragraph selection',copied(selection))
    QMetaObject.invokeMethod(selection,'selectAll');expected=copied(selection)
    QTest.mouseClick(window,Qt.RightButton,Qt.NoModifier,point);QTest.qWait(100)
    assert copied(selection)==expected,'Right-click collapsed a multi-block selection'
    action=find('copySelectedText');QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,action.mapToScene(action.boundingRect().center()).toPoint());QTest.qWait(50)
    assert app.clipboard().text()==expected and paragraph in expected and chinese in expected
    assert not warnings,'\n'.join(warnings)
    print('SELECTION_CLICK_UI_OK: double-click word survives release; triple-click wrapped and Unicode paragraphs')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
