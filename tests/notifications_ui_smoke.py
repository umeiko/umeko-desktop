"""Native handoff, foreground long-task alerts, independent clicks and suppression."""
import os, sys, tempfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen');os.environ.setdefault('QT_QUICK_BACKEND','software')
from PySide6.QtGui import QIcon
from PySide6.QtQuick import QQuickWindow
from PySide6.QtWidgets import QApplication,QSystemTrayIcon
from PySide6.QtTest import QTest
from app.notifications import TaskNotifications
from app.controller import Controller
app=QApplication([])
class NativeFixture:
    def __init__(self):self.sent=[];self.events=[]
    def send(self,identifier,title,body):self.sent.append((identifier,title,body));return 1
    def poll(self):return self.events.pop(0) if self.events else None
window=QQuickWindow();window.show();native=NativeFixture()
tray=QSystemTrayIcon(QIcon(str(ROOT/'app/icons/yanami-pixel.png')))
client=TaskNotifications(window,tray,ROOT,native=native);opened=[];client.activated.connect(opened.append)
client.task_finished('visible','Visible task',True);assert not native.sent
window.showMinimized();QTest.qWait(20)
client.task_finished('A','First task',True)
window.hide();client.task_finished('B','Second task',True)
assert len(native.sent)==2 and '任务完成' in native.sent[0][1]
first,second=native.sent[0][0],native.sent[1][0]
native.events += ['clicked:'+second,'clicked:'+first,'clicked:'+first]
QTest.qWait(200);assert opened==['B','A'],'Older Notification Center entries opened the wrong task'
client.language='en';client.task_finished('C','Failed task',False)
assert 'needs attention' in native.sent[-1][1]
native.events += ['dismissed:'+native.sent[-1][0]];QTest.qWait(170);assert opened==['B','A']
window.showNormal();QTest.qWait(20)
client.task_finished('visible-short','Short task',True,False);assert len(native.sent)==3
client.task_finished('visible-long','Long task',True,True);assert len(native.sent)==4
native.events += ['clicked:'+native.sent[-1][0]];QTest.qWait(170);assert opened==['B','A','visible-long']
client.task_finished('visible-long-error','Long failed task',False,True)
assert len(native.sent)==5 and 'needs attention' in native.sent[-1][1]
client.close();client.task_finished('closed','Ignore after shutdown',True,True);assert len(native.sent)==5
with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,{'UMEKO_DATA_DIR':temp}):
    backend=Controller(ROOT);events=[];backend.taskFinished.connect(lambda *args:events.append(args))
    record=backend._view;record.id='notification-fixture';record.title='Local task';record.ready=True;record.action='prompt';record.phase='running'
    backend._handle_pi_event(record,{'type':'done'});backend._handle_pi_event(record,{'type':'done'})
    assert events==[('notification-fixture','Local task',True,False)]
    record.phase='running';record.cancelled=True;backend._handle_pi_event(record,{'type':'done'});assert len(events)==1
    record.cancelled=False;record.phase='running';record.failed=True;backend._handle_pi_event(record,{'type':'done'})
    assert events[-1][2] is False
    record.phase='working';record.action='reload';backend._handle_pi_event(record,{'type':'done'});assert len(events)==2
    with patch('app.controller_runtime.time.monotonic', return_value=1000):
        for duration, expected in ((179.999,False),(180,False),(180.001,True)):
            record.action='prompt';record.phase='running';record.failed=False;record.prompt_started=1000-duration
            backend._handle_pi_event(record,{'type':'done'})
            assert events[-1][3] is expected, (duration,events[-1])
            assert record.prompt_started is None
        count=len(events);record.phase='running';record.cancelled=True;record.prompt_started=0
        backend._handle_pi_event(record,{'type':'done'});assert len(events)==count and record.prompt_started is None
    backend.close()
print('TASK_NOTIFICATIONS_OK: foreground long tasks, strict three-minute boundary, background alerts, activation and cancellation suppression')
