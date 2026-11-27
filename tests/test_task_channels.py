import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.task_channels import project_request, read_child_history


SESSION = '0' * 8 + '-1111-7777-8111-' + '1' * 12
LEAD = 'agent:' + 'a' * 32
TARGET = 'session:' + SESSION
FIRST, SECOND = '1' * 32, '2' * 32


def entry(entry_id, parent_id, kind, **values):
    return {'type': kind, 'id': entry_id, 'parentId': parent_id, **values}


def receipt(entry_id, parent_id, request, target=TARGET):
    return entry(entry_id, parent_id, 'custom_message', customType='umeko-widget-update',
                 details={'widgetId': 'global-agents', 'widgetEventId': 'f' * 32, 'requestId': request,
                          'data': {'bridgeRequestId': request, 'source': LEAD, 'target': target,
                                   'status': 'queued', 'task': '合成任务 ' + request}})


def assistant(entry_id, parent_id, tool_name, call_id, arguments=None):
    return entry(entry_id, parent_id, 'message', message={'role': 'assistant', 'stopReason': 'toolUse',
                 'content': [{'type': 'toolCall', 'id': call_id, 'name': tool_name,
                              'arguments': arguments or {}}]})


def write(file, rows):
    file.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')


class ChannelProjectionTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix='umeko-channel-projection-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.parent = self.root / 'parent.jsonl'
        self.child_root = self.root / 'parent' / 'tasks'
        self.child_root.mkdir(parents=True)
        self.rows = [entry(SESSION, None, 'session', cwd=str(self.workspace))]

    def add_child(self, key, owner, after, *, recorded=True, path=None, artifact=None):
        native_id = key.lower() * 16
        file = path or self.child_root / f'{key}.jsonl'
        msgs = [entry(native_id, None, 'session', parentSession=SESSION, cwd=str(self.workspace)),
                entry('prompt', None, 'message', message={'role': 'user', 'content': '合成执行 ' + key})]
        if artifact:
            msgs.extend([assistant('write', 'prompt', 'write', 'save', {'path': str(artifact), 'content': '内容'}),
                         entry('saved', 'write', 'message', message={'role': 'toolResult',
                               'toolCallId': 'save', 'toolName': 'write', 'isError': False})])
        msgs.append(entry('result', 'saved' if artifact else 'prompt', 'message',
                          message={'role': 'assistant', 'content': '合成结果 ' + key}))
        write(file, msgs)
        child = {'id': key, 'type': 'general-purpose', 'task': key, 'status': 'completed',
                 'outputFile': str(file)}
        ref = entry(key + '-ref', after, 'custom', customType='umeko-subagent',
                    data={'version': 1, 'ownerEntryId': owner, 'toolCallId': owner + '-call',
                          'tool': {'id': 'subagent:' + key, 'name': 'subagent', 'subagent': child}})
        self.rows.append(ref)
        if recorded:
            self.rows.append(entry(key + '-record', ref['id'], 'custom', customType='subagents:record',
                                   data={'id': key, 'outputFile': str(file)}))
        return native_id, file

    def project(self, request):
        write(self.parent, self.rows)
        return project_request(self.parent, (request, LEAD, TARGET), self.workspace)[1]

    def test_same_named_role_and_same_parent_do_not_merge_distinct_requests(self):
        self.rows.extend([receipt('first', None, FIRST), assistant('a', 'first', 'subagent', 'a-call')])
        a, _ = self.add_child('a', 'a', 'a')
        self.rows.append(assistant('b', 'a-record', 'subagent', 'b-call'))
        b, bpath = self.add_child('b', 'b', 'b')
        self.rows.extend([receipt('second', 'b-record', SECOND), assistant('c', 'second', 'subagent', 'c-call')])
        c, _ = self.add_child('c', 'c', 'c')
        self.rows.extend([entry('human', 'c-record', 'message', message={'role': 'user', 'content': FIRST}),
                          assistant('d', 'human', 'subagent', 'd-call')])
        self.add_child('d', 'd', 'd')
        self.assertEqual({k: r['sessionId'] for k, r in self.project(FIRST).items()}, {'a': a, 'b': b})
        self.assertEqual({k: r['sessionId'] for k, r in self.project(SECOND).items()}, {'c': c})
        history = read_child_history(bpath, (FIRST, 'b', b), SESSION, self.workspace)
        self.assertEqual([row['text'] for row in history], ['合成执行 b', '合成结果 b'])

    def test_unknown_owner_or_mismatched_receipt_is_not_a_subtask(self):
        self.rows.extend([receipt('other-target', None, FIRST, 'session:' + '2' * 32),
                          assistant('a', 'other-target', 'subagent', 'a-call')])
        self.add_child('a', 'a', 'a')
        self.rows.extend([receipt('second', 'a-record', SECOND),
                          assistant('b', 'second', 'read', 'b-call')])
        self.add_child('b', 'b', 'b')
        self.assertEqual(self.project(FIRST), {})
        self.assertEqual(self.project(SECOND), {})

    def test_native_pointer_and_workspace_artifact_are_revalidated(self):
        output = self.workspace / '合成记录.md'
        output.write_text('内容', encoding='utf-8')
        self.rows.extend([receipt('request', None, FIRST), assistant('a', 'request', 'subagent', 'a-call')])
        self.add_child('a', 'a', 'a', artifact=output)
        self.rows.append(assistant('b', 'a-record', 'subagent', 'b-call'))
        self.add_child('b', 'b', 'b', recorded=False)
        self.rows.append(assistant('c', 'b-ref', 'subagent', 'c-call'))
        self.add_child('c', 'c', 'c', path=self.root / 'outside.jsonl')
        result = self.project(FIRST)
        self.assertEqual([(row['ready'], row['artifactCount']) for row in result.values()],
                         [(True, 1), (False, 0), (False, 0)])
        output.write_text('其他任务已更新这份文件', encoding='utf-8')
        self.assertEqual(self.project(FIRST)['a']['artifactCount'], 0)
