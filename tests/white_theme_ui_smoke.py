"""Default white palette, retained grass palette, API selection and custom inheritance."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
profile = tempfile.TemporaryDirectory(prefix='umeko-white-theme-', ignore_cleanup_errors=True)
os.environ.update(UMEKO_DATA_DIR=profile.name, UMEKO_LANGUAGE='zh', PI_CODING_AGENT_DIR=str(Path(profile.name)/'agent'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from app.storage import Store
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
shots = ROOT/'artifacts/screenshots'
shots.mkdir(parents=True, exist_ok=True)


def descendants(root):
    yield root
    for child in root.childItems():
        yield from descendants(child)


def find(name):
    return next(item for item in descendants(window.contentItem()) if item.objectName() == name)


def click(name):
    item = find(name)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())
    QTest.qWait(160)


try:
    QTest.qWait(250)
    assert backend.config['theme'] == 'white' and not backend.config['dark']
    assert window.color().name() == '#ffffff'
    assert not app.windowIcon().isNull() and not backend._system_tray.tray.icon().isNull()
    assert backend.setCharacterEnabled(False)
    window.setProperty('page', 'settings')
    window.setProperty('settingsTab', 5)
    QTest.qWait(200)
    for name in ('white', 'light', 'dark', 'yanami'):
        assert find('theme_'+name).isVisible()
    labels = {item.property('text') for item in descendants(window.contentItem()) if item.isVisible() and isinstance(item.property('text'), str)}
    assert {'纯白', '草绿', '深色', '海盐蓝'} <= labels
    assert window.grabWindow().save(str(shots/'pure-white-theme-picker.png'))
    click('theme_light')
    assert window.color().name() == '#fcfcfa' and Store().data['theme'] == 'light'
    click('theme_white')
    assert window.color().name() == '#ffffff' and Store().data['theme'] == 'white'
    control = backend._umeko_control
    catalog = control.execute({'operation': 'themes.list'})
    assert catalog['ok'] and 'white' in catalog['builtins'], catalog
    for identifier in ('dark', 'white'):
        result = control.execute({'operation': 'themes.select', 'arguments': {'id': identifier}})
        assert result['ok'] and backend.config['theme'] == identifier, result
    custom = Path(profile.name)/'white-theme.json'
    custom.write_text(json.dumps({'format':'umeko-theme', 'version':1, 'id':'blue-white', 'name':'Test white',
                                 'base':'white', 'colors':{'accent':'#2356ce'}}), encoding='utf-8')
    assert backend.importTheme(str(custom))
    QTest.qWait(100)
    assert window.color().name() == '#ffffff'
    backend.removeTheme('custom:blue-white')
    assert backend.config['theme'] == 'white'
    backend.setDark(True)
    backend.setDark(False)
    assert backend.config['theme'] == 'white'
    window.setProperty('page', 'chat')
    QTest.qWait(150)
    click('promptInput')
    # Record the actual focused input and default branding at native UI size.
    QTest.qWait(200)
    assert window.grabWindow().save(str(shots/'pure-white-welcome.png'))
    window.setProperty('page', 'settings')
    window.setProperty('settingsTab', 6)
    QTest.qWait(150)
    assert window.grabWindow().save(str(shots/'pure-white-about.png'))
    assert not warnings, '\n'.join(warnings)
    print('PURE_WHITE_UI_OK: new default, grass preserved, four choices, persistence, public API and custom inheritance')
finally:
    backend.close()
    window.hide()
    import shiboken6
    shiboken6.delete(engine)
    profile.cleanup()
