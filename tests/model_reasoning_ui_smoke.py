"""Exercise draft model gears, persistence, validation and the real effort slider."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-model-reasoning-')
os.environ['UMEKO_LANGUAGE'] = 'zh'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QObject, QMetaObject, Q_ARG, QPointF, Qt
from PySide6.QtTest import QTest
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
out = ROOT / 'artifacts/screenshots'
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

def click(name):
    item = find(name)
    ancestor = item.parentItem()
    while ancestor:
        if ancestor.property('contentY') is not None and ancestor.property('contentHeight') is not None:
            y = item.mapToItem(ancestor, item.boundingRect().center()).y()
            ancestor.setProperty('contentY', max(0, min(ancestor.property('contentY') + y - ancestor.height() / 2, max(0, ancestor.property('contentHeight') - ancestor.height()))))
        ancestor = ancestor.parentItem()
    QTest.qWait(80)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())
    QTest.qWait(120)

def edit(name, value):
    item = find(name)
    item.setProperty('text', value)
    assert QMetaObject.invokeMethod(item, 'textEdited')

def count(prefix, value):
    item = find(prefix + '_count')
    item.setProperty('value', value)
    assert QMetaObject.invokeMethod(item, 'valueModified')
    QTest.qWait(50)

try:
    window.resize(1200, 850)
    rows = [{'upstream': 'fixture-a', 'alias': 'fixture-a'}, {'upstream': 'fixture-b', 'alias': 'fixture-b', 'reasoningLevels': ['medium', 'xhigh']}]
    assert backend.saveProvider('', '档位配置预览', 'openai', 'http://127.0.0.1:1/v1', 'fixture-only-key', json.dumps(rows))
    provider = backend.config['providers'][0]['id']
    backend.selectModel(provider, 'fixture-a')
    window.setProperty('page', 'settings'); window.setProperty('settingsTab', 0); QTest.qWait(200)
    click('editProvider_' + provider)
    click('providerModelSettings_0')
    popup = find('providerModelReasoning')
    assert popup.property('visible'), (find('providerModelSettings_0').mapToScene(find('providerModelSettings_0').boundingRect().center()), warnings)
    assert find('providerModelReasoning_count').property('value') == 3
    click('providerModelReasoning_increase')
    assert find('providerModelReasoning_count').property('value') == 4
    assert find('providerModelReasoning_name_3')
    for i, name in enumerate(['low', 'medium', 'high', 'xhigh']): edit('providerModelReasoning_name_' + str(i), name)
    QTest.qWait(100)
    assert window.grabWindow().save(str(out / 'model-reasoning-gear.png'))
    click('providerModelReasoning_save')
    assert not popup.property('visible')
    assert backend.reasoningLevels == ['low', 'high', 'max'], 'gear must remain an outer-editor draft'
    click('saveProviderButton')
    assert backend.reasoningLevels == ['low', 'medium', 'high', 'xhigh']
    saved = json.loads((Path(os.environ['UMEKO_DATA_DIR']) / 'settings.json').read_text())
    assert saved['providers'][0]['models'][0]['reasoningLevels'] == backend.reasoningLevels
    click('editProvider_' + provider); click('providerModelSettings_0')
    edit('providerModelReasoning_name_1', 'low'); click('providerModelReasoning_save')
    assert popup.property('visible') and popup.property('error'), 'duplicate must not save'
    click('providerModelReasoning_cancel'); click('cancelProviderButton')
    assert backend.reasoningLevels == ['low', 'medium', 'high', 'xhigh']
    assert backend.setReasoningEffort('high')
    backend.selectModel(provider, 'fixture-b')
    assert backend.reasoningLevels == ['medium', 'xhigh'] and backend.reasoningEffort == 'medium'
    assert not backend.setReasoningEffort('max')
    assert backend.setReasoningEffort('xhigh')
    backend.newSession()
    assert backend.reasoningEffort == 'xhigh'
    # Mapping-page gear is independent of the provider modal and serializes the same data.
    settings = find('settingsPage')
    assert QMetaObject.invokeMethod(settings, 'openMappingProvider', Q_ARG('QVariant', provider))
    QTest.qWait(200)
    gear = find('mappingModelSettings_1')
    assert QMetaObject.invokeMethod(gear, 'clicked')
    count('mappingModelReasoning', 0); click('mappingModelReasoning_save')
    assert QMetaObject.invokeMethod(find('saveMappingsButton'), 'clicked')
    QTest.qWait(150)
    assert backend.reasoningLevels == [] and backend.reasoningEffort == 'off'
    window.setProperty('page', 'chat'); click('modelSelector'); QTest.qWait(700)
    assert not find('reasoningEffortSlider').property('enabled')
    QMetaObject.invokeMethod(find('modelPopup'), 'close'); QTest.qWait(700)
    backend.selectModel(provider, 'fixture-a'); click('modelSelector'); QTest.qWait(700)
    slider = find('reasoningEffortSlider')
    slider.forceActiveFocus(); QTest.keyClick(window, Qt.Key_End); QTest.qWait(100)
    assert backend.reasoningEffort == 'xhigh'
    assert find('reasoningEffortBadge').property('text') == '· xhigh'
    QTest.keyClick(window, Qt.Key_Left); QTest.qWait(100)
    assert backend.reasoningEffort == 'high'
    QTest.keyClick(window, Qt.Key_Home); QTest.qWait(100)
    assert backend.reasoningEffort == 'off'
    # The large handle and ticks must agree with the native Slider hit mapping.
    handle = slider.property('handle')
    for index, level in enumerate(['off', 'low', 'medium', 'high', 'xhigh']):
        x = handle.width()/2 + index/4*(slider.width()-handle.width())
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, slider.mapToScene(QPointF(x, slider.height()/2)).toPoint())
        QTest.qWait(50)
        assert backend.reasoningEffort == level, (index, backend.reasoningEffort)
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, handle.mapToScene(handle.boundingRect().center()).toPoint())
    QTest.mouseMove(window, slider.mapToScene(QPointF(handle.width()/2, slider.height()/2)).toPoint(), 60)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, slider.mapToScene(QPointF(handle.width()/2, slider.height()/2)).toPoint())
    assert backend.reasoningEffort == 'off'
    assert window.grabWindow().save(str(out / 'model-reasoning-slider.png'))
    # Large text must still leave the footer and all fields reachable.
    QMetaObject.invokeMethod(find('modelPopup'), 'close'); QTest.qWait(700)
    window.setProperty('page', 'settings'); window.setProperty('settingsTab', 0); QTest.qWait(150)
    click('editProvider_' + provider); click('providerModelSettings_0')
    backend.setFontScale(2); window.resize(980, 640); QTest.qWait(150)
    save = find('providerModelReasoning_save')
    pt = save.mapToScene(save.boundingRect().center())
    assert 0 <= pt.y() <= window.height() and popup.property('height') <= window.height() - 31
    assert window.grabWindow().save(str(out / 'model-reasoning-large-font.png'))
    count('providerModelReasoning', 32);QTest.qWait(100)
    assert find('providerModelReasoning_name_31')
    count('providerModelReasoning', 0);QTest.qWait(100)
    click('providerModelReasoning_reset');QTest.qWait(100)
    assert find('providerModelReasoning_count').property('value') == 3
    assert not warnings, warnings
    print('MODEL_REASONING_UI_OK: gears, draft/cancel, names/count, persistence, validation, model fallback, off-only, slider pointer/keyboard, font bounds')
finally:
    backend.close(); window.hide()
    import shiboken6
    shiboken6.delete(engine)
