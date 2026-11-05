"""Keep failure indexing and display payloads linear without changing native logs."""
import json
from pathlib import Path
import tempfile
import unittest
import zlib
from unittest.mock import patch

from app import transcript_index


class FailedHistoryLoadingTests(unittest.TestCase):
    def test_large_failure_fragments_keep_linear_payload_and_complete_text(self):
        from app.chat_model import ChatModel

        failure = 'Upstream failure: ' + 'detail ' * 40000
        native = {'role': 'assistant', 'text': failure, 'errorMessage': failure,
                  'error': True, 'stopReason': 'error'}
        row = ChatModel.project([native])[0]
        fragments = list(transcript_index.display_fragments(row))
        self.assertGreater(len(fragments), 8)
        restored = ''.join(step['text'] for fragment in fragments
                           for step in fragment['activity'] if step.get('error'))
        self.assertEqual(restored, failure)
        # Bound the work before compression: a complete raw failure in every
        # fragment turns one upstream response into quadratic index/QML traffic.
        payload_bytes = sum(len(json.dumps(fragment).encode()) for fragment in fragments)
        self.assertLess(payload_bytes, 3 * len(failure.encode()))
        self.assertEqual(native['errorMessage'], failure)

    def test_large_failure_index_and_schema_refresh_preserve_native_history(self):
        with tempfile.TemporaryDirectory(prefix='umeko-failure-payload-') as directory:
            root = Path(directory)
            source = root / 'history.jsonl'
            failure = 'Upstream failure: ' + 'detail ' * 40000
            entries = [{'type': 'message', 'id': 'failed', 'parentId': None,
                        'message': {'role': 'assistant', 'content': [],
                                    'stopReason': 'error', 'errorMessage': failure}}]
            original = (json.dumps(entries[0]) + '\n').encode()
            source.write_bytes(original)
            repository = transcript_index.TranscriptRepository(root / 'cache')
            snapshot = repository.open(source)

            def check(snapshot):
                with transcript_index.connect(snapshot.database) as db:
                    payloads = [zlib.decompress(row[0]) for row in db.execute('SELECT body FROM display ORDER BY seq')]
                self.assertLess(sum(map(len, payloads)), 3 * len(original))
                restored = ''.join(step['text'] for payload in payloads for step in json.loads(payload)['activity'] if step.get('error'))
                self.assertEqual(restored, failure)
                self.assertLess(repository.cache.weight, 4 * len(original))
                self.assertEqual(source.read_bytes(), original)

            check(snapshot)
            with transcript_index.connect(snapshot.database) as db:
                db.execute("UPDATE meta SET value='6' WHERE key='schema'")
                for row in db.execute('SELECT seq,body FROM display').fetchall():
                    value = json.loads(zlib.decompress(row['body']))
                    value['errorMessage'] = failure
                    db.execute('UPDATE display SET body=? WHERE seq=?',
                               (zlib.compress(json.dumps(value).encode()), row['seq']))
            # Reopen as an upgraded process; old in-memory revisions belong to
            # the existing bounded LRU and are separate from on-disk migration.
            repository = transcript_index.TranscriptRepository(root / 'cache')
            refreshed = repository.open(source)
            self.assertGreater(refreshed.revision, snapshot.revision)
            check(refreshed)

    def test_failure_history_has_linear_index_work(self):
        with tempfile.TemporaryDirectory(prefix='umeko-failed-history-') as directory:
            root = Path(directory)
            work = {}
            connect = transcript_index.connect
            for failed in (False, True):
                source = root / f'{failed}.jsonl'
                with source.open('w', encoding='utf-8') as handle:
                    for row in range(1200):
                        message = {'role': 'assistant' if row % 2 else 'user',
                                   'content': 'A short fixture record.',
                                   'provider': 'test-provider', 'model': 'test-model'}
                        if failed and row % 2:
                            message.update(content='', stopReason='error',
                                           errorMessage='Provider returned HTTP 503: service unavailable.')
                        handle.write(json.dumps({'type': 'message', 'id': str(row),
                            'parentId': str(row - 1) if row else None, 'message': message}) + '\n')
                steps = [0]

                def counted(path):
                    db = connect(path)

                    def tick():
                        steps[0] += 100
                        return 0

                    db.set_progress_handler(tick, 100)
                    return db

                with patch.object(transcript_index, 'connect', counted):
                    snapshot = transcript_index.TranscriptRepository(root / f'cache-{failed}').open(source)
                self.assertEqual(snapshot.count, 1200)
                self.assertEqual(bool(snapshot.row(1199)['error']), failed)
                work[failed] = steps[0]
            # Count SQLite work, not machine speed. A full branch scan per
            # failure exceeds this by an order of magnitude at this small size.
            self.assertLess(work[True], 2 * work[False], work)


if __name__ == '__main__':
    unittest.main()
