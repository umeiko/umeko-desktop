"""Exercise the real submenu, six brand icons, optional alias and Key-only save."""
import os
import sys
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('UMEKO_LANGUAGE', 'zh')
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-common-provider-ui-')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import Qt, QObject, QUrl, Slot, QPointF
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QTest
from main import create_application
app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
opened_urls = []
class LinkRecorder(QObject):
    @Slot(QUrl)
    def record(self, url): opened_urls.append(url.toString())
recorder = LinkRecorder()
QDesktopServices.setUrlHandler('https', recorder, 'record')
def find(name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name: return item
        stack.extend(item.childItems())
    raise AssertionError(name)
def click(name):
    QTest.qWait(70)
    item = find(name)
    # Focusing the inline editor can scroll Settings. After it collapses,
    # ensure the next real pointer click is inside the viewport on every OS.
    settings = find('settingsScroll').property('contentItem')
    if within(item, settings):
        settings.cancelFlick()
        position = item.mapToItem(settings, QPointF(0, 0))
        top = settings.property('contentY') + position.y() - settings.height() / 2 + item.height() / 2
        settings.setProperty('contentY', max(0, min(top, max(0, settings.property('contentHeight') - settings.height()))))
        QTest.qWait(70)
    # At large text sizes the choices scroll inside the popup.
    if name.startswith('commonProvider_'):
        scroll = find('commonProviderScroll')
        position = item.mapToItem(scroll, QPointF(0, 0))
        scroll.setProperty('contentY', max(0, min(scroll.property('contentY') + position.y() - 30,
                                                scroll.property('contentHeight') - scroll.height())))
        QTest.qWait(70)
    # ScrollView can still be fixing its content bounds after the editor
    # disappears. A press during that motion only stops the flick.
    previous = None
    stable = 0
    for _ in range(40):
        QTest.qWait(25)
        target = item.mapToScene(item.boundingRect().center()).toPoint()
        current = (target.x(), target.y(), item.width(), item.height())
        stable = stable + 1 if current == previous and not settings.property('moving') else 0
        previous = current
        if stable >= 4: break
    assert stable >= 4, (name, 'Click target did not settle', previous)
    QTest.mouseMove(window, target)
    QTest.qWait(100)
    target = item.mapToScene(item.boundingRect().center()).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, target, delay=50)
    QTest.qWait(100)
    if name == 'addCommonProviderButton':
        dialog = window.findChild(QObject, 'commonProviderDialog')
        if not dialog or not dialog.property('visible'):
            window.grabWindow().save(str(ROOT/'artifacts/screenshots/common-provider-open-failed.png'))
        assert dialog and dialog.property('visible'), 'Add common provider did not open the popup'
def choose_international():
    click('commonProviderRegion')
    assert find('commonProviderRegion').property('count') == 2
    QTest.keyClick(window, Qt.Key_End)
    QTest.keyClick(window, Qt.Key_Return)
    QTest.qWait(100)
    assert find('commonProviderRegion').property('currentIndex') == 1
def within(item, parent):
    while item:
        if item == parent: return True
        item = item.parentItem()
    return False
