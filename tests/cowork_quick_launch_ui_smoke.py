"""Real Umeko Qt + real Pi bridge, with a local scripted model and synthetic files."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import time
from xml.sax.saxutils import escape
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                  UMEKO_LANGUAGE='zh', XDG_CACHE_HOME='/tmp/umeko-cowork-cache')

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QTest
from app.storage import Store
from main import create_application


def workbook(path, rows):
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    cells = ''.join(f'<row r="{i}">' + ''.join(
        f'<c r="{chr(65+j)}{i}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
        for j, value in enumerate(row)) + '</row>' for i, row in enumerate(rows, 1))
    with ZipFile(path, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('_rels/.rels', f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets><sheet name="区域汇总" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml', f'<worksheet xmlns="{ns}"><sheetData>{cells}</sheetData></worksheet>')


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='umeko-cowork-launch-') as temp:
        home = Path(temp); work = home / '季度复盘'; work.mkdir()
        original = work / '销售明细.xlsx'
        artifact = work / '区域销售汇总.xlsx'
        workbook(original, [('区域', '销售额 / 元'), ('华东', 128000), ('华南', 96000), ('华北', 72000)])
        requests, errors = [], []
        run_gate, tool_gate, stop_gate = threading.Event(), threading.Event(), threading.Event()

        class Server(ThreadingHTTPServer):
            daemon_threads = True

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                messages = body.get('messages', [])
                tools = [r.get('function', {}).get('name') for r in body.get('tools', [])]
                if 'submit_to_chatbox' not in tools:
                    self.send_error(400)
                    return
                requests.append(body)
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.end_headers()

                    def emit(delta, reason=None):
                        chunk = {'id': 'cowork-fixture', 'object': 'chat.completion.chunk', 'created': 1,
                                 'model': 'fixture-model', 'choices': [
                                     {'index': 0, 'delta': delta, 'finish_reason': reason}]}
                        self.wfile.write(('data: ' + json.dumps(chunk, ensure_ascii=False) + '\n\n').encode())
                        self.wfile.flush()

                    emit({'role': 'assistant'})
                    if any('停止用例' in str(m.get('content')) for m in messages if m['role'] == 'user'):
                        emit({'content': '正在处理停止验收示例。'})
                        stop_gate.wait(35)
                        return
                    if not any(m['role'] == 'tool' for m in messages):
                        emit({'content': '已读取任务，正在准备区域汇总。'})
                        if not run_gate.wait(45):
                            raise AssertionError('Running checkpoint timed out')
                        # Deterministic synthetic providers create the example artifact;
                        # the genuine Pi tool below publishes it to the real conversation.
                        workbook(artifact, [('区域', '销售额 / 元'), ('华东', 128000), ('华南', 96000),
                                            ('华北', 72000), ('合计', 296000)])
                        emit({'tool_calls': [{'index': 0, 'id': 'cowork-artifact', 'type': 'function', 'function': {
                            'name': 'submit_to_chatbox', 'arguments': json.dumps({'items': [{'path':str(artifact)}]})}}]})
                        emit({}, 'tool_calls')
                    else:
                        emit({'content': '区域汇总已完成，共 3 个区域，合计 ¥296,000。'})
                        emit({}, 'stop')
                        tool_gate.set()
                    self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as e:
                    errors.append(repr(e))
        srv = Server(('127.0.0.1', 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        os.environ.update(UMEKO_DATA_DIR=str(home/'profile'), PI_CODING_AGENT_DIR=str(home/'agent'))
        store = Store()
        store.data['agent']['agentDir'] = str(home/'agent')
        store.data['desktop'].update(coworkEnabled=True, autoOpenSubmissions=True)
        store.data['providers'] = [{'id':'fixture', 'name':'本地测试模型','api':'openai',
            'baseUrl':f'http://127.0.0.1:{srv.server_port}/v1', 'key':'',
            'proxy':{'mode':'direct'}, 'models':[{'upstream':'fixture-model','alias':'fixture-model',
                                               'reasoning':False, 'input':['text']}]}]
        store.data['selectedProvider'], store.data['selectedModel'] = 'fixture','fixture-model'
        store.save()
        app, engine, backend = create_application()
        window = engine.rootObjects()[0]
        warnings = []
        engine.warnings.connect(lambda ws: warnings.extend(x.toString() for x in ws))
        window.resize(1370, 820)
        window.requestActivate()

        def items():
            stack = [window.contentItem()]
            while stack:
                item = stack.pop()
                yield item
                stack.extend(item.childItems())
        def named(name):
            return next((x for x in items() if x.objectName() == name), None)
        def vis(name):
            return next((x for x in items() if x.objectName() == name and x.isVisible()), None)
        def wait(fn, detail, secs=20):
            end = time.monotonic() + secs
            while time.monotonic() < end:
                QTest.qWait(30)
                val = fn()
                if val:
                    return val
            raise AssertionError({'detail':detail,'warnings':warnings[-15:],'errors':errors,'toast':backend.lastSendError,
                                  'tool':backend.toolStatus,'requests':len(requests),'launchType':backend.cowork.launchType,
                                  'focus':window.activeFocusItem().objectName() if window.activeFocusItem() else ''})
        def click(item):
            if isinstance(item,str):
                item = wait(lambda:vis(item) and vis(item).isEnabled() and vis(item), 'clickable '+item)
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())
        def key(k, modifier=Qt.NoModifier):
            QTest.keyClick(window, k, modifier)
        def capture(name):
            QTest.mouseMove(window, window.contentItem().boundingRect().center().toPoint())
            QTest.qWait(500)
            assert window.grabWindow().save(str(output / name))
        def prop(name,key):
            item = wait(lambda:vis(name), name)
            return item.property(key)

        text = '按区域汇总销售额，生成一份表格。'
        try:
            backend.setLanguage('zh')
            backend.setTheme('white')
            backend.saveSidebarLayout(220, False)
            QTest.qWait(400)
            click('openCoworkButton')
            wait(lambda:backend.cowork.active and not backend.cowork.activeRole and prop('promptInput','activeFocus'), 'focused home')
            backend.cowork.selectLaunchFolder(str(work))
            assert not backend.cowork.profiles and not requests
            capture('01-Cowork-首页-实测.png')
            point = vis('promptInput').mapToScene(vis('promptInput').boundingRect().center()).toPoint()
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(original))])
            app.sendEvent(window, QDragEnterEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
            app.sendEvent(window, QDragMoveEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
            drop = QDropEvent(QPointF(point), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
            app.sendEvent(window, drop)
            assert drop.isAccepted()
            wait(lambda:len(backend.attachments) == 1, 'native Qt dropped file')
            prop('promptInput','activeFocus')
            vis('promptInput').setProperty('text',text)
            key(Qt.Key_K, Qt.ControlModifier)
            wait(lambda:vis('coworkLauncherInput') and prop('coworkLauncherInput','activeFocus'), 'launcher keyboard focus')
            vis('coworkLauncherInput').setProperty('text','表格')
            wait(lambda:vis('coworkLaunch_data'), 'search finds data role')
            capture('02-Cowork-快捷入口-实测.png')
            key(Qt.Key_Escape)
            wait(lambda:not vis('coworkLauncherInput') and prop('promptInput','activeFocus'), 'Escape restores focus')
            assert backend._view.draft == text and len(backend.attachments) == 1
            key(Qt.Key_K, Qt.ControlModifier)
            wait(lambda:vis('coworkLauncherInput') and prop('coworkLauncherInput','activeFocus'), 'reopen search')
            vis('coworkLauncherInput').setProperty('text','表格')
            wait(lambda:vis('coworkLaunch_data'), 'data row')
            key(Qt.Key_Return)
            wait(lambda:backend.cowork.launchType == 'data' and prop('promptInput','activeFocus'), 'Enter chooses capability')
            assert backend._view.draft == text and len(backend.attachments) == 1 and not requests
            click('openCoworkButton')
            wait(lambda:not backend.cowork.active, 'back to coding')
            key(Qt.Key_K, Qt.ControlModifier)
            wait(lambda:vis('conversationSearchInput') and prop('conversationSearchInput','activeFocus'), 'Coding search unchanged')
            key(Qt.Key_Escape)
            click('openCoworkButton')
            wait(lambda:backend.cowork.active and prop('promptInput','activeFocus'), 'return to Cowork')
            assert backend._view.draft == text and len(backend.attachments) == 1
            key(Qt.Key_Return)
            wait(lambda:backend.running and len(requests) == 1, 'real Pi first send', secs=35)
            assert backend.cowork.role['typeId'] == 'data'
            assert vis('sendButton').property('stopAction')
            user = ''.join(str(m.get('content')) for m in requests[0]['messages'] if m['role']=='user')
            assert text in user and original.name in user
            capture('03-Cowork-运行中-实测.png')
            run_gate.set()
            wait(lambda:tool_gate.is_set() and not backend.busy, 'real Pi delivered', secs=40)
            def find_card():
                return next((x for x in items() if x.isVisible() and x.objectName().startswith('openChatbox_')),None)
            card = wait(find_card, 'genuine artifact card')
            assert not vis('documentSurfaceLoader'), 'No automatic Cowork preview'
            click(card)
            wait(lambda:vis('workbookPreview') and backend.documentPreview.state.get('sheetRows'), 'xlsx opened manually')
            rows = backend.documentPreview.state['sheetRows']
            assert rows[-1] == ['合计','296000'], rows
            capture('04-Cowork-产物预览-实测.png')
            click('closeWebPaneButton')
            wait(lambda:not vis('workbookPreview'), 'close workbook view')
            assert backend.desktopPlugins.openPage('file-tree')
            wait(lambda:vis('desktopPluginSurfaceLoader'), 'Right-sidebar Widget still opens')
            click('closeWebPaneButton')
            window.resize(1060,700)
            click('openCoworkButton')
            wait(lambda:not backend.cowork.active, 'narrow returns to coding')
            click('openCoworkButton')
            wait(lambda:backend.cowork.active and prop('promptInput','activeFocus'), 'narrow home')
            backend.setFontScale(1.5)
            QTest.qWait(300)
            assert vis('composer').width() <= 600 and vis('composer').width() > 280
            assert vis('coworkLaunchDirectory').mapRectToScene(vis('coworkLaunchDirectory').boundingRect()).bottom() < window.height()
            vis('promptInput').setProperty('text', '停止用例')
            key(Qt.Key_Return)
            wait(lambda:backend.running and len(requests) == 3, 'general work does not require selecting capability')
            assert backend.cowork.role['typeId'] == 'general'
            click('sendArea')
            wait(lambda:not backend.busy and backend.turnStatus.get('state') == 'stopped', 'actual cancellation', secs=25)
            assert not errors and not [x for x in warnings if 'Binding loop' in x or 'TypeError' in x], warnings
            print('PASS: real Qt and Pi 1.5.2; home focus, text+file survival, search/locale, one explicit dispatch, running Stop, genuine artifact, manual workbook preview and Widget, minimum width and 150% fonts, real Stop.')
        finally:
            run_gate.set(); stop_gate.set()
            backend.close(); window.close(); QTest.qWait(130)
            srv.shutdown(); srv.server_close()

if __name__ == '__main__':
    run(Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'build/cowork-quick-launch')
