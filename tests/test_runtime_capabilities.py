"""Local protocol fixtures: no models, package installation or external services."""
import copy
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, Signal

from app.runtime_capabilities import RuntimeCapabilities
from app.runtime_dependencies import PACKAGES, PYTHON_PROBE, inspect_dependencies, python_command, run_probe, version_state
from app.umeko_control import UmekoControl


class DependencyTests(unittest.TestCase):
    def fixture(self, missing=(), broken=(), old=()):
        packages = {module: {'state': 'missing' if module in missing else 'error' if module in broken else 'available',
            'version': '0.1.0' if module in old else minimum, 'path': '/tools/' + module} for module, _, minimum in PACKAGES}
        payload = {'version': '3.12.0', 'path': '/tools/python', 'packages': packages,
            'chromium': {'state': 'available', 'path': '/tools/chromium'}}
        calls = []

        def runner(command, **options):
            calls.append((command, options))
            output = json.dumps(payload) if '-c' in command else {'--version': 'git version 2.40.1', '-v': 'pdftoppm version 24.0.1'}[command[-1]]
            if command[0].endswith('soffice'):
                output = 'LibreOffice 24.2.0'
            return {'state': 'available', 'output': output}
        return runner, calls

    def inspect(self, runner, absent=()):
        with patch('app.runtime_dependencies.python_command', return_value=['/tools/python']), patch(
                'app.runtime_dependencies.shutil.which', side_effect=lambda name, **_: None if name in absent else '/tools/' + name):
            return inspect_dependencies('/任务 目录', {'PATH': '/tools', 'PRIVATE_KEY': 'fixture-secret'}, runner)

    def test_available_has_versions_paths_scope_and_no_quality_claim(self):
        runner, calls = self.fixture()
        report = self.inspect(runner)
        self.assertEqual({c['state'] for c in report['capabilities']}, {'available'})
        self.assertFalse(report['qualityVerified'])
        self.assertEqual(report['remote']['state'], 'unchecked')
        self.assertEqual(report['pythonCommand'], ['/tools/python'])
        self.assertEqual(report['workspace'], '/任务 目录')
        self.assertNotIn('fixture-secret', json.dumps(report))
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[0][0][1:4], ['-I', '-B', '-c'])
        self.assertTrue(all(c['scope'] == 'local' for c in report['capabilities']))

    def test_optional_renderers_missing_preserves_generation_as_partial(self):
        runner, _ = self.fixture()
        report = self.inspect(runner, absent=('soffice', 'libreoffice', 'pdftoppm'))
        self.assertEqual({c['id']: c['state'] for c in report['capabilities']},
            {'office': 'partial', 'pdf': 'partial', 'git': 'available', 'browser': 'available'})

    def test_missing_import_error_and_incompatible_versions_are_distinct(self):
        runner, _ = self.fixture(missing=('docx',), broken=('pypdf',), old=('playwright.sync_api',))
        report = self.inspect(runner)
        self.assertEqual({c['id']: c['state'] for c in report['capabilities']},
            {'office': 'missing', 'pdf': 'error', 'git': 'available', 'browser': 'missing'})
        dependencies = {r['id']: r for r in report['dependencies']}
        self.assertEqual(dependencies['playwright.sync_api']['reason'], '版本低于最低要求')

    def test_absent_python_is_not_replaced_by_desktop_interpreter(self):
        with patch('app.runtime_dependencies.python_command', return_value=[]), patch('app.runtime_dependencies.shutil.which', return_value=None):
            report = inspect_dependencies('/empty', {})
        self.assertEqual(report['pythonCommand'], [])
        self.assertEqual({c['state'] for c in report['capabilities']}, {'missing'})
        self.assertEqual(report['dependencies'][0]['reason'], '未找到任务 Python')

    def test_probe_errors_and_malformed_results_are_never_available(self):
        for probe in ({'state': 'error', 'reason': '检测超时'}, {'state': 'available', 'output': 'invalid'}):
            report = self.inspect(lambda *_args, **_kwargs: probe)
            self.assertNotIn('available', {r['state'] for r in report['capabilities']})
            self.assertTrue(all(r['state'] == 'error' for r in report['dependencies']))

    def test_task_venv_with_unicode_spaces_takes_precedence(self):
        with tempfile.TemporaryDirectory(prefix='依赖 空格 ') as temporary:
            path = Path(temporary) / '.umeko-tools' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            path.parent.mkdir(parents=True)
            path.touch()
            self.assertEqual(python_command(temporary, {'PATH': ''}), [str(path.absolute())])

    def test_version_boundaries_and_unknown_prereleases(self):
        for value, minimum, expected in [('1.2', '1.2.0', 'available'), ('1.1.99', '1.2', 'missing'),
                ('unknown', '1.2', 'error'), ('1.2.0rc1', '1.2', 'error')]:
            self.assertEqual(version_state(value, minimum)[0], expected)

    def test_real_probe_timeout_output_limit_and_stderr_redaction(self):
        self.assertEqual(run_probe([sys.executable, '-c', 'import time; time.sleep(5)'], timeout=.05)['reason'], '检测超时')
        self.assertEqual(run_probe([sys.executable, '-c', 'print("x" * 70000)'])['reason'], '检测输出超过上限')
        result = run_probe([sys.executable, '-c', 'import sys; print("fixture-secret",file=sys.stderr); sys.exit(1)'])
        self.assertEqual(result, {'state': 'error', 'reason': '依赖检查进程失败'})

    def test_real_python_protocol_is_isolated_and_does_not_write_workspace(self):
        with tempfile.TemporaryDirectory(prefix='模块 空格 ') as temporary:
            directory = Path(temporary)
            (directory / 'json.py').write_text('raise RuntimeError("workspace imported")')
            result = run_probe([sys.executable, '-I', '-B', '-c', PYTHON_PROBE, '[]'], env=dict(os.environ, PYTHONPATH=temporary))
            self.assertEqual(result['state'], 'available')
            self.assertEqual(json.loads(result['output'])['packages'], {})
            self.assertEqual([p.name for p in directory.iterdir()], ['json.py'])


