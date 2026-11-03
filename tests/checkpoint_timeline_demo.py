"""Build and exercise a real three-turn checkpoint Timeline demo."""
import json
import os
import shutil
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
interactive = '--interactive' in sys.argv
base = ROOT / 'build/checkpoint-timeline-demo'
if base.exists():
    def writable(function, path, error):
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        function(path)
    shutil.rmtree(base, onerror=writable)
workspace = base / 'workspace'
profile = base / 'profile'
(workspace / 'src').mkdir(parents=True)
(workspace / 'docs').mkdir(parents=True)
os.environ.update(UMEKO_DATA_DIR=str(profile), PI_CODING_AGENT_DIR=str(base / 'agent'), UMEKO_LANGUAGE='zh', QT_QUICK_BACKEND='software', GIT_CEILING_DIRECTORIES=str(base))
if not interactive:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtCore import QObject, QUrl, Qt, QMetaObject
from PySide6.QtTest import QTest
from app.integration import Completion
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
window.resize(1600, 1000)
warnings = []
engine.warnings.connect(lambda values: warnings.extend(value.toString() for value in values))
manager = backend.desktopPlugins
responses = {}
managed = {}
manager.response.connect(lambda request, value: responses.__setitem__(request, value))
manager.managed.connect(lambda request, value: managed.__setitem__(request, value))
out = base / 'screenshots'
out.mkdir(parents=True, exist_ok=True)


def find(name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name:
            return item
        stack.extend(item.childItems())
    return window.findChild(QObject, name)


def wait(predicate, label, attempts=600):
    for _ in range(attempts):
        QTest.qWait(20)
        if predicate():
            return
    window.grabWindow().save(str(out / 'failure.png'))
    raise AssertionError(label + '\n' + '\n'.join(warnings))


def click(name):
    wait(lambda: find(name) is not None, 'Missing control ' + name)
    window.grabWindow()
    item = find(name)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())
    QTest.qWait(100)


def call(method, arguments):
    request = manager.call_for('change-review', method, json.dumps(arguments), session=manager.bridge.snapshot(backend._view))
    assert request, method
    wait(lambda: request in responses, method + ' did not finish')
    assert responses[request]['ok'], responses[request]
    return responses[request]['result']


def capture(name):
    wait(lambda: not find('webPane').property('moving'), 'Timeline pane did not settle')
    QTest.qWait(150)
    window.grabWindow().save(str(out / name))


def restore_result_value(name):
    result = find('changeReviewWidget').property('restoreResult')
    return result.get(name) if hasattr(result, 'get') else result.property(name)


def send(prompt):
    assert backend.send(prompt), backend._last_send_error
    wait(lambda: not backend.busy, 'Agent turn did not finish: ' + prompt)
    assert not backend.messages[-1].get('error'), backend.messages[-1]


def switch_to(row, preview_name=None):
    widget = find('changeReviewWidget')
    for _ in range(4):
        if widget.property('viewMode') == 'timeline':
            break
        click('changeReviewBack')
    click('changeReviewTimelineRow_' + row['checkpointId'])
    click('changeReviewRestore')
    wait(lambda: widget.property('viewMode') == 'restore', 'Version switch preview did not open')
    assert widget.property('restoreReport')['conflicts'] == 0, widget.property('restoreReport')
    if preview_name:
        capture(preview_name)
    click('changeReviewRestoreConfirm')
    wait(lambda: restore_result_value('ok') is True, 'Version switch did not complete')
    assert restore_result_value('currentId') == row['checkpointId']
    wait(lambda: not manager.hostServices.workspace_locked(str(workspace)), 'Workspace lock was not released')


initial = {
    'src/app.py': 'from config import DEFAULT_REGION\n\n\ndef main():\n    print(DEFAULT_REGION)\n\n\nif __name__ == "__main__":\n    main()\n',
    'src/config.py': 'DEFAULT_REGION = "local"\n',
    'src/legacy.py': 'LEGACY_MODE = True\n',
    'docs/usage.md': '# Demo App\n\nRun `python src/app.py`.\n',
}
for name, content in initial.items():
    (workspace / name).write_text(content, encoding='utf-8')


