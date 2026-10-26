import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.chat_model import ChatModel
from app.pi_sessions import PiSessionPool, SessionState
from app.transcript_index import TranscriptRepository, WeightedLRU, FRAGMENT_CHARS, StaleIndex, Cancelled
from app.transcripts import preview


class TranscriptIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.file = self.path / 'conversation.jsonl'
        self.repo = TranscriptRepository(self.path / 'cache', cache_bytes=96 * 1024)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, entries):
        self.file.write_text(''.join(json.dumps(entry, ensure_ascii=False) + '\n' for entry in [{'type':'session', 'id':'fixture', 'cwd':str(self.path)}, *entries]), encoding='utf-8')

    def message(self, id, parent, role, text, **values):
        return {'type':'message', 'id':id, 'parentId':parent, 'message':{'role':role, 'content':text, **values}}

    def rows(self, snapshot):
        result = []
        for i in range(snapshot.count):
            row = dict(snapshot.row(i))
            for key in ('_logical', 'continuation', 'segmentLast'):
                row.pop(key, None)
            result.append(row)
        return result

    def test_active_branch_tools_deliveries_and_original_file_are_preserved(self):
        entries = [self.message('u', None, 'user', 'task'),
                   self.message('old', 'u', 'assistant', 'unselected branch'),
                   self.message('a', 'u', 'assistant', [{'type':'thinking','thinking':'plan'}, {'type':'text','text':'inspect'}, {'type':'toolCall','id':'call','name':'read','arguments':{'path':'report.txt'}}]),
                   self.message('r', 'a', 'toolResult', [{'type':'text','text':'result'}], toolCallId='call'),
                   {'type':'custom','id':'delivery','parentId':'r','customType':'umeko-chatbox','data':{'version':1,'toolCallId':'call/nested','items':[{'kind':'file','path':str(self.path/'report.txt'),'title':'Report'}]}},
                   self.message('final', 'delivery', 'assistant', 'finished')]
        self.write(entries)
        before = hashlib.sha256(self.file.read_bytes()).hexdigest()
        snapshot = self.repo.open(self.file)
        self.assertEqual(self.rows(snapshot), ChatModel.project(preview(self.file)[0]))
        self.assertEqual(snapshot.question(0), {'row':0,'title':'task'})
        self.assertEqual(hashlib.sha256(self.file.read_bytes()).hexdigest(), before)

    def test_append_only_parses_new_entries_and_warm_open_reuses_index(self):
        self.write([self.message('u',None,'user','first'), self.message('a','u','assistant','answer')])
        first = self.repo.open(self.file)
        warm = self.repo.open(self.file)
        self.assertEqual(warm.parsed_entries, 0)
        self.assertEqual(warm.revision, first.revision)
        with self.file.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(self.message('next','a','user','next question')) + '\n')
        second = self.repo.open(self.file)
        self.assertEqual(second.parsed_entries, 1)
        self.assertEqual(second.native_count, 3)
        self.assertEqual(second.question_count, 2)
        self.assertEqual(second.question(1), {'row':2,'title':'next question'})

    def test_replaced_and_same_size_modified_files_never_reuse_old_rows(self):
        self.write([self.message('u',None,'user','first')])
        first = self.repo.open(self.file)
        self.assertEqual(first.row(0)['text'], 'first')
        self.write([self.message('u',None,'user','other')])
        second = self.repo.open(self.file)
        self.assertGreater(second.revision, first.revision)
        self.assertEqual(second.row(0)['text'], 'other')
        replacement = self.path/'replacement.jsonl'
        replacement.write_text(self.file.read_text(encoding='utf-8').replace('other','third'),encoding='utf-8')
        replacement.replace(self.file)
        third = self.repo.open(self.file)
        self.assertEqual(third.row(0)['text'], 'third')

    def test_partial_append_and_explicit_branch_jump(self):
        self.write([self.message('u',None,'user','first'), self.message('a','u','assistant','old')])
        with self.file.open('a',encoding='utf-8') as stream:
            stream.write('{"type":"message",')
        first = self.repo.open(self.file)
        self.assertEqual(first.count, 2)
        with self.file.open('a',encoding='utf-8') as stream:
            stream.write('"id":"b","parentId":"u","message":{"role":"assistant","content":"new"}}\n')
        second = self.repo.open(self.file)
        self.assertEqual(second.row(1)['text'], 'new')
        old = self.repo.open(self.file, leaf='a')
        self.assertEqual(old.row(1)['text'], 'old')

    def test_context_edit_omits_recovery_error_from_selected_branch(self):
        self.write([self.message('u',None,'user','first'), self.message('a','u','assistant','failed',stopReason='error',errorMessage='failed'),
                    {'type':'context_edit','id':'edit','parentId':'a','targetId':'a','replacement':None},
                    self.message('ok','edit','assistant','recovered')])
        snapshot = self.repo.open(self.file)
        self.assertEqual(self.rows(snapshot), ChatModel.project(preview(self.file)[0]))

    def test_large_single_reply_is_bounded_and_copy_recovers_original_markdown(self):
        text = '```rust\n' + 'println!("a long code line");\n' * 4000 + '```\n\n| key | value |\n| --- | --- |\n' + '| item | data |\n' * 3000
        self.write([self.message('u',None,'user','code'),self.message('a','u','assistant',text)])
        snapshot = self.repo.open(self.file)
        self.assertGreater(snapshot.count, 4)
        for i in range(1, snapshot.count):
            row = snapshot.row(i)
            self.assertLess(len(row['text']), FRAGMENT_CHARS + 200)
            self.assertEqual(row['continuation'], i > 1)
        self.assertEqual(snapshot.copy_text(1), text)
        self.assertEqual(snapshot.question_count, 1)

    def test_page_eviction_reload_and_cancellation(self):
        entries, parent = [], None
        for i in range(250):
            id = str(i)
            entries.append(self.message(id,parent,'user' if i%2==0 else 'assistant', 'Body '+str(i)+' '+('fixture '*100)))
            parent = id
        self.write(entries)
        snapshot = self.repo.open(self.file)
        for i in range(snapshot.count):
            self.assertTrue(snapshot.row(i)['text'].startswith('Body '+str(i)))
        self.assertLessEqual(self.repo.cache.weight, self.repo.cache.limit)
        self.assertIsNone(snapshot.cached(0))
        self.assertTrue(snapshot.row(0)['text'].startswith('Body 0'))
        other = TranscriptRepository(self.path/'cancelled')
        with self.assertRaises(Cancelled):
            other.open(self.file,cancelled=lambda:True)
        self.assertEqual(other.open(self.file).count, 250)

    def test_discard_removes_derived_database_and_memory_only(self):
        self.write([self.message('u', None, 'user', 'private fixture')])
        snapshot = self.repo.open(self.file)
        self.assertIsNotNone(snapshot.cached(0))
        self.repo.discard(self.file)
        self.assertFalse(Path(snapshot.database).exists())
        self.assertIsNone(snapshot.cached(0))
        self.assertTrue(self.file.exists())
        self.assertEqual(self.repo.open(self.file).row(0)['text'], 'private fixture')

    def test_streaming_reprojects_only_tail_and_keeps_native_messages_unchanged(self):
        messages = [{'role':'user' if i%2==0 else 'assistant','text':'message '+str(i)} for i in range(4000)]
        model = ChatModel()
        model.update(messages)
        seen = []
        project = ChatModel.project
        def observe(values, **kwargs):
            seen.append(len(values))
            return project(values, **kwargs)
        with patch.object(ChatModel,'project',side_effect=observe):
            messages[-1]['text'] += ' delta'
            before = copy.deepcopy(messages)
            model.update(messages, dirty_from=len(messages)-1)
            self.assertEqual(messages, before)
        self.assertEqual(seen,[1])
        self.assertEqual(model.rows[-1]['text'], messages[-1]['text'])
        model.close()

    def test_idle_body_lru_preserves_active_tasks_drafts_and_restore_metadata(self):
        pool = PiSessionPool(body_limit=10000)
        active = SessionState(file='active.jsonl',messages=[{'text':'a'*10000}],draft='keep')
        pool.touch(active,current=True)
        oldest = SessionState(id='older',file='older.jsonl',messages=[{'text':'b'*10000}],draft='draft',scroll_index=42)
        pool.touch(oldest)
        running = SessionState(file='running.jsonl',messages=[{'text':'c'*10000}],phase='running')
        pool.touch(running)
        self.assertFalse(oldest.loaded)
        self.assertEqual(oldest.messages,[])
        self.assertEqual((oldest.draft,oldest.scroll_index),('draft',42))
        self.assertTrue(active.loaded)
        self.assertTrue(running.loaded)
        pool.close()


if __name__ == '__main__':
    unittest.main()
