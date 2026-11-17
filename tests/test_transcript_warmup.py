import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from app import transcript_warmup
from app.transcript_index import LARGE_FILE, TranscriptRepository


class TranscriptWarmupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.repo = TranscriptRepository(self.path / 'cache')

    def tearDown(self):
        self.temp.cleanup()

    def transcript(self, name, size, age):
        file = self.path / f'{name}.jsonl'
        lines = [json.dumps({'type': 'session', 'id': name, 'cwd': str(self.path)})]
        parent, turn = None, 0
        while sum(len(line) + 1 for line in lines) < size:
            for role in ('user', 'assistant'):
                entry = f'{name}-{turn}-{role}'
                lines.append(json.dumps({'type': 'message', 'id': entry, 'parentId': parent,
                                         'message': {'role': role, 'content': f'{role} {turn} ' + 'x' * 400}}))
                parent = entry
            turn += 1
        file.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        stamp = time.time() - age
        os.utime(file, (stamp, stamp))
        return str(file)

    def test_recent_transcripts_picks_newest_large_files(self):
        old = self.transcript('old', LARGE_FILE + 10, 300)
        newest = self.transcript('newest', LARGE_FILE + 10, 10)
        middle = self.transcript('middle', LARGE_FILE + 10, 100)
        small = self.transcript('small', 2_000, 0)
        sessions = [{'file': old}, {'file': small}, {'file': newest}, {'file': middle}, {'file': None},
                    {'file': str(self.path / 'missing.jsonl')}, 'not a session']
        self.assertEqual(transcript_warmup.recent_transcripts(sessions, 2), [newest, middle])

    def test_warm_builds_indexes_that_later_opens_reuse(self):
        file = self.transcript('long', LARGE_FILE + 10, 0)
        self.assertEqual(transcript_warmup.warm(self.repo, [file], cancelled=lambda: False), [file])
        snapshot = TranscriptRepository(self.path / 'cache').open(file)
        self.assertEqual(snapshot.parsed_entries, 0)
        self.assertGreater(snapshot.count, 0)

    def test_warm_stops_when_cancelled_and_waits_while_paused(self):
        first = self.transcript('first', LARGE_FILE + 10, 0)
        second = self.transcript('second', LARGE_FILE + 10, 0)
        self.assertEqual(transcript_warmup.warm(self.repo, [first, second], cancelled=lambda: True), [])
        checks = []
        def paused():
            checks.append(1)
            return len(checks) < 3
        self.assertEqual(transcript_warmup.warm(self.repo, [first], cancelled=lambda: False, paused=paused), [first])
        self.assertGreaterEqual(len(checks), 3)

    def test_start_reports_built_files_from_a_background_thread(self):
        file = self.transcript('background', LARGE_FILE + 10, 0)
        built = []
        thread = transcript_warmup.start(self.repo, [file], cancelled=lambda: False, finished=built.extend)
        thread.join(30)
        self.assertEqual(built, [file])


if __name__ == '__main__':
    unittest.main()