class DemoAdapter:
    def complete(self, model, messages, tools, max_tokens):
        prompt = next(message['content'] for message in reversed(messages) if message['role'] == 'user')
        if isinstance(prompt, list):
            prompt = ' '.join(block.get('text', '') for block in prompt if block.get('type') == 'text')
        if prompt == prompts[0]:
            write('src/app.py', 'from config import load_config\n\n\ndef main():\n    settings = load_config()\n    print(settings["region"])\n\n\nif __name__ == "__main__":\n    main()\n')
            write('src/config.py', 'DEFAULT_REGION = "local"\n\n\ndef load_config():\n    return {"region": DEFAULT_REGION, "debug": False}\n')
            write('docs/usage.md', '# Demo App\n\nRun `python src/app.py`.\n\n## Configuration\n\n`load_config()` loads the local region and debug flag.\n')
            return Completion('已完成配置加载：更新 app.py、config.py，并补充配置文档。')
        if prompt == prompts[1]:
            write('src/app.py', 'from config import load_config\nfrom cache import TTLCache\nfrom logging import StructuredLogger\n\n\ndef main():\n    settings = load_config()\n    cache = TTLCache()\n    logger = StructuredLogger()\n    logger.info("app.start", settings)\n    print(cache)\n\n\nif __name__ == "__main__":\n    main()\n')
            write('src/cache.py', 'import time\n\nDEFAULT_TTL = 60\n\n\nclass TTLCache:\n    def __init__(self, ttl=DEFAULT_TTL):\n        self.ttl = ttl\n        self.values = {}\n\n    def get(self, key):\n        value = self.values.get(key)\n        if not value:\n            return None\n        expires, payload = value\n        return payload if expires >= time.time() else None\n')
            write('src/logging.py', 'import json\nimport time\n\n\nclass StructuredLogger:\n    def info(self, event, fields=None):\n        print(json.dumps({"event": event, "time": time.time(), "fields": fields or {}}))\n')
            write('docs/usage.md', '# Demo App\n\nRun `python src/app.py`.\n\n## Configuration\n\n`load_config()` loads the local region and debug flag.\n\n## Cache and logging\n\nThe app uses a 60-second TTL cache and JSON structured logs.\n')
            return Completion('已加入缓存和结构化日志：新增两个模块，并更新应用入口和文档。')
        if prompt == prompts[2]:
            write('src/cache.py', 'import time\n\nDEFAULT_TTL = 30\n\n\nclass TTLCache:\n    def __init__(self, ttl=DEFAULT_TTL):\n        self.ttl = ttl\n        self.values = {}\n\n    def get(self, key):\n        value = self.values.get(key)\n        if not value:\n            return None\n        expires, payload = value\n        if expires < time.time():\n            self.values.pop(key, None)\n            return None\n        return payload\n')
            write('src/legacy.py', None)
            write('docs/usage.md', '# Demo App\n\nRun `python src/app.py`.\n\n## Configuration\n\n`load_config()` loads the local region and debug flag.\n\n## Cache and logging\n\nThe app uses a 30-second TTL cache and JSON structured logs. Expired entries are removed eagerly.\n')
            return Completion('已修复缓存过期清理策略，将 TTL 调整为 30 秒，并移除 legacy.py。')
        if prompt == prompts[3]:
            write('src/app.py', 'from config import load_config\nfrom cache import TTLCache\nfrom logging import StructuredLogger\n\n\ndef with_retry(operation, attempts=3):\n    for attempt in range(attempts):\n        try:\n            return operation()\n        except RuntimeError:\n            if attempt + 1 == attempts:\n                raise\n\n\ndef main():\n    settings = load_config()\n    cache = TTLCache()\n    logger = StructuredLogger()\n    logger.info("app.start", settings)\n    print(cache)\n\n\nif __name__ == "__main__":\n    main()\n')
            write('docs/usage.md', '# Demo App\n\nRun `python src/app.py`.\n\n## Configuration\n\n`load_config()` loads the local region and debug flag.\n\n## Cache and logging\n\nThe app uses a 30-second TTL cache and JSON structured logs. Expired entries are removed eagerly.\n\n## Retry\n\nTransient operations can be retried up to three times.\n')
            return Completion('已增加最多三次的请求重试，并在文档中记录新的线性版本。')
        raise AssertionError(prompt)


def write(name, content):
    target = workspace / name
    if content is None:
        target.unlink()
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')


prompts = ['实现配置加载并更新使用文档', '加入缓存和结构化日志', '修复缓存过期策略并移除旧模块', '增加请求重试并记录版本历史']

