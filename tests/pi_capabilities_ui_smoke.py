"""Scoped Pi presets/tool switches using the real Widget and embedded runtime."""
import json,os,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
temporary=tempfile.TemporaryDirectory(prefix='umeko-pi-capabilities-');base=Path(temporary.name)
os.environ.update(UMEKO_DATA_DIR=str(base/'profile'),UMEKO_LANGUAGE='zh',QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest,QSignalSpy
from PySide6.QtGui import QEnterEvent
from app.storage import Store
from main import create_application
store=Store();agent=base/'agent';work=base/'work';agent.mkdir();work.mkdir()
store.data['workspace']=str(work);store.data['agent']['agentDir']=str(agent);store.data['agent']['safeMode']=False
store.data.update(providers=[{'id':'fixture','name':'Fixture','api':'openai','baseUrl':'http://127.0.0.1:1/v1','key':'fixture','models':[{'upstream':'fixture','alias':'fixture'}]}],selectedProvider='fixture',selectedModel='fixture')
extension=agent/'capability-fixture.mjs'
extension.write_text("export default pi=>{for(const name of ['fixture_one','fixture_two'])pi.registerTool({name,label:name,description:'Fixture tool '+name,parameters:{type:'object',properties:{}},execute:async()=>({content:[{type:'text',text:'fixture'}]})});};",encoding='utf-8')
(agent/'settings.json').write_text(json.dumps({'extensions':[str(extension)]}),encoding='utf-8')
store.save();app,engine,backend=create_application();window=engine.rootObjects()[0];warnings=[]
engine.warnings.connect(lambda errors:warnings.extend(e.toString() for e in errors));manager=backend.desktopPlugins
def find(name):
    stack=[window.contentItem()]
    while stack:
        item=stack.pop()
        if item.objectName()==name:return item
        stack.extend(item.childItems())
def wait(check,label):
    for _ in range(1000):
        QTest.qWait(20);time.sleep(.001)
        if check():return
    page=find('piManagerWidget')
    output=ROOT/'build/pi-capabilities-ui';output.mkdir(parents=True,exist_ok=True);window.grabWindow().save(str(output/'failure.png'))
    raise AssertionError(label+' '+repr({'notice':page.property('notice') if page else None,'working':page.property('working') if page else None,'sessionBusy':page.property('sessionBusy') if page else None,'profile':backend._view.pi_capabilities,'phase':backend._view.phase,'approval':backend.desktopPlugins._host_services.pendingApproval})+'\n'+'\n'.join(warnings))
def click(name):
    wait(lambda:find(name) is not None and find(name).isEnabled() and ready(),name);item=find(name);window.grabWindow()
    QTest.qWait(120);wait(lambda:ready() and item.isEnabled(),name+' did not settle')
    assert item.isEnabled(),(name,'disabled',find('piManagerWidget').property('sessionBusy'))
    spy=QSignalSpy(item,item.metaObject().method(item.metaObject().indexOfSignal('clicked()')))
    point=item.mapToScene(item.boundingRect().center()).toPoint()
    app.sendEvent(window,QEnterEvent(point,point,window.mapToGlobal(point)))
    QTest.mouseMove(window,point);QTest.qWait(30)
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,point);QTest.qWait(80)
    assert spy.count()==1,(name,'click was not delivered')
def ready():return find('piManagerWidget') is not None and not find('piManagerWidget').property('working') and not backend._view.busy and not backend.kernelBusy
def open_page():
    assert manager.openPage('pi-manager');wait(lambda:find('piManagerWidget') is not None,'Widget failed to load');wait(ready,'Widget did not settle')
    wait(lambda:find('webPane') and not find('webPane').property('moving'),'Widget pane did not settle')
