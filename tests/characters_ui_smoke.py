"""Live character replacement, fallback and animated-file playback in real QML."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
profile = tempfile.TemporaryDirectory(prefix='umeko-character-ui-', ignore_cleanup_errors=True)
os.environ['UMEKO_DATA_DIR'] = profile.name
os.environ.setdefault('UMEKO_LANGUAGE','zh')
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
from PySide6.QtCore import QObject, QUrl, QMetaObject
from PySide6.QtQml import QQmlComponent
from PySide6.QtTest import QTest
from main import create_application
from tests.test_characters import GIF

app,engine,backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors:warnings.extend(error.toString() for error in errors))
out = ROOT/'artifacts/screenshots'
out.mkdir(parents=True,exist_ok=True)
def find(name):
    stack=[window.contentItem()]
    while stack:
        item=stack.pop()
        if item.objectName()==name:return item
        stack.extend(item.childItems())
    return window.findChild(QObject,name)

art=component=None
try:
    QTest.qWait(300)
    welcome=find('welcomeMascot')
    assert welcome and welcome.property('loaded')
    assert backend.selectCharacter('komari')
    QTest.qWait(500)
    assert welcome.property('loaded')
    assert len(backend.characterStyle['assets'])==10
    assert window.grabWindow().save(str(out/'character-komari-welcome.png'))
    assert backend._umeko_control.execute({'operation':'characters.select','arguments':{'id':'yanami'}})['ok']
    QTest.qWait(250)
    assert welcome.property('loaded')
    assert backend.characterStyle['assets']=={}
    assert backend.selectCharacter('komari')
    assert backend.configureCharacter(json.dumps({'scenes':{'welcome':{'tap':['UI scene line']}},'subagents':[{'name':'UI Worker','tap':['UI role line']}]}))
    QTest.qWait(150)
    values=welcome.property('tapLines')
    assert (values.toVariant() if hasattr(values,'toVariant') else values)==['UI scene line']
    backend.subagents.merge(backend._view,{'id':'character-ui-role','avatarSlot':0,'status':'completed'})
    assert backend.subagents.agents[0]['name']=='UI Worker'
    assert backend.configureCharacter('{}')
    backend.setLanguage('en')
    QTest.qWait(150)
    QMetaObject.invokeMethod(welcome,'tap')
    assert welcome.property('reactionText').startswith(('Hm?','You can','I\'m')),welcome.property('reactionText')
    backend.setLanguage('zh')
    backend.setTheme('dark')
    assert backend.characterStyle['id']=='komari'
    backend.setTheme('light')

    fixture=Path(profile.name)/'animated'
    fixture.mkdir()
    (fixture/'portrait.gif').write_bytes(GIF)
    manifest={'format':'umeko-character','version':1,'id':'animated-test','name':'Animated',
              'assets':{'welcome':'portrait.gif','reply':'portrait.gif'}}
    (fixture/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    assert backend.importCharacter(str(fixture/'manifest.json'))
    QTest.qWait(350)
    assert welcome.property('loaded')
    previous_source=backend.characterStyle['assets']['welcome']
    manifest['name']='Animated updated'
    (fixture/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    assert backend.importCharacter(str(fixture/'manifest.json')), 'Updating a playing GIF pack failed'
    QTest.qWait(350)
    assert welcome.property('loaded')
    assert backend.characterStyle['name']=='Animated updated'
    assert backend.characterStyle['assets']['welcome']!=previous_source
    component=QQmlComponent(engine,QUrl.fromLocalFile(str(ROOT/'app/qml/CharacterArt.qml')),engine)
    art=component.create()
    assert art,component.errorString()
    art.setProperty('artwork',QUrl.fromLocalFile(str(fixture/'portrait.gif')))
    art.setParentItem(window.contentItem())
    art.setParent(window.contentItem())
    art.setWidth(32);art.setHeight(32)
    QTest.qWait(350)
    assert art.property('frameCount')==2
    assert art.property('playing')
    art.setVisible(False)
    QTest.qWait(100)
    assert not art.property('playing')
    assert backend.selectCharacter('yanami')
    QTest.qWait(150)
    assert welcome.property('loaded')
    assert not warnings,'\n'.join(warnings)
    print('Character UI: Komari, live selection, Yanami fallback, theme independence, two-frame GIF and hidden playback passed')
finally:
    backend.close()
    window.close()
    import shiboken6
    shiboken6.delete(engine)
    profile.cleanup()
