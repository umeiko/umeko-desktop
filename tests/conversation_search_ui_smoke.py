"""Search retention, read-only jumps into paged history, and running sessions."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['UMEKO_DATA_DIR']=tempfile.mkdtemp(prefix='umeko-conversation-search-')
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
os.environ.setdefault('UMEKO_LANGUAGE','zh')
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from main import create_application

app,engine,backend=create_application()
window=engine.rootObjects()[0]
warnings=[]
engine.warnings.connect(lambda errors:warnings.extend(str(e) for e in errors))
def find(name):
    pending=[window.contentItem()]
    while pending:
        item=pending.pop()
        if item.objectName()==name:return item
        pending.extend(item.childItems())
    raise AssertionError(name)
def click(name):
    QTest.qWait(60);item=find(name)
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(item.boundingRect().center()).toPoint())
def wait(predicate,label):
    for _ in range(1000):
        QTest.qWait(10)
        time.sleep(0.002)  # Let Python history-reader workers run under QTest.
        if predicate():return
    raise AssertionError(label)
try:
    QTest.qWait(700)
    profile=Path(os.environ['UMEKO_DATA_DIR']);workspace=profile/'workspace';workspace.mkdir()
    history=profile/'history.jsonl'
    with history.open('w',encoding='utf-8') as handle:
        handle.write(json.dumps({'type':'session','id':'search-history','cwd':str(workspace)})+'\n')
        for i in range(1800):
            text='marker original question' if i==6 else 'marker code answer' if i==7 else 'ordinary text '+('sample code text '*90)
            handle.write(json.dumps({'type':'message','id':f'entry-{i}','parentId':f'entry-{i-1}' if i else None,
                'message':{'role':'assistant' if i%2 else 'user','content':text,'timestamp':1700000000000+i}},ensure_ascii=False)+'\n')
    backend._sessions=[{'id':'search-history','title':'Search fixture','file':str(history),'workspace':str(workspace)}]
    running=backend._new_view(str(workspace));running.id='running-fixture';running.phase='working'
    running.draft='keep my draft';running.attachments=[{'id':'fixture','path':str(history),'name':'fixture','kind':'file'}]
    backend._activate(running)
    click('searchChatsButton');wait(lambda:window.property('searchVisible'),'search visible')
    pane=find('conversationSearch');field=find('conversationSearchInput')
    field.setProperty('text','marker');pane.execute()
    wait(lambda:not backend.chatSearch.busy,'search finished');assert backend.chatSearch.count==2,backend.chatSearch.error
    # A broad query must yield to the UI while thousands of streamed rows arrive.
    ticks=[]; heartbeat=QTimer();heartbeat.setInterval(10);heartbeat.timeout.connect(lambda:ticks.append(time.monotonic()));heartbeat.start()
    field.setProperty('text','sample');pane.execute();wait(lambda:not backend.chatSearch.busy,'large result batch finished')
    heartbeat.stop();assert backend.chatSearch.count==20000 and backend.chatSearch.limitHit
    assert len(ticks)>=4,'search starved the UI event loop'
    max_gap=max((b-a for a,b in zip(ticks,ticks[1:])),default=0)
    assert max_gap<1.0,f'UI stalled for {max_gap:.2f}s'
    print(f'20,000 search hits: {len(ticks)} UI heartbeats; maximum interval {max_gap*1000:.1f} ms')
    field.setProperty('text','marker');pane.execute();wait(lambda:not backend.chatSearch.busy,'restore precise query')
    QTest.keyClick(window,Qt.Key_Escape);wait(lambda:not window.property('searchVisible'),'Esc closes')
    QTest.keyClick(window,Qt.Key_K,Qt.ControlModifier);wait(lambda:window.property('searchVisible'),'shortcut opens')
    assert field.property('text')=='marker' and backend.chatSearch.count==2
    click('searchBackButton');wait(lambda:not window.property('searchVisible'),'back closes')
    assert field.property('text')=='' and backend.chatSearch.count==0
    click('searchChatsButton');field.setProperty('text','marker');pane.execute()
    wait(lambda:not backend.chatSearch.busy,'second search finished')
    assert backend.chatSearch.count==2,backend.chatSearch.error
    click('searchResult_1');wait(lambda:backend.activeSession=='search-history','jump opened history')
    assert not window.property('searchVisible')
    assert backend._chat_model.paged,'large history keeps its paged presentation'
    wait(lambda:window.property('searchHighlightRow')>=0,'message highlighted')
    row=window.property('searchHighlightRow')
    wait(lambda:backend._chat_model.isReady(row),'target page loaded')
    assert 'marker original question' in backend._chat_model.message(row)['text']
    assert running.phase=='working' and running.draft=='keep my draft' and len(running.attachments)==1
    assert backend._view.process is None,'search does not inspect/start Pi'
    assert backend.chatSearch.query=='marker'
    assert not warnings,warnings
    print('conversation_search_ui_smoke: PASS (retention, clear, paged jump, draft/attachments/running session preserved)')
finally:
    backend.close()
    from shiboken6 import delete
    delete(window);delete(engine);app.processEvents()
