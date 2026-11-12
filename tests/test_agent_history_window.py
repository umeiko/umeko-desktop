import copy
import json
import tempfile
import unittest
from pathlib import Path
from app.transcript_index import TranscriptRepository, connect
from app.chat_model import ChatModel

class AgentHistoryWindowTests(unittest.TestCase):
    def test_failed_and_running_compactions_do_not_advance_retention(self):
        def event(identifier, state):
            return {'customType':'umeko-compaction','compaction':{'eventId':identifier,'state':state}}
        rows=[{'role':'user','text':'before'},event('a','success'),{'role':'user','text':'round-a'},event('b','success'),{'role':'user','text':'round-b'},event('c','failure')]
        before=copy.deepcopy(rows)
        self.assertEqual(ChatModel.recent_compaction_interval(rows), rows[1:])
        rows.append(event('c','running'))
        self.assertEqual(ChatModel.recent_compaction_interval(rows), rows[1:])
        rows.append(event('c','success'))
        self.assertEqual(ChatModel.recent_compaction_interval(rows), rows[3:])
        self.assertEqual(rows[:len(before)], before)

    def test_paged_window_rebases_questions_copy_and_rows_without_touching_native_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);file=path/'session.jsonl';entries=[{'type':'session','id':'fixture','cwd':directory}];parent=None
            def add(entry):
                nonlocal parent
                entry.update(id=str(len(entries)),parentId=parent);parent=entry['id'];entries.append(entry)
            for period in range(4):
                for index in range(4):
                    add({'type':'message','message':{'role':'assistant' if index%2 else 'user','content':f'round-{period}-{index}'}})
                if period<3:
                    add({'type':'custom','customType':'umeko-compaction','data':{'version':2,'eventId':f'00000000-0000-0000-0000-{period:012d}','mode':'manual','afterEstimated':True,'error':'','state':'success','before':1000,'after':100,'summary':f'summary-{period}'}})
            original=''.join(json.dumps(entry)+'\n' for entry in entries).encode();file.write_bytes(original)
            repo=TranscriptRepository(path/'cache')
            snapshot=repo.open(file).recent_compaction_interval()
            self.assertGreater(snapshot.row_offset,0)
            self.assertEqual(snapshot.question(0)['title'],'round-2-0')
            self.assertEqual(snapshot.row(0)['customType'],'umeko-compaction')
            self.assertEqual(snapshot.row(snapshot.count-1)['text'],'round-3-3')
            self.assertNotIn('round-0',repr(snapshot.page(0)))
            self.assertEqual(snapshot.question_index(snapshot.question(1)['row']),1)
            self.assertEqual(snapshot.row(0)['compaction']['summary'],'summary-1')
            self.assertIn('round-2-0',snapshot.copy_text(snapshot.question(0)['row']))
            for key in repo.cache.items:self.assertGreaterEqual(key[2],snapshot.row_offset)
            self.assertEqual(file.read_bytes(),original)

if __name__=='__main__':unittest.main()