# A persisted native transcript, so reopening exercises metadata restoration.
record=backend._view;record.id='pi-capabilities-fixture'
transcript=store.directory/'pi/sessions/fixture.jsonl';transcript.parent.mkdir(parents=True,exist_ok=True)
transcript.write_text(json.dumps({'type':'session','version':3,'id':record.id,'timestamp':'2026-01-01T00:00:00.000Z','cwd':str(work)})+'\n',encoding='utf-8')
record.file=str(transcript);record.title='Pi fixture';backend._index_record(record)
try:
    window.resize(1480,1000);window.show();window.requestActivate();wait(window.isActive,'Test window did not activate');window.setProperty('page','chat');open_page()
    wait(lambda:find('piToolSwitch_read') is not None and 'toolCatalog' in backend._view.resources and ready(),'Native tools not loaded')
    QTest.qWait(500);wait(ready,'Initial inspection did not settle')
    assert find('piManagerWidget').property('profile')['preset']=='full'
    # One plugin with two tools: a child switch must not disable its sibling.
    search=find('piManagerSearch');search.setProperty('text','capability-fixture')
    wait(lambda:find('piManagerList').property('count')==1 and ready(),'Fixture plugin not found')
    row=next(r for r in backend.piManagement.extensions if r['path']==str(extension))
    assert find('piPreset_full').property('contentItem').property('text')=='默认'
    wait(lambda:find('piExtensionDetails_'+row['id']) is not None,'Details button did not render')
    for scale in (1.0,1.6,2.0):
        backend.setFontScale(scale);QTest.qWait(120)
        details=find('piExtensionDetails_'+row['id']);content=details.property('contentItem')
        icon=next(child for child in content.childItems() if child.isVisible())
        assert abs(details.width()-details.height())<1,(scale,details.width(),details.height())
        assert icon.x()>=-.5 and icon.x()+icon.width()<=content.width()+.5,(scale,icon.x(),icon.width(),content.width())
    backend.setFontScale(1.0);QTest.qWait(150)
    click('piExtension_'+row['id']);wait(lambda:find('piToolSwitch_fixture_one') is not None and ready(),'Plugin tools not expanded')
    click('piToolSwitch_fixture_one');wait(lambda:ready() and 'fixture_one' not in backend._view.resources['tools'],'Plugin tool was not excluded')
    assert 'fixture_two' in backend._view.resources['tools']
    click('piPluginSwitch_'+row['id']);wait(lambda:ready() and 'fixture_two' not in backend._view.resources['tools'],'Parent switch did not exclude the plugin')
    assert find('piToolSwitch_fixture_one') is not None,'Disabled plugin lost its cached tool catalog'
    click('piPluginSwitch_'+row['id']);wait(lambda:ready() and 'fixture_two' in backend._view.resources['tools'],'Plugin was not re-enabled')
    assert 'fixture_one' not in backend._view.resources['tools'],'Re-enabling parent erased child choices'
    search.setProperty('text','');wait(lambda:find('piManagerWidget').property('query')=='' and ready(),'Search did not settle')
    click('piPreset_full');wait(lambda:ready() and backend._view.pi_capabilities['preset']=='full','Full preset did not reset overrides')
    click('piExtension_builtin:pi-tools');wait(lambda:find('piToolSwitch_read') is not None and ready(),'Native tools did not expand')
    for preset,count in [('minimal',4),('standard',8)]:
        click('piPreset_'+preset);wait(lambda:ready() and backend._view.pi_capabilities.get('preset')==preset,'Preset did not apply')
        assert len(backend._view.resources['tools'])==count,backend._view.resources['tools']
    click('piToolSwitch_grep');wait(lambda:ready() and backend._view.pi_capabilities.get('preset')=='custom','Tool switch did not create a custom profile')
    assert 'grep' not in backend._view.resources['tools']
    assert find('piToolSwitch_grep') is not None,'Disabled tool cannot be re-enabled'
    click('piPreset_full');wait(lambda:ready() and backend._view.pi_capabilities['preset']=='full','Full preset failed')
    assert 'umeko_desktop' in backend._view.resources['tools']
    click('piPreset_custom');wait(lambda:ready() and backend._view.pi_capabilities['preset']=='custom','Custom profile was not restored')
    assert 'grep' not in backend._view.resources['tools']
    origin=backend._view;identifier=origin.id;assert identifier
    assert backend.store.data['sessionMeta'][identifier]['piCapabilities']==origin.pi_capabilities
    backend.newSession();open_page();assert find('piManagerWidget').property('profile')['preset']=='full'
    backend._pool.retire(origin);backend._pool.records.pop(origin.key,None)
    backend.openSession(identifier);wait(lambda:not backend._view.busy,'Restored chat did not settle');open_page()
    assert find('piManagerWidget').property('profile')['preset']=='custom'
    icon=next(r for r in manager.rows if r['id']=='pi-manager');assert icon['iconGlyph']=='pi-widget' and not icon.get('iconSource')
    output=ROOT/'build/pi-capabilities-ui';output.mkdir(parents=True,exist_ok=True);window.grabWindow().save(str(output/'capabilities.png'))
    assert not warnings,'\n'.join(warnings)
    print('PI_CAPABILITIES_UI_OK: presets, per-plugin child/parent exclusions, restored custom configuration, chat isolation, themed icon')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine);app.processEvents();temporary.cleanup()
