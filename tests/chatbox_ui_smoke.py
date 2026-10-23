"""Real Pi delivery, QML preview, file actions and persisted media replay."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('UMEKO_LANGUAGE','zh')
os.environ['UMEKO_DATA_DIR']=tempfile.mkdtemp(prefix='umeko-chatbox-ui-')
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
from PySide6.QtCore import QPoint, QPointF, Qt, QMetaObject, QObject
from PySide6.QtGui import QImage, QPainter, QColor, QWheelEvent
from PySide6.QtTest import QTest
from app.integration import Completion
from app.transcripts import preview
from main import create_application

app,engine,backend=create_application()
window=engine.rootObjects()[0]
warnings=[]
engine.warnings.connect(lambda errors:warnings.extend(e.toString() for e in errors))
directory=backend.store.directory
image=directory/'展示 # sample.png'; report=directory/'report.txt'
pixels=QImage(720,320,QImage.Format_RGB32);pixels.fill(QColor('#e8efff'))
painter=QPainter(pixels);painter.setPen(QColor('#315b9e'));font=painter.font();font.setPixelSize(30);painter.setFont(font)
painter.drawText(pixels.rect(),Qt.AlignCenter,'Umeko · media delivery');painter.end();assert pixels.save(str(image))
report.write_text('Synthetic report fixture; never executed',encoding='utf-8')
backend.store.data.update(selectedProvider='fixture',selectedModel='fixture',providers=[{'id':'fixture','name':'Fixture','api':'internal','baseUrl':'','models':[{'upstream':'fixture','alias':'fixture'}]}])
backend.store.data['agent']['agentDir']=str(directory/'agent')
backend.store.data['agent']['autoCompaction']=False

class Fixture:
    def complete(self,_model,messages,*_):
        if messages[-1]['role']=='tool':return Completion('图片和报告已放在聊天框中。')
        return Completion(tool_calls=[{'id':'delivery','name':'submit_to_chatbox','arguments':{'items':[
            {'path':str(image),'title':'预览图片','caption':'图片无需模型启用视觉即可显示。'},
            {'path':str(report),'title':'测试报告','caption':'展开可查看路径并在文件夹中定位。'}]}}])

backend.gateway.adapter=Fixture()
backend.changed.emit()

def find(name):
    stack=[window.contentItem()]
    while stack:
        item=stack.pop()
        if item.objectName()==name:return item
        stack.extend(item.childItems())
    return None

def wait(predicate):
    for _ in range(1500):
        QTest.qWait(10)
        if predicate():return
    raise AssertionError('Timed out; '+backend.toolStatus+'; '+str(warnings))

def click(name):
    QTest.qWait(200)
    item=find(name);assert item,name
    point=item.mapToScene(item.boundingRect().center()).toPoint()
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,point);QTest.qWait(100)

def context(name):
    QTest.qWait(150)
    item=find(name); assert item,name
    QTest.mouseClick(window,Qt.RightButton,Qt.NoModifier,item.mapToScene(item.boundingRect().center()).toPoint());QTest.qWait(100)
    from PySide6.QtCore import QObject
    menu=find('copyChatboxFile_delivery_1').parent()
    assert menu and menu.property('desiredOpen') and menu.property('animating'), 'Context menu has no PID opening animation'
    assert .9 < menu.property('scale') < 1.04
    for action in ('attachChatbox_', 'copyChatboxFile_', 'copyChatbox_', 'revealChatbox_'):
        name=action+'delivery_1'
        assert find(name).property('glyph'), name+' has no icon'
        label=find(name+'Label');assert label, name
        assert label.width() >= label.implicitWidth() - 1, (name, label.width(), label.implicitWidth())

try:
    assert backend.send('展示图片，并把报告文件给我。')
    wait(lambda:not backend.busy)
    wait(lambda:find('chatboxImage_delivery_0') is not None and find('chatboxImage_delivery_0').property('loaded'))
    assert find('chatboxCard_delivery_0').isVisible()
    assert find('chatboxCard_delivery_1').isVisible()
    assert find('chatboxCard_delivery_1').height() <= 36
    header=find('openChatbox_delivery_1')
    QTest.mouseMove(window,header.mapToScene(QPointF(50,17)).toPoint());QTest.qWait(750)
    assert header.property('interactionHovered'),'Selection overlay swallowed file hover'
    assert find('chatPointerArea').property('cursorShape')==Qt.PointingHandCursor
    tip=find('hoverTipContent_chatboxTip_delivery_1')
    assert tip and tip.isVisible() and 96<=tip.width()<=336
    assert window.grabWindow().save(str(ROOT/'artifacts/screenshots/63-file-hover.png'))
    with patch('app.controller.QDesktopServices.openUrl',return_value=True) as opened:
        click('openChatbox_delivery_1')
        assert Path(opened.call_args.args[0].toLocalFile()).samefile(report)
    with patch('app.controller.subprocess.Popen') as launched,patch('app.controller.QDesktopServices.openUrl',return_value=True) as opened:
        assert find('toggleChatbox_delivery_1') is None, 'File dropdown should be removed'
        context('openChatbox_delivery_1')
        click('revealChatbox_delivery_1')
        assert launched.called if sys.platform in ('win32','darwin') else opened.called
    click('previewChatbox_delivery_0')
    viewer=window.findChild(QObject,'imagePreview');assert viewer.property('visible')
    assert not tip.isVisible(),'A chat tooltip should not float above the image preview'
    center=QPoint(window.width()//2,window.height()//2)
    event=QWheelEvent(QPointF(center),QPointF(window.mapToGlobal(center)),QPoint(),QPoint(0,120),Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
    app.sendEvent(window,event);QTest.qWait(80)
    assert viewer.property('zoom')>1,'Image preview wheel zoom failed'
    QTest.mousePress(window,Qt.LeftButton,Qt.NoModifier,center)
    QTest.mouseMove(window,center+QPoint(70,45),30)
    QTest.mouseRelease(window,Qt.LeftButton,Qt.NoModifier,center+QPoint(70,45));QTest.qWait(100)
    assert viewer.property('visible') and viewer.property('panX')>40,'Dragging should pan without dismissing'
    assert window.grabWindow().save(str(ROOT/'artifacts/screenshots/image-preview-zoom-pan.png'))
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,center);QTest.qWait(150)
    assert not viewer.property('visible'),'A stationary click should close the preview'
    click('previewChatbox_delivery_0')
    QTest.mouseClick(window,Qt.RightButton,Qt.NoModifier,center);QTest.qWait(150)
    click('attachChatbox_imagePreview');QTest.qWait(180)
    assert not viewer.property('visible')
    assert any(item['kind']=='image' and Path(item['path']).samefile(image) for item in backend.attachments)
    backend.removeAttachment(backend.attachments[0]['id'])
    context('openChatbox_delivery_1');click('attachChatbox_delivery_1');QTest.qWait(120)
    assert any(Path(item['path']).samefile(report) for item in backend.attachments)
    assert find('promptInput').hasActiveFocus(),'Reattached file should focus the composer'
    backend.removeAttachment(backend.attachments[0]['id'])
    context('openChatbox_delivery_1');click('copyChatboxFile_delivery_1')
    assert Path(app.clipboard().mimeData().urls()[0].toLocalFile()).samefile(report)
    context('openChatbox_delivery_1')
    QTest.qWait(350)
    assert window.grabWindow().save(str(ROOT/'artifacts/screenshots/62-context-menu.png'))
    click('copyChatbox_delivery_1');assert Path(app.clipboard().text()).samefile(report)
    selection=find('chatSelection');QMetaObject.invokeMethod(selection,'selectAll');QMetaObject.invokeMethod(selection,'copy')
    assert '测试报告' in app.clipboard().text() and '模型启用视觉' in app.clipboard().text()
    QMetaObject.invokeMethod(selection,'clear')
    output=ROOT/'artifacts/screenshots/60-chatbox-media.png';output.parent.mkdir(parents=True,exist_ok=True)
    QTest.qWait(200);assert window.grabWindow().save(str(output))
    original=Path(backend._view.file).read_bytes()
    backend._view.messages,backend._view.tree=preview(backend._view.file)
    backend.chatChanged.emit();backend.transcriptChanged.emit();backend.viewChanged.emit()
    wait(lambda:find('chatboxImage_delivery_0') is not None and find('chatboxImage_delivery_0').property('loaded'))
    assert Path(backend._view.file).read_bytes()==original
    assert len([s for r in backend.displayMessages for s in r.get('activity',[]) if s['kind']=='media'])==1
    for language in ('zh','en'):
        backend.setLanguage(language)
        for scale in (.5,1,2):
            backend.setFontScale(scale);QTest.qWait(250)
            context('openChatbox_delivery_1')
            QTest.keyClick(window,Qt.Key_Escape);QTest.qWait(80)
    assert not warnings,'\n'.join(warnings)
    print('CHATBOX_UI_OK: real Pi delivery, compact files, context attach/reveal/copy, image zoom/pan/click-close, selection and native-history replay')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
