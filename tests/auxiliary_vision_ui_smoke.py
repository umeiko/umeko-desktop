"""Real QML + Pi + loopback providers; no real accounts or user configuration."""
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
temp=tempfile.TemporaryDirectory(prefix='umeko-vision-ui-')
os.environ.update(UMEKO_DATA_DIR=str(Path(temp.name)/'profile'),UMEKO_LANGUAGE='zh',QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software')
from PySide6.QtCore import QEventLoop,QObject,QTimer,Qt,QUrl
from PySide6.QtTest import QTest
from PySide6.QtGui import QImage
from tests.reasoning_stream_fixture import _LoopbackServer
from main import create_application

release=threading.Event();entered=threading.Event();requests=[]
VISION_MODEL='vision-upstream-model'
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body)
        if body['model']==VISION_MODEL:
            entered.set();release.wait(20);text='The image contains a blue square.'
        else:text='I received the auxiliary visual observation.'
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
        self.wfile.write(('data: '+json.dumps({'choices':[{'index':0,'delta':{'role':'assistant','content':text},'finish_reason':None}]})+'\n\ndata: '+json.dumps({'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n').encode());self.wfile.flush()

server=_LoopbackServer(('127.0.0.1',0),Handler)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
app=engine=b=None
out=ROOT/'build/auxiliary-vision-ui';out.mkdir(parents=True,exist_ok=True)
try:
    with patch('app.controller.Controller.loadNativeIndex',lambda self:None):
        app,engine,b=create_application()
    window=engine.rootObjects()[0];window.setWidth(1250);window.setHeight(900)
    warnings=[];engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
    b.store.data['agent'].update(agentDir=str(Path(temp.name)/'agent'),safeMode=True,autoCompaction=False)
    b.store.data.update(providers=[{'id':'p','name':'Local vision fixture','api':'openai','baseUrl':f'http://127.0.0.1:{server.server_port}/v1','key':'',
        'models':[{'upstream':VISION_MODEL if name=='eyes' else name,'alias':name,'vision':name=='eyes','visionAuto':False} for name in ('text','eyes')]}],selectedProvider='p',selectedModel='text')
    b._view.provider='p';b._view.model='text';b.changed.emit()
    def find(name):
        stack=[window.contentItem()]
        while stack:
            item=stack.pop()
            if item.objectName()==name:return item
            stack.extend(item.childItems())
        return window.findChild(QObject,name)
    loop=QEventLoop()
    def wait(predicate,timeout=20):
        deadline=time.monotonic()+timeout
        while not predicate():
            assert time.monotonic()<deadline,'Timed out waiting for auxiliary vision UI'
            QTimer.singleShot(10,loop.quit);loop.exec()
    def click(item):
        window.grabWindow();QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(item.boundingRect().center()).toPoint())
    window.setProperty('settingsTab',0);window.setProperty('page','settings')
    wait(lambda:find('multimodalSettingsEntry').isVisible())
    wait(lambda:find('multimodalSettingsEntry').mapToScene(find('multimodalSettingsEntry').boundingRect().topRight()).x() <= window.width())
    assert not find('auxiliaryVisionModel').isVisible()
    window.grabWindow().save(str(out/'settings-entry-zh.png'))
    click(find('multimodalSettingsEntry'))
    wait(lambda:find('auxiliaryVisionModel').isVisible())
    assert not find('apiProvidersSection').isVisible()
    assert not find('commonProvidersSection').isVisible()
    picker=find('auxiliaryVisionModel');click(picker);QTest.keyClick(window,Qt.Key_End);QTest.keyClick(window,Qt.Key_Return)
    wait(lambda:b.config['auxiliaryVision']['model']=='eyes')
    automatic=find('auxiliaryVisionAutomatic');click(automatic)
    wait(lambda:not b.config['auxiliaryVision']['autoAnalyze'])
    assert b.config['auxiliaryVision']['toolEnabled']
    click(automatic);wait(lambda:b.config['auxiliaryVision']['autoAnalyze'])
    tool=find('auxiliaryVisionTool');click(tool);wait(lambda:not b.config['auxiliaryVision']['toolEnabled'])
    assert b.config['auxiliaryVision']['autoAnalyze'];click(tool);wait(lambda:b.config['auxiliaryVision']['toolEnabled'])
    window.grabWindow().save(str(out/'settings-zh.png'))
    click(find('backMultimodalSettings'));wait(lambda:find('multimodalSettingsEntry').isVisible())
    assert find('apiProvidersSection').isVisible()
    click(find('multimodalSettingsEntry'));wait(lambda:find('auxiliaryVisionModel').isVisible())
    assert picker.property('currentIndex') == 1
    b.setLanguage('en');b.setFontScale(2.)
    wait(lambda:picker.property('font').pixelSize() >= 24)
    wait(lambda:picker.property('currentIndex') == 1)
    window.grabWindow()
    window.grabWindow().save(str(out/'settings-en-200.png'))
    assert automatic.mapToItem(find('auxiliaryVisionSettings'),automatic.boundingRect().center()).x() < find('auxiliaryVisionSettings').width()
    b.setFontScale(1.);b.setLanguage('zh');window.setProperty('page','chat')
    path=Path(temp.name)/'square.png';image=QImage(32,32,QImage.Format_ARGB32);image.fill(0xff2244aa);assert image.save(str(path))
    assert b.addAttachments(json.dumps([QUrl.fromLocalFile(str(path)).toString()]))
    assert b.send('Describe the square')
    wait(entered.is_set)
    def automatic_tools():
        return [tool for message in b._view.messages for tool in message.get('tools',[]) if tool.get('arguments',{}).get('automatic')]
    wait(lambda:len(automatic_tools())==1 and automatic_tools()[0]['state']=='running')
    automatic_id=automatic_tools()[0]['id']
    assert automatic_tools()[0]['arguments']['model']==VISION_MODEL
    assert automatic_tools()[0]['arguments']['provider']=='Local vision fixture'
    assert find('auxiliaryVisionStatus') is None
    wait(lambda:find('toolHistoryHeader') is not None)
    assert VISION_MODEL in find('toolHistorySummary').property('text'),'The collapsed tool card identifies the actual vision model'
    assert 'Local vision fixture' not in find('toolHistorySummary').property('text'),'Provider information belongs in expanded details'
    click(find('toolHistoryHeader'))
    wait(lambda:find('toggleToolDetail_'+automatic_id).isVisible())
    click(find('toggleToolDetail_'+automatic_id))
    wait(lambda:find('toolDetail_'+automatic_id).isVisible())
    assert VISION_MODEL in find('toolDetail_'+automatic_id).property('text')
    window.grabWindow().save(str(out/'analyzing.png'))
    release.set();wait(lambda:not b.busy)
    assert not b._view.failed,b._view.messages
    assert automatic_tools()[0]['state']=='done'
    assert 'blue square' in automatic_tools()[0]['result']
    window.grabWindow().save(str(out/'analyzed.png'))
    assert len(requests)==2,[row['model'] for row in requests]
    assert requests[0]['model']==VISION_MODEL and requests[1]['model']=='text'
    assert 'blue square' in json.dumps(requests[1]['messages'])
    assert not any(block.get('type')=='image_url' for row in requests[1]['messages'] if isinstance(row['content'],list) for block in row['content'])
    assert b.send('What is two plus two?')
    wait(lambda:not b.busy)
    assert [row['model'] for row in requests] == [VISION_MODEL,'text','text']
    assert len(automatic_tools())==1,'Browsing and follow-up turns must not create another analysis card'
    assert b.saveAuxiliaryVision('{"autoAnalyze":false}')
    b.newSession()
    assert b.addAttachments(json.dumps([QUrl.fromLocalFile(str(path)).toString()]))
    assert b.send('Keep this attachment for an on-demand image tool')
    wait(lambda:not b.busy)
    assert not b._view.failed
    assert [row['model'] for row in requests] == [VISION_MODEL,'text','text','text']
    assert 'square.png' in json.dumps(requests[-1]['messages'])
    assert not warnings,warnings
    print('AUXILIARY_VISION_UI_OK: settings, independent switches, English/200%, actual tool cards, real Pi image fallback and follow-up reuse')
finally:
    release.set()
    if b:b.close()
    if engine:
        import shiboken6
        shiboken6.delete(engine)
    server.shutdown();server.server_close();thread.join(5);temp.cleanup()
