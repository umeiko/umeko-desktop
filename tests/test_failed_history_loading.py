"""Failed requests must not rescan the entire branch once per error."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import transcript_index


class FailedHistoryLoadingTests(unittest.TestCase):
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
