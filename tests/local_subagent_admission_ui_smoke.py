"""Exercise the desktop-wide native Pi concurrency limit with a gated local model."""
import json, os, re, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software', UMEKO_LANGUAGE='zh')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtQml import QQmlEngine, QQmlExpression
from app.storage import Store
from main import create_application


def run(output):
    begun, gates, launched, errors = [], {}, set(), []
    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            try:
                raw = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                users = [row.get('content', '') for row in raw.get('messages', []) if row.get('role') == 'user']
                latest = str(users[-1] if users else '')
                child_context = any('notify_parent' in str(row.get('content', ''))
                                    for row in raw.get('messages', []) if row.get('role') in ('system', 'developer'))
                child = re.search(r'CHILD_(?:[ADE][0-9]+|B|WARM|COLD)\b', latest) if child_context else None
                job = re.search(r'PARENT_([ABCDE])\b', latest)
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                def emit(delta, reason=None):
                    body={'id':'local-admission','object':'chat.completion.chunk','created':1,'model':'fixture',
                          'choices':[{'index':0,'delta':delta,'finish_reason':reason}]}
                    self.wfile.write(('data: '+json.dumps(body)+'\n\n').encode()); self.wfile.flush()
                emit({'role':'assistant'})
                reason = 'stop'
                if child:
                    tag = child[0]
                    gate = gates.setdefault(tag, Event())
                    begun.append(tag)
                    assert gate.wait(150), tag
                    emit({'content':'合成子执行完成 '+tag})
                elif job and job[1] not in launched and job[1] in 'ABDE':
                    group = job[1]; launched.add(group)
                    tags=['CHILD_B'] if group=='B' else [f'CHILD_{group}{i}' for i in range({'A':11, 'D':5, 'E':8}[group])]
                    emit({'tool_calls':[{'index':i,'id':'call-'+tag,'type':'function','function':{
                        'name':'subagent','arguments':json.dumps({'prompt':tag,'subagent_type':'general-purpose',
                          'description':'合成并发任务 '+str(i+1),'run_in_background':group!='B'})}} for i,tag in enumerate(tags)]})
                    reason = 'tool_calls'
                else:
                    emit({'content':'独立会话正常回复' if job and job[1]=='C' else '协调回复已完成'})
                emit({},reason); self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass
            except Exception as error: errors.append(repr(error))

    server=ThreadingHTTPServer(('127.0.0.1',0),Provider)
    server.daemon_threads=True
    thread=Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        with TemporaryDirectory(prefix='umeko-270-native-') as d, patch('app.storage.protect', lambda value,*a,**kw:value):
            base=Path(d).resolve(); agent=base/'agent'
            os.environ.update(UMEKO_DATA_DIR=str(base/'profile'),PI_CODING_AGENT_DIR=str(agent))
            seed=Store(); seed.default_workspace.mkdir()
            seed.data['agent'].update(agentDir=str(agent),safeMode=True)
            seed.data['providers']=[{'id':'local','name':'Local fixture','api':'openai','key':'fixture-key',
                'baseUrl':f'http://127.0.0.1:{server.server_port}/v1','proxy':{'mode':'direct'},
                'models':[{'upstream':'fixture','alias':'fixture'}]}]
            seed.data.update(selectedProvider='local',selectedModel='fixture'); seed.save()
            app,engine,backend=create_application(); window=engine.rootObjects()[0]; window.resize(1450,920)
            broker=backend._pool.subagent_admission
            def wait(check,label,timeout=35):
                deadline=monotonic()+timeout
                while monotonic()<deadline:
                    QTest.qWait(20)
                    if value:=check(): return value
                    assert not errors, errors
                raise AssertionError((label,begun,len(broker.active),len(broker.waiting),errors))
            def find(name):
                pending=[window.contentItem()]
                while pending:
                    item=pending.pop()
                    if item.objectName()==name and item.isVisible(): return item
                    pending.extend(item.childItems())
            def click(name):
                item=wait(lambda:find(name),name); window.grabWindow()
                QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(item.boundingRect().center()).toPoint())
            def screen(name):
                if output:
                    QTest.qWait(220); assert window.grabWindow().save(str(output/name))
            def expression(item,code):
                expr=QQmlExpression(QQmlEngine.contextForObject(item),item,code); expr.evaluate()
                assert not expr.hasError(), expr.error().toString()
            paths={}
            def parent(name):
                path=paths.setdefault(name,base/name); path.mkdir(exist_ok=True)
                assert backend.setWorkspace(str(path)); backend.newSession(); rec=backend._view
                editor=wait(lambda:find('promptInput'),'main composer'); editor.setProperty('text','PARENT_'+name)
                click('sendArea'); wait(lambda:rec.process is not None,'Pi parent started'); return rec
            def queued(rec):
                return next((row for row in rec.subagents.values() if row['status']=='queued' and '并发名额' in row.get('activity','')),None)
            try:
                assert backend.desktopSettings['subagentConcurrency']==10 and broker.limit==10
                expression(window, 'settings(3)'); QTest.qWait(250)
                click('openPiSettingsButton')
                click('piFold_runtimeToggle')
                if not find('desktopSubagentConcurrency'):
                    click('piFold_contextToggle')
                spin = wait(lambda:find('desktopSubagentConcurrency'), 'concurrency setting in Pi')
                assert spin.property('value') == 10 and spin.property('from') == 1 and spin.property('to') == 20
                screen('270-settings-zh.png')
                spin.forceActiveFocus()
                QTest.keyClick(window, Qt.Key_Up)
                wait(lambda: broker.limit == 11, 'settings control immediately raises cap')
                QTest.keyClick(window, Qt.Key_Down)
                wait(lambda: broker.limit == 10, 'settings control immediately restores cap')
                window.setProperty('page','chat')
                a=parent('A')
                wait(lambda:len([tag for tag in begun if tag.startswith('CHILD_A')])==10 and queued(a), 'Default admits exactly ten, leaves a native queued child')
                assert sum(tag.startswith('CHILD_A') for tag in begun)==10 and len(broker.active)==10
                row_a=queued(a); backend.subagents.open(row_a['id'])
                wait(lambda:find('subagentAdmissionActivity') and not find('webPane').property('moving'),'queued label visible and pane settled')
                screen('270-background-queued-zh.png')
                print('before queued stop', row_a['id'], row_a['task'], backend.subagents.selected.get('id'),
                      len(broker.active), len(broker.waiting), flush=True)
                assert backend.subagents.selected['id'] == row_a['id'] and backend._view is a
                calls = []
                active_before, waiting_before = set(broker.active), set(broker.waiting)
                original_event = broker.event
                def trace(owner, event):
                    key = (owner, event.get('ticket'))
                    original_event(owner, event)
                    if event.get('action') != 'acquire':
                        calls.append((event.get('action'), key in active_before, key in waiting_before))
                backend._pool.event.connect(lambda record, event:
                    print('command-reply', record is a, event, flush=True)
                    if event.get('type') == 'subagent_command' else None)
                with patch.object(backend._pool,'write',wraps=backend._pool.write) as outgoing, patch.object(broker,'event',side_effect=trace):
                    click('stopSubagentButton')
                    QTest.qWait(500)
                    assert any(call.args[1].get('action') == 'stop' and call.args[1].get('id') == row_a['id'] for call in outgoing.call_args_list), outgoing.call_args_list
                    print('stop trace',calls,flush=True)
                print('after queued stop', a.subagents[row_a['id']]['status'], len(broker.active),
                      len(broker.waiting), begun, flush=True)
                wait(lambda:a.subagents[row_a['id']]['status'] in ('stopped','aborted'), 'Queued cancellation appears')
                screen('270-queue-cancelled-zh.png')
                assert not queued(a) and row_a['task'] not in begun
                b=parent('B')
                wait(lambda:queued(b),'Foreground placed in desktop queue across Pi processes')
                row_b=queued(b); assert '前台' in row_b['activity'] and not row_b.get('isBackground')
                assert a.process is not b.process and 'CHILD_B' not in begun
                backend.subagents.open(row_b['id'])
                wait(lambda:find('subagentAdmissionActivity') and '前台执行' in find('subagentAdmissionActivity').property('text')
                     and not find('webPane').property('moving'), 'foreground waiting UI settled')
                screen('270-foreground-queued-zh.png')
                editor=wait(lambda:find('promptInput'),'main composer during foreground wait')
                editor.forceActiveFocus()
                editor.setProperty('text','主会话补充消息')
                QTest.keyClick(window, Qt.Key_Return)
                wait(lambda:any('主会话补充消息' in row.get('text','') for row in b.queue),
                     'main chat accepts a queued follow-up')
                c=parent('C')
                wait(lambda:any('独立会话正常回复' in row.get('text','') for row in c.messages),'independent parent can answer')
                assert backend.saveDesktopSettings('{"subagentConcurrency":1}')
                release=[tag for tag in gates if tag.startswith('CHILD_A')]
                for tag in release[:-1]: gates[tag].set()
                wait(lambda:len(broker.active)==1,'Lowering did not preempt and waits for nine real completions')
                assert 'CHILD_B' not in begun and len(broker.waiting)==1
                assert backend.saveDesktopSettings('{"subagentConcurrency":2}')
                wait(lambda:'CHILD_B' in begun,'Raising frees next FIFO slot')
                assert len(broker.active)==2
                backend.openSession(a.id)
                wait(lambda:backend._view is a, 'return to parent A')
                warm = next(row for row in a.subagents.values() if row['status']=='completed')
                def send_child(record, row, tag):
                    backend.subagents.open(row['id'])
                    wait(lambda:backend.subagents.owner is record and backend.subagents.selected.get('id')==row['id']
                         and not backend.subagents.context.get('loading') and find('subagentPromptInput')
                         and not find('webPane').property('moving'), 'child composer loaded')
                    find('subagentPromptInput').setProperty('text', tag)
                    expression(find('subagentComposer'), 'send(false)')
                def wait_child_queue(tag):
                    wait(lambda:a.subagents[warm['id']]['status']=='queued' and
                         '补充已排队' in a.subagents[warm['id']].get('activity','') and len(broker.waiting)==1,
                         tag+' waiting for its shared slot')
                    assert tag not in begun
                send_child(a,warm,'CHILD_WARM')
                wait_child_queue('CHILD_WARM')
                screen('270-followup-queued-zh.png')
                gates[release[-1]].set()
                wait(lambda:'CHILD_WARM' in begun,'warm continuation starts after a release')
                gates['CHILD_WARM'].set()
                wait(lambda:len(broker.active)==1 and a.subagents[warm['id']]['status']=='completed', 'warm continuation settled')
                assert backend.saveDesktopSettings('{"subagentConcurrency":1}')
                wait(lambda:not a.busy and not a.subagents_active, 'parent is idle before booting a fresh worker')
                backend.subagents.closeView()
                previous=a.process
                backend._pool.retire(a)
                wait(lambda:previous not in backend._pool.retiring and a.process is None, 'old parent Pi process fully exited')
                backend.toast.connect(lambda value: print('app toast', value, flush=True))
                def context_count():
                    return sum(row.get('customType')=='umeko-subagent-context' and row.get('data',{}).get('id')==warm['id']
                        for line in Path(a.file).read_text(encoding='utf-8').splitlines() if line
                        for row in [json.loads(line)])
                context_before = context_count()
                send_child(a,warm,'CHILD_COLD')
                wait(lambda:a.process is not None, 'a fresh parent bridge starts for cold worker')
                wait_child_queue('CHILD_COLD')
                assert a.process is not previous and len(broker.active)==1 and context_count()==context_before
                gates['CHILD_B'].set()
                wait(lambda:'CHILD_COLD' in begun,'cold continuation starts only after B settles')
                gates['CHILD_COLD'].set()
                wait(lambda:len(broker.active)==0 and a.subagents[warm['id']]['status']=='completed'
                     and b.subagents[row_b['id']]['status']=='completed', 'all native runs released')
                assert row_a['task'] not in begun
                assert a.subagents[warm['id']]['outputFile']==warm['outputFile']
                assert begun.count('CHILD_WARM')==begun.count('CHILD_COLD')==1
                assert backend.saveDesktopSettings('{"subagentConcurrency":10}')
                # The pinned package resolves project settings from process.cwd();
                # ordinary desktop workers here use this isolated agent-wide file.
                legacy_settings=agent/'subagents.json'
                legacy_settings.write_text('{"maxConcurrent":3}',encoding='utf-8')
                d=parent('D')
                matching=lambda prefix:[tag for tag in begun if tag.startswith(prefix)]
                wait(lambda:len(d.subagents)==5 and len(matching('CHILD_D'))==3, 'explicit legacy cap admits three')
                legacy_settings.unlink()
                assert len(broker.active)==3 and not broker.waiting
                local_waiters=[row for row in d.subagents.values() if row['status']=='queued']
                assert len(local_waiters)==2 and all('并发名额' not in row.get('activity','') for row in local_waiters)
                cancelled=local_waiters[0]
                backend.subagents.open(cancelled['id'])
                wait(lambda:find('stopSubagentButton') and not find('webPane').property('moving'),'locally queued child can be stopped')
                click('stopSubagentButton')
                wait(lambda:d.subagents[cancelled['id']]['status'] in ('stopped','aborted'),'locally queued cancellation')
                e=parent('E')
                wait(lambda:len(matching('CHILD_E'))==7 and queued(e),'another project can use all seven remaining shared slots')
                assert len(matching('CHILD_D'))==3 and len(broker.active)==10 and len(broker.waiting)==1
                gates[matching('CHILD_D')[0]].set()
                wait(lambda:len(matching('CHILD_E'))==8 and len(broker.waiting)==1,'older shared waiter starts before locally queued work')
                gates[matching('CHILD_E')[0]].set()
                wait(lambda:len(matching('CHILD_D'))==4,'remaining local job gets slot')
                assert cancelled['task'] not in begun
                for gate in gates.values(): gate.set()
                wait(lambda:not broker.active and not broker.waiting,'legacy-limit regression drains')
                print('SUBAGENT_ADMISSION_QT_OK default10; cross-process FIFO; foreground mode preserved; queued cancel; lower/raise; independent parent; warm/cold; explicit legacy 3 plus independent 7; local queue cancel')
            finally:
                for gate in gates.values(): gate.set()
                window.hide(); backend.close(); app.quit()
    finally:
        for gate in gates.values(): gate.set()
        server.shutdown(); server.server_close(); thread.join(timeout=5)

if __name__=='__main__':
    output=Path(sys.argv.pop(1)).resolve() if len(sys.argv)>1 else None
    if output: output.mkdir(parents=True,exist_ok=True)
    run(output)
