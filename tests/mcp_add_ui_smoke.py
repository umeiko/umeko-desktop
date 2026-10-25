"""Add global and project MCP configs through the actual desktop popup."""
import json,os,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
os.environ.setdefault('QT_QUICK_CONTROLS_STYLE','Basic')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QUrl,QMetaObject,Qt,QCoreApplication,QEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest
from app.storage import Store
from main import create_application
with tempfile.TemporaryDirectory(prefix='umeko-mcp-popup-') as temp:
 base=Path(temp);profile=base/'profile';cwd=base/'workspace';cwd.mkdir();agent=base/'agent'
 os.environ['UMEKO_DATA_DIR']=str(profile)
 seed=Store(profile);seed.data['agent']['agentDir']=str(agent);seed.data['agent']['safeMode']=False;seed.data['workspace']=str(cwd);seed.save()
 app,engine,controller=create_application()
 warnings=[]
 engine.warnings.connect(lambda errors:warnings.extend(str(e) for e in errors))
 assert engine.rootObjects();window=engine.rootObjects()[0]
 def find(name):
  pending=[window.contentItem()]
  while pending:
   item=pending.pop()
   if item.objectName()==name:return item
   pending.extend(item.childItems())
  raise AssertionError(name)
 def wait(predicate):
  for _ in range(600):
   QTest.qWait(25)
   if predicate():return
  raise AssertionError(controller.piManagement.installMessage)
 def click(name):
  target=find(name);assert target.property('enabled'),name
  assert QMetaObject.invokeMethod(target,'clicked',Qt.DirectConnection)
 window.setProperty('page','settings');window.setProperty('settingsTab',3);QTest.qWait(300)
 click('openPiSettingsButton')
 find('piFold_extensions').setProperty('expanded',True);find('piFold_mcp').setProperty('expanded',True)
 wait(lambda:not controller.piManagement.busy)
 click('addMcpButton');QTest.qWait(150)
 command=find('mcpInstallCommand');scope=find('mcpInstallScope')
 command.setProperty('text','pi mcp add global-fixture --url http://127.0.0.1:9/mcp')
 out=ROOT/'artifacts/screenshots';out.mkdir(parents=True,exist_ok=True)
 assert window.grabWindow().save(str(out/'mcp-add-popup.png'))
 click('confirmMcpInstallButton');wait(lambda:controller.piManagement.installState in ('succeeded','failed'))
 assert controller.piManagement.installState=='succeeded',controller.piManagement.installMessage
 assert json.loads((agent/'mcp.json').read_text())['mcpServers']['global-fixture']['url']=='http://127.0.0.1:9/mcp'
 scope.setProperty('currentIndex',1)
 command.setProperty('text',json.dumps({'mcpServers':{'project-fixture':{'url':'http://127.0.0.1:9/mcp','enabled':False}}}))
 click('confirmMcpInstallButton');wait(lambda:controller.piManagement.installState in ('succeeded','failed'))
 assert controller.piManagement.installState=='succeeded',controller.piManagement.installMessage
 assert 'project-fixture' in json.loads((cwd/'.pi/mcp.json').read_text())['mcpServers']
 assert 'project-fixture' not in json.loads((agent/'mcp.json').read_text())['mcpServers']
 command.setProperty('text','pi mcp add invalid --url not-a-url')
 before=(cwd/'.pi/mcp.json').read_bytes()
 click('confirmMcpInstallButton');wait(lambda:controller.piManagement.installState in ('succeeded','failed'))
 assert controller.piManagement.installState=='failed'
 assert (cwd/'.pi/mcp.json').read_bytes()==before
 assert not warnings,warnings
 controller._system_tray.mark_quitting()
 controller.close();window.close()
 engine.deleteLater();QCoreApplication.sendPostedEvents(engine,QEvent.DeferredDelete)
 app.processEvents()
 print('MCP_ADD_UI_OK: native command, JSON, scope, invalid input and popup wiring')
