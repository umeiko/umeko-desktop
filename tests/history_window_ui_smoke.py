"""Only prepare the saved viewport and its neighbors; supersede distant requests."""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QMetaObject, Q_ARG, Qt, QTimer, QPointF
from PySide6.QtTest import QTest
from app.transcript_index import Snapshot, PAGE_ROWS
from app.storage import Store
from main import create_application

with tempfile.TemporaryDirectory(prefix='umeko-history-window-') as temporary:
    base = Path(temporary)
    os.environ['UMEKO_DATA_DIR'] = str(base / 'profile')
    source = base / 'history.jsonl'
    with source.open('w', encoding='utf-8') as stream:
        stream.write(json.dumps({'type':'session','id':'fixture','cwd':str(base)})+'\n')
        for i in range(2400):
            text = f'Question {i}' if i % 2 == 0 else f'## Reply {i}\n\n**Formatted** answer.\n\n| Step | Value |\n| --- | --- |\n'+''.join(f'| {j} | value-{i}-{j} |\n' for j in range(30))+'\n```rust\nfn main() { println!("hello"); }\n```'
            stream.write(json.dumps({'type':'message','id':str(i),'parentId':str(i-1) if i else None,
                'message':{'role':'user' if i%2==0 else 'assistant','content':text}},ensure_ascii=False)+'\n')
    app, engine, backend = create_application()
    window = engine.rootObjects()[0]
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    backend._sessions = [{'id':'fixture','file':str(source),'title':'History window','workspace':str(base)}]
    backend.store.data['sessionMeta']['fixture'] = {'viewport':{'row':1200,'offset':0,'follow':False}}

    def find(name):
        stack = [window.contentItem()]
        while stack:
            item = stack.pop()
            if item.objectName() == name: return item
            stack.extend(item.childItems())
        return None

    def wait(check, timeout=20):
        until = time.monotonic()+timeout
        while time.monotonic()<until:
            QTest.qWait(10);time.sleep(.001)
            if check(): return
        raise AssertionError('Timeout: '+str(warnings))

    def jump(row):
        QMetaObject.invokeMethod(view,'jumpToMessage',Qt.DirectConnection,Q_ARG('QVariant',row))

    disk_pages = []
    page = Snapshot.page
    def read(snapshot, number):
        disk_pages.append(number)
        return page(snapshot, number)

    ticks = []
    timer = QTimer();timer.timeout.connect(lambda:ticks.append(time.monotonic()))
    try:
        with patch.object(Snapshot,'page',read):
            timer.start(10)
            started = time.monotonic()
            backend.openSession('fixture')
            wait(lambda: backend.activeSession=='fixture')
            view = find('conversation')
            wait(lambda: not view.property('restoring') and backend.messageModel.isReady(1200))
            opened = time.monotonic()-started
            QTest.qWait(100)
            assert set(disk_pages) <= {49,50,51}, disk_pages
            assert len(backend._chat_model._prepared) <= 16
            assert backend._view.scroll_index==1200, backend._view.scroll_index
            reply = backend.messageModel.message(1201)
            assert any('<table' in str(step.get('_rendered')) for step in reply.get('activity', [])) or '<table' in str(reply.get('_rendered'))
            anchor = find('messageBubble_1200').mapToItem(view,QPointF()).y()
            assert abs(anchor)<2, anchor
            initial_pages = sorted(set(disk_pages))

            # Pause one obsolete range to make the spinner and priority ordering
            # observable, then jump across several distant ranges.
            entered, release = threading.Event(), threading.Event()
            prepared_ranges = []
            prepare = backend._chat_model._presentation.prepare
            def prepare_range(rows, cancelled):
                prepared_ranges.append(min(rows) if rows else -1)
                if 400 in rows:
                    entered.set();release.wait(3)
                return prepare(rows, cancelled)
            with patch.object(backend._chat_model._presentation,'prepare',prepare_range):
                jump(400);wait(entered.is_set)
                spinner = find('historyLoading_400')
                assert spinner and spinner.isVisible() and spinner.property('running')
                for row in (800,1600,2000):jump(row)
                QTest.qWait(60);release.set()
                wait(lambda: backend.messageModel.isReady(2000) and not view.property('restoring'))
                assert not ({800,1600} & set(prepared_ranges)), prepared_ranges
                assert backend._view.scroll_index==2000, backend._view.scroll_index
            assert len(backend._chat_model._prepared)<=16
            assert not find('historyLoading_2000').isVisible()
            # Cached presentation remains theme-independent, selectable, and
            # copyable; neither view state nor prepared HTML enters Pi's file.
            original = source.read_bytes()
            backend.copyChatSelection(json.dumps({'anchor':{'row':2000,'block':-100000,'offset':0},
                'cursor':{'row':2001,'block':2147483647,'offset':0},'expanded':{}}))
            wait(lambda:'value-2001-29' in app.clipboard().text())
            assert 'Formatted' in app.clipboard().text() and 'println!' in app.clipboard().text()
            assert '<html' not in app.clipboard().text()
            backend.setTheme('dark');backend.setFontScale(1.3)
            wait(lambda:not view.property('restoring'))
            assert source.read_bytes()==original

            # Recreate the session record as on a fresh launch, keeping only the
            # persisted viewport and transcript index.
            backend.saveViewport(2000,0,False);backend.store.save()
            assert Store(backend.store.directory).data['sessionMeta']['fixture']['viewport']['row']==2000
            previous = backend._view
            backend.newSession();backend._pool.records.pop(previous.key,None)
            disk_pages.clear();started=time.monotonic()
            backend.openSession('fixture')
            wait(lambda:backend.activeSession=='fixture' and backend.messageModel.isReady(2000) and not view.property('restoring'))
            reopened = time.monotonic()-started
            assert backend._view.transcript.parsed_entries==0
            assert set(disk_pages)<={82,83,84},disk_pages
            assert len(backend._chat_model._prepared)<=16
            timer.stop()
            output=ROOT/'artifacts/history-window';output.mkdir(parents=True,exist_ok=True)
            assert window.grabWindow().save(str(output/'history-window.png'))
            assert not warnings,warnings
            metrics={'rows':2400,'initialSourcePages':initial_pages,'preparedRows':len(backend._chat_model._prepared),
                'coldOpenSeconds':round(opened,3),'restoredOpenSeconds':round(reopened,3),
                'maxGuiTimerGapMs':round(max(b-a for a,b in zip(ticks,ticks[1:]))*1000,1)}
            (output/'metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
            print('HISTORY_WINDOW_UI_OK: saved-position load, bounded render window, background rich Markdown, loading spinner, obsolete ranges skipped, cold-record restoration; '+json.dumps(metrics))
    finally:
        backend.close()
        import shiboken6
        shiboken6.delete(engine)
