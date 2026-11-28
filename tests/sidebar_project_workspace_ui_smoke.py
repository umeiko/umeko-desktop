"""Verify project name, fold control, Pi workspace and Cowork round trip."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software', UMEKO_LANGUAGE='zh')
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from app.storage import Store
from main import create_application


def test():
    reads = []

    class Model(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            rows = json.loads(self.rfile.read(int(self.headers['Content-Length'])))['messages']
            user = str(next((row['content'] for row in reversed(rows) if row['role']=='user'), ''))
            result = next((str(row['content']) for row in rows if row['role']=='tool' and row.get('tool_call_id')=='probe-b'), '')
            if '校验乙项目' in user and not result:
                delta = {'role':'assistant','tool_calls':[{'index':0,'id':'probe-b','type':'function','function':{'name':'read','arguments':'{"path":"probe.txt"}'}}]}
                reason = 'tool_calls'
            else:
                if result:
                    reads.append(result)
                delta, reason = {'role':'assistant','content':'合成测试完成。'}, 'stop'
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            for chunk, finish in ((delta,None), ({},reason)):
                value = {'id':'workspace-fixture','object':'chat.completion.chunk','created':1,'model':'fixture',
                         'choices':[{'index':0,'delta':chunk,'finish_reason':finish}]}
                self.wfile.write(('data: '+json.dumps(value)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')

    server = ThreadingHTTPServer(('127.0.0.1',0),Model)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='umeko-sidebar-project-') as tmp, patch('app.storage.protect',lambda value,*a,**kw:value):
            base=Path(tmp).resolve()
            first, second = base/'合成甲项目', base/'合成乙项目'
            for folder, marker in ((first,'FIXTURE_WORKSPACE_A'),(second,'FIXTURE_WORKSPACE_B')):
                folder.mkdir(); (folder/'probe.txt').write_text(marker,encoding='utf-8')
            agent=base/'agent'
            os.environ.update(UMEKO_DATA_DIR=str(base/'profile'),PI_CODING_AGENT_DIR=str(agent))
            seed=Store(); seed.default_workspace.mkdir()
            seed.data['desktop']['coworkEnabled']=True
            seed.data['agent'].update(agentDir=str(agent),safeMode=True)
            seed.data['providers']=[{'id':'local','name':'Loopback','api':'openai','key':'fixture-key',
                'baseUrl':f'http://127.0.0.1:{server.server_port}/v1','proxy':{'mode':'direct'},
                'models':[{'upstream':'fixture','alias':'fixture'}]}]
            seed.data.update(selectedProvider='local',selectedModel='fixture'); seed.save()
            app,engine,backend=create_application(); window=engine.rootObjects()[0]; window.resize(1360,850)

            def find(name):
                nodes=[window.contentItem()]
                while nodes:
                    item=nodes.pop()
                    if item.objectName()==name and item.isVisible(): return item
                    nodes.extend(item.childItems())

            def wait(predicate, label):
                deadline=time.monotonic()+25
                while time.monotonic()<deadline:
                    QTest.qWait(20)
                    if result:=predicate(): return result
                raise AssertionError((label,backend._view.workspace,backend.lastSendError,reads))

            def click(name,x=None):
                item=wait(lambda:find(name),name)
                assert item.isEnabled(),name
                point=item.boundingRect().center() if x is None else QPointF(x,item.height()/2)
                QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(point).toPoint())

            def placeholder():
                editor=find('promptInput')
                return editor.property('placeholderText') if editor else ''

            def send(text):
                editor=wait(lambda:find('promptInput'),'composer ready')
                editor.forceActiveFocus(); editor.setProperty('text',text)
                click('sendArea')

            try:
                assert backend.setWorkspace(str(second)) and backend.setWorkspace(str(first))
                a=backend._view
                send('开启甲项目中的已有对话')
                wait(lambda:a.id and a.file and not a.busy and any('合成测试完成' in row.get('text','') for row in a.messages),'native A session')
                assert backend.setWorkspace(str(second))
                backend.openSession(a.id)
                wait(lambda:backend._view is a and first.name in placeholder(),'opening A history refreshes A')
                QTest.qWait(450)
                def project_b(): return next(r for r in backend.projectRows if r.get('path')==str(second))
                ident=project_b()['id']; was=project_b()['collapsed']
                click('toggleProject_'+ident)
                wait(lambda:project_b()['collapsed']!=was,'B chevron changes fold only')
                assert backend._view is a and first.name in placeholder(),placeholder()
                click('sidebarRow_'+ident,x=70)
                wait(lambda:backend._view.workspace==str(second) and backend._view is not a,'B row selects its own draft')
                QTest.qWait(350)
                b=backend._view
                expected=first.name if os.getenv('UMEKO_284_BASELINE')=='1' else second.name
                assert expected in placeholder(),(expected,placeholder(),backend.workspaceName)
                assert backend.workspaceName==second.name and backend.store.data['activeProject']==ident
                if path:=os.getenv('UMEKO_284_SCREEN'):
                    assert window.grabWindow().save(path)
                send('校验乙项目')
                wait(lambda:reads and b.file and not b.busy,'real Pi reading B')
                assert len(reads)==1 and 'FIXTURE_WORKSPACE_B' in reads[0] and 'FIXTURE_WORKSPACE_A' not in reads[0],reads
                header=json.loads(Path(b.file).read_text(encoding='utf-8').splitlines()[0]);assert header['cwd']==str(second),header
                click('openCoworkButton');wait(lambda:backend.cowork.active,'enter Cowork')
                click('openCoworkButton');wait(lambda:not backend.cowork.active and backend._view is b,'restore B from Cowork')
                assert second.name in placeholder(),placeholder()
                print('SIDEBAR_PROJECT_WORKSPACE_UI_OK: fold unchanged; row body selects B; actual Pi read from B; Cowork round trip; initial placeholder '+expected)
            finally:
                window.hide(); backend.close(); app.quit()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)


if __name__=='__main__':
    test()