try:
    window.resize(1100, 780); window.setProperty('page', 'settings'); window.setProperty('settingsTab', 0)
    QTest.qWait(200)
    assert find('commonProvidersSection').parentItem() == find('apiProvidersSection').parentItem()
    assert within(find('addCommonProviderButton'), find('commonProvidersSection'))
    assert not within(find('addCommonProviderButton'), find('apiProvidersSection'))
    out = ROOT/'artifacts/screenshots'; out.mkdir(parents=True, exist_ok=True)
    assert window.grabWindow().save(str(out/'provider-sections.png'))
    click('addCommonProviderButton')
    dialog = window.findChild(QObject, 'commonProviderDialog')
    assert dialog.property('visible')
    for preset in backend.commonProviders: assert find('commonProvider_'+preset['id']).isVisible()
    assert window.grabWindow().save(str(out/'common-provider-menu.png'))
    for preset in backend.commonProviders:
        click('commonProvider_' + preset['id'])
        assert find('commonProviderKeyLink').property('targetUrl') == preset['keyUrl']
        click('commonProviderKeyLink')
        assert opened_urls[-1] == preset['keyUrl']
        click('commonProviderBack')
    click('commonProvider_kimi')
    assert not find('confirmCommonProvider').property('enabled')
    find('commonProviderKey').setProperty('text', 'fixture-key')
    find('commonProviderAlias').setProperty('text', 'Work')
    assert find('commonProviderNamePreview').property('text') == 'Kimi(Work)'
    assert window.grabWindow().save(str(out/'common-provider-key.png'))
    click('commonProviderBack'); click('commonProvider_codex')
    assert find('commonProviderKey').property('text') == ''
    find('commonProviderKey').setProperty('text', 'fixture-key')
    click('confirmCommonProvider')
    assert not dialog.property('visible')
    provider = backend.store.data['providers'][-1]
    assert (provider['name'], provider['wireApi']) == ('Codex', 'responses')
    assert backend.config['selectedProvider'] == provider['id']
    assert within(find('editProvider_' + provider['id']), find('commonProvidersSection'))
    assert not within(find('editProvider_' + provider['id']), find('apiProvidersSection'))
    click('editProvider_' + provider['id'])
    assert within(find('providerEditor'), find('commonProvidersSection'))
    assert find('providerKey').property('text') == ''
    assert find('providerName').property('text') == 'Codex'
    click('editProvider_' + provider['id'])
    click('addCommonProviderButton'); click('commonProvider_codex')
    find('commonProviderKey').setProperty('text', 'fixture-key-2'); click('confirmCommonProvider')
    assert backend.store.data['providers'][-1]['name'] == 'Codex(2)'
    for preset_id, region, name in [('glm', 'cn', 'GLM'), ('glm', 'international', 'Z.ai'),
                                    ('minimax', 'cn', 'MiniMax'), ('minimax', 'international', 'MiniMax')]:
        click('addCommonProviderButton'); click('commonProvider_' + preset_id)
        check = find('commonProviderRegion')
        assert check.isVisible() and check.property('currentIndex') == 0, 'Region choice did not reset'
        assert check.property('currentText') == ('zcode.z.ai/cn（中国大陆）' if preset_id == 'glm' else 'platform.minimax.cn（中国大陆）')
        international = region == 'international'
        alias = 'Global' if international else 'Work'
        if international:
            find('commonProviderKey').setProperty('text', 'key-for-other-region')
            find('commonProviderAlias').setProperty('text', alias)
            if preset_id == 'glm':
                click('commonProviderRegion')
                assert window.grabWindow().save(str(out/'glm-region-options.png'))
                QTest.keyClick(window, Qt.Key_Escape); QTest.qWait(80)
            choose_international()
            assert check.property('currentIndex') == 1
            assert check.property('currentText') == ('z.ai（国际）' if preset_id == 'glm' else 'platform.minimax.io（国际）')
            assert find('commonProviderKey').property('text') == ''
            assert find('commonProviderAlias').property('text') == alias
            assert not find('confirmCommonProvider').isEnabled()
            preset = next(p for p in backend.commonProviders if p['id'] == preset_id)['international']
            assert find('commonProviderKeyLink').property('targetUrl') == preset['keyUrl']
            click('commonProviderKeyLink'); assert opened_urls[-1] == preset['keyUrl']
        assert find('commonProviderKeyHint').property('text') == ('填写国际站订阅 Key，即可添加使用。' if international else '填写国内站订阅 Key，即可添加使用。')
        if preset_id == 'glm':
            assert window.grabWindow().save(str(out/('glm-' + region + '-subscription-key.png')))
        find('commonProviderKey').setProperty('text', 'fixture-subscription-key')
        find('commonProviderAlias').setProperty('text', alias)
        assert find('commonProviderNamePreview').property('text') == name + '(' + alias + ')'
        click('confirmCommonProvider')
        provider = backend.store.data['providers'][-1]
        assert (provider['name'], provider['presetId'], provider['presetRegion']) == (name + '(' + alias + ')', preset_id, region)
        click('addCommonProviderButton'); click('commonProvider_' + preset_id)
        if international: choose_international()
        find('commonProviderKey').setProperty('text', 'fixture-subscription-key-2')
        click('confirmCommonProvider')
        assert backend.store.data['providers'][-1]['name'] == name + ('(3)' if preset_id == 'minimax' and international else '(2)')
    assert len(backend.commonProviders) == 6
    click('addCommonProviderButton'); click('commonProvider_kimi')
    assert not find('commonProviderRegion').isVisible()
    click('commonProviderBack'); click('commonProvider_glm')
    choose_international(); click('commonProviderBack'); click('commonProvider_glm')
    assert find('commonProviderRegion').property('currentIndex') == 0
    dialog.close()
    backend.setLanguage('en'); click('addCommonProviderButton')
    assert window.grabWindow().save(str(out/'common-provider-menu-english.png'))
    dialog.close(); backend.setTheme('dark'); click('addCommonProviderButton')
    assert window.grabWindow().save(str(out/'common-provider-menu-dark.png'))
    dialog.close()
    assert not warnings, warnings
    print('COMMON_PROVIDERS_UI_OK: submenu, icons, Key-only accounts, alias, numbering, language and dark theme')
finally:
    QDesktopServices.unsetUrlHandler('https')
    backend.close(); window.hide()
    import shiboken6
    shiboken6.delete(engine)
