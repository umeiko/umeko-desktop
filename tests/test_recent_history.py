"""A long conversation shown from its latest messages matches its complete index."""
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication

from app.chat_model import ChatModel
from app.transcript_index import TranscriptRepository

EVENT = '01da3365-8d24-46cc-bdb1-ed1999a7231a'


def message(entry_id, parent, role, content, **values):
    return {'type': 'message', 'id': entry_id, 'parentId': parent, 'message': {'role': role, 'content': content, **values}}


def compaction(entry_id, parent, state, event=EVENT):
    return {'type': 'custom', 'customType': 'umeko-compaction', 'id': entry_id, 'parentId': parent,
            'timestamp': '2026-10-29T01:00:00Z', 'data': {'version': 2, 'eventId': event, 'state': state, 'mode': 'manual',
            'before': 22000, 'after': 8000 if state == 'success' else None, 'afterEstimated': True, 'summary': '', 'error': ''}}


def subagent(entry_id, parent, call, owner):
    return {'type': 'custom', 'customType': 'umeko-subagent', 'id': entry_id, 'parentId': parent, 'data': {
        'version': 1, 'toolCallId': call, 'ownerEntryId': owner, 'tool': {
            'id': 'subagent:' + call, 'name': 'subagent', 'arguments': {'type': 'Explore', 'task': 'Inspect', 'mode': 'background'},
            'state': 'done', 'result': 'Found ' + call, 'subagent': {'id': call, 'type': 'Explore', 'status': 'completed', 'toolUses': 2}}}}


class Conversation:
    """Writes a transcript with ordinary turns, tools, branches, compaction and subagents."""

    def __init__(self, path):
        self.path, self.entries, self.parent, self.turn = path, [{'type': 'session', 'id': 'fixture', 'cwd': str(path.parent)}], None, 0

    def add(self, entry):
        self.entries.append(entry)
        self.parent = entry['id']
        return entry['id']

    def turns(self, count, tools=True, branch=False, subagents=False):
        for _ in range(count):
            n = self.turn = self.turn + 1
            question = self.add(message(f'u{n}', self.parent, 'user', f'Question {n} ' + 'detail ' * 30))
            if branch:
                # An unselected reply on another branch from the same question.
                self.entries.append(message(f'alt{n}', question, 'assistant', 'unselected reply'))
            if tools:
                self.add(message(f'a{n}', self.parent, 'assistant', [
                    {'type': 'thinking', 'thinking': 'plan ' * 20}, {'type': 'text', 'text': 'checking'},
                    {'type': 'toolCall', 'id': f'call{n}', 'name': 'read', 'arguments': {'path': f'file{n}.txt'}}]))
                self.add(message(f'r{n}', self.parent, 'toolResult', [{'type': 'text', 'text': 'result ' * 40}], toolCallId=f'call{n}'))
            if subagents:
                self.add(message(f's{n}', self.parent, 'assistant', [
                    {'type': 'toolCall', 'id': f'agent{n}', 'name': 'subagent', 'arguments': {'prompt': 'Inspect files'}}]))
                self.add(subagent(f'child{n}', self.parent, f'agent{n}', f's{n}'))
            self.add(message(f'f{n}', self.parent, 'assistant', f'## Answer {n}\n\n' + 'Finished the step. ' * 40))

    def write(self):
        self.path.write_text(''.join(json.dumps(entry, ensure_ascii=False) + '\n' for entry in self.entries), encoding='utf-8')


class RecentHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.file = self.root / 'conversation.jsonl'
        self.repo = TranscriptRepository(self.root / 'cache')
        self.chat = Conversation(self.file)

    def tearDown(self):
        self.temp.cleanup()

    def rows(self, snapshot, first=0):
        return [snapshot.row(row) for row in range(first, snapshot.count)]

    def recent(self, messages=24):
        recent = self.repo.open_recent(self.file, messages=messages, chunk=4096)
        self.assertIsNotNone(recent)
        self.assertTrue(recent.partial)
        self.assertEqual(recent.origin, str(self.file.resolve()))
        self.assertTrue(recent.matches_source())
        return recent

    def assert_same_tail(self, recent):
        self.assertFalse(self.repo.current(self.file))
        complete = self.repo.open(self.file)
        self.assertTrue(self.repo.current(self.file))
        self.assertLess(recent.count, complete.count)
        self.assertEqual(self.rows(recent), self.rows(complete, complete.count - recent.count))
        self.assertTrue(self.repo.same_tail(recent, complete))
        # The complete index is what a first visit showed before this change.
        cold = TranscriptRepository(self.root / 'cold').open(self.file)
        self.assertEqual(self.rows(complete), self.rows(cold))
        return complete

    def test_tail_starts_at_a_question_and_matches_the_complete_index(self):
        self.chat.turns(40)
        self.chat.write()
        recent = self.recent()
        self.assertEqual(recent.row(0)['role'], 'user')
        self.assert_same_tail(recent)

    def test_branches_keep_only_the_selected_replies(self):
        self.chat.turns(30, branch=True)
        self.chat.write()
        recent = self.recent()
        self.assertNotIn('unselected reply', json.dumps(self.rows(recent)))
        self.assert_same_tail(recent)

    def test_compaction_inside_the_tail_is_one_row(self):
        self.chat.turns(30)
        self.chat.add(compaction('start', self.chat.parent, 'running'))
        self.chat.add(compaction('finish', self.chat.parent, 'success'))
        self.chat.turns(4)
        self.chat.write()
        recent = self.recent()
        notices = [row for row in self.rows(recent) if row.get('customType') == 'umeko-compaction']
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]['compaction']['state'], 'success')
        self.assert_same_tail(recent)

    def test_compaction_that_started_before_the_tail_is_detected(self):
        self.chat.turns(30)
        self.chat.add(compaction('start', self.chat.parent, 'running'))
        self.chat.turns(8)
        self.chat.add(compaction('finish', self.chat.parent, 'success'))
        self.chat.turns(1)
        self.chat.write()
        recent = self.recent(messages=12)
        complete = self.repo.open(self.file)
        self.assertFalse(self.repo.same_tail(recent, complete))

    def test_subagents_fill_their_launch_rows(self):
        self.chat.turns(30, subagents=True)
        # A background child of the first launch reports long after it.
        late = subagent('late', self.chat.parent, 'agent1', 's1')
        late['data']['tool']['result'] = 'Late report'
        self.chat.add(late)
        self.chat.turns(2, subagents=True)
        self.chat.write()
        recent = self.recent()
        self.assertIn('Found agent32', json.dumps(self.rows(recent)))
        complete = self.assert_same_tail(recent)
        self.assertIn('Late report', json.dumps(self.rows(complete, 0)[:6]))

    def test_short_files_and_current_indexes_open_completely(self):
        self.chat.turns(2)
        self.chat.write()
        self.assertIsNone(self.repo.open_recent(self.file, chunk=4096))

    def test_model_inserts_earlier_rows_above_without_reset(self):
        self.chat.turns(40)
        self.chat.write()
        recent = self.recent()
        complete = self.repo.open(self.file)
        model = ChatModel()
        events = []
        model.modelReset.connect(lambda: events.append('reset'))
        model.rowsInserted.connect(lambda parent, first, last: events.append(('inserted', first, last)))
        model.set_snapshot(recent)
        self.assertTrue(model.partialHistory)
        self.assertEqual(model.questionCount, 0)
        last = recent.count - 1
        model.requestRange(last - 2, last)
        for _ in range(500):
            QCoreApplication.processEvents()
            if model.isReady(last):
                break
        self.assertTrue(model.isReady(last))
        before = model.message(last)
        model.recordHeight(last, 321.0)
        events.clear()
        from dataclasses import replace
        model.set_snapshot(replace(complete, extends=recent))
        shift = complete.count - recent.count
        self.assertEqual(events, [('inserted', 0, shift - 1)])
        self.assertFalse(model.partialHistory)
        self.assertEqual(model.rowCount(), complete.count)
        self.assertEqual(model.questionCount, complete.question_count)
        # The prepared and measured row keeps its content under its new number.
        self.assertTrue(model.isReady(last + shift))
        self.assertEqual(model.message(last + shift), before)
        self.assertEqual(model.estimatedHeight(last + shift), 321.0)
        model.close()


if __name__ == '__main__':
    unittest.main()
