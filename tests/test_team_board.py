import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from app.task_records import TaskStore
from app.team_board import recipients, roster


class TeamBoardTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'tasks.sqlite3'
        self.store = TaskStore(self.path)
        self.lead, self.api, self.ui, self.tester = roster('agent:lead', 'lead', [
            {'targetId': 'agent:api', 'name': 'api-dev', 'groups': ['devs']},
            {'targetId': 'agent:ui', 'name': 'ui-dev', 'groups': ['devs']},
            {'targetId': 'agent:test', 'name': 'tester'},
        ])
        self.members = [self.lead, self.api, self.ui, self.tester]
        self.team = self.store.create_team('Release', self.members)

    def post(self, actor, kind, **fields):
        return self.store.post_team_event(self.team, actor, kind, {'text': '', **fields}, [])

    def new_task(self, title, blocked_by=()):
        return self.post(self.lead, 'task', title=title, text=title, blockedBy=list(blocked_by))['task']['id']

    def test_mentions_resolve_aliases_groups_and_broadcast(self):
        names = lambda text, **kw: [member['name'] for member in recipients(text, self.members, 'agent:lead', **kw)]
        self.assertEqual(names('接手。@API-dev 请查看，@devs 和 @all 请确认'), ['api-dev', 'ui-dev', 'tester'])
        self.assertEqual(names('@agent-tester run tests', leading=True), ['tester'])
        self.assertEqual(names('note @tester run tests', leading=True), [])
        self.assertEqual(names('@tester', leading=True), [])
        self.assertEqual(names('@tester/src.py ping api@ui-dev.com'), [])
        with self.assertRaisesRegex(ValueError, '同一名称'):
            roster('agent:lead', 'lead', [{'targetId': 'agent:api', 'name': 'api', 'groups': ['lead']}])

    def test_concurrent_claim_has_one_winner_and_board_survives_reopen(self):
        task = self.new_task('Implement')
        barrier = Barrier(2)

        def claim(member):
            barrier.wait(timeout=5)
            try:
                return self.post(member, 'claim', taskId=task, expectedVersion=1)['actor']
            except ValueError as error:
                self.assertIn('当前版本为 2', str(error))
                return None

        with ThreadPoolExecutor(2) as pool:
            winners = [name for name in pool.map(claim, [self.api, self.ui]) if name]
        self.assertEqual(len(winners), 1)
        winner = next(member for member in self.members if member['name'] == winners[0])
        self.post(winner, 'progress', taskId=task, expectedVersion=2, text='Interfaces ready')
        self.post(winner, 'handoff', taskId=task, expectedVersion=3, to='tester', text='Verify')
        self.post(self.tester, 'result', taskId=task, expectedVersion=4, text='Tests passed')
        restarted = TaskStore(self.path)
        page = restarted.team_board(self.team['id'], 0, 3)
        self.assertTrue(page['hasMore'])
        next_page = restarted.team_board(self.team['id'], page['nextAfter'], 3)
        self.assertFalse(next_page['hasMore'])
        self.assertEqual([event['kind'] for event in page['events'] + next_page['events']],
                         ['task', 'claim', 'progress', 'handoff', 'result'])
        self.assertEqual([(row['owner'], row['version'], row['result']) for row in page['tasks']],
                         [('tester', 5, 'Tests passed')])

    def test_claim_requires_finished_dependencies_and_graph_stays_acyclic(self):
        api_task = self.new_task('Build API')
        ui_task = self.new_task('Build UI', [api_task])
        with self.assertRaisesRegex(ValueError, '依赖成环'):
            self.post(self.lead, 'dependencies', taskId=api_task, expectedVersion=1, blockedBy=[ui_task])
        with self.assertRaisesRegex(ValueError, '依赖已完成'):
            self.post(self.ui, 'claim', taskId=ui_task, expectedVersion=1)
        self.post(self.api, 'claim', taskId=api_task, expectedVersion=1)
        with self.assertRaisesRegex(ValueError, '负责人和协调者'):
            self.post(self.ui, 'result', taskId=api_task, expectedVersion=2, text='not my task')
        self.post(self.api, 'result', taskId=api_task, expectedVersion=2, text='done')
        self.assertTrue(self.store.team_board(self.team['id'], 0, 10)['tasks'][-1]['ready'])


if __name__ == '__main__':
    unittest.main()