try:
    backend.store.data['providers'].append({'id': 'internal', 'name': 'Demo Fixture', 'api': 'internal', 'baseUrl': '', 'key': '',
        'models': [{'upstream': 'default', 'alias': 'demo-model', 'vision': False, 'visionAuto': False}]})
    backend.selectModel('internal', 'demo-model')
    backend.setWorkspace(QUrl.fromLocalFile(str(workspace)).toString())
    QTest.qWait(150)
    manager.setEnabled('change-review', True)
    request = manager.saveConfig('change-review', json.dumps({'autoOpen': True, 'checkpoints': True, 'maxCheckpoints': 20, 'maxCheckpointMB': 512}))
    wait(lambda: request in managed and not manager.busy, 'Could not enable checkpoints')
    assert managed[request]['ok'], managed[request]
    backend.gateway.adapter = DemoAdapter()
    backend.adapter = backend.gateway.adapter
    backend._restart_pi()
    for index, prompt in enumerate(prompts[:3], 1):
        send(prompt)
        wait(lambda: call('timeline', {})['total'] == index + 1, f'Checkpoint {index} was not persisted')

    assert len(backend.messages) == 6, backend.messages
    assert [row['text'] for row in backend.messages if row['role'] == 'user'] == prompts[:3]
    rows = call('timeline', {})['entries']
    agent_rows = [row for row in rows if row['kind'] == 'agent']
    assert len(agent_rows) == 3 and any(row['kind'] == 'origin' for row in rows)
    first, second, third = agent_rows[2], agent_rows[1], agent_rows[0]
    assert second['title'] == prompts[1]
    manager.openPage('change-review')
    wait(lambda: find('changeReviewTimelineRow_' + second['checkpointId']) is not None, 'Timeline did not render the checkpoints')
    conversation = find('conversation')
    if conversation:
        QMetaObject.invokeMethod(conversation, 'positionViewAtEnd')
    capture('timeline.png')

    click('changeReviewTimelineRow_' + second['checkpointId'])
    wait(lambda: find('changeReviewRow_src') is not None, 'Second checkpoint file tree did not open')
    click('changeReviewRow_src')
    click('changeReviewRow_src/cache.py')
    widget = find('changeReviewWidget')
    wait(lambda: '+DEFAULT_TTL = 60' in widget.property('diff'), 'Second checkpoint did not show its historical cache diff')
    assert 'DEFAULT_TTL = 30' not in widget.property('diff'), 'Historical diff leaked the third turn'
    assert widget.property('selectedCheckpoint') == second['checkpointId']
    capture('history-diff.png')

    switch_to(second, 'restore-preview.png')
    assert 'DEFAULT_TTL = 60' in (workspace / 'src/cache.py').read_text(encoding='utf-8')
    click('changeReviewBack')
    click('changeReviewBack')
    capture('linear-future.png')
    switch_to(third)
    assert 'DEFAULT_TTL = 30' in (workspace / 'src/cache.py').read_text(encoding='utf-8')
    switch_to(second)
    assert 'DEFAULT_TTL = 60' in (workspace / 'src/cache.py').read_text(encoding='utf-8')

    send(prompts[3])
    timeline = call('timeline', {})
    final_agents = [row for row in timeline['entries'] if row['kind'] == 'agent']
    assert [row['title'] for row in final_agents] == [prompts[3], prompts[1], prompts[0]], timeline
    assert third['checkpointId'] not in [row['checkpointId'] for row in timeline['entries']]
    assert timeline['notice'] == '已放弃当前点之后的 1 个检查点', timeline
    assert timeline['futureCount'] == 0 and not timeline['diverged']
    fourth = timeline['currentId']
    manager.closePage()
    manager.stop('change-review')
    restarted = call('timeline', {})
    assert restarted['currentId'] == fourth, 'Current pointer did not survive the worker restart'
    manager.openPage('change-review')
    wait(lambda: find('changeReviewTimelineRow_' + fourth) is not None, 'Linear timeline did not reopen')
    assert next(row for row in restarted['entries'] if row['checkpointId'] == fourth)['current']
    capture('linear-history.png')
    assert len(backend.messages) == 8, backend.messages
    summary = {'sessionId': backend.activeSession, 'messages': len(backend.messages), 'turns': prompts,
        'initialCheckpoints': [{'id': row['checkpointId'], 'title': row['title']} for row in agent_rows],
        'switches': [second['checkpointId'], third['checkpointId'], second['checkpointId']],
        'discardedCheckpoint': third['checkpointId'], 'currentId': fourth,
        'finalTimeline': [{'id': row['checkpointId'], 'title': row['title'], 'current': row['current']} for row in restarted['entries']],
        'workspace': str(workspace), 'profile': str(profile),
        'screenshots': [str(out / name) for name in ('timeline.png', 'history-diff.png', 'restore-preview.png', 'linear-future.png', 'linear-history.png')]}
    (base / 'demo.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    assert not warnings, '\n'.join(warnings)
    print('CHECKPOINT_TIMELINE_DEMO_OK')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if interactive:
        app.exec()
finally:
    backend.close()
    if not interactive:
        import shiboken6
        shiboken6.delete(engine)
        app.processEvents()
