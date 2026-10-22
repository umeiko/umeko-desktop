"""The retry countdown must not rebuild the transcript or leak between chats."""
import os
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-retry-ui-')
os.environ['UMEKO_LANGUAGE'] = 'zh'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QObject
from PySide6.QtTest import QTest
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda items: warnings.extend(e.toString() for e in items))
try:
    record = backend._view
    record.phase = 'running'
    record.messages = [{'role':'user','text':'fixture','error':False}, {'role':'assistant','text':'partial','error':False}]
    backend.chatChanged.emit()
    QTest.qWait(150)
    updates = [0]
    backend.chatChanged.connect(lambda: updates.__setitem__(0, updates[0]+1))
    status = window.findChild(QObject, 'networkRetryStatus')
    assert status is not None
    backend._handle_pi_event(record, {'type':'network_retry','active':True,'waiting':True,'attempt':1,'delayMs':4000,'startedAt':int(time.time()*1000)})
    QTest.qWait(1500)
    assert status.property('visible')
    assert '第一次' in status.property('text') and '1s/4s' in status.property('text'), (status.property('text'), status.property('clock'), status.property('elapsed'), backend.networkRetry)
    assert updates[0] == 0, 'Countdown notified chat rendering'
    backend._handle_pi_event(record, {'type':'assistant_start','retry':True})
    assert record.messages[-1]['text'] == '' and len(record.messages) == 2
    backend._stop()
    QTest.qWait(20)
    assert not status.property('visible')
    backend.newSession()
    assert backend.networkRetry == {}
    assert not warnings, '\n'.join(warnings)
    print('NETWORK_RETRY_UI_OK', flush=True)
finally:
    backend.close(); engine.deleteLater(); app.processEvents()
