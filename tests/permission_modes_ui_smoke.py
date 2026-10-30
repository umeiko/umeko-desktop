"""Real settings controls remain independent; optional Chinese review image."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = Path('C:/UmekoTests/p373-ui') if os.name == 'nt' else Path(tempfile.gettempdir())
BASE.mkdir(parents=True, exist_ok=True)
profile = Path(tempfile.mkdtemp(prefix='permission-settings-', dir=BASE))
os.environ.update(UMEKO_DATA_DIR=str(profile/'data'), PI_CODING_AGENT_DIR=str(profile/'agent'),
                  UMEKO_LANGUAGE='zh', QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                  PI_OFFLINE='1', PI_SKIP_VERSION_CHECK='1')
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest
from app.storage import Store
from main import create_application
import shiboken6

seed = Store()
agent, workspace = profile/'agent', profile/'workspace'
agent.mkdir(); workspace.mkdir()
seed.data['agent']['agentDir'] = str(agent)
seed.data['workspace'] = str(workspace)
seed.save()
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
    raise AssertionError('Missing QML item: '+name)

def wait(predicate, label):
    until = time.monotonic()+60
    while time.monotonic()<until:
        QTest.qWait(10); time.sleep(.01)
        if predicate(): return
    raise AssertionError(label+'\n'+'\n'.join(warnings))

def click(name):
    item = find(name)
    assert item.isVisible() and item.isEnabled(), name
    viewport = find('settingsScroll').property('contentItem')
    top = item.mapToItem(viewport, QPointF(0,0)).y()
    if top < 0 or top+item.height() > viewport.height():
        viewport.setProperty('contentY', max(0, min(viewport.property('contentHeight')-viewport.height(),
                                                 viewport.property('contentY')+top-40)))
        QTest.qWait(60)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier,
                     item.mapToScene(item.boundingRect().center()).toPoint())

def modes():
    saved = Store(backend.store.directory).data['agent']
    return saved['installPermission'], saved['toolPermissionMode']

try:
    window.resize(1360, 1500)
    window.setProperty('page', 'settings'); window.setProperty('settingsTab', 3)
    find('agentPage').setProperty('piOpen', True)
    for name, opened in (('kernel',False),('extensions',True),('packages',True),('mcp',False),
                         ('tools',False),('runtime',True),('context',False),('paths',False),('management',False)):
        find('piFold_'+name).setProperty('expanded', opened)
    wait(lambda: not backend.piManagement.busy, 'Initial scan did not settle')
    QTest.qWait(250)
    wait(lambda: not backend.piManagement.busy and not backend.piManagement._scan_pending,
         'Queued startup scan did not settle')
    assert modes() == ('ask','auto')
    click('toolPermission_ask'); assert modes() == ('ask','ask')
    click('agentExtensionsPermissionAutomatic'); assert modes() == ('automatic','ask')
    click('toolPermission_auto'); assert modes() == ('automatic','auto')
    click('agentExtensionsPermissionAsk'); assert modes() == ('ask','auto')
    # Show both expanded sections in the same offscreen image, including the
    # native extension rows between them. Normal clicks above scroll as needed.
    viewport = find('settingsScroll').property('contentItem')
    window.resize(1360, int(viewport.property('contentHeight'))+320)
    QTest.qWait(200)
    viewport.setProperty('contentY', 0)
    QTest.qWait(60)
    wait(lambda: not backend.piManagement.busy and not backend.piManagement._scan_pending,
         'Settings layout refresh did not settle')
    viewport = find('settingsScroll').property('contentItem')
    for name in ('agentExtensionsPermissionTitle','agentExtensionsPermissionAsk',
                 'agentExtensionsPermissionAutomatic','toolPermissionTitle','toolPermission_ask','toolPermission_auto'):
        item = find(name)
        top = item.mapToItem(viewport, QPointF(0,0)).y()
        assert item.isVisible() and 0<=top and top+item.height()<=viewport.height(), (name,top,viewport.height())
    assert find('agentExtensionsPermissionTitle').property('text') == '扩展包安装权限'
    assert find('toolPermissionTitle').property('text') == '工具执行权限'
    screenshot = os.environ.get('UMEKO_PERMISSION_SCREENSHOT')
    if screenshot:
        assert window.grabWindow().save(screenshot)
    backend.setLanguage('en'); QTest.qWait(50)
    assert find('agentExtensionsPermissionTitle').property('text') == 'Package installation permissions'
    assert find('toolPermissionTitle').property('text') == 'Tool permissions'
    assert not warnings, warnings
    print('PERMISSION_MODES_UI_OK: distinct labels, actual clicks persist independently, both controls visible, zh/en')
finally:
    backend.close()
    shiboken6.delete(engine)
    shutil.rmtree(profile)
