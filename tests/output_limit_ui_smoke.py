"""Manual fallback and contiguous rendering across automatic output continuation."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-output-limit-')
os.environ['UMEKO_LANGUAGE'] = 'zh'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))

def find(name):
    pending = [window.contentItem()]
    while pending:
        item = pending.pop()
        if item.objectName() == name: return item
        pending.extend(item.childItems())
    raise AssertionError(name)

try:
    backend._view.messages = [{'role':'user', 'text':'Long drawing', 'error':False},
                              {'role':'assistant', 'text':'<svg>unfinished', 'error':False}]
    backend.chatChanged.emit()
    QTest.qWait(200)
    assert not find('outputLimitNotice_1').isVisible()
    backend._handle_pi_event(backend._view, {'type':'message', 'role':'assistant', 'text':'<svg>unfinished', 'stopReason':'length'})
    QTest.qWait(180)
    assert backend.messages[-1]['stopReason'] == 'length'
    assert find('outputLimitNotice_1').isVisible()
    button = find('continueOutputButton')
    assert button.isVisible()
    with patch.object(backend, '_send', return_value=True) as send:
        QTest.qWait(80)
        send.assert_not_called()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, button.mapToScene(button.boundingRect().center()).toPoint())
        QTest.qWait(80)
        send.assert_called_once_with('继续刚才未完成的回答，从中断处接着输出，不要重复已有内容。')
    backend._view.phase = 'running'
    backend.chatChanged.emit()
    QTest.qWait(100)
    assert not button.isVisible(), 'Continue was offered during a running task'
    backend._view.phase = 'idle'
    backend._handle_pi_event(backend._view, {'type':'message', 'role':'assistant', 'text':'Complete', 'stopReason':'stop'})
    QTest.qWait(100)
    assert not find('outputLimitNotice_1').isVisible()
    prefix, suffix = '```rust\nfn ma', 'in() {}\n```'
    backend._view.phase = 'running'
    backend._view.messages = [{'role':'user','text':'code','error':False},
                              {'role':'assistant','text':prefix,'stopReason':'length','error':False}]
    backend.chatChanged.emit()
    backend._handle_pi_event(backend._view, {'type':'assistant_start'})
    backend._handle_pi_event(backend._view, {'type':'delta','text':suffix})
    backend._handle_pi_event(backend._view, {'type':'message','role':'assistant','text':suffix,'stopReason':'stop'})
    QTest.qWait(100)
    assert len(backend.displayMessages)==2
    assert backend.displayMessages[-1]['text']==prefix+suffix
    assert backend.displayMessages[-1]['activity'][-1]['text']==prefix+suffix
    assert not find('outputLimitNotice_1').isVisible()
    assert not warnings, '\n'.join(warnings)
    print('OUTPUT_LIMIT_UI_OK', flush=True)
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
