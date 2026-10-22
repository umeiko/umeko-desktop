"""Nested Pi search/folds, click-gated scrolling and selectable help popups."""
import os
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('UMEKO_LANGUAGE','zh')
os.environ['UMEKO_DATA_DIR']=tempfile.mkdtemp(prefix='umeko-settings-interaction-')
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
from PySide6.QtCore import Qt,QPoint,QPointF,QMetaObject
from PySide6.QtGui import QWheelEvent
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
def center(item):return item.mapToScene(item.boundingRect().center()).toPoint()
def click(item):
    if isinstance(item,str):item=find(item)
    QTest.qWait(100);QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,center(item));QTest.qWait(100)
def reveal(item):
    QTest.qWait(100)
    y=item.mapToItem(flick,QPointF(0,0)).y()+flick.property('contentY')
    flick.setProperty('contentY',max(0,min(y-80,flick.property('contentHeight')-flick.height())))
    QTest.qWait(100)
def wheel(item,y=-120,x=0):
    pos=QPointF(center(item));event=QWheelEvent(pos,QPointF(window.mapToGlobal(pos.toPoint())),QPoint(),QPoint(x,y),Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
    app.sendEvent(window,event);QTest.qWait(100)
try:
    window.resize(1060,700);window.setProperty('page','settings');window.setProperty('settingsTab',3);QTest.qWait(150)
    flick=find('settingsScroll').property('contentItem');click('openPiSettingsButton')
    assert not find('piFold_runtime').property('opened')
    search=find('piSettingsSearch');search.setProperty('text','自定义指令');QTest.qWait(120)
    assert find('piFold_runtime').isVisible() and find('piFold_context').property('opened')
    assert find('agentInstructions').isVisible() and not find('piFold_kernel').isVisible()
    search.setProperty('text','npm');QTest.qWait(120)
    assert find('piNpmRegistry').isVisible() and not find('piFold_runtime').isVisible()
    search.setProperty('text','no-such-setting-392');QTest.qWait(100)
    assert not find('piFold_kernel').isVisible() and not find('piFold_runtime').isVisible()
    search.setProperty('text','');QTest.qWait(100)
    assert not find('piFold_runtime').property('opened'),'Search overwrote saved collapse state'
    for name in ['piFold_runtime','piFold_context','piFold_management','piFold_recovery']:find(name).setProperty('expanded',True)
    editor=find('agentInstructions');editor.setProperty('text','A long editable instruction\n'*60)
    region=find('agentInstructionsScroll');reveal(region)
    before=flick.property('contentY');inner=region.property('contentItem');inner_before=inner.property('contentY')
    wheel(region)
    assert flick.property('contentY')>before+20,'Inactive editor swallowed global scrolling'
    assert inner.property('contentY')==inner_before
    reveal(region);click(region)
    assert region.property('wheelActive'),'Click did not activate editor scrolling'
    before=flick.property('contentY');wheel(region)
    assert inner.property('contentY')>inner_before+10,'Active editor did not scroll'
    assert abs(flick.property('contentY')-before)<1,'Active editor moved settings page'
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,QPoint(400,90));QTest.qWait(80)
    assert not region.property('wheelActive'),'Outside click did not deactivate editor'
    window.setProperty('settingsTab',1);QTest.qWait(150)
    for i in range(3):assert backend.saveProxyKey('',f'Fixture {i}','')
    table=find('proxyKeysTable');reveal(table);before=flick.property('contentY');wheel(table,120)
    assert flick.property('contentY')<before-20,'API Key table swallowed global scrolling'
    reveal(table);click(table);assert table.property('wheelActive')
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,QPoint(400,90));QTest.qWait(80)
    assert not table.property('wheelActive')
    help_button=find('mappingHelp');reveal(help_button);click(help_button)
    from PySide6.QtCore import QObject
    popup=window.findChild(QObject,'helpTooltip_mappingHelp');assert popup and popup.property('visible')
    text=find('helpText_mappingHelp');pos=text.mapToScene(QPointF(8,8)).toPoint()
    QTest.mouseDClick(window,Qt.LeftButton,Qt.NoModifier,pos);QTest.mouseRelease(window,Qt.LeftButton,Qt.NoModifier,pos);QTest.qWait(100)
    assert text.property('selectedText'),'Help text cannot be selected'
    QTest.mouseMove(window,QPoint(400,90));QTest.qWait(3250)
    assert popup.property('visible'),'Selected help expired'
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,QPoint(400,90));QTest.qWait(100)
    assert not popup.property('visible'),'Outside click did not dismiss selected help'
    QTest.mouseMove(window,center(help_button));QTest.qWait(500)
    assert popup.property('visible') and not help_button.property('bubbleVisited')
    QTest.mouseMove(window,QPoint(400,90));QTest.qWait(550)
    assert not popup.property('visible'),'Unvisited explanation should dismiss in about 0.3 seconds'
    QTest.mouseMove(window,center(help_button));QTest.qWait(500)
    assert popup.property('visible')
    text=popup.property('contentItem');QTest.mouseMove(window,center(text));QTest.qWait(100)
    assert help_button.property('bubbleVisited'),'Entering the explanation was not recorded'
    QTest.mouseMove(window,QPoint(400,90));QTest.qWait(550)
    assert popup.property('visible'),'Visited explanation did not get its 3 second grace period'
    QTest.qWait(2800);assert not popup.property('visible')
    assert not warnings,'\n'.join(warnings)
    print('SETTINGS_INTERACTION_UI_OK: two-level search/folds, editor and key-table wheel gating, selectable persistent help')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
