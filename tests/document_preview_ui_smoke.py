"""Local artifact preview needs no WebEngine: render, bounded fallback, close and session isolation."""
import os,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen');os.environ.setdefault('QT_QUICK_BACKEND','software')
from PySide6.QtCore import QCoreApplication,QEvent,QMetaObject,Qt,QPointF,QPoint,QTimer
from PySide6.QtTest import QTest
from main import create_application

with tempfile.TemporaryDirectory(prefix='umeko-document-ui-') as temporary:
    base=Path(temporary);os.environ['UMEKO_DATA_DIR']=str(base/'profile');os.environ['UMEKO_WEBVIEW_COMPONENT_DIR']=str(base/'missing-components')
    markdown=base/'Readme.md';markdown.write_text('# 交付物预览\n\n**Markdown 渲染**\n\n| 功能 | 状态 |\n| --- | --- |\n| 文档预览 | 完成 |\n\n![No network](http://127.0.0.1:1/never-fetch.png)\n',encoding='utf-8')
    code=base/'example.py';code.write_text('def hello(name):\n    # 用户产物\n    return f"Hello, {name}"\n',encoding='utf-8')
    large=base/'large.py'
    with large.open('wb') as stream:stream.write(b'print("hello")\n'*30000);stream.truncate(512*1024*1024)
    app,engine,controller=create_application();window=engine.rootObjects()[0];warnings=[];engine.warnings.connect(lambda es:warnings.extend(str(e) for e in es))
    assert not controller.webviewAvailable
    def find(name):
        pending=[window.contentItem()]
        while pending:
            item=pending.pop()
            if item.objectName()==name:return item
            if item.objectName()!='webSurfaceLoader':pending.extend(item.childItems())
        raise AssertionError(name)
    def wait(check):
        for _ in range(400):
            QTest.qWait(25)
            if check():return
        raise AssertionError('Timeout: '+str(warnings))
    def click(name):
        item=find(name);QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(item.boundingRect().center()).toPoint());QTest.qWait(150)
    def submit(path,kind):
        controller._handle_pi_event(controller._view,{'type':'tool','id':'document-'+path.name,'name':'submit_to_chatbox','state':'done','args':{'items':[{'path':str(path)}]},'media':[{'path':str(path),'title':path.name,'kind':kind}]})
    pane=find('webPane');web=find('webSurfaceLoader');loader=find('documentSurfaceLoader')
    submit(markdown,'markdown');wait(lambda:controller.documentPreview.state.get('html') and not pane.property('moving'))
    assert pane.property('mode')=='document' and web.property('item') is None and loader.property('item') is not None
    assert '<img' not in controller.documentPreview.state['html']
    assert 'Markdown' in find('documentPreviewText').property('text')
    output=ROOT/'artifacts/screenshots';output.mkdir(parents=True,exist_ok=True);assert window.grabWindow().save(str(output/'document-markdown.png'))
    # All settings entry points close the entire pane and unload its content.
    for entry in ('button','shortcut','direct'):
        wait(lambda:controller.documentPreview.state.get('html') and not pane.property('moving'))
        before=pane.width()
        if entry=='button':click('settingsButton')
        elif entry=='shortcut':QTest.keyClick(window,Qt.Key_Comma,Qt.ControlModifier)
        else:window.setProperty('page','settings')
        assert window.property('page')=='settings'
        assert not pane.property('opened') and not pane.isVisible() and not find('webPaneResizeHandle').isVisible()
        assert controller.documentPreview.state=={}
        wait(lambda:loader.property('item') is None and not pane.property('moving'))
        assert pane.width()<0.5 and find('settingsPage').width()==find('mainArea').width()
        if entry=='button':assert window.grabWindow().save(str(output/'settings-preview-dismissed.png'))
        QTest.keyClick(window,Qt.Key_Escape)
        assert window.property('page')=='chat' and not pane.property('opened') and not pane.isVisible()
        QTest.qWait(150)  # Let the full-width chat delegates finish their layout.
        click('openChatbox_document-Readme.md_0')
        wait(lambda:controller.documentPreview.state.get('html') and not pane.property('moving'))
        assert abs(pane.width()-before)<0.1
    submit(code,'code');wait(lambda:controller.documentPreview.state.get('kind')=='code' and not controller.documentPreview.state.get('busy'))
    wait(lambda:find('documentPreviewText').property('syntaxColors').property('status')=='highlighted')
    assert window.grabWindow().save(str(output/'document-code.png'))
    click('copyDocumentPreviewButton');assert app.clipboard().text()==code.read_text(encoding='utf-8')
    # Drag follows the pointer and remains bounded while resizing an actual document.
    handle=find('webPaneResizeHandle');start=handle.mapToScene(QPointF(handle.width()/2,100)).toPoint();before=pane.width()
    QTest.mousePress(window,Qt.LeftButton,Qt.NoModifier,start)
    for dx in [25,50,80]:QTest.mouseMove(window,start+QPoint(dx,0));QTest.qWait(40)
    assert handle.property('pressed') and pane.width()<before-65
    QTest.mouseRelease(window,Qt.LeftButton,Qt.NoModifier,start+QPoint(80,0));QTest.qWait(100)
    assert abs(find('chatPage').width()+pane.width()-find('mainArea').width())<0.1
    submit(large,'code');wait(lambda:controller.documentPreview.state.get('truncated'))
    state=controller.documentPreview.state;assert len(state['text'])<=48002 and not state['highlight']
    assert find('documentPreviewText').property('syntaxColors').property('status')!='highlighted'
    ticks=[];timer=QTimer();timer.timeout.connect(lambda:ticks.append(1));timer.start(10);QTest.qWait(150);timer.stop();assert len(ticks)>3
    submit(large,'code');submit(markdown,'markdown');wait(lambda:controller.documentPreview.state.get('kind')=='markdown' and not controller.documentPreview.state.get('busy'))
    click('closeWebPaneButton');wait(lambda:not pane.property('moving'));assert controller.documentPreview.state=={} and loader.property('item') is None
    click('openChatbox_document-Readme.md_0');wait(lambda:controller.documentPreview.state.get('html') and not pane.property('moving'))
    submit(base/'missing.txt','text');wait(lambda:controller.documentPreview.state.get('error'))
    controller.newSession();wait(lambda:not pane.property('opened'));assert controller.documentPreview.state=={}
    assert not [w for w in warnings if 'DocumentSurface' in w or 'WebPane' in w or 'Main.qml' in w],warnings
    controller.close();engine.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    print('DOCUMENT_UI_OK: Markdown, highlighted code, no WebEngine, settings dismiss/unload, no automatic reopen, retained width, drag resize, bounded 512MiB preview, event-loop responsiveness, latest request, close/reopen, missing file, session isolation')
