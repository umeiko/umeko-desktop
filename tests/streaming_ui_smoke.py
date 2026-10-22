"""Replay code and real-time rich tables without a model; coalesce UI updates."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-streaming-ui-')
os.environ['UMEKO_LANGUAGE'] = 'zh'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QEventLoop, QTimer, Qt, QMetaObject, Q_ARG, Q_RETURN_ARG
from PySide6.QtTest import QTest
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))

def editors():
    pending = [window.contentItem()]
    while pending:
        item = pending.pop()
        if item.objectName() == 'selectText_1_0' and item.isVisible(): yield item
        pending.extend(item.childItems())

def plain(item):
    return QMetaObject.invokeMethod(item, 'getText', Qt.DirectConnection, Q_RETURN_ARG(str),
                                   Q_ARG(int, 0), Q_ARG(int, item.property('length')))

rust = '```rust\nfn rob(nums: &[i32]) -> i32 {\n    let (mut skip, mut take) = (0, 0);\n    for &money in nums {\n        (skip, take) = (skip.max(take), skip + money);\n    }\n    skip.max(take)\n}\n' + '\n'.join(f'// case {i}\nassert_eq!(rob(&[2, 7, 9, 3, 1]), 12);' for i in range(40)) + '\n```'
table = '| 状态 | 输入 | 当前值 | 选择 | 下一状态 | 转移表达式 | 说明 | 结果 |\n|---|---|---|---|---|---|---|---|\n' + '\n'.join(f'| S{i} | {i%9} | dp[{i}] | 跳过 / 取走 | S{i+1} | max(prev, curr + value) | 不能选择相邻房屋 | {i*3} |' for i in range(100))
reports = []
try:
    backend.setFontScale(1.49)
    backend.setTheme('yanami')
    for name, text in [('rust', rust), ('table', table)]:
        backend.newSession()
        record = backend._view
        record.phase = 'running'
        record.messages = [{'role':'user','text':'fixture','error':False}, {'role':'assistant','text':'','error':False}]
        backend.chatChanged.emit()
        QTest.qWait(100)
        updates, position, live_table = [0], [0], [False]
        gaps, previous = [], [time.perf_counter()]
        def updated(*args): updates[0] += 1
        backend._chat_model.dataChanged.connect(updated)
        loop = QEventLoop()
        def beat():
            now = time.perf_counter(); gaps.append((now-previous[0])*1000); previous[0] = now
            if name == 'table' and position[0] > 2000:
                live_table[0] |= record.busy and any('S0' in plain(item) and '| 状态 |' not in plain(item) for item in editors())
        def feed():
            # Replay all chunks that a network producer would have delivered
            # while the GUI was busy; GUI timers themselves cannot run then.
            target = min(len(text), max(32, int((time.perf_counter()-started)/.008)*32))
            while position[0] < target:
                chunk = text[position[0]:min(target, position[0]+32)]
                backend._handle_pi_event(record, {'type':'delta','text':chunk})
                position[0] += len(chunk)
            if position[0] == len(text):
                source.stop()
                backend._handle_pi_event(record, {'type':'message','role':'assistant','text':text})
                backend._handle_pi_event(record, {'type':'done'})
                QTimer.singleShot(450, loop.quit)
        started = time.perf_counter()
        heartbeat = QTimer(); heartbeat.setInterval(10); heartbeat.timeout.connect(beat); heartbeat.start()
        source = QTimer(); source.setInterval(8); source.timeout.connect(feed); source.start()
        timeout = QTimer(); timeout.setSingleShot(True); timeout.setInterval(30000); timeout.timeout.connect(loop.quit); timeout.start()
        loop.exec(); heartbeat.stop(); source.stop(); timeout.stop()
        backend._chat_model.dataChanged.disconnect(updated)
        assert position[0] == len(text) and record.messages[-1]['text'] == text, 'Stream lost content'
        assert not record.busy
        assert updates[0] < (len(text)+31)//32 * .75, 'Every chunk caused a model notification'
        if name == 'table':
            assert live_table[0], 'Table was not rendered as rich Markdown during the stream'
            assert any('S99' in plain(item) and '| 状态 |' not in plain(item) for item in editors()), 'Final table content is incomplete'
        reports.append(dict(scenario=name, chunks=(len(text)+31)//32, row_updates=updates[0], p95_gap_ms=round(sorted(gaps)[int(len(gaps)*.95)],2)))
    assert not warnings, '\n'.join(warnings)
    print('STREAMING_UI_OK: '+json.dumps(reports), flush=True)
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
