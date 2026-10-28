"""Exercise the paginated custom-entry join without opening/checksumming a cache."""
import json
import sqlite3
import tempfile
import unittest
import zlib
from pathlib import Path

from app.transcript_index import TranscriptRepository


class SubagentIndexProjectionTests(unittest.TestCase):
    def test_child_snapshots_join_their_launch_in_a_bounded_page(self):
        entries = [
            {'id':'launch', 'type':'message', 'message':{'role':'assistant', 'content':[
                {'type':'toolCall', 'id':'call', 'name':'subagent', 'arguments':{'prompt':'Inspect files'}}]}},
            {'id':'child', 'type':'custom', 'customType':'umeko-subagent', 'data':{'version':1,
                'toolCallId':'call', 'ownerEntryId':'launch', 'tool':{'id':'subagent:a', 'name':'subagent',
                'arguments':{'type':'Explore','task':'Inspect files','mode':'background'}, 'state':'done',
                'result':'Found it', 'subagent':{'id':'a','type':'Explore','status':'completed','toolUses':2}}}},
        ]
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / 'conversation.jsonl'
            data = b''; positions = []
            for entry in entries:
                encoded = (json.dumps(entry) + '\n').encode()
                positions.append((len(data), len(encoded))); data += encoded
            file.write_bytes(data)
            db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
            db.executescript('''
                CREATE TABLE entries(id TEXT, num INTEGER, offset INTEGER, length INTEGER, role TEXT, tool TEXT, kind TEXT, tools INTEGER, stop TEXT, error INTEGER);
                CREATE TABLE native(pos INTEGER, id TEXT);
                CREATE TABLE branch(id TEXT);
                CREATE TABLE display(seq INTEGER, first_native INTEGER, last_native INTEGER, role TEXT, hint REAL, body BLOB, logical TEXT, continuation INTEGER, last INTEGER);
                CREATE TABLE questions(seq INTEGER, row INTEGER, title TEXT);
            ''')
            for i, entry in enumerate(entries):
                db.execute('INSERT INTO entries VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (entry['id'], i, *positions[i], 'assistant' if i==0 else '', 'call' if i else '', entry['type'], int(i==0), '', 0))
                db.execute('INSERT INTO branch VALUES(?)', (entry['id'],))
            db.execute('INSERT INTO native VALUES(0, ?)', ('launch',))
            TranscriptRepository._project(None, db, file, temp, 0, lambda: False)
            rows = [json.loads(zlib.decompress(row[0])) for row in db.execute('SELECT body FROM display')]
            children = [tool for row in rows for step in row.get('steps',[]) for tool in step.get('tools',[]) if tool.get('subagent')]
            # ChatModel may expose the same data directly when the fragment is small.
            if not children:
                children = [tool for row in rows for tool in row.get('tools',[]) if tool.get('subagent')]
            self.assertEqual(len(children), 1)
            self.assertEqual(children[0]['result'], 'Found it')
            db.close()
