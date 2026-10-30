"""Immediate provider modal, proxy status and localized menu bounds."""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-provider-popup-')
os.environ['UMEKO_LANGUAGE'] = 'en'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QObject, QPointF, QMetaObject, Q_ARG, Qt
from PySide6.QtTest import QTest
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
out = ROOT/'artifacts/screenshots'
out.mkdir(parents=True, exist_ok=True)


def find(name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name: return item
        stack.extend(item.childItems())
    item = window.findChild(QObject, name)
    assert item is not None, name
    return item


def wait(check, label):
    for _ in range(120):
        if check(): return
        QTest.qWait(20)
    raise AssertionError((label, warnings))


def click(name):
    item = find(name)
    scroll = find('settingsScroll').property('contentItem')
    ancestor = item.parentItem()
    while ancestor and ancestor != scroll: ancestor = ancestor.parentItem()
    if ancestor:
        y = item.mapToItem(scroll, QPointF()).y()
        scroll.setProperty('contentY', max(0, min(scroll.property('contentY')+y-scroll.height()/2,
                                                 scroll.property('contentHeight')-scroll.height())))
    QTest.qWait(150)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())


def edit(name, value):
    item = find(name)
    item.setProperty('text', value)
    if name.startswith('providerModel'): QMetaObject.invokeMethod(item, 'textEdited')


try:
    window.resize(1180, 820)
    window.setProperty('page', 'settings'); window.setProperty('settingsTab', 0)
    QTest.qWait(250)
    assert not find('apiProxySidebarStatus').isVisible()
    click('addProviderButton')
    popup = find('providerEditorPopup')
    wait(lambda: popup.property('visible'), 'modal did not open')
    QTest.qWait(30)
    assert popup.property('opacity') == 1 and popup.property('scale') == 1, 'Provider editor faded or scaled in'
    assert popup.property('modal')
    assert find('providerEditor').parentItem() != find('apiProviderAccounts').parentItem()
    assert window.grabWindow().save(str(out/'provider-popup-add-en.png'))
    click('saveProviderButton'); QTest.qWait(100)
    assert popup.property('visible'), 'Invalid provider dismissed the editor'
    for name, value in {'providerName':'Popup fixture', 'providerUrl':'http://127.0.0.1:1/v1',
                        'providerKey':'fixture-only-key', 'providerModelId_0':'fixture-model',
                        'providerModelAlias_0':'fixture-model'}.items(): edit(name, value)
    click('saveProviderButton')
    QTest.qWait(35)
    assert not popup.property('visible'), 'Provider editor still animated after saving'
    wait(lambda: not popup.property('visible'), 'modal did not close')
    assert len(backend.config['providers']) == 1
    provider = backend.config['providers'][0]
    click('editProvider_'+provider['id'])
    wait(lambda: popup.property('visible'), 'edit modal did not open')
    assert find('providerName').property('text') == 'Popup fixture'
    assert not find('providerKey').property('text')
    edit('providerName', 'Popup fixture edited')
    click('saveProviderButton')
    wait(lambda: not popup.property('visible'), 'saved edit did not close')
    assert backend.config['providers'][0]['name'] == 'Popup fixture edited'
    assert backend.store.data['providers'][0]['key'] == 'fixture-only-key'
    click('addProviderButton')
    wait(lambda: popup.property('visible'), 'second modal did not open')
    window.resize(980, 640); backend.setFontScale(2); QTest.qWait(300)
    save = find('saveProviderButton')
    point = save.mapToScene(save.boundingRect().center())
    assert 0 <= point.x() <= window.width() and 0 <= point.y() <= window.height()
    assert popup.property('height') <= window.height()-39
    assert window.grabWindow().save(str(out/'provider-popup-large-font.png'))
    QTest.keyClick(window, Qt.Key_Escape)
    wait(lambda: not popup.property('visible'), 'Escape did not close the editor')
    assert window.property('page') == 'settings', 'Closing the modal also left Settings'
    assert not find('settingsPage').property('editingProvider')
    backend.setFontScale(1); window.resize(1180, 820)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
    assert backend.saveServer(port, True, True, False)
    assert backend.saveProxyKey('', 'Popup fixture', backend.generateProxyKey())
    backend.toggleServer(); QTest.qWait(100)
    assert backend.serverRunning and find('apiProxySidebarStatus').isVisible()
    backend.toggleServer(); QTest.qWait(100)
    assert not find('apiProxySidebarStatus').isVisible()
    window.setProperty('page', 'chat')
    menus = find('sidebarMenus')
    for scale in (0.5, 1, 2):
        backend.setFontScale(scale)
        for kind, popup_name, labels in (
            ('project','projectContextMenu',['contextRevealProject','contextArchiveProject','contextRenameProject']),
            ('session','sessionContextMenu',['contextFork','contextCopyId','contextExportSession'])):
            target = {'kind':kind,'id':'fixture','title':'Fixture','pinned':False,'busy':False,'archived':False}
            assert QMetaObject.invokeMethod(menus, 'openFor', Q_ARG('QVariant',target), Q_ARG('QVariant',{'x':window.width()-12,'y':window.height()-12}))
            menu = find(popup_name)
            wait(lambda: menu.property('visible') and not menu.property('animating'), 'menu did not settle')
            for label in labels:
                text = find(label+'Label')
                assert text.property('paintedWidth') <= text.width()+1, (label,scale,text.width(),text.property('paintedWidth'))
                assert text.height()+1 >= text.property('implicitHeight'), (label,scale,'row clipped')
            assert menu.property('x') >= 0 and menu.property('x')+menu.property('width') <= window.width()+1, (kind,scale,menu.property('x'),menu.property('width'),window.width())
            if scale == 2: window.grabWindow().save(str(out/('sidebar-menu-'+kind+'-en.png')))
            QMetaObject.invokeMethod(menu, 'close'); QTest.qWait(120)
    backend.setFontScale(1)
    prompt = find('promptInput'); prompt.forceActiveFocus()
    sent = []
    original_send = backend._send
    backend._send = lambda text, steering=False: sent.append(text) or False
    try:
        prompt.setProperty('text', 'first'); prompt.setProperty('cursorPosition', 5)
        for key, modifier in ((Qt.Key_Return,Qt.AltModifier),(Qt.Key_Enter,Qt.AltModifier),(Qt.Key_Return,Qt.ShiftModifier)):
            before = prompt.property('text')
            QTest.keyClick(window, key, modifier); QTest.qWait(30)
            assert prompt.property('text') == before+'\n' and not sent
        QMetaObject.invokeMethod(prompt, 'select', Q_ARG(int,0), Q_ARG(int,5))
        QTest.keyClick(window, Qt.Key_Return, Qt.AltModifier); QTest.qWait(30)
        assert prompt.property('text') == '\n\n\n\n' and not sent
        prompt.setProperty('text','Plain Enter sends')
        QTest.keyClick(window, Qt.Key_Return); QTest.qWait(30)
        assert sent == ['Plain Enter sends']
    finally: backend._send = original_send
    assert not warnings, warnings
    print('PROVIDER_POPUP_UI_OK: immediate add/edit/cancel without fade, saved credentials, bounded layout, active-only proxy status, localized menus and Alt/Shift+Enter')
finally:
    backend.close(); window.hide()
    import shiboken6
    shiboken6.delete(engine)
