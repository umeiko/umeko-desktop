"""A plain hover hint must never swallow a click on the control behind it."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-tooltip-click-')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import Qt, QUrl, QObject
from PySide6.QtQml import QQmlComponent
from PySide6.QtTest import QTest
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
fixture = None
try:
    window.setProperty('page', 'settings')
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(ROOT/'tests/fixtures/tooltip-click.qml')))
    assert not component.isError(), component.errorString()
    fixture = component.create(engine.rootContext())
    assert fixture, component.errorString()
    fixture.setParentItem(window.contentItem())
    fixture.setZ(500)
    QTest.qWait(750)
    button = fixture.findChild(QObject, 'tooltipClickTarget')
    hint = fixture.findChild(QObject, 'overlappingHoverTip')
    assert hint.property('visible')
    tip = hint.property('contentItem')
    center = tip.mapToItem(fixture, tip.boundingRect().center())
    button.setX(center.x() - button.width()/2)
    button.setY(center.y() - button.height()/2)
    QTest.qWait(50)
    point = button.mapToScene(button.boundingRect().center()).toPoint()
    assert tip.contains(tip.mapFromScene(point)), 'Test hint does not cover the target'
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(50)
    assert fixture.property('clicks') == 1, 'Hover hint swallowed the underlying button click'
    print('TOOLTIP_CLICK_UI_OK', flush=True)
finally:
    if fixture:
        fixture.setParentItem(None)
        fixture.deleteLater()
    QTest.qWait(200)
    pending = [window.contentItem()]
    while pending:
        item = pending.pop()
        assert item.objectName() != 'hoverTipContent_overlappingHoverTip', 'Hint outlived its owning control'
        pending.extend(item.childItems())
    component.deleteLater()
    QTest.qWait(100)
    backend.close(); window.hide()
    import shiboken6
    shiboken6.delete(engine)
