"""Fast viewport reversals must settle without a second nudge or edge flicker."""
import json, os, sys, tempfile, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
base=Path(tempfile.mkdtemp(prefix='umeko-scroll-pages-'))
os.environ.update(UMEKO_DATA_DIR=str(base/'profile'),QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',PI_OFFLINE='1')
from PySide6.QtCore import QMetaObject,Q_ARG,Qt
from PySide6.QtTest import QTest
from main import create_application
import shiboken6
app,engine,c=create_application();w=engine.rootObjects()[0];w.resize(1400,1000)
warnings=[];engine.warnings.connect(lambda es:warnings.extend(e.toString() for e in es))
def wait(check,label,seconds=15):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  QTest.qWait(10);time.sleep(.001)
  if check():return
 raise AssertionError(label)
def find(name):
 todo=[w.contentItem()]
 while todo:
  item=todo.pop()
  if item.objectName()==name:return item
  todo.extend(item.childItems())
 raise AssertionError(name)
def invoke(method,value):
 assert QMetaObject.invokeMethod(view,method,Qt.DirectConnection,Q_ARG('QVariant',value))
def visible_rows():
 top=view.property('contentY');bottom=top+view.height()
 return sorted((item.property('index'),item.property('bodyReady'),round(item.y()-top,1),round(item.height(),1))
  for item in view.property('contentItem').childItems() if item.property('bodyReady') is not None and item.y()+item.height()>top+2 and item.y()<bottom-2)
def ready():
 rows=visible_rows();return bool(rows) and all(row[1] for row in rows) and not view.property('restoring')
def state():
 return {'visible':visible_rows(),'wanted':c.messageModel._wanted,'prepared':list(c.messageModel._prepared),'job':c.messageModel._job,'restore':view.property('restoring')}
try:
 file=base/'history.jsonl'
 with file.open('w') as out:
  for i in range(360):
   lines=(1,2,22,3,45,1,8)[i%7]
   text=f'Message {i}\n\n'+('A varied paragraph to exercise viewport height changes.\n\n'*lines if i%2 else 'Short question')
   out.write(json.dumps({'type':'message','id':str(i),'parentId':str(i-1) if i else None,'message':{'role':'assistant' if i%2 else 'user','content':text}})+'\n')
 c._sessions=[{'id':'history','file':str(file),'title':'Scrolling history','workspace':str(base)}];c.chatChanged.emit()
 c.sessionPreview.prepare('history',1);wait(lambda:c.sessionPreview.prepared is not None,'prepare',30);assert c.sessionPreview.activate(1)
 view=find('conversation');wait(ready,'initial body')
 for target in (20,100,220):
  invoke('jumpToMessage',target);wait(ready,'jump')
  for delta in (620,740,-510,1200,-880,690,-330):
   invoke('scrollBy',delta);QTest.qWait(8)
  try:wait(ready,'visible bodies require another scroll',6)
  except AssertionError:
   print('STALLED',json.dumps(state()),flush=True);raise
  # Do not move again: loading at the viewport edge must converge and stay ready.
  QTest.qWait(250)
  ys=[]
  for _ in range(70):
   QTest.qWait(10);time.sleep(.001);ys.append(view.property('contentY'))
   assert ready(),('Settled viewport reverted to loading',state())
  assert max(ys)-min(ys)<2,('Stationary viewport kept jumping',max(ys)-min(ys),state())
  print('SETTLED',target,json.dumps(state()),flush=True)
 assert not warnings,'\n'.join(warnings[:5])
 print('SCROLL_PAGING_UI_OK',flush=True)
finally:
 c.close();shiboken6.delete(engine)
