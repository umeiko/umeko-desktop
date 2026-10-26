"""Long-history paging, viewport restoration, copying, and live-tail regression."""
import os,sys,json,tempfile,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));base=Path(tempfile.mkdtemp(prefix='umeko-page-smoke-'))
os.environ['UMEKO_DATA_DIR']=str(base/'profile');os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['QT_QUICK_BACKEND']='software'
from main import create_application
from PySide6.QtCore import QMetaObject,Q_ARG,Qt,QTimer,QPointF
from PySide6.QtTest import QTest
file=base/'large.jsonl'
with file.open('w',encoding='utf-8') as out:
 out.write(json.dumps({'type':'session','id':'fixture','cwd':str(base)})+'\n')
 for i in range(6000):
  out.write(json.dumps({'type':'message','id':'m'+str(i),'parentId':'m'+str(i-1) if i else None,'message':{'role':'user' if i%2==0 else 'assistant','content':'Question '+str(i) if i%2==0 else ('Reply '+str(i)+'\n\n'+('A bounded paragraph for virtual history. '*25))}})+'\n')
import faulthandler
faulthandler.dump_traceback_later(45,exit=True)
app,engine,c=create_application();w=engine.rootObjects()[0];warnings=[];engine.warnings.connect(lambda es:warnings.extend(e.toString() for e in es))
c._sessions=[{'id':'fixture','file':str(file),'title':'Large history','workspace':str(base)}];c.chatChanged.emit()
ticks=[];timer=QTimer();timer.setInterval(10);timer.timeout.connect(lambda:ticks.append(1));timer.start()
def wait(check):
 for i in range(2000):
  QTest.qWait(10);time.sleep(0.001)
  if check():return
 raise AssertionError('timeout '+str(warnings[:10])+str((c.activeSession,c.messageCount,c.sessionPreview.request,c.sessionPreview.reading,c.sessionPreview.direct_token)))
def find(name):
 todo=[w.contentItem()]
 while todo:
  p=todo.pop()
  if p.objectName()==name:return p
  todo.extend(p.childItems())
 raise AssertionError(name)
try:
 t=time.perf_counter();c.openSession('fixture');wait(lambda:c.activeSession=='fixture' and c.messageModel.rowCount()==6000);print('OPEN',time.perf_counter()-t,'ticks',len(ticks),'cache',c.transcripts.cache.weight,flush=True)
 assert c._view.process is None and not c._view.messages
 view=find('conversation');QTest.qWait(300)
 for row in (0,3000,5998,1200):
  QMetaObject.invokeMethod(view,'jumpToMessage',Qt.DirectConnection,Q_ARG('QVariant',row));wait(lambda:c.messageModel.isReady(row) and not view.property('restoring'));y=find('messageBubble_'+str(row)).mapToItem(view,QPointF()).y();print('JUMP',row,view.property('contentY'),'relative',y,'cache',c.transcripts.cache.weight,flush=True);assert -2<=y<=5 or view.property('atYEnd') and 0<=y<view.height(),(row,y)
 assert c.messageModel.questionCount==3000
 c.copyDisplayMessage(5999);wait(lambda:app.clipboard().text().startswith('Reply 5999'))
 c.copyChatSelection(json.dumps({'anchor':{'row':0,'block':-100000,'offset':0},'cursor':{'row':3,'block':2147483647,'offset':0},'expanded':{}}));wait(lambda:'Reply 3' in app.clipboard().text());print('COPY_OK',len(app.clipboard().text()),flush=True)
 # Full copy must include pages that have never entered the display cache.
 before=len(ticks)
 c.copyChatSelection(json.dumps({'anchor':{'row':0,'block':-100000,'offset':0},'cursor':{'row':5999,'block':2147483647,'offset':0},'expanded':{}}))
 wait(lambda:app.clipboard().text().count('Reply ')==3000)
 assert app.clipboard().text().count('Question ')==3000
 assert len(ticks)>before+5
 print('FULL_COPY_OK',len(app.clipboard().text()),flush=True)
 old=c._view;old.draft='preserved draft';old.scroll_index=1200;old.scroll_y=0;old.follow_tail=False
 c._pool.body_limit=1;c.newSession();assert not old.loaded and not old.messages
 c.openSession('fixture');wait(lambda:c.activeSession=='fixture' and c.messageModel.paged)
 assert old.draft=='preserved draft' and old.transcript.parsed_entries==0
 wait(lambda:not view.property('restoring'))
 print('EVICT_RESTORE_OK',flush=True)
 c._pool.body_limit=32*1024*1024
 from app.chat_model import ChatModel
 project=ChatModel.project;seen=[]
 def observe(messages,**kwargs):
  seen.append(len(messages));return project(messages,**kwargs)
 with patch.object(ChatModel,'project',side_effect=observe):
  c._handle_pi_event(old,{'type':'user_start','text':'Live tail'})
  for i in range(30):
   c._handle_pi_event(old,{'type':'delta','text':' token'});QTest.qWait(3)
  QTest.qWait(100)
 assert max(seen)<=2 and c.messageModel.rowCount()==6002,(seen,c.messageModel.rowCount())
 assert c.transcripts.cache.weight<=c.transcripts.cache.limit
 # Artificial rendering boundaries must not enter clipboard text.
 from app.chat_copy import selected_text
 from app.transcript_index import display_fragments
 script=(ROOT/'app/qml/markdown.js').read_text(encoding='utf-8')
 first={'row':0,'block':-100000,'offset':0}
 last={'row':0,'block':2147483647,'offset':0}
 for text in ('```rust\n'+''.join(f'println!("line {i}");\n' for i in range(4000))+'```',
              '| Key | Value |\n| --- | --- |\n'+''.join(f'| item{i} | data{i} |\n' for i in range(4000)),
              '```python\n'+'value = 1; '*10000+'\n```',
              '代码示例：\n\n```python\n'+'value = 1; '*10000+'\n```', '长段落🙂'*16000):
  original=ChatModel.project([{'role':'assistant','text':text}])
  pieces=list(display_fragments(original[0]))
  for i,row in enumerate(pieces):row['continuation']=i>0
  actual=selected_text(script,None,pieces,first,{**last,'row':len(pieces)-1},{})
  assert actual==selected_text(script,None,original,first,last,{})
 original=[{'role':'user','text':'超长用户输入🙂'*12000}]
 pieces=list(display_fragments(original[0]))
 for i,row in enumerate(pieces):row['continuation']=i>0
 assert selected_text(script,None,pieces,first,{**last,'row':len(pieces)-1},{})==selected_text(script,None,original,first,last,{})
 assert selected_text(script,None,[{'role':'user','text':'甲🙂乙𠮷尾'}],{'row':0,'block':0,'offset':1},{'row':0,'block':0,'offset':3},{})=='🙂'
 print('FRAGMENT_COPY_OK',flush=True)
 c.newSession();QTest.qWait(50)
 assert not view.isVisible()
 c._view.messages=[{'role':'user','text':'A new question'},{'role':'assistant','text':'A new reply'}]
 c.chatChanged.emit();c.viewChanged.emit();QTest.qWait(150)
 assert view.isVisible() and find('messageBubble_1').isVisible()
 assert not warnings,warnings[:10]
 print('PAGED_UI_OK',flush=True)
finally:
 faulthandler.cancel_dump_traceback_later();c.close();import shiboken6;shiboken6.delete(engine)
