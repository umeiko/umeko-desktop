"""Skill host boundaries with controlled asynchronous jobs and no real Pi process."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication, QObject, Signal

from app.pi_sessions import SessionState, clean_skill_modes
from app.widget_host import WidgetHost


class FixtureStore:
    """Only the session metadata used by skill jobs; no profile or credentials."""

    def __init__(self, path):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {'sessionMeta': {}}

    def save(self):
        self.path.write_text(json.dumps(self.data), encoding='utf-8')


class Backend(QObject):
    jobDone = Signal(str, object)
    changed = Signal()
    chatChanged = Signal()

    def __init__(self, root):
        super().__init__()
        self.busy = self.kernelBusy = False
        self.pendingApproval = {}
        self._view = SessionState(key='chat-one', id='one', workspace=str(root / 'workspace'))
        self.second = SessionState(key='chat-two', id='two', workspace=str(root / 'other-workspace'))
        self.store = FixtureStore(root / 'session-metadata.json')
        self.piManagement = SimpleNamespace(busy=False, uninstallPackage=lambda *_: None,
            _context=lambda: (root / 'release', Path(self._view.workspace), root / 'agent', {}))
        self._pool = SimpleNamespace(retire=Mock(), event=SimpleNamespace(connect=Mock()))
        self._restart_pi = Mock()
        self.pending_jobs = {}

    def _job(self, name, run):
        # Match Controller._job's result envelope, but let each test choose when
        # the real jobDone signal is emitted, including after a chat switches.
        self.pending_jobs[name] = run

    def finish(self):
        name, run = next(iter(self.pending_jobs.items()))
        del self.pending_jobs[name]
        try:
            value = {'ok': True, 'value': run()}
        except Exception as error:
            value = {'ok': False, 'value': str(error)}
        self.jobDone.emit(name, value)


class Manager(QObject):
    hostResponse = Signal(str, str, 'QVariantMap')

    def __init__(self, root):
        super().__init__()
        self.b = Backend(root)
        self.closed = False
        self._session = {'token': self.b._view.key, 'id': self.b._view.id,
                         'workspace': self.b._view.workspace}
        self.entries = {identifier: {'name': 'Fixture skill panel',
            'permissions': ['skills.read', 'skills.manage']} for identifier in ('a', 'b')}
        self.workers = {identifier: {'ready': True} for identifier in self.entries}
        self.replies, self.frames = {}, []
        self.hostResponse.connect(lambda widget, request, value: self.replies.__setitem__(request, value))

    def enabled(self, identifier): return True
    def session_enabled(self, identifier): return True
    def application(self, identifier): return True
    def send(self, identifier, value): self.frames.append((identifier, value))


class SkillHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='skill-host-fixture-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.manager = Manager(self.root)
        self.backend = self.manager.b
        self.host = WidgetHost(self.manager)
        self.addCleanup(self.host.deleteLater)
        self.cli_calls = []
        self.rows = [self.row('disabled', enabled=False), self.row('registered', removable=True),
                     self.row('project', scope='project', defaultMutable=False)]
        self.native = patch('app.skill_management.subprocess.run', side_effect=self.native_cli).start()
        self.addCleanup(patch.stopall)
        patch('app.skill_management.node_executable', return_value=str(self.root / 'node.exe')).start()
        patch('app.skill_management.npm_environment', return_value={'NODE_OPTIONS': 'untrusted', 'NODE_PATH': 'untrusted'}).start()
        self.open_folder = patch('app.skill_management.QDesktopServices.openUrl', return_value=True).start()
        self.remove_package = patch('app.skill_management.remove_package').start()

    def row(self, name, **changes):
        return {'id': 'skill_' + name, 'name': name, 'path': str(self.root / name / 'SKILL.md'),
            'description': 'Fixture description', 'source': 'package' if name == 'registered' else 'user',
            'scope': 'global', 'enabled': True, 'attached': True, 'defaultMutable': True,
            'defaultReason': 'Project defaults are scoped', 'removable': False,
            'packageSource': 'npm:fixture-skills@1.0.0' if name == 'registered' else '', **changes}

    def native_cli(self, command, **kwargs):
        action = json.loads(kwargs['input'])
        self.cli_calls.append((command, kwargs, action))
        if action['action'] == 'details':
            payload = {'ok': True, 'details': {'id': action['id'], 'markdown': '# Fixture skill\nUse the fixture.'}}
        else:
            payload = {'ok': True, 'skills': copy.deepcopy(self.rows)}
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), '')

    def request(self, operation, args=None, widget='a', session=None):
        identifier = self.host.request_for(widget, {'operation': operation, 'arguments': args or {},
            'session': dict(self.manager._session) if session is None else session})
        self.app.processEvents()
        return identifier

    def accepted(self, operation, args=None, approve=False):
        identifier = self.request(operation, args)
        if approve:
            self.assertNotIn(identifier, self.manager.replies)
            self.host.respondApproval(True)
        reply = self.manager.replies[identifier]
        self.assertTrue(reply['ok'], reply)
        self.assertTrue(reply['accepted'])
        return reply['jobId']

    def finish(self, job):
        self.backend.finish()
        identifier = self.request('skills.job', {'id': job})
        return self.manager.replies[identifier]['jobs'][0]

    def catalog(self):
        job = self.accepted('skills.list')
        result = self.finish(job)
        self.assertEqual(result['status'], 'completed', result)
        return result['result']['skills']

    def test_catalog_and_details_use_native_cli_and_complete_through_job_signal(self):
        known = str(self.root / 'dynamic' / 'SKILL.md')
        loaded = str(self.root / 'loaded' / 'SKILL.md')
        self.backend._view.known_skills[known] = {'path': known, 'name': 'dynamic'}
        self.backend._view.resources['skills'] = [{'filePath': loaded, 'name': 'loaded'}]
        self.backend._view.skill_modes[self.rows[0]['path']] = False
        job = self.accepted('skills.list')
        self.assertEqual(self.cli_calls, [])
        running = self.request('skills.job', {'id': job})
        self.assertEqual(self.manager.replies[running]['jobs'][0]['status'], 'running')
        rows = self.finish(job)['result']['skills']
        self.assertEqual(rows, self.rows)
        self.assertFalse(rows[0]['enabled'])
        self.assertFalse(rows[2]['defaultMutable'])
        command, options, action = self.cli_calls[0]
        self.assertEqual(Path(command[1]).name, 'skills.mjs')
        self.assertEqual(action['sessionSkills'], self.backend._view.skill_modes)
        self.assertEqual({item.get('path') or item.get('filePath') for item in action['loadedSkills']}, {known, loaded})
        self.assertEqual(options['env']['PI_OFFLINE'], '1')
        self.assertNotIn('NODE_OPTIONS', options['env'])
        self.assertNotIn('NODE_PATH', options['env'])
        self.assertIn(loaded, self.backend._view.known_skills)
        details = self.finish(self.accepted('skills.details', {'id': rows[0]['id']}))
        self.assertEqual(details['result']['details']['markdown'], '# Fixture skill\nUse the fixture.')
        self.assertEqual(self.cli_calls[-1][2]['action'], 'details')

    def test_every_operation_requires_its_permission(self):
        for operation in ('skills.list', 'skills.details', 'skills.job', 'skills.attach',
                          'skills.default', 'skills.reveal', 'skills.remove'):
            with self.subTest(operation=operation):
                self.manager.entries['a']['permissions'] = []
                args = {} if operation == 'skills.list' else {'id': self.rows[0]['id']}
                if operation in ('skills.attach', 'skills.default'): args['enabled'] = True
                identifier = self.request(operation, args)
                self.assertIn('permission', self.manager.replies[identifier]['error'])
                self.assertFalse(self.host.panelApproval)
        self.assertFalse(self.backend.pending_jobs)
        self.assertFalse(self.native.called)

    def test_busy_rejects_all_reads_and_writes_except_owned_job_poll(self):
        self.catalog()
        job = self.accepted('skills.list')
        for busy in ('chat', 'kernel', 'management', 'skill-job'):
            if busy != 'skill-job':
                self.backend.finish()
                self.backend.busy = busy == 'chat'
                self.backend.kernelBusy = busy == 'kernel'
                self.backend.piManagement.busy = busy == 'management'
            for operation in ('skills.list', 'skills.details', 'skills.attach', 'skills.default', 'skills.reveal', 'skills.remove'):
                with self.subTest(busy=busy, operation=operation):
                    args = {} if operation == 'skills.list' else {'id': self.rows[0]['id']}
                    if operation in ('skills.attach', 'skills.default'): args['enabled'] = True
                    identifier = self.request(operation, args)
                    self.assertIn('busy', self.manager.replies[identifier]['error'].lower())
                    self.assertFalse(self.host.panelApproval)
            poll = self.request('skills.job', {'id': job})
            self.assertTrue(self.manager.replies[poll]['ok'])
            self.backend.busy = self.backend.kernelBusy = self.backend.piManagement.busy = False
            if busy != 'skill-job': job = self.accepted('skills.list')

    def test_stale_chat_and_other_widget_cannot_access_owned_jobs(self):
        job = self.accepted('skills.list')
        identifier = self.request('skills.job', {'id': job}, widget='b')
        self.assertFalse(self.manager.replies[identifier]['ok'])
        stale = {**self.manager._session, 'token': 'previous-chat'}
        for operation in ('skills.list', 'skills.details', 'skills.job', 'skills.attach', 'skills.default', 'skills.reveal', 'skills.remove'):
            with self.subTest(operation=operation):
                args = {} if operation == 'skills.list' else {'id': job if operation == 'skills.job' else self.rows[0]['id']}
                if operation in ('skills.attach', 'skills.default'): args['enabled'] = True
                identifier = self.request(operation, args, session=stale)
                self.assertIn('changed', self.manager.replies[identifier]['error'])
        self.manager.workers['a'] = {'ready': True}
        identifier = self.request('skills.job', {'id': job})
        self.assertFalse(self.manager.replies[identifier]['ok'])

    def test_attach_persists_current_chat_and_marks_native_reload_without_touching_second(self):
        self.catalog()
        path = self.rows[0]['path']
        self.backend.second.skill_modes[path] = False
        self.backend.store.data['sessionMeta']['two'] = {'skillModes': {path: False}}
        job = self.accepted('skills.attach', {'id': self.rows[0]['id'], 'enabled': True}, approve=True)
        self.assertNotIn(path, self.backend._view.skill_modes)
        result = self.finish(job)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(self.backend._view.skill_modes, {path: True})
        self.assertTrue(self.backend._view.stale)
        reloaded = FixtureStore(self.backend.store.path)
        restored = SessionState(skill_modes=clean_skill_modes(reloaded.data['sessionMeta']['one']['skillModes']))
        self.assertEqual(restored.skill_modes, {path: True})
        self.assertEqual(reloaded.data['sessionMeta']['two']['skillModes'], {path: False})
        self.assertEqual(self.backend.second.skill_modes, {path: False})
        self.assertFalse(self.backend.second.stale)
        self.backend._restart_pi.assert_not_called()
        self.assertEqual(len(self.cli_calls), 1)

    def test_default_uses_native_settings_and_preserves_chat_overrides(self):
        self.catalog()
        path = self.rows[0]['path']
        self.backend._view.skill_modes[path] = True
        self.backend.second.skill_modes[path] = False
        job = self.accepted('skills.default', {'id': self.rows[0]['id'], 'enabled': False}, approve=True)
        result = self.finish(job)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(self.cli_calls[-1][2]['action'], 'default')
        self.assertFalse(self.cli_calls[-1][2]['enabled'])
        self.assertEqual(self.backend._view.skill_modes, {path: True})
        self.assertEqual(self.backend.second.skill_modes, {path: False})
        self.backend._restart_pi.assert_called_once_with()

    def test_confirmation_is_panel_only_and_cannot_be_forged_by_widget_arguments(self):
        self.catalog()
        identifier = self.request('skills.attach', {'id': self.rows[0]['id'], 'enabled': True})
        self.assertEqual(self.host.panelApproval['id'], identifier)
        self.assertEqual(self.host.panelApproval['widget'], 'a')
        self.assertEqual(self.host.pendingApproval, {})
        forged = self.request('skills.approve', {'id': identifier})
        self.assertFalse(self.manager.replies[forged]['ok'])
        forged = self.request('skills.attach', {'id': self.rows[0]['id'], 'enabled': True, 'approved': True})
        self.assertFalse(self.manager.replies[forged]['ok'])
        self.assertEqual(self.host.panelApproval['id'], identifier)
        self.assertFalse(self.backend.pending_jobs)
        self.host.respondApproval(False)
        self.assertEqual(self.manager.replies[identifier]['status'], 'declined')
        self.assertFalse(self.host.panelApproval)

    def test_approval_revalidates_workspace_and_busy_state_before_starting(self):
        self.catalog()
        for change in ('workspace', 'busy'):
            with self.subTest(change=change):
                identifier = self.request('skills.attach', {'id': self.rows[0]['id'], 'enabled': True})
                original = self.manager._session['workspace']
                if change == 'workspace': self.manager._session['workspace'] = str(self.root / 'moved')
                else: self.backend.busy = True
                self.host.respondApproval(True)
                self.assertFalse(self.manager.replies[identifier]['ok'])
                self.assertFalse(self.backend.pending_jobs)
                self.manager._session['workspace'] = original
                self.backend.busy = False

    def test_only_registered_packages_can_be_removed_and_project_defaults_are_refused(self):
        self.catalog()
        for operation, row in (('skills.remove', self.rows[0]), ('skills.default', self.rows[2])):
            args = {'id': row['id']}
            if operation == 'skills.default': args['enabled'] = False
            identifier = self.request(operation, args)
            self.host.respondApproval(True)
            self.assertFalse(self.manager.replies[identifier]['ok'])
            self.assertFalse(self.backend.pending_jobs)
        job = self.accepted('skills.remove', {'id': self.rows[1]['id']}, approve=True)
        self.assertFalse(self.remove_package.called)
        self.assertEqual(self.finish(job)['status'], 'completed')
        self.assertEqual(self.remove_package.call_args.args[3], self.rows[1]['packageSource'])
        self.assertFalse(self.remove_package.call_args.args[4])
        self.backend._restart_pi.assert_called_once_with()

    def test_reveal_uses_host_confirmation_and_mocked_folder_open(self):
        self.catalog()
        job = self.accepted('skills.reveal', {'id': self.rows[0]['id']}, approve=True)
        self.open_folder.assert_not_called()
        self.assertEqual(self.finish(job)['status'], 'completed')
        self.assertEqual(Path(self.open_folder.call_args.args[0].toLocalFile()), Path(self.rows[0]['path']).parent)

    def test_attach_completion_refuses_chat_switch_or_new_busy_state(self):
        self.catalog()
        for state in ('chat-switch', 'busy'):
            with self.subTest(state=state):
                job = self.accepted('skills.attach', {'id': self.rows[0]['id'], 'enabled': True}, approve=True)
                original = self.manager._session['token']
                if state == 'chat-switch': self.manager._session['token'] = 'another-chat'
                else: self.backend._view.busy = True
                self.backend.finish()
                self.manager._session['token'] = original
                self.backend._view.busy = False
                identifier = self.request('skills.job', {'id': job})
                result = self.manager.replies[identifier]['jobs'][0]
                self.assertEqual(result['status'], 'failed', result)
                self.assertEqual(self.backend._view.skill_modes, {})
                self.assertFalse(self.backend.store.path.exists())

    def import_fixture(self, *, project=False, errors=None):
        """Keep parser/archive behavior in its own tests; exercise host ownership."""
        source = self.root / 'input' / 'SKILL.md'
        source.parent.mkdir(exist_ok=True)
        source.write_text('---\nname: imported-fixture\ndescription: Fixture skill\n---\nUse the fixture.', encoding='utf-8')
        destination = (Path(self.backend._view.workspace) / '.pi/skills' if project
                       else self.root / 'agent/skills')
        plan = {'planId': 'fixture-import-preview', 'source': str(source),
            'skills': [{'name': 'imported-fixture', 'path': 'imported-fixture/SKILL.md'}],
            'errors': errors or []}

        def commit(value, decisions, target):
            self.assertIs(value, plan)
            self.assertEqual(Path(target), destination)
            output = Path(target) / 'imported-fixture/SKILL.md'
            output.parent.mkdir(parents=True)
            output.write_text(source.read_text(encoding='utf-8'), encoding='utf-8')
            return {'imported': ['imported-fixture']}

        module = SimpleNamespace(preview_import=Mock(return_value=plan),
            commit_import=Mock(side_effect=commit), discard_import=Mock())
        patch.dict(sys.modules, {'app.skill_import': module}).start()
        job = self.accepted('skills.importPreview', {'source': str(source), 'project': project})
        self.assertFalse(self.host.panelApproval)
        self.assertFalse(destination.exists())
        result = self.finish(job)
        self.assertEqual(result['status'], 'completed', result)
        preview = result['result']['preview']
        self.assertEqual(preview['project'], project)
        self.assertEqual(preview['sourceName'], 'SKILL.md')
        self.assertNotIn('source', preview)
        self.assertEqual(Path(module.preview_import.call_args.args[1]), destination)
        return preview, destination, module

    def test_import_preview_does_not_write_until_host_confirmation_in_each_scope(self):
        for project in (False, True):
            with self.subTest(project=project):
                preview, destination, module = self.import_fixture(project=project)
                identifier = self.request('skills.import', {'id': preview['id'], 'decisions': {}})
                self.assertEqual(self.host.panelApproval['operation'], 'skills.import')
                self.assertEqual(self.host.panelApproval['project'], project)
                self.assertEqual(self.host.pendingApproval, {})
                self.assertFalse(destination.exists())
                self.assertFalse(module.commit_import.called)
                self.host.respondApproval(True)
                job = self.manager.replies[identifier]['jobId']
                self.assertFalse(destination.exists())
                self.assertFalse(module.commit_import.called)
                result = self.finish(job)
                self.assertEqual(result['status'], 'completed', result)
                self.assertTrue((destination / 'imported-fixture/SKILL.md').is_file())
                module.commit_import.assert_called_once()
                self.assertNotIn(preview['id'], self.host._skills.previews)

    def test_import_rejects_forged_and_foreign_preview_ownership_before_confirmation(self):
        preview, destination, module = self.import_fixture()
        for widget, identifier in (('a', 'forged-preview'), ('b', preview['id'])):
            with self.subTest(widget=widget):
                request = self.request('skills.import', {'id': identifier}, widget=widget)
                self.assertFalse(self.manager.replies[request]['ok'])
                self.assertFalse(self.host.panelApproval)
        self.manager.workers['a'] = {'ready': True}
        request = self.request('skills.import', {'id': preview['id']})
        self.assertFalse(self.manager.replies[request]['ok'])
        self.assertFalse(self.host.panelApproval)
        self.assertFalse(destination.exists())
        module.commit_import.assert_not_called()

    def test_import_confirmation_rechecks_ownership_and_busy_state(self):
        preview, destination, module = self.import_fixture()
        for state in ('busy', 'chat'):
            with self.subTest(state=state):
                identifier = self.request('skills.import', {'id': preview['id']})
                original = self.manager._session['workspace']
                if state == 'busy': self.backend.busy = True
                else: self.manager._session['workspace'] = str(self.root / 'different-project')
                self.host.respondApproval(True)
                self.assertFalse(self.manager.replies[identifier]['ok'])
                self.assertFalse(self.backend.pending_jobs)
                self.backend.busy = False
                self.manager._session['workspace'] = original
        module.commit_import.assert_not_called()
        self.assertFalse(destination.exists())

    def test_import_read_manage_permissions_validation_errors_and_busy_refusal(self):
        self.manager.entries['a']['permissions'] = ['skills.manage']
        identifier = self.request('skills.importPreview', {'source': str(self.root / 'source')})
        self.assertIn('skills.read', self.manager.replies[identifier]['error'])
        self.manager.entries['a']['permissions'] = ['skills.read', 'skills.manage']
        preview, destination, module = self.import_fixture(errors=['Invalid frontmatter'])
        identifier = self.request('skills.import', {'id': preview['id']})
        self.assertIn('validation', self.manager.replies[identifier]['error'])
        self.assertFalse(self.host.panelApproval)
        module.commit_import.assert_not_called()
        self.assertFalse(destination.exists())
        self.manager.entries['a']['permissions'] = ['skills.read']
        identifier = self.request('skills.import', {'id': preview['id']})
        self.assertIn('skills.manage', self.manager.replies[identifier]['error'])
        self.manager.entries['a']['permissions'] = ['skills.read', 'skills.manage']
        preview, destination, module = self.import_fixture()
        self.backend.busy = True
        for operation, args in (('skills.importPreview', {'source': str(self.root / 'source')}),
                                ('skills.import', {'id': preview['id']})):
            identifier = self.request(operation, args)
            self.assertIn('busy', self.manager.replies[identifier]['error'].lower())
        self.assertFalse(self.host.panelApproval)
        module.commit_import.assert_not_called()
        self.assertFalse(destination.exists())


if __name__ == '__main__':
    unittest.main()
