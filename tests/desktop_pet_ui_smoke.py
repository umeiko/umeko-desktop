"""Offscreen Qt rendering and input regression; never controls a user desktop."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
temp=tempfile.TemporaryDirectory(prefix='umeko-pet-ui-')
os.environ.update(UMEKO_DATA_DIR=str(Path(temp.name)/'profile'),PI_CODING_AGENT_DIR=str(Path(temp.name)/'agent'),UMEKO_LANGUAGE='zh',QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software')
from PySide6.QtCore import QObject, QPoint, Qt
from PySide6.QtTest import QTest
from main import create_application

app,engine,backend=create_application()
main=engine.rootObjects()[0]
warnings=[]
engine.warnings.connect(lambda values:warnings.extend(e.toString() for e in values))
pet=backend.desktopPlugins.pet
window=None
out=ROOT/'build/desktop-pet-ui';out.mkdir(parents=True,exist_ok=True)

def find(name):
    stack=[main.contentItem()]
    while stack:
        item=stack.pop()
        if item.objectName()==name:return item
        stack.extend(item.childItems())
    return main.findChild(QObject,name)

def wait(predicate,description):
    for _ in range(400):
        QTest.qWait(20)
        if predicate():return
    raise AssertionError(description+'\n'+'\n'.join(warnings))

try:
    window_loader=main.findChild(QObject,'desktopPetWindowLoader')
    assert pet.running and window_loader.property('item') is None
    # Select the real Widget settings page, not a test-only control surface.
    main.setProperty('settingsTab',3);main.setProperty('page','settings');QTest.qWait(100)
    page=find('desktopPluginsPage');page.setProperty('selectedId','desktop-pet')
    agent=page.parentItem().parentItem();agent.setProperty('pluginsOpen',True)
    wait(lambda:find('desktopPetSettings') is not None,'Pet settings did not load')
    wait(lambda:find('desktopPetAppearancePicker').property('count')==1,'Appearance list did not load')
    main.grabWindow().save(str(out/'settings.png'))
    settings_loader=find('desktopPluginSettingsLoader')
    for identifier in ('git-viewer','file-tree','desktop-pet','git-viewer','desktop-pet'):
        page.setProperty('selectedId',identifier);QTest.qWait(50)
        if identifier=='desktop-pet':
            wait(lambda:find('desktopPetSettings') is not None,'Pet settings did not reload')
            assert settings_loader.isVisible() and settings_loader.height()>0
        else:
            assert not settings_loader.isVisible() and settings_loader.property('item') is None,'Inactive settings reserved a blank area'
            divider=find('desktopPluginSettingsDivider');heading=find('desktopPluginReadmeHeading')
            assert 0<=heading.y()-divider.y()-divider.height()<30,'Widget description was pushed down by an empty settings container'
    pet.ui('show',{})
    wait(lambda:main.findChild(QObject,'desktopPetWindow') is not None,'Pet window did not load')
    window=main.findChild(QObject,'desktopPetWindow')
    loader=window.findChild(QObject,'desktopPetAnimationLoader')
    wait(lambda:window.isVisible() and window.findChild(QObject,'desktopPetAnimation') is not None,'Pet did not show')
    animation=window.findChild(QObject,'desktopPetAnimation')
    wait(lambda:animation.property('ready'),'Animation did not decode')
    assert animation.property('frameCount')>1 and not animation.property('cache')
    first=animation.property('currentFrame');QTest.qWait(180)
    assert animation.property('currentFrame')!=first,'Animation is static'
    window.grabWindow().save(str(out/'pet.png'))
    pet.ui('configure',{'paused':True});QTest.qWait(100)
    frame=animation.property('currentFrame');QTest.qWait(200)
    assert animation.property('currentFrame')==frame,'Pause did not stop playback'
    pet.ui('configure',{'paused':False})
    pointer=window.findChild(QObject,'desktopPetPointer')
    point=pointer.mapToScene(pointer.boundingRect().center()).toPoint()
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,point)
    wait(lambda:bool(window.property('caption')),'Click interaction did not respond')
    original=(window.x(),window.y())
    QTest.mousePress(window,Qt.LeftButton,Qt.NoModifier,point)
    QTest.mouseMove(window,point+QPoint(-25,-15),30)
    QTest.mouseRelease(window,Qt.LeftButton,Qt.NoModifier,point)
    assert (window.x(),window.y())!=original,'Drag did not move window'
    QTest.mouseClick(window,Qt.RightButton,Qt.NoModifier,point)
    menu=window.findChild(QObject,'desktopPetContextMenu')
    wait(lambda:menu.property('opened'),'Context menu did not open')
    menu.close()
    pet.ui('hide',{})
    wait(lambda:window_loader.property('item') is None,'Hidden pet retained decoder')
    assert pet.running and pet.timer.isActive()
    backend.desktopPlugins.setEnabled('desktop-pet',False)
    wait(lambda:not pet.running,'Disabled pet is still observing')
    assert find('desktopPluginSettingsLoader').property('item') is None
    relevant=[w for w in warnings if any(s in w for s in ('DesktopPet','desktop-pet','DesktopPlugin','ReferenceError','TypeError'))]
    assert not relevant,'\n'.join(relevant)
    (out/'result.json').write_text(json.dumps({'settings':'passed','animation':'passed','click':'passed','drag':'passed','contextMenu':'passed','hiddenDecoderReleased':True,'warnings':relevant},indent=2),encoding='utf-8')
    print('Desktop pet offscreen Qt acceptance passed')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
    app.processEvents();temp.cleanup()
