"""Imported palette persistence, update/delete, prompt copy and reply mascot."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.setdefault('UMEKO_LANGUAGE','zh')
os.environ['UMEKO_DATA_DIR']=tempfile.mkdtemp(prefix='umeko-theme-ui-')
os.environ.setdefault('QT_QPA_PLATFORM','offscreen');os.environ.setdefault('QT_QUICK_BACKEND','software')
from PySide6.QtCore import Qt,QUrl,QPointF,QMetaObject
from PySide6.QtTest import QTest
from app.storage import Store
from main import create_application

seed=Store();seed.data['agent']['agentDir']=str(seed.directory/'agent');seed.save()
app,engine,backend=create_application();window=engine.rootObjects()[0]
warnings=[];engine.warnings.connect(lambda errors:warnings.extend(e.toString() for e in errors))
def find(name):
    stack=[window.contentItem()]
    while stack:
        item=stack.pop()
        if item.objectName()==name:return item
        stack.extend(item.childItems())
    raise AssertionError(name)
def click(item):
    if isinstance(item,str):item=find(item)
    QTest.qWait(80);QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(item.boundingRect().center()).toPoint());QTest.qWait(80)
try:
    backend.setTheme('yanami');window.setProperty('page','settings');window.setProperty('settingsTab',3);QTest.qWait(150)
    click('openPiSettingsButton')
    for _ in range(400):
        QTest.qWait(20)
        if not backend.piManagement.busy:break
    find('piFold_management').setProperty('expanded',True);find('piFold_recovery').setProperty('expanded',True);QTest.qWait(200)
    button=find('openPiTerminalButton');stack=[button];glyph=None
    while stack:
        item=stack.pop()
        if item.property('name')=='terminal':glyph=item;break
        stack.extend(item.childItems())
    assert glyph and glyph.property('color').name()=='#ffffff','Primary icon did not follow its text color'
    flick=find('settingsScroll').property('contentItem')
    y=button.mapToItem(flick,QPointF(0,0)).y()+flick.property('contentY')
    flick.setProperty('contentY',max(0,min(y-100,flick.property('contentHeight')-flick.height())));QTest.qWait(300)
    output=ROOT/'artifacts/screenshots/66-primary-icon.png';output.parent.mkdir(parents=True,exist_ok=True);assert window.grabWindow().save(str(output))
    window.setProperty('page','settings');window.setProperty('settingsTab',5);QTest.qWait(150)
    click('copyThemePrompt');prompt=app.clipboard().text()
    assert 'umeko-theme' in prompt and '#RRGGBB' in prompt and 'buttonText' in prompt
    theme=json.JSONDecoder().raw_decode(prompt[prompt.index('{'):])[0]
    file=backend.store.directory/'moon.umeko-theme.json';file.write_text(json.dumps(theme),encoding='utf-8')
    assert backend.importTheme(QUrl.fromLocalFile(str(file)).toString());QTest.qWait(150)
    assert backend.config['theme']=='custom:moon-violet' and backend.config['dark']
    assert window.color().name().lower()==theme['colors']['bg'].lower()
    assert find('theme_custom:moon-violet').isVisible()
    assert Store().data['theme']=='custom:moon-violet' and len(Store().data['themes'])==1
    theme['colors']['bg']='#252033';file.write_text(json.dumps(theme),encoding='utf-8')
    assert backend.importTheme(str(file));QTest.qWait(120)
    assert len(backend.customThemes)==1 and window.color().name()=='#252033'
    click('theme_light');assert not backend.config['dark']
    click('theme_custom:moon-violet');assert backend.config['dark']
    invalid=dict(theme,colors={'bg':'not a color'});file.write_text(json.dumps(invalid),encoding='utf-8')
    assert not backend.importTheme(str(file));assert backend.config['theme']=='custom:moon-violet'
    output=ROOT/'artifacts/screenshots/64-custom-themes.png';output.parent.mkdir(parents=True,exist_ok=True);QTest.qWait(250);assert window.grabWindow().save(str(output))
    click('deleteTheme_custom:moon-violet');assert not backend.customThemes and backend.config['theme']=='dark'
    assert not Store().data['themes']
    backend.setTheme('yanami');window.setProperty('page','chat')
    backend._view.messages=[{'role':'assistant','text':'点一下小八奈见试试。','error':False,'stopReason':'stop'}]
    backend.chatChanged.emit();backend.transcriptChanged.emit();QTest.qWait(350)
    mascot=find('replyEndMascot_0');assert mascot.property('loaded')
    for _ in range(3):click(mascot)
    assert mascot.property('animating') and '饼干' in mascot.property('reaction')
    assert window.grabWindow().save(str(ROOT/'artifacts/screenshots/65-reply-mascot.png'))
    backend.newSession();QTest.qWait(100)
    assert not warnings,'\n'.join(warnings)
    print('THEME_UI_OK: import/apply/update/persist/delete, complete prompt copying and reply mascot click combo')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