class Backend(QObject):
    jobDone = Signal(str, object)
    viewChanged = Signal()

    def __init__(self):
        super().__init__()
        self._closing = False
        self._view = SimpleNamespace(workspace='/view')
        self.store = SimpleNamespace(directory=Path('/profile'))
        self.jobs = []

    def _job(self, name, function):
        self.jobs.append((name, function))

    def finish(self, index=0, ok=True, value=None):
        name, function = self.jobs[index]
        self.jobDone.emit(name, {'ok': ok, 'value': value or {'capabilities': [], 'qualityVerified': False}})


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.service = RuntimeCapabilities(self.backend)

    def test_async_dedup_shared_ui_api_cache_refresh_expiry_and_copy(self):
        with patch('app.runtime_capabilities.time.monotonic', return_value=100):
            self.assertEqual(self.service.snapshot['state'], 'unchecked')
            self.assertEqual(self.service.request()['state'], 'checking')
            self.service.request(force=True)
            self.assertEqual(len(self.backend.jobs), 1)
            self.backend.finish(value={'capabilities': [{'id': 'fixture'}]})
            snapshot = self.service.request()
            self.assertEqual(snapshot, self.service.snapshot)
            snapshot['capabilities'].clear()
            self.assertEqual(self.service.snapshot['capabilities'], [{'id': 'fixture'}])
            self.assertFalse(self.service.snapshot['stale'])
            self.assertEqual(len(self.backend.jobs), 1)
        with patch('app.runtime_capabilities.time.monotonic', return_value=221):
            self.assertTrue(self.service.snapshot['stale'])
            self.assertEqual(self.service.request()['state'], 'checking')
            self.assertEqual(len(self.backend.jobs), 2)
            self.backend.finish(1)
            self.service.refresh()
            self.assertEqual(len(self.backend.jobs), 3)

    def test_caller_and_view_are_isolated_including_out_of_order_completion(self):
        caller = SimpleNamespace(workspace='/caller')
        self.service.request(caller)
        self.service.request()
        self.backend.finish(1, value={'capabilities': [{'id': 'view'}]})
        self.backend.finish(0, value={'capabilities': [{'id': 'caller'}]})
        self.assertEqual(self.service.snapshot['capabilities'][0]['id'], 'view')
        self.assertEqual(self.service.request(caller)['capabilities'][0]['id'], 'caller')
        self.backend._view = SimpleNamespace(workspace='/new')
        self.assertEqual(self.service.snapshot['state'], 'unchecked')

    def test_environment_change_invalidates_cache_and_failed_refresh_drops_old_success(self):
        self.service.request()
        self.backend.finish()
        with patch.dict(os.environ, {'PLAYWRIGHT_BROWSERS_PATH': '/changed'}):
            self.assertEqual(self.service.snapshot['state'], 'unchecked')
        self.service.refresh()
        self.backend.finish(1, ok=False, value='fixture-secret')
        self.assertEqual(self.service.snapshot['state'], 'error')
        self.assertNotIn('capabilities', self.service.snapshot)
        self.assertNotIn('fixture-secret', json.dumps(self.service.snapshot))

    def test_bounded_concurrency_and_queue_and_closing(self):
        for index in range(self.service.LIMIT):
            self.service.request(SimpleNamespace(workspace='/work-' + str(index)))
        self.assertEqual(len(self.backend.jobs), 2)
        with self.assertRaises(ValueError):
            self.service.request(SimpleNamespace(workspace='/overflow'))
        self.backend.finish(0)
        self.assertEqual(len(self.backend.jobs), 3)
        self.backend._closing = True
        self.backend.finish(1)
        self.assertEqual(len(self.backend.jobs), 3)

    def test_desktop_tool_reads_caller_cache_and_rejects_command_injection(self):
        self.backend.runtimeCapabilities = self.service
        control = UmekoControl.__new__(UmekoControl)
        QObject.__init__(control)
        control.b = self.backend
        caller = SimpleNamespace(workspace='/background', global_agent='')
        result = control.execute({'operation': 'capabilities.get'}, caller)
        self.assertTrue(result['ok'])
        self.assertEqual(result['snapshot']['workspace'], '/background')
        self.backend.finish(value={'capabilities': [{'id': 'git', 'state': 'missing'}]})
        result = control.execute({'operation': 'capabilities.get'}, caller)
        self.assertEqual(result['snapshot']['state'], 'ready')
        self.assertEqual(result['snapshot']['capabilities'][0]['state'], 'missing')
        self.assertFalse(control.execute({'operation': 'capabilities.refresh', 'arguments': {'command': 'install'}}, caller)['ok'])
        self.assertFalse(control.execute({'operation': 'capabilities.get'}, SimpleNamespace(global_agent='coordinator'))['ok'])

    def test_real_controller_worker_finishes_without_starting_pi_or_a_model(self):
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtTest import QTest
        from app.controller import Controller
        application = QCoreApplication.instance() or QCoreApplication([])
        with tempfile.TemporaryDirectory(prefix='runtime 依赖 ') as directory, patch.dict(os.environ, {'UMEKO_DATA_DIR': directory}):
            backend = Controller(Path(__file__).resolve().parents[1])
            try:
                service = backend.runtimeCapabilities
                service.request()
                for _ in range(800):
                    QTest.qWait(25)
                    if not service.snapshot['busy']:
                        break
                self.assertEqual(service.snapshot['state'], 'ready')
                self.assertFalse(service.snapshot['qualityVerified'])
                self.assertFalse(any(record.process for record in backend._pool.records.values()))
                self.assertEqual(backend._umeko_control.execute({'operation': 'capabilities.get'})['snapshot']['checkedAt'], service.snapshot['checkedAt'])
            finally:
                backend.close()


class CapabilitiesUiTests(unittest.TestCase):
    def test_production_qml_shared_service_and_localized_states(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, str(root / 'tests/runtime_capabilities_ui_smoke.py')],
            cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('RUNTIME_CAPABILITIES_UI_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
