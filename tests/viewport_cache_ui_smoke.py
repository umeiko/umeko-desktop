"""Real QML: retained control identity, bounded paging, LRU and anchor restore."""
import json,os,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
base=Path(tempfile.mkdtemp(prefix='umeko-viewport-cache-'))
os.environ['UMEKO_DATA_DIR']=str(base/'profile')
os.environ.setdefault('QT_QPA_PLATFORM','offscreen');os.environ.setdefault('QT_QUICK_BACKEND','software')
from PySide6.QtCore import QMetaObject,Q_ARG,Qt,QPointF
from PySide6.QtTest import QTest
import shiboken6
from main import create_application
app,engine,c=create_application();w=engine.rootObjects()[0];warnings=[]
engine.warnings.connect(lambda es:warnings.extend(e.toString() for e in es))
def items(root=None):
 todo=[root or w.contentItem()]
 while todo:
  item=todo.pop();yield item;todo.extend(item.childItems())
def find(name):
 return next(item for item in items() if item.objectName()==name)
def wait(check,label):
 deadline=time.monotonic()+30
 while time.monotonic()<deadline:
  QTest.qWait(10)
  if check():return
 raise AssertionError(label+': '+str(warnings[:4]))
def invoke(item,method,*args):
 assert QMetaObject.invokeMethod(item,method,Qt.DirectConnection,*[Q_ARG('QVariant',x) for x in args])
token=0

def open_session(identifier):
 global token
 token+=1;c.sessionPreview.prepare(identifier,token)
 wait(lambda:c.sessionPreview.prepared is not None,'prepare')
 start=time.perf_counter();assert c.sessionPreview.activate(token)
 view=find('conversation')
 wait(lambda:not view.property('restoring'),'restore')
 wait(lambda:any(item.objectName().startswith('messageBubble_') and item.isVisible() for item in items(view)),'body')
 return view,(time.perf_counter()-start)*1000
try:
 c._sessions=[]
 for name in 'abcd':
  file=base/(name+'.jsonl')
  with file.open('w') as out:
   for i in range(160):
    out.write(json.dumps({'type':'message','id':str(i),'parentId':str(i-1) if i else None,'message':{
     'role':'user' if i%2==0 else 'assistant','content':f'{name} message {i}\n\n'+ ('A paragraph for cached text layout. '*16 if i%2 else 'Question')}})+'\n')
  c._sessions.append({'id':name,'file':str(file),'title':name,'workspace':str(base)})
 c.chatChanged.emit()
 a,cold=open_session('a');invoke(a,'jumpToMessage',40)
 wait(lambda:not a.property('restoring'),'jump')
 wait(lambda:any(item.objectName()=='messageBubble_40' for item in items(a)),'target body')
 QTest.qWait(160)
 anchor=find('messageBubble_40');y=anchor.mapToItem(a,QPointF()).y()
 identity=shiboken6.getCppPointer(anchor)[0];model=c.messageModel
 b,_=open_session('b');open_session('c')
 with patch.object(c.store,'save',wraps=c.store.save) as save:
  warm,elapsed=open_session('a')
  save.assert_not_called()
 assert warm is a,'Warm switch recreated the ListView'
 assert c.messageModel is model,'Warm switch reset the model'
 current=next(item for item in items(a) if item.objectName()=='messageBubble_40')
 assert shiboken6.getCppPointer(current)[0]==identity,'Warm switch recreated a cached body'
 assert abs(current.mapToItem(a,QPointF()).y()-y)<2,'Warm anchor moved'
 assert len(c._conversation_views.models)==3
 assert len(c.messageModel._prepared)<=16
 for row in (4,80,152):
  invoke(a,'jumpToMessage',row);wait(lambda:not a.property('restoring'),'jump '+str(row));QTest.qWait(100)
  assert len(c.messageModel._prepared)<=16
 open_session('d');QTest.qWait(50)
 assert not shiboken6.isValid(b),'LRU did not release old QML view'
 b2,_=open_session('b');assert b2 is not b
 assert len(c._conversation_views.models)==3
 # A changed transcript must replace stale content even when its view is cached.
 open_session('d')
 with (base/'b.jsonl').open('a') as out:
  out.write(json.dumps({'type':'message','id':'160','parentId':'159','message':{'role':'user','content':'new external history'}})+'\n')
 open_session('b')
 assert c.displayMessage(c.messageCount-1)['text']=='new external history'
 assert not warnings,'\n'.join(warnings[:10])
 print(json.dumps({'result':'VIEWPORT_CACHE_UI_OK','cold_attach_ms':round(cold,1),'warm_attach_ms':round(elapsed,1),'retained_views':len(c._conversation_views.models),'prepared_rows':len(c.messageModel._prepared)}),flush=True)
finally:
 c.close();shiboken6.delete(engine)
