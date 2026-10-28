"""Exercise actual ToolHistory QML translations without a model or app profile."""
import json
import os
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QObject, Property, Signal, QUrl
from PySide6.QtGui import QFont
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import shiboken6

ROOT = Path(__file__).resolve().parents[1]
_application = None


class Display(QObject):
    changed = Signal()

    def __init__(self, tools):
        super().__init__()
        self.rows = tools
        self.locale = 'zh'
        self.open = False

    @Property('QVariantList', notify=changed)
    def tools(self): return self.rows
    @Property(str, notify=changed)
    def language(self): return self.locale
    @Property(bool, notify=changed)
    def detailsOpen(self): return self.open
    @Property(float, constant=True)
    def fontScale(self): return 1.0
    @Property('QVariantMap', constant=True)
    def themeStyle(self): return {'base': 'light', 'colors': {}}
    @Property('QVariantMap', constant=True)
    def config(self): return {'theme': 'light'}


def create_scene(tools):
    global _application
    _application = QApplication.instance() or QApplication([])
    _application.setFont(QFont('sans-serif', 11))
    display = Display(tools)
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    engine.rootContext().setContextProperty('backend', display)
    source = '''import QtQuick
import QtQuick.Controls
import "QML_DIRECTORY" as Umeko
ApplicationWindow {
    width: 1440; height: 1080; visible: true; color: "#fafafa"
    property string probe: JSON.stringify({
        action: history.action("subagent"),
        preview: history.preview(backend.tools[0]), detail: history.detail(backend.tools[0]),
        states: ["queued", "running", "done", "completed", "error", "interrupted", "aborted", "stopped"].map(value => history.agentState(value)),
        types: ["general-purpose", "Explore", "Plan", "custom-agent", ""].map(value => history.agentType(value))
    })
    ScrollView {
        anchors.fill: parent; anchors.margins: 30; contentWidth: availableWidth
        Umeko.ToolHistory {
            id: history; width: parent.width; tools: backend.tools; messageIndex: 0
            expansionState: {
                const details = {}; for (const tool of tools) details[tool.id] = backend.detailsOpen
                return {expanded: true, details: details}
            }
        }
    }
}'''.replace('QML_DIRECTORY', QUrl.fromLocalFile(str(ROOT / 'app/qml')).toString())
    engine.loadData(source.encode('utf-8'))
    assert engine.rootObjects(), warnings
    QTest.qWait(80)
    return _application, engine, display, engine.rootObjects()[0], warnings


class ToolHistoryI18nTests(unittest.TestCase):
    def test_live_language_changes_translate_labels_and_preserve_metadata(self):
        tool = {'id': 'child', 'name': 'subagent', 'state': 'running', 'arguments': {},
                'result': 'Model result', 'subagent': {'type': 'general-purpose',
                    'task': 'User task', 'status': 'running', 'isBackground': True,
                    'toolUses': 3, 'activity': 'Continuing', 'continued': True, 'error': 'Raw error'}}
        original = json.dumps(tool)
        app, engine, backend, window, warnings = create_scene([tool])
        try:
            expected = {
                'zh': ('子代理', '通用 · 运行中 · 后台 · 调用工具 3 次 · User task · 继续执行中',
                       '类型：通用\n任务：User task\n状态：运行中\n模式：后台\n工具调用次数：3\n活动：继续执行中\n已继续：是\n错误：Raw error\n\nModel result',
                       ['排队中', '运行中', '已完成', '已完成', '出错', '已中断', '已取消', '已停止'],
                       ['通用', '探索', '规划', 'custom-agent', '子代理']),
                'en': ('Sub-agent', 'General-purpose · Running · Background · 3 tool uses · User task · Continuing',
                       'Type: General-purpose\nTask: User task\nState: Running\nMode: Background\nTool uses: 3\nActivity: Continuing\nContinued: yes\nError: Raw error\n\nModel result',
                       ['Queued', 'Running', 'Done', 'Done', 'Error', 'Interrupted', 'Aborted', 'Stopped'],
                       ['General-purpose', 'Explore', 'Plan', 'custom-agent', 'Sub-agent'])}
            for language, values in expected.items():
                backend.locale = language; backend.changed.emit(); QTest.qWait(30)
                actual = json.loads(window.property('probe'))
                self.assertEqual([actual[key] for key in ('action', 'preview', 'detail', 'states', 'types')], list(values))
            self.assertEqual(original, json.dumps(tool), 'Display translation mutated stored values')
            # Foreground, argument fallback, whitespace normalization and model-authored activity.
            tool.update(state='', result='', arguments={'type': 'custom-agent', 'task': 'Line 1\nLine 2'})
            tool['subagent'] = {'status': 'queued', 'isBackground': False, 'activity': 'Model activity'}
            backend.rows = [tool]; backend.changed.emit(); QTest.qWait(30)
            actual = json.loads(window.property('probe'))
            self.assertEqual(actual['preview'], 'custom-agent · Queued · Foreground · 0 tool uses · Line 1 Line 2 · Model activity')
            self.assertIn('Activity: Model activity', actual['detail'])
            self.assertNotIn('Continued:', actual['detail'])
            self.assertNotIn('Error:', actual['detail'])
            backend.locale = 'zh'; backend.changed.emit(); QTest.qWait(30)
            actual = json.loads(window.property('probe'))
            self.assertIn('排队中 · 前台 · 调用工具 0 次', actual['preview'])
            self.assertIn('活动：Model activity', actual['detail'])
            self.assertFalse(warnings, warnings)
        finally:
            window.hide(); shiboken6.delete(engine)


if __name__ == '__main__': unittest.main()
