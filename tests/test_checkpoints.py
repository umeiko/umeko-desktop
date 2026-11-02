import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugin-runtime'))
from umeko_plugin_sdk.packages import validate


@unittest.skipUnless(shutil.which('git'), 'Git required')
class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='umeko-checkpoints-')
        self.root = Path(self.temp.name)
        self.work = self.root / '中文 workspace'
        self.work.mkdir()
        self.state = self.root / 'state'
        self.state.mkdir()
        self.target = {'token': 'chat-token', 'id': 'chat-id', 'workspace': str(self.work), 'title': '检查点演示'}
        self.proc = None
        _, defaults, _ = validate(ROOT / 'umeko-plugins/change-review')
        self.config = {**defaults, 'checkpoints': True, 'autoOpen': False}

    def tearDown(self):
        self.stop()
        self.temp.cleanup()

    def start(self):
        self.stop()
        self.proc = subprocess.Popen([sys.executable, '-B', str(ROOT / 'plugin-runtime/worker.py')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        self.call('initialize', {'path': str(ROOT / 'umeko-plugins/change-review'), 'stateDir': str(self.state),
            'config': self.config, 'session': self.target}, initialize=True)

    def stop(self):
        if not self.proc:
            return
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        finally:
            self.proc.stdout.close()
            self.proc.stderr.close()
            self.proc = None

    def call(self, method, arguments, initialize=False, ok=True):
        operation = 'initialize' if initialize else 'call'
        payload = {'id': uuid.uuid4().hex, 'operation': operation,
                   'arguments': arguments if initialize else {'method': method, 'arguments': arguments, 'session': self.target}}
        self.proc.stdin.write(json.dumps(payload) + '\n')
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise AssertionError('Worker stopped')
            value = json.loads(line)
            if value.get('type') == 'event':
                continue
            if ok:
                self.assertTrue(value['ok'], value)
            return value if not ok else value['result']

    def loop(self, identifier, title, changes):
        self.call('begin', {'loopId': identifier})
        for path, content in changes.items():
            target = self.work / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if content is None:
                target.unlink()
            else:
                target.write_text(content, encoding='utf-8')
        return self.call('finish', {'loopId': identifier, 'reason': 'completed', 'title': title})

    def test_history_restart_conflicts_and_recovery(self):
        (self.work / 'src').mkdir()
        (self.work / 'src/app.py').write_text('version = 1\n', encoding='utf-8')
        (self.work / 'obsolete.txt').write_text('remove me\n', encoding='utf-8')
        self.start()
        first = self.loop('loop-one', 'A：第一轮', {'src/app.py': 'version = 2\n', 'src/new.py': 'new = True\n'})
        second = self.loop('loop-two', 'B：第二轮', {'src/app.py': 'version = 3\n', 'src/new.py': None, 'obsolete.txt': None})
        third = self.loop('loop-three', 'C：第三轮', {'src/app.py': 'version = 4\n', 'docs.txt': 'C\n'})
        rows = self.call('timeline', {})['entries']
        self.assertEqual([row['title'] for row in rows], ['C：第三轮', 'B：第二轮', 'A：第一轮', '初始状态'])
        self.assertEqual(self.call('timeline', {})['currentId'], third['checkpointId'])
        old_diff = self.call('diff', {'checkpointId': first['checkpointId'], 'path': 'src/app.py'})['text']
        self.assertIn('-version = 1', old_diff)
        self.assertIn('+version = 2', old_diff)
        self.assertNotIn('version = 3', old_diff)

        self.start()
        self.assertEqual(self.call('timeline', {})['currentId'], third['checkpointId'])
        restored = self.call('restore', {'checkpointId': second['checkpointId'], 'lockToken': uuid.uuid4().hex})
        self.assertTrue(restored['ok'], restored)
        self.assertEqual(restored['currentId'], second['checkpointId'])
        self.assertEqual((self.work / 'src/app.py').read_text(encoding='utf-8'), 'version = 3\n')
        self.assertFalse((self.work / 'src/new.py').exists())
        self.assertFalse((self.work / 'docs.txt').exists())
        self.assertTrue(self.call('timeline', {})['entries'][1]['current'])

        redone = self.call('restore', {'checkpointId': third['checkpointId'], 'lockToken': uuid.uuid4().hex})
        self.assertTrue(redone['ok'], redone)
        self.assertEqual(redone['currentId'], third['checkpointId'])
        self.assertEqual((self.work / 'src/app.py').read_text(encoding='utf-8'), 'version = 4\n')
        self.assertEqual((self.work / 'docs.txt').read_text(encoding='utf-8'), 'C\n')

        self.call('restore', {'checkpointId': second['checkpointId'], 'lockToken': uuid.uuid4().hex})
        fourth = self.loop('loop-four', 'D：第四轮', {'src/app.py': 'version = 5\n'})
        timeline = self.call('timeline', {})
        self.assertEqual([row['title'] for row in timeline['entries']], ['D：第四轮', 'B：第二轮', 'A：第一轮', '初始状态'])
        self.assertEqual(timeline['currentId'], fourth['checkpointId'])
        self.assertNotIn(third['checkpointId'], [row['checkpointId'] for row in timeline['entries']])
        self.assertEqual(timeline['notice'], '已放弃当前点之后的 1 个检查点')
        self.start()
        self.assertEqual(self.call('timeline', {})['currentId'], fourth['checkpointId'])

        historical = self.call('restore', {'checkpointId': first['checkpointId'], 'lockToken': uuid.uuid4().hex})
        self.assertTrue(historical['ok'], historical)
        self.assertEqual((self.work / 'src/app.py').read_text(encoding='utf-8'), 'version = 2\n')
        self.assertEqual((self.work / 'src/new.py').read_text(encoding='utf-8'), 'new = True\n')
        self.assertEqual((self.work / 'obsolete.txt').read_text(encoding='utf-8'), 'remove me\n')
        self.assertFalse((self.work / 'docs.txt').exists())

    def test_restore_preserves_dirty_baseline_and_git_index(self):
        subprocess.check_call(['git', '-C', str(self.work), 'init', '-q'])
        subprocess.check_call(['git', '-C', str(self.work), 'config', 'user.name', 'fixture'])
        subprocess.check_call(['git', '-C', str(self.work), 'config', 'user.email', 'fixture@example.invalid'])
        target = self.work / 'dirty.txt'
        target.write_text('committed\n', encoding='utf-8')
        subprocess.check_call(['git', '-C', str(self.work), 'add', '.'])
        subprocess.check_call(['git', '-C', str(self.work), 'commit', '-qm', 'baseline'])
        target.write_text('staged\n', encoding='utf-8')
        subprocess.check_call(['git', '-C', str(self.work), 'add', '.'])
        target.write_text('user dirty baseline\n', encoding='utf-8')
        index = (self.work / '.git/index').read_bytes()
        self.start()
        result = self.loop('loop-git', '修改 dirty 文件', {'dirty.txt': 'agent rewrite\n', 'added.txt': 'agent\n'})
        origin = next(row for row in self.call('timeline', {})['entries'] if row['kind'] == 'origin')
        restored = self.call('restore', {'checkpointId': origin['checkpointId'], 'lockToken': uuid.uuid4().hex})
        self.assertTrue(restored['ok'], restored)
        self.assertEqual(target.read_text(encoding='utf-8'), 'user dirty baseline\n')
        self.assertFalse((self.work / 'added.txt').exists())
        self.assertEqual((self.work / '.git/index').read_bytes(), index)

    def test_no_change_turn_preserves_future_versions(self):
        (self.work / 'file.txt').write_text('A\n', encoding='utf-8')
        self.start()
        first = self.loop('loop-a', 'A', {'file.txt': 'B\n'})
        second = self.loop('loop-b', 'B', {'file.txt': 'C\n'})
        self.call('restore', {'checkpointId': first['checkpointId'], 'lockToken': uuid.uuid4().hex})
        result = self.loop('loop-empty', '无文件变化', {})
        self.assertEqual(result['checkpointId'], '')
        timeline = self.call('timeline', {})
        self.assertIn(second['checkpointId'], [row['checkpointId'] for row in timeline['entries']])
        self.assertEqual(timeline['currentId'], first['checkpointId'])

    def test_external_edit_is_still_a_conflict(self):
        (self.work / 'file.txt').write_text('before\n', encoding='utf-8')
        self.start()
        result = self.loop('loop-external', 'Agent 修改', {'file.txt': 'agent\n'})
        (self.work / 'file.txt').write_text('user external edit\n', encoding='utf-8')
        plan = self.call('restorePreview', {'checkpointId': result['checkpointId']})
        self.assertEqual(plan['conflicts'], 1)
        response = self.call('restore', {'checkpointId': result['checkpointId'], 'lockToken': uuid.uuid4().hex}, ok=False)
        self.assertFalse(response['ok'])
        self.assertEqual((self.work / 'file.txt').read_text(encoding='utf-8'), 'user external edit\n')

    def test_interrupted_checkpoint_is_visible_but_not_restorable(self):
        (self.work / 'file.txt').write_text('before\n', encoding='utf-8')
        self.start()
        self.call('begin', {'loopId': 'interrupted'})
        (self.work / 'file.txt').write_text('after\n', encoding='utf-8')
        self.start()
        rows = self.call('timeline', {})['entries']
        self.assertEqual(rows[0]['state'], 'interrupted')
        response = self.call('restorePreview', {'checkpointId': rows[0]['checkpointId']}, ok=False)
        self.assertFalse(response['ok'])


if __name__ == '__main__':
    unittest.main()
