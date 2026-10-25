"""Exercise actual Qt WebView via live Agent delivery events and a local HTTP server."""
import hashlib,json,os,sys,tempfile,threading,zipfile
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QUICK_BACKEND','software');os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QMetaObject,Qt,QCoreApplication,QEvent,QObject,Slot,QUrl,QPointF,QPoint
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QTest
from app.storage import Store
from main import create_application

class Handler(BaseHTTPRequestHandler):
    counts={}
    def do_GET(self):
        self.counts[self.path]=self.counts.get(self.path,0)+1
        name='Second' if self.path.startswith('/second') else 'Preview'
        raw=('<!doctype html><meta charset="utf-8"><title>'+name+'</title><style>body{font:18px sans-serif;padding:35px;background:#fcfcfa;color:#29352f}a{color:#355d49}</style><h1>'+name+'</h1><p>Umeko WebView</p><a href="/second">Second page</a><p><input placeholder="输入中文测试"></p>').encode()
        self.send_response(200);self.send_header('Content-Type','text/html;charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def log_message(self,*args): pass
    def handle(self):
        try: super().handle()
        except (BrokenPipeError,ConnectionResetError): pass

with tempfile.TemporaryDirectory(prefix='umeko-webview-ui-') as temp:
    base=Path(temp);spec=json.loads((ROOT/'runtime/webview-component.json').read_text());component=base/'components';component.mkdir()
    archive=ROOT.parent/'umeko-desktop-cpp/release-assets/webview'/spec['filename']
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==spec['sha256']
    folder=spec['id']+'-'+spec['sha256'][:16];destination=component/folder;destination.mkdir()
    with zipfile.ZipFile(archive) as stream: stream.extractall(destination)
    (destination/'libexec/QtWebEngineProcess').chmod(0o755)
    (component/'active.json').write_text(json.dumps({'id':spec['id'],'sha256':spec['sha256'],'directory':folder}))
    os.environ['UMEKO_DATA_DIR']=str(base/'profile');os.environ['UMEKO_WEBVIEW_COMPONENT_DIR']=str(component)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    url='http://127.0.0.1:'+str(server.server_port)+'/preview'
    app,engine,controller=create_application();warnings=[];engine.warnings.connect(lambda es:warnings.extend(str(e) for e in es));window=engine.rootObjects()[0]
    assert controller.webviewAvailable
    def find(name):
        pending=[window.contentItem()]
        while pending:
            item=pending.pop()
            if item.objectName()==name:return item
            if item.objectName()!='webSurfaceLoader': pending.extend(item.childItems())
        raise AssertionError(name)
    def wait(check):
        for _ in range(600):
            QTest.qWait(25)
            if check(): return
        raise AssertionError('Timeout: '+str(warnings))
    def click(name, button=Qt.LeftButton):
        item=find(name)
        QTest.mouseClick(window,button,Qt.NoModifier,item.mapToScene(item.boundingRect().center()).toPoint())
        QTest.qWait(200)
    pane=find('webPane');loader=find('webSurfaceLoader')
    assert not pane.property('opened') and loader.property('item') is None
    sidebar=find('sidebar');sidebarMotion=find('sidebarWidthMotion');expanded=sidebar.width()
    assert QMetaObject.invokeMethod(window,'toggleSidebar',Qt.DirectConnection)
    QTest.qWait(100);assert sidebarMotion.property('moving') and 0<sidebar.width()<expanded
    wait(lambda:not sidebarMotion.property('moving'));assert sidebar.width()==0 and not sidebar.isVisible()
    assert QMetaObject.invokeMethod(window,'toggleSidebar',Qt.DirectConnection)
    QTest.qWait(100);assert sidebarMotion.property('moving') and 0<sidebar.width()<expanded
    wait(lambda:not sidebarMotion.property('moving'));assert abs(sidebar.width()-expanded)<0.1
    def submit(address):
        controller._handle_pi_event(controller._view,{'type':'tool','id':'web-'+str(sum(Handler.counts.values())),'name':'submit_to_chatbox','args':{'items':[{'path':address}]},'state':'done','media':[{'kind':'web','path':address,'url':address,'title':'Preview','presentation':'webview'}]})
    submit(url);wait(lambda:loader.property('item') is not None and not pane.property('moving'))
    view=loader.property('item');wait(lambda:view.property('title')=='Preview' and not view.property('loading'))
    count=Handler.counts['/preview'];submit(url);wait(lambda:Handler.counts['/preview']>count)
    assert loader.property('item') is view
    address=find('webAddress');find('promptInput').forceActiveFocus()
    first=address.mapToScene(QPointF(25,address.height()/2)).toPoint()
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,first);QTest.qWait(100)
    assert address.property('selectedText')==url,address.property('selectedText')
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,first);QTest.qWait(100)
    assert address.property('selectedText')=='' and 0<address.property('cursorPosition')<len(url)
    find('promptInput').forceActiveFocus();click('webAddress')
    assert address.property('selectedText')==url
    handle=find('webPaneResizeHandle');start=handle.mapToScene(QPointF(handle.width()/2,100)).toPoint();original=pane.width()
    QTest.mousePress(window,Qt.LeftButton,Qt.NoModifier,start)
    for dx in [-30,-60,-100]:QTest.mouseMove(window,start+QPoint(dx,0));QTest.qWait(40)
    assert handle.property('pressed') and pane.width()>original+90
    QTest.mouseRelease(window,Qt.LeftButton,Qt.NoModifier,start+QPoint(-100,0));QTest.qWait(100)
    assert loader.property('item') is view
    enlarged=pane.width();click('closeWebPaneButton');wait(lambda:loader.property('item') is None and not pane.property('moving'))
    click('openChatbox_web-0_0');wait(lambda:loader.property('item') is not None and not pane.property('moving'))
    view=loader.property('item');wait(lambda:view.property('title')=='Preview' and not view.property('loading'))
    assert abs(pane.width()-enlarged)<0.1
    address=find('webAddress');address.setProperty('text',url.replace('/preview','/second'));assert QMetaObject.invokeMethod(address,'accepted',Qt.DirectConnection)
    wait(lambda:view.property('title')=='Second' and not view.property('loading'))
    assert QMetaObject.invokeMethod(find('webBackButton'),'clicked',Qt.DirectConnection)
    wait(lambda:view.property('title')=='Preview' and not view.property('loading'))
    output=ROOT/'artifacts/screenshots';output.mkdir(parents=True,exist_ok=True);assert window.grabWindow().save(str(output/'webview-pane.png'))
    assert QMetaObject.invokeMethod(find('closeWebPaneButton'),'clicked',Qt.DirectConnection)
    wait(lambda:not pane.property('moving') and loader.property('item') is None)
    assert pane.width()<0.5
    controller.chatChanged.emit();QTest.qWait(150);assert not pane.property('opened')
    # A card click reopens the side pane; its context Open action uses the OS browser.
    click('openChatbox_web-0_0')
    wait(lambda:loader.property('item') is not None and not pane.property('moving'))
    view=loader.property('item');wait(lambda:view.property('title')=='Preview' and not view.property('loading'))
    click('closeWebPaneButton');wait(lambda:loader.property('item') is None and not pane.property('moving'))
    find('promptInput').setProperty('text','Existing draft')
    def context():
        click('openChatbox_web-0_0',Qt.RightButton)
        for prefix in ['openChatboxWeb_','copyChatboxUrl_','attachChatboxWeb_']:
            assert find(prefix+'web-0_0').isVisible()
        for prefix in ['attachChatbox_','copyChatboxFile_','copyChatbox_','revealChatbox_']:
            assert not find(prefix+'web-0_0').isVisible()
    context();click('copyChatboxUrl_web-0_0')
    assert app.clipboard().text()==url and not pane.property('opened')
    class Receiver(QObject):
        urls=[]
        @Slot(QUrl)
        def open(self, value): self.urls.append(value.toString())
    receiver=Receiver();QDesktopServices.setUrlHandler('http',receiver,'open')
    try:
        context();click('openChatboxWeb_web-0_0')
        assert receiver.urls==[url] and not pane.property('opened')
    finally: QDesktopServices.unsetUrlHandler('http')
    context();click('attachChatboxWeb_web-0_0')
    assert find('promptInput').property('text')=='Existing draft' and find('promptInput').hasActiveFocus()
    assert len(controller.attachments)==1 and controller.attachments[0]['url']==url
    assert not pane.property('opened')
    from unittest.mock import patch
    with patch.object(controller,'_command_pi',return_value=True) as command:
        assert controller._send('Existing draft')
        assert '- web: '+url in command.call_args.kwargs['text']
        assert command.call_args.kwargs['images']==[]
    controller.chatChanged.emit();controller.transcriptChanged.emit();QTest.qWait(250)
    index,row=next((i,r) for i,r in reversed(list(enumerate(controller.displayMessages))) if r['role']=='user')
    assert row['text']=='Existing draft' and row['attachments'][0]['url']==url
    assert find('userAttachmentName_'+str(index)+'_0').property('text')=='127.0.0.1'
    submit(url);wait(lambda:pane.property('opened') and not pane.property('moving'))
    controller.newSession();wait(lambda:not pane.property('opened'))
    assert controller.normalizeWebUrl('javascript:alert(1)')==''
    assert not [w for w in warnings if 'WebPane' in w or 'WebSurface' in w],warnings
    controller.close();engine.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete);server.shutdown()
    print('WEBVIEW_UI_OK: sidebar PID collapse/expand, submit, reload same instance, navigate/back, PID close, card reopens pane, three context actions, URL attachment preserves draft and sent prompt, session isolation')
