"""Request and response tabs must expose the recorded HTTP exchange, not a summary."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-request-details-')
os.environ['UMEKO_LANGUAGE'] = 'zh'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QObject, QMetaObject, Q_ARG, Qt
from PySide6.QtTest import QTest
from main import create_application

app, engine, backend = create_application()
# As in the compaction fixture, offscreen UI checks do not depend on a
# continuous rendered-frame budget for asynchronous delegate incubation.
engine.setIncubationController(None)
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))

def find(name, required=True):
    pending = [window.contentItem()]
    while pending:
        item = pending.pop()
        if item.objectName() == name:
            return item
        pending.extend(item.childItems())
    if required:
        raise AssertionError(name)
    return None

def click(name):
    item = find(name)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())
    QTest.qWait(80)

def wait(predicate, label):
    for _ in range(400):
        QTest.qWait(20)
        if predicate(): return
    raise AssertionError(label + '\n' + '\n'.join(warnings))

def show(failure):
    identifier = str(failure).split('[Umeko:', 1)[1].split(']', 1)[0]
    assert QMetaObject.invokeMethod(dialog, 'show', Q_ARG('QVariant', identifier))
    QTest.qWait(150)

try:
    QTest.qWait(150)
    dialog = window.findChild(QObject, 'requestDetailsDialog')
    assert dialog
    original_body = '{"error":{"message":"complete upstream error <tag> 中文\\nsecond line","code":"rate_limit"}}'
    calls = [
        {'request':{'method':'POST','url':'https://example.invalid/auth','body':{'operation':'fixture auth'}},
         'response':{'status':200,'headers':{'X-Request-ID':'auth-fixture'},'body':'earlier response'}},
        {'request':{'method':'POST','url':'https://example.invalid/v1/chat/completions','headers':{'Authorization':'Bearer fixture-secret'},'body':{'model':'fixture','messages':[{'role':'user','content':'full HTTP request'}]}},
         'response':{'status':429,'headers':{'X-Request-ID':'response-fixture','Content-Type':'application/json'},'body':original_body}},
    ]
    failure = backend.gateway.diagnostics.failure({'name':'Fixture','key':'fixture-secret'},
        {'model':'fixture','messages':[{'role':'user','content':'logical request'}]}, calls[-1]['response'], 'fixture transport error', calls)
    # Enter through the actual failed chat row, including a partial completion.
    record = backend._view
    record.id = 'request-details-fixture'
    record.messages = [{'role':'assistant','text':'Partial answer before the failure'}]
    backend._handle_pi_event(record, {'type':'message','role':'assistant','text':record.messages[0]['text'],
                                     'error':str(failure),'stopReason':'error'})
    window.setProperty('page', 'chat')
    wait(lambda:(item := find('requestDetails_0', required=False)) is not None and item.isVisible(), 'Failed chat row lost the request-details button')
    click('requestDetails_0')
    wait(lambda:dialog.property('opened'), 'Chat request-details button did not open the report')
    text = find('requestDetailsText')
    assert text.isVisible() and 'full HTTP request' in text.property('text')
    assert 'complete upstream error' not in text.property('text')
    assert find('requestDetailsHttpCall').isVisible()
    click('requestDetailsResponseTab')
    response = text.property('text')
    assert '429' in response and 'response-fixture' in response and original_body in response
    assert 'fixture transport error' in response and 'full HTTP request' not in response
    assert 'fixture-secret' not in response
    out = ROOT/'artifacts/screenshots'
    out.mkdir(parents=True, exist_ok=True)
    QTest.qWait(300)
    assert window.grabWindow().save(str(out/'request-response-details.png'))
    selector = find('requestDetailsHttpCall')
    selector.setProperty('currentIndex', 0)
    assert QMetaObject.invokeMethod(selector, 'activated', Q_ARG(int, 0))
    QTest.qWait(80)
    assert 'earlier response' in text.property('text') and 'auth-fixture' in text.property('text')
    click('requestDetailsRequestTab')
    assert 'fixture auth' in text.property('text')
    click('copyRequestDetails')
    copied = json.loads(app.clipboard().text())
    assert copied['http'][1]['response']['body'] == original_body
    assert 'fixture-secret' not in app.clipboard().text()
    dialog.close(); QTest.qWait(80)

    # A cold child pane recovers the same failure from its native transcript.
    native = Path(os.environ['UMEKO_DATA_DIR']) / 'child-failure.jsonl'
    native.write_text(json.dumps({'type':'session','id':'child-fixture','cwd':str(ROOT)})+'\n'+json.dumps({
        'type':'message','id':'failed','parentId':None,'message':{'role':'assistant',
        'content':[{'type':'text','text':'Partial child answer'}], 'stopReason':'error','errorMessage':str(failure)}})+'\n',encoding='utf-8')
    backend.subagents.merge(record, {'id':'failed-child','status':'error','outputFile':str(native),'task':'Fixture'})
    backend.subagents.open('failed-child')
    wait(lambda:not backend.subagents.context['loading'] and not find('webPane').property('moving'), 'Child error history did not load')
    wait(lambda:(item := find('subagentRequestDetails_0', required=False)) is not None and item.isVisible(), 'Child request-details button is missing')
    click('subagentRequestDetails_0')
    wait(lambda:dialog.property('opened'), 'Child request-details button did not open the shared report')
    click('requestDetailsResponseTab')
    assert original_body in text.property('text')
    dialog.close(); backend.subagents.closeView()

    # Legacy reports without an HTTP trace still have both independent panes.
    failure = backend.gateway.diagnostics.failure({'name':'Fixture'}, {'messages':['legacy request']},
        {'status':400,'body':'legacy raw server response'}, 'legacy error')
    show(failure)
    assert not find('requestDetailsHttpCall').isVisible()
    assert 'legacy request' in text.property('text')
    click('requestDetailsResponseTab')
    assert 'legacy raw server response' in text.property('text')

    failure = backend.gateway.diagnostics.failure({'name':'Fixture'}, {'messages':['timeout request']}, {}, 'fixture connection timeout')
    show(failure)
    click('requestDetailsResponseTab')
    assert '未收到服务器响应' in text.property('text') and 'fixture connection timeout' in text.property('text')
    backend.setLanguage('en'); QTest.qWait(80)
    assert find('requestDetailsResponseTab').property('text') == 'Response'
    assert 'No response received from the server' in text.property('text')
    assert QMetaObject.invokeMethod(dialog, 'show', Q_ARG('QVariant', '00000000-0000-0000-0000-000000000000'))
    QTest.qWait(100)
    assert 'expired' in text.property('text')
    assert not warnings, '\n'.join(warnings)
    print('REQUEST_DETAILS_UI_OK: partial failure chat/child entry points, request/response tabs, full raw body/status/headers, HTTP selection, redaction, legacy and no-response reports')
finally:
    app.clipboard().clear()
    backend.close(); window.hide()
    QTest.qWait(100)
    import shiboken6
    shiboken6.delete(engine)
